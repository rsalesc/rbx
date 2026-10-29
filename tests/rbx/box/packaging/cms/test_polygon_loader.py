"""What CMS's Polygon importer reads from a `--cms` Polygon package.

The rendered `cms_conf.py` runs inside CMS. A batch problem's only stores tests
with CMS, so it is executed here against stand-ins for the two `cms` classes it
uses; an interactive one's also compiles the manager, so only its configuration
is checked.
"""

import ast
import datetime
import pathlib
import subprocess
import sys
import tempfile
import types
from typing import Any, List, NamedTuple, Optional
from unittest import mock

import pytest

from rbx.box.environment import Environment
from rbx.box.packaging.cms import communication, polygon_loader
from rbx.box.packaging.cms.extension import CmsExtension
from rbx.box.schema import Interactor, TaskType
from rbx.config import get_app_file
from tests.rbx.box.packaging.cms._entries import build_entries


class StoredTestcase(NamedTuple):
    codename: str
    public: bool
    input: str
    output: str


class StoredManager(NamedTuple):
    filename: str
    digest: str


class FileCacher:
    def put_file_from_path(self, path: str, description: str) -> str:
        return pathlib.Path(path).read_text()


@pytest.fixture(autouse=True)
def compilations(monkeypatch) -> List[List[str]]:
    """Stands in for `g++` (whose `-static` macOS cannot link): the "binary" names
    the source it was built from."""
    commands: List[List[str]] = []

    def fake_run(command, check=False, **kwargs):
        commands.append(command)
        output = command[command.index('-o') + 1]
        pathlib.Path(output).write_text('built from ' + command[-1])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, 'run', fake_run)
    return commands


@pytest.fixture(autouse=True)
def bundled_testlib(monkeypatch):
    # `get_testlib` would download testlib.h, which a test must never do.
    monkeypatch.setattr(
        polygon_loader,
        'get_testlib',
        lambda: get_app_file(pathlib.Path('testlib.h'), predownloaded=True),
    )


@pytest.fixture(autouse=True)
def cms_modules(monkeypatch):
    db = types.ModuleType('cms.db')
    db.Testcase = StoredTestcase  # type: ignore[attr-defined]
    db.Manager = StoredManager  # type: ignore[attr-defined]
    filecacher = types.ModuleType('cms.db.filecacher')
    filecacher.FileCacher = FileCacher  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'cms', types.ModuleType('cms'))
    monkeypatch.setitem(sys.modules, 'cms.db', db)
    monkeypatch.setitem(sys.modules, 'cms.db.filecacher', filecacher)


def _polygon_package(root: pathlib.Path, inputs: List[str]) -> pathlib.Path:
    """The parts of a Polygon package the conf reads: `problem.xml` and tests."""
    (root / 'files').mkdir(parents=True)
    (root / 'files' / 'check.cpp').write_text('// checker')
    (root / 'files' / 'cms_testlib.h').write_text('// cms testlib')
    (root / 'tests').mkdir()
    for i, data in enumerate(inputs):
        (root / 'tests' / f'{i + 1:02d}').write_text(data)
        (root / 'tests' / f'{i + 1:02d}.a').write_text(f'answer {i}')
    (root / 'problem.xml').write_text(
        '<problem><judging><testset name="tests">'
        f'<test-count>{len(inputs)}</test-count>'
        '<input-path-pattern>tests/%02d</input-path-pattern>'
        '<answer-path-pattern>tests/%02d.a</answer-path-pattern>'
        '</testset></judging></problem>'
    )
    return root / 'files' / polygon_loader.CONF_FILE


# Every test public: the conf then stores no test, so it needs no `cms`.
ALL_PUBLIC = CmsExtension.model_validate({'task': {'publicTestcases': 'all'}})


def _run(conf: str, path: Optional[str] = None) -> dict:
    if path is None:
        root = pathlib.Path(tempfile.mkdtemp()) / 'A'
        path = str(_polygon_package(root, []))
    namespace: dict[str, Any] = {'__file__': path}
    exec(conf, namespace)
    return namespace


def _config(conf: str) -> dict:
    (line,) = [line for line in conf.splitlines() if line.startswith('CONFIG = ')]
    return ast.literal_eval(line[len('CONFIG = ') :])


def _interactive(testing_pkg, legacy: bool):
    if legacy:
        testing_pkg.set_checker('checker.cpp')
    testing_pkg.add_file('interactor.cpp').write_text('')
    testing_pkg.yml.type = TaskType.COMMUNICATION
    testing_pkg.yml.interactor = Interactor(path='interactor.cpp', legacy=legacy)
    testing_pkg.save()


def test_batch_conf_sets_group_scoring_and_score_mode(
    testing_pkg, tmp_path, cms_modules
):
    entries = build_entries(tmp_path, ['main', 'main'])
    conf = _polygon_package(tmp_path / 'A', ['1', '2'])

    namespace = _run(polygon_loader.render_conf(testing_pkg.yml, entries), str(conf))

    # The task score is the best submission's, not the last one's.
    assert namespace['general'] == {'score_mode': 'max', 'score_precision': 2}
    assert namespace['datasets']['tests']['score_type'] == 'GroupMin'
    assert namespace['datasets']['tests']['score_type_parameters'] == [[100, '.*']]


def test_batch_conf_makes_only_samples_public(testing_pkg, tmp_path, cms_modules):
    entries = build_entries(tmp_path, ['samples', 'main', 'main'])
    conf = _polygon_package(tmp_path / 'A', ['sample', 'one', 'two'])

    namespace = _run(polygon_loader.render_conf(testing_pkg.yml, entries), str(conf))

    assert namespace['datasets']['tests']['testcases'] == {
        '000': StoredTestcase('000', True, 'sample', 'answer 0'),
        '001': StoredTestcase('001', False, 'one', 'answer 1'),
        '002': StoredTestcase('002', False, 'two', 'answer 2'),
    }


def test_batch_conf_leaves_the_tests_alone_when_all_are_public(testing_pkg, tmp_path):
    entries = build_entries(tmp_path, ['samples', 'main'])
    namespace = _run(polygon_loader.render_conf(testing_pkg.yml, entries, ALL_PUBLIC))

    assert 'testcases' not in namespace['datasets']['tests']


def test_conf_sets_the_task_settings(testing_pkg, tmp_path):
    cms_settings = CmsExtension.model_validate(
        {
            'contest': {'allowUserTests': True},
            'task': {
                'scoreMode': 'maxSubtask',
                'feedbackLevel': 'restricted',
                'maxSubmissionNumber': 50,
                'minSubmissionInterval': 60,
                'publicTestcases': 'all',
                'tokens': {'mode': 'finite', 'genInterval': 1800},
            },
        }
    )

    namespace = _run(polygon_loader.render_conf(testing_pkg.yml, [], cms_settings))

    # Only task settings: the importer takes nothing else from this file.
    assert namespace['general'] == {
        'score_mode': 'max_subtask',
        'feedback_level': 'restricted',
        'max_submission_number': 50,
        'min_submission_interval': datetime.timedelta(seconds=60),
        'token_mode': 'finite',
        'score_precision': 2,
        'token_gen_interval': datetime.timedelta(minutes=30),
    }


def test_conf_packs_inputs_like_the_manager_reads_them(testing_pkg, tmp_path):
    # The conf packs answers into the tests inside CMS; a native packager would
    # do it with `communication.pack_input`. Both must agree with the manager.
    namespace = _run(polygon_loader.render_conf(testing_pkg.yml, [], ALL_PUBLIC))

    for data, answer in [(b'', b''), (b'5 3\n', b'2\n'), (b'\x00\n\n', b'x')]:
        assert namespace['_pack_input'](data, answer) == communication.pack_input(
            data, answer
        )
    assert communication.pack_input(b'5 3\n', b'2\n') == b'RBX-CMS-INPUT 4 2\n5 3\n2\n'


def test_modern_interactor_conf_compiles_only_the_manager(testing_pkg, tmp_path):
    _interactive(testing_pkg, legacy=False)

    config = _config(polygon_loader.render_conf(testing_pkg.yml, []))

    assert config['communication'] == {
        'task_type': 'Communication',
        'task_type_parameters': [1, 'alone', 'std_io'],
        'manager': 'cms_manager.cpp',
        'manager_flags': ['-std=gnu++20', '-O2'],
        'checker_runner': None,
        'checker_runner_flags': ['-std=gnu++20', '-O2'],
    }


def test_legacy_interactor_conf_also_runs_the_checker(testing_pkg, tmp_path):
    _interactive(testing_pkg, legacy=True)

    config = _config(polygon_loader.render_conf(testing_pkg.yml, []))

    assert config['communication']['checker_runner'] == 'cms_checker.cpp'


def test_interactive_files_ship_the_manager_sources(testing_pkg, tmp_path):
    _interactive(testing_pkg, legacy=True)
    files = tmp_path / 'files'
    files.mkdir()

    polygon_loader.write_files(testing_pkg.yml, [], files)

    assert sorted(p.name for p in files.iterdir()) == [
        'cms_checker.cpp',
        'cms_conf.py',
        'cms_manager.cpp',
        'rbx_cms_report.h',
    ]


def test_batch_files_ship_the_conf_and_the_cms_testlib(testing_pkg, tmp_path):
    files = tmp_path / 'files'
    files.mkdir()

    polygon_loader.write_files(testing_pkg.yml, [], files)

    assert sorted(p.name for p in files.iterdir()) == ['cms_conf.py', 'cms_testlib.h']
    assert '#ifdef RBX_CMS' in (files / 'cms_testlib.h').read_text()


def test_batch_conf_builds_the_checker_against_the_cms_testlib(
    testing_pkg, tmp_path, compilations
):
    conf = _polygon_package(tmp_path / 'A', ['1'])

    namespace = _run(polygon_loader.render_conf(testing_pkg.yml, []), str(conf))

    # The importer's own checker would read `quitp` as a fraction.
    manager = namespace['datasets']['tests']['managers']['checker']
    assert manager.filename == 'checker'
    assert manager.digest.startswith('built from ')
    assert manager.digest.endswith('check.cpp')
    (command,) = compilations
    assert '-DRBX_CMS' in command
    # Compiled from a copy where `testlib.h` is the CMS variant.
    build = pathlib.Path(command[-1]).parent
    assert (build / 'testlib.h').read_text() == '// cms testlib'


def _cpp_env(flags: Optional[str]) -> Environment:
    language: dict[str, Any] = {
        'name': 'cpp',
        'extension': 'cpp',
        'execution': {'command': 'run'},
    }
    if flags is not None:
        language['extensions'] = {'cms': {'flags': flags}}
    return Environment.model_validate({'languages': [language]})


def test_batch_conf_builds_the_checker_with_the_default_flags(
    testing_pkg, tmp_path, compilations
):
    conf = _polygon_package(tmp_path / 'A', ['1'])

    _run(polygon_loader.render_conf(testing_pkg.yml, []), str(conf))

    (command,) = compilations
    assert command[:5] == ['g++', '-x', 'c++', '-std=gnu++20', '-O2']


def test_batch_conf_builds_the_checker_with_its_language_flags(
    testing_pkg, tmp_path, compilations
):
    testing_pkg.set_checker('checker.cpp')
    conf = _polygon_package(tmp_path / 'A', ['1'])

    with mock.patch(
        'rbx.box.environment.get_environment',
        return_value=_cpp_env('-std=gnu++17 -O2 -DLOCAL_CMS'),
    ):
        rendered = polygon_loader.render_conf(testing_pkg.yml, [])
    _run(rendered, str(conf))

    (command,) = compilations
    assert command[:6] == ['g++', '-x', 'c++', '-std=gnu++17', '-O2', '-DLOCAL_CMS']
    # What rbx needs is added whatever the flags say.
    assert '-static' in command
    assert '-DRBX_CMS' in command
    assert '-std=gnu++20' not in command


def test_interactive_conf_builds_the_manager_and_runner_with_their_flags(
    testing_pkg, tmp_path, compilations
):
    _interactive(testing_pkg, legacy=True)
    conf = _polygon_package(tmp_path / 'A', ['1'])

    with mock.patch(
        'rbx.box.environment.get_environment',
        return_value=_cpp_env('-std=c++17 -O1'),
    ):
        rendered = polygon_loader.render_conf(testing_pkg.yml, [], ALL_PUBLIC)
    _run(rendered, str(conf))

    runner, manager = compilations
    assert runner[-1].endswith('cms_checker.cpp')
    assert manager[-1].endswith('cms_manager.cpp')
    for command in (runner, manager):
        assert command[:5] == ['g++', '-x', 'c++', '-std=c++17', '-O1']
        assert '-static' in command
    assert any(flag.startswith('-DRBX_CMS_CHECKER=') for flag in manager)
