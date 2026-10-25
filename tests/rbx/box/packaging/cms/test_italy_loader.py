"""The CMS contest `rbx contest package cms-contest` builds, without its problems."""

import os
import pathlib
import zipfile
from unittest import mock

import pytest
import yaml

from rbx.box import package_utils
from rbx.box.contest import contest_package
from rbx.box.contest.schema import Contest
from rbx.box.environment import Environment
from rbx.box.packaging import contest_main
from rbx.box.packaging.cms import italy_loader
from rbx.box.packaging.cms.extension import CmsExtension


def _language(name: str, cms_languages=None) -> dict:
    language = {'name': name, 'extension': name, 'execution': {'command': 'run'}}
    if cms_languages is not None:
        language['extensions'] = {'cms': {'languages': cms_languages}}
    return language


def _env(*languages: dict) -> Environment:
    return Environment.model_validate({'languages': list(languages)})


def _contest(**fields) -> Contest:
    return Contest.model_validate(
        {
            'name': 'obi-2026',
            'titles': {'pt': 'OBI 2026'},
            'problems': [{'short_name': 'B'}, {'short_name': 'A'}],
            **fields,
        }
    )


def test_languages_come_in_env_order_each_once():
    env = _env(
        _language('cpp', ['C++20 / g++', 'C++17 / g++']),
        _language('kt'),
        _language('cpp17', ['C++17 / g++']),
        _language('py', ['Python 3 / PyPy']),
        _language('rs', []),
    )
    with mock.patch('rbx.box.environment.get_environment', return_value=env):
        languages, unmapped = italy_loader.contest_languages()

    assert languages == ['C++20 / g++', 'C++17 / g++', 'Python 3 / PyPy']
    assert unmapped == ['kt', 'rs']


def test_the_default_preset_maps_every_language_cms_has(testing_pkg):
    testing_pkg.save()

    assert italy_loader.contest_languages() == (
        ['C++20 / g++', 'C11 / gcc', 'Python 3 / CPython', 'Java / JDK'],
        ['kt'],
    )


def test_a_contest_lists_its_tasks_in_order_and_leaves_tokens_to_them():
    conf = italy_loader.contest_conf(
        _contest(), CmsExtension(), ['C++20 / g++', 'Java / JDK']
    )

    assert conf == {
        'name': 'obi-2026',
        'description': 'OBI 2026',
        'languages': ['C++20 / g++', 'Java / JDK'],
        'token_mode': 'infinite',
        'tasks': ['B', 'A'],
    }


def test_no_mapped_language_leaves_the_cms_default():
    conf = italy_loader.contest_conf(_contest(), CmsExtension(), [])

    assert 'languages' not in conf


def test_contest_settings_use_cms_names():
    cms = CmsExtension.model_validate(
        {
            'contest': {
                'start': '2026-09-28T08:00:00-03:00',
                'stop': '2026-09-28T13:00:00-03:00',
                'perUserTime': 7200,
                'timezone': 'America/Sao_Paulo',
                'allowUserTests': False,
                'allowQuestions': True,
                'allowedLocalizations': ['pt-BR'],
                'maxSubmissionNumber': 100,
                'minSubmissionInterval': 30,
                'scorePrecision': 2,
                'tokens': {'mode': 'finite', 'genInitial': 2, 'genInterval': 600},
            },
            # Task settings belong to the tasks' own packages.
            'task': {'scoreMode': 'maxSubtask'},
        }
    )

    conf = italy_loader.contest_conf(_contest(), cms, [])

    assert conf == {
        'name': 'obi-2026',
        'description': 'OBI 2026',
        'allow_user_tests': False,
        'allow_questions': True,
        'start': 1790593200,
        'stop': 1790611200,
        'per_user_time': 7200,
        'timezone': 'America/Sao_Paulo',
        'allowed_localizations': ['pt-BR'],
        'max_submission_number': 100,
        'min_submission_interval': 30,
        'score_precision': 2,
        'token_mode': 'finite',
        'token_gen_initial': 2,
        'token_gen_interval': 600,
        'tasks': ['B', 'A'],
    }


def test_the_description_follows_the_first_statement():
    contest = _contest(
        titles={'en': 'OBI 2026 (en)', 'pt': 'OBI 2026'},
        statements=[{'name': 'statement-pt', 'language': 'pt'}],
    )

    conf = italy_loader.contest_conf(contest, CmsExtension(), [])

    assert conf['description'] == 'OBI 2026'


def test_each_task_gets_a_stub_naming_it(tmp_path):
    italy_loader.write_contest(tmp_path, _contest(), CmsExtension(), ['C11 / gcc'])

    written = yaml.safe_load((tmp_path / 'contest.yaml').read_text())
    assert written == italy_loader.contest_conf(
        _contest(), CmsExtension(), ['C11 / gcc']
    )
    for task in ('A', 'B'):
        stub = yaml.safe_load((tmp_path / task / 'task.yaml').read_text())
        assert stub == {'name': task}


def _clear_caches():
    contest_package.find_contest_yaml.cache_clear()
    contest_package.find_contest_package.cache_clear()
    contest_package.get_contest_build_path.cache_clear()
    package_utils.clear_package_cache()


@pytest.fixture
def cms_contest_dir(tmp_path: pathlib.Path):
    # No problem is built, but a contest refuses to load without their folders.
    (tmp_path / 'A').mkdir()
    (tmp_path / 'A' / 'problem.rbx.yml').write_text(
        'name: problem-a\ntimeLimit: 1000\nmemoryLimit: 256\n'
    )
    (tmp_path / 'contest.rbx.yml').write_text(
        'name: obi-2026\n'
        'titles: {pt: OBI 2026}\n'
        'problems:\n'
        '  - short_name: A\n'
        'extensions:\n'
        '  cms:\n'
        '    contest:\n'
        '      timezone: America/Sao_Paulo\n'
    )
    cwd = os.getcwd()
    os.chdir(tmp_path)
    _clear_caches()
    try:
        yield tmp_path
    finally:
        os.chdir(cwd)
        _clear_caches()


def test_the_command_zips_the_contest_under_its_name(cms_contest_dir, capsys):
    env = _env(_language('cpp', ['C++20 / g++']), _language('kt'))
    with mock.patch('rbx.box.environment.get_environment', return_value=env):
        contest_main.cms_contest()

    with zipfile.ZipFile(cms_contest_dir / 'build' / 'cms-contest.zip') as archive:
        assert sorted(archive.namelist()) == [
            'obi-2026/',
            'obi-2026/A/',
            'obi-2026/A/task.yaml',
            'obi-2026/contest.yaml',
        ]
        conf = yaml.safe_load(archive.read('obi-2026/contest.yaml'))
    assert conf['languages'] == ['C++20 / g++']
    assert conf['timezone'] == 'America/Sao_Paulo'
    assert conf['tasks'] == ['A']
    assert 'kt' in capsys.readouterr().out
