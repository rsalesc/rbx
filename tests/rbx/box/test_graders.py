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


def test_secrets_are_stable_per_slug_and_distinct_across_slugs():
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
            grader={'path': 'grader.cpp'},
            interactor={'path': 'interactor.cpp', 'legacy': True},
            checker={'path': 'checker.cpp'},
        )


def test_attachments_accept_files_and_samples():
    pkg = _package(
        attachments=[
            {'path': 'graders/grader.cpp', 'public': True},
            {'path': 'graders/template.cpp', 'name': 'task.cpp'},
            {'samples': 'examples'},
        ]
    )
    names = [a.archive_name for a in pkg.attachments[:2]]
    assert names == ['grader.cpp', 'task.cpp']
    assert pkg.attachments[2].samples == 'examples'


def test_cms_batch_grader_config():
    pkg = _package(grader={'path': 'graders/grader.cpp'})
    assert cms_graders.grader_config(pkg, ['grader.cpp', 'rbx.h', 'task.h']) == {
        'managers': {'grader.cpp': 'grader.cpp', 'rbx.h': 'rbx.h', 'task.h': 'task.h'},
        'task_type': 'Batch',
        'task_type_parameters': ['grader', ['', ''], 'comparator'],
    }


def test_cms_stub_is_stored_as_stub_cpp():
    pkg = _package(
        type='communication',
        grader={'path': 'graders/grader.cpp'},
        interactor={'path': 'interactor.cpp'},
    )
    assert cms_graders.grader_config(pkg, ['grader.cpp', 'rbx.h']) == {
        'managers': {'stub.cpp': 'grader.cpp', 'rbx.h': 'rbx.h'},
    }


def test_cms_refuses_a_grader_dependency_it_cannot_compile_with():
    pkg = _package(grader={'path': 'graders/grader.cpp'})
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
