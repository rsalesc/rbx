import shutil
import subprocess

import pytest
import typer
from pydantic import ValidationError

from rbx.box import graders
from rbx.box.packaging.cms import graders as cms_graders
from rbx.box.packaging.polygon import xml_schema as polygon_schema
from rbx.box.schema import Package

GRADER = """#include <cstdio>
#include "rbx.h"
#include "task.h"

int main() {
  rbx::grader::start();
  // BEGIN SECRET
  int hidden = getVar<int>("SEED");
  // END SECRET
  rbx::grader::before_call();
    // BEGIN SECRET
  check(hidden);
    // END SECRET
  rbx::grader::after_call();
}
"""


def _package(**kwargs) -> Package:
    return Package.model_validate(
        {'name': 'grader-pkg', 'timeLimit': 1000, 'memoryLimit': 256, **kwargs}
    )


def test_strip_secret_blocks_removes_every_block_and_its_markers():
    stripped = graders.strip_secret_blocks(GRADER)
    assert 'SECRET' not in stripped
    assert 'getVar' not in stripped
    assert 'check(hidden)' not in stripped
    assert 'rbx::grader::before_call();' in stripped
    assert 'rbx::grader::after_call();' in stripped


def test_make_public_source_inlines_a_secret_free_shim():
    public = graders.make_public_source(GRADER)
    assert '#include "rbx.h"' not in public
    assert 'public grader flavour' in public
    assert '#include "task.h"' in public
    assert 'secrets::' not in public
    assert 'getVar' not in public


def test_secrets_are_stable_per_secret_and_distinct_across_secrets():
    assert graders.derive_secret('abc', 'input') == graders.derive_secret(
        'abc', 'input'
    )
    assert graders.derive_secret('abc', 'input') != graders.derive_secret(
        'abd', 'input'
    )
    assert graders.derive_secret('abc', 'input') != graders.derive_secret(
        'abc', 'output'
    )
    assert len(graders.derive_secret('abc', 'input')) == 32


def test_grader_with_legacy_interactor_is_rejected():
    with pytest.raises(ValidationError, match='GRADER_WITH_LEGACY_INTERACTOR|legacy'):
        _package(
            type='communication',
            grader={'path': 'grader.cpp', 'secret': 's3cr3t'},
            interactor={'path': 'interactor.cpp', 'legacy': True},
            checker={'path': 'checker.cpp'},
        )


def test_attachments_accept_files_and_samples():
    pkg = _package(
        attachments=[
            {'path': 'graders/grader.cpp', 'stripSecret': True},
            {'path': 'graders/template.cpp', 'name': 'task.cpp'},
            {'samples': 'examples'},
        ]
    )
    names = [a.archive_name for a in pkg.attachments[:2]]
    assert names == ['grader.cpp', 'task.cpp']
    assert pkg.attachments[2].samples == 'examples'


def test_cms_batch_grader_config():
    pkg = _package(grader={'path': 'graders/grader.cpp', 'secret': 's3cr3t'})
    assert cms_graders.grader_config(pkg, ['grader.cpp', 'rbx.h', 'task.h']) == {
        'managers': {'grader.cpp': 'grader.cpp', 'rbx.h': 'rbx.h', 'task.h': 'task.h'},
        'task_type': 'Batch',
        'task_type_parameters': ['grader', ['', ''], 'comparator'],
    }


def test_cms_stub_is_stored_as_stub_cpp():
    pkg = _package(
        type='communication',
        grader={'path': 'graders/grader.cpp', 'secret': 's3cr3t'},
        interactor={'path': 'interactor.cpp'},
    )
    assert cms_graders.grader_config(pkg, ['grader.cpp', 'rbx.h']) == {
        'managers': {'stub.cpp': 'grader.cpp', 'rbx.h': 'rbx.h'},
    }


def test_cms_refuses_a_grader_dependency_it_cannot_compile_with():
    pkg = _package(grader={'path': 'graders/grader.cpp', 'secret': 's3cr3t'})
    with pytest.raises(typer.Exit):
        cms_graders.grader_config(pkg, ['grader.cpp', 'lib.hpp'])


def test_polygon_grader_resource_xml():
    file = polygon_schema.File(
        path='files/grader.cpp',
        type='cpp.g++17',
        for_types='cpp.*',
        stages=[polygon_schema.NamedRef(name='compile')],
        assets=[polygon_schema.NamedRef(name='solution')],
    )
    xml = file.to_xml(skip_empty=True)
    if isinstance(xml, bytes):
        xml = xml.decode()
    assert 'for-types="cpp.*"' in xml
    assert '<stages><stage name="compile"/></stages>' in xml
    assert '<assets><asset name="solution"/></assets>' in xml


def test_plain_polygon_file_has_no_grader_elements():
    xml = polygon_schema.File(path='files/rbx.h', type='h.g++').to_xml(skip_empty=True)
    if isinstance(xml, bytes):
        xml = xml.decode()
    assert 'stages' not in xml and 'assets' not in xml and 'for-types' not in xml


@pytest.mark.parametrize(
    'source',
    [
        '// BEGIN SECRET\nint hidden;\n',
        'int x;\n// END SECRET\n',
        'int x; // BEGIN SECRET\nint y;\n// END SECRET\n',
    ],
)
def test_unmatched_secret_marker_is_refused(source):
    with pytest.raises(graders.SecretBlockError):
        graders.strip_secret_blocks(source)


def test_grader_requires_a_secret():
    with pytest.raises(ValidationError, match='secret'):
        _package(grader={'path': 'graders/grader.cpp'})


# What rbx.h provides ahead of the judge helpers, reduced to what they use.
_JUDGE_PREAMBLE = """#include <cstdio>
#include <cstdlib>
#include <optional>
#include <string>
#include <type_traits>
#include <utility>
namespace rbx {
namespace detail {
inline std::optional<std::string> &headerGroup() {
  static std::optional<std::string> group;
  return group;
}
} // namespace detail
} // namespace rbx
"""

# A grader that turns off stdio synchronisation and does its I/O through cin and
# cout, the common competitive-programming idiom (#965). The C++ streams then
# buffer apart from the C stdio the hidden header and the framing go through.
_UNSYNCED_GRADER = """
#include <iostream>
int main(int argc, char **argv) {
  std::cin.tie(0)->sync_with_stdio(0);
  rbx::grader::Grader grader;
  int n = -1;
  std::cin >> n;
  int r = grader.run([&] {
    if (argc > 1) {
      std::cout << "leak\\n";
      if (argv[1][0] == 'w') {
        grader.wrong_answer("bad");
      }
    }
    return 2 * n;
  });
  std::cout << r << "\\n";
}
"""


@pytest.mark.parametrize(
    ('args', 'expected'),
    [
        ([], 'OUT\nEND\nOK\n42\n'),
        # The contestant's unsynchronised output stays inside the frame, where
        # the checker reports it as the solution writing to stdout.
        (['leak'], 'OUT\nleak\nEND\nOK\n42\n'),
        (['wa'], 'OUT\nleak\nEND\nWA\nbad\n'),
    ],
)
def test_judge_framing_survives_unsynced_cout(tmp_path, args, expected):
    # libc++ (Apple's g++) writes cout through C stdio even unsynchronised, so
    # it never shows the bug: prefer a real GCC, whose libstdc++ is what judges
    # run.
    candidates = [f'g++-{version}' for version in range(16, 10, -1)] + ['g++']
    gpp = next(filter(None, map(shutil.which, candidates)), None)
    if gpp is None:
        pytest.skip('g++ is not available')
    helpers = graders.judge_helpers(
        graders.Secrets(input='IN', output='OUT', output_end='END')
    )
    source = tmp_path / 'grader.cpp'
    source.write_text(_JUDGE_PREAMBLE + helpers + _UNSYNCED_GRADER)
    binary = tmp_path / 'grader'
    subprocess.run(
        [gpp, '-std=c++20', '-Wall', '-Werror', '-o', str(binary), str(source)],
        check=True,
    )
    result = subprocess.run(
        [str(binary), *args],
        input='IN\ngroup\n21\n',
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == expected
