"""What CMS's Polygon importer reads from a `--cms` Polygon package.

The rendered `cms_conf.py` runs inside CMS. A batch problem's needs nothing from
CMS, so it is executed here; an interactive one's would import `cms`, so only
its configuration is checked.
"""

import ast

from rbx.box.packaging.cms import communication, polygon_loader
from rbx.box.schema import Interactor, TaskType
from tests.rbx.box.packaging.cms._entries import build_entries


def _run(conf: str) -> dict:
    namespace = {'__file__': '/pkg/problems/A/files/cms_conf.py'}
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


def test_batch_conf_sets_group_scoring_and_score_mode(testing_pkg, tmp_path):
    entries = build_entries(tmp_path, ['main', 'main'])

    namespace = _run(polygon_loader.render_conf(testing_pkg.yml, entries))

    # The task score is the best submission's, not the last one's.
    assert namespace['general'] == {'score_mode': 'max'}
    assert namespace['datasets'] == {
        'tests': {
            'score_type': 'GroupMin',
            'score_type_parameters': [[100, '.*']],
        }
    }


def test_conf_packs_inputs_like_the_manager_reads_them(testing_pkg, tmp_path):
    # The conf packs answers into the tests inside CMS; a native packager would
    # do it with `communication.pack_input`. Both must agree with the manager.
    namespace = _run(polygon_loader.render_conf(testing_pkg.yml, []))

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
