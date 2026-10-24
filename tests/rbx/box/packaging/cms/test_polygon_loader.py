"""What CMS's Polygon importer reads from a `--cms` Polygon package.

The rendered `cms_conf.py` runs inside CMS. A batch problem's only stores tests
with CMS, so it is executed here against stand-ins for the two `cms` classes it
uses; an interactive one's also compiles the manager, so only its configuration
is checked.
"""

import ast
import datetime
import pathlib
import sys
import types
from typing import Any, List, NamedTuple

import pytest

from rbx.box.packaging.cms import communication, polygon_loader
from rbx.box.packaging.cms.extension import CmsExtension
from rbx.box.schema import Interactor, TaskType
from tests.rbx.box.packaging.cms._entries import build_entries


class StoredTestcase(NamedTuple):
    codename: str
    public: bool
    input: str
    output: str


class FileCacher:
    def put_file_from_path(self, path: str, description: str) -> str:
        return pathlib.Path(path).read_text()


@pytest.fixture
def cms_modules(monkeypatch):
    db = types.ModuleType('cms.db')
    db.Testcase = StoredTestcase  # type: ignore[attr-defined]
    filecacher = types.ModuleType('cms.db.filecacher')
    filecacher.FileCacher = FileCacher  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'cms', types.ModuleType('cms'))
    monkeypatch.setitem(sys.modules, 'cms.db', db)
    monkeypatch.setitem(sys.modules, 'cms.db.filecacher', filecacher)


def _polygon_package(root: pathlib.Path, inputs: List[str]) -> pathlib.Path:
    """The parts of a Polygon package the conf reads: `problem.xml` and tests."""
    (root / 'files').mkdir(parents=True)
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


def _run(conf: str, path: str = '/pkg/problems/A/files/cms_conf.py') -> dict:
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
    assert namespace['general'] == {'score_mode': 'max'}
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
        'checker_runner': None,
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


def test_batch_files_ship_only_the_conf(testing_pkg, tmp_path):
    files = tmp_path / 'files'
    files.mkdir()

    polygon_loader.write_files(testing_pkg.yml, [], files)

    assert [p.name for p in files.iterdir()] == ['cms_conf.py']
