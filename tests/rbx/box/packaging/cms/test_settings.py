"""How the CMS settings of a preset and a contest combine, and what CMS gets."""

import os
import pathlib

import pytest

from rbx.box import package_utils
from rbx.box.contest import contest_package
from rbx.box.packaging.cms import settings
from rbx.box.packaging.cms.extension import CmsExtension
from tests.rbx.box.packaging.cms._entries import build_entries


def _cms(**blocks) -> CmsExtension:
    return CmsExtension.model_validate(blocks)


def test_a_contest_overrides_a_preset_field_by_field():
    env = _cms(task={'scoreMode': 'maxSubtask', 'minSubmissionInterval': 60})
    contest = _cms(task={'minSubmissionInterval': 30})

    merged = settings.merge(env, contest)

    assert merged.task is not None
    assert merged.task.scoreMode == 'maxSubtask'
    assert merged.task.minSubmissionInterval == 30


def test_a_contest_replaces_the_preset_tokens_whole():
    env = _cms(task={'tokens': {'mode': 'finite', 'genNumber': 2, 'genMax': 5}})
    contest = _cms(task={'tokens': {'mode': 'infinite'}})

    merged = settings.merge(env, contest)

    assert merged.task is not None
    assert merged.task.tokens == contest.task.tokens  # type: ignore[union-attr]


def test_either_level_alone_is_kept():
    env = _cms(contest={'allowUserTests': True})
    contest = _cms(task={'feedbackLevel': 'full'})

    assert settings.merge(env, contest) == _cms(
        contest={'allowUserTests': True}, task={'feedbackLevel': 'full'}
    )
    assert settings.merge(None, None) == CmsExtension()


def test_unset_settings_emit_only_rbx_score_mode():
    assert settings.task_keys(None) == {'score_mode': 'max'}


def test_task_settings_use_cms_names():
    task = _cms(
        task={
            'scoreMode': 'maxTokenedLast',
            'feedbackLevel': 'restricted',
            'maxSubmissionNumber': 50,
            'minSubmissionInterval': 60,
            'scorePrecision': 2,
            'tokens': {'mode': 'finite', 'genInitial': 1, 'genInterval': 1800},
        }
    ).task

    assert settings.task_keys(task) == {
        'score_mode': 'max_tokened_last',
        'feedback_level': 'restricted',
        'max_submission_number': 50,
        'min_submission_interval': 60,
        'score_precision': 2,
        'token_mode': 'finite',
        'token_gen_initial': 1,
        'token_gen_interval': 1800,
    }


def test_only_samples_are_public_by_default(tmp_path):
    entries = build_entries(tmp_path, ['samples', 'samples', 'main'])

    assert settings.public_testcases(None, entries) == [0, 1]


@pytest.mark.parametrize('public, expected', [('all', 'all'), ('none', [])])
def test_public_testcases_can_be_all_or_none(tmp_path, public, expected):
    entries = build_entries(tmp_path, ['samples', 'main'])
    task = _cms(task={'publicTestcases': public}).task

    assert settings.public_testcases(task, entries) == expected


def test_contest_settings_are_reported_as_not_carried_by_polygon(capsys):
    settings.warn_for_polygon(_cms(contest={'allowUserTests': True}))

    out = ' '.join(capsys.readouterr().out.split())
    assert 'Ignoring allowUserTests' in out


def test_task_settings_alone_carry_no_warning(capsys):
    settings.warn_for_polygon(_cms(task={'scoreMode': 'maxSubtask'}))

    assert capsys.readouterr().out == ''


def test_scoring_on_tokens_with_tokens_off_is_reported(capsys):
    settings.warn_for_polygon(_cms(task={'scoreMode': 'maxTokenedLast'}))

    out = ' '.join(capsys.readouterr().out.split())
    assert 'tokens are disabled' in out


def test_scoring_on_tokens_with_tokens_on_is_fine(capsys):
    settings.warn_for_polygon(
        _cms(task={'scoreMode': 'maxTokenedLast', 'tokens': {'mode': 'infinite'}})
    )

    assert capsys.readouterr().out == ''


def _clear_caches():
    contest_package.find_contest_yaml.cache_clear()
    contest_package.find_contest_package.cache_clear()
    package_utils.clear_package_cache()


@pytest.fixture
def problem_in_a_cms_contest(tmp_path: pathlib.Path):
    (tmp_path / 'A').mkdir()
    (tmp_path / 'A' / 'problem.rbx.yml').write_text(
        'name: problem-a\ntimeLimit: 1000\nmemoryLimit: 256\n'
    )
    (tmp_path / 'contest.rbx.yml').write_text(
        'name: cms-contest\n'
        'problems:\n'
        '  - short_name: A\n'
        'extensions:\n'
        '  cms:\n'
        '    task:\n'
        '      feedbackLevel: full\n'
    )
    cwd = os.getcwd()
    os.chdir(tmp_path / 'A')
    _clear_caches()
    try:
        yield tmp_path
    finally:
        os.chdir(cwd)
        _clear_caches()


def test_a_problem_takes_the_settings_of_its_contest(problem_in_a_cms_contest):
    resolved = settings.resolve()

    assert resolved.task is not None
    assert resolved.task.feedbackLevel == 'full'
