"""The `cms` block of `env.rbx.yml` and `contest.rbx.yml` refuses what CMS would."""

import datetime

import pydantic
import pytest

from rbx.box.contest.schema import Contest
from rbx.box.environment import Environment
from rbx.box.yaml_validation import YamlValidationError, load_yaml_model

START = '2026-09-28T08:00:00-03:00'
STOP = '2026-09-28T12:00:00-03:00'


def _env(cms: dict) -> Environment:
    return Environment.model_validate({'extensions': {'cms': cms}})


def _contest(cms: dict) -> Contest:
    return Contest.model_validate({'name': 'cms-contest', 'extensions': {'cms': cms}})


def test_a_contest_carries_its_schedule():
    contest = _contest(
        {
            'contest': {
                'start': START,
                'stop': STOP,
                'perUserTime': 3600,
                'timezone': 'America/Sao_Paulo',
            },
            'task': {'scoreMode': 'maxSubtask', 'feedbackLevel': 'restricted'},
        }
    )

    assert contest.extensions is not None
    assert contest.extensions.cms is not None
    cms_contest = contest.extensions.cms.contest
    assert cms_contest is not None
    assert cms_contest.start is not None and cms_contest.stop is not None
    assert (cms_contest.stop - cms_contest.start).total_seconds() == 4 * 3600


@pytest.mark.parametrize('field', ['start', 'stop', 'perUserTime'])
def test_a_preset_cannot_carry_a_schedule(field):
    value = {'start': START, 'stop': STOP, 'perUserTime': 60}[field]

    with pytest.raises(pydantic.ValidationError, match='only be set in contest'):
        _env({'contest': {field: value}})


def test_a_preset_carries_the_rest_of_the_contest_settings():
    env = _env({'contest': {'timezone': 'America/Sao_Paulo', 'allowUserTests': True}})

    assert env.extensions is not None
    assert env.extensions.cms is not None
    assert env.extensions.cms.contest is not None
    assert env.extensions.cms.contest.allowUserTests is True


def test_stop_must_come_after_start():
    with pytest.raises(pydantic.ValidationError, match='`stop` must come after'):
        _contest({'contest': {'start': STOP, 'stop': START}})


def test_per_user_time_must_fit_the_window():
    with pytest.raises(pydantic.ValidationError, match='longer than the contest'):
        _contest({'contest': {'start': START, 'stop': STOP, 'perUserTime': 5 * 3600}})


def test_times_need_an_offset():
    with pytest.raises(pydantic.ValidationError, match='timezone'):
        _contest({'contest': {'start': '2026-09-28T08:00:00'}})


def test_timezone_must_be_an_iana_name():
    with pytest.raises(pydantic.ValidationError, match='not an IANA timezone'):
        _env({'contest': {'timezone': 'Mars/Olympus'}})


def test_feedback_level_takes_only_what_cms_1_5_knows():
    with pytest.raises(pydantic.ValidationError):
        _env({'task': {'feedbackLevel': 'oiRestricted'}})


@pytest.mark.parametrize('mode', ['disabled', 'infinite'])
def test_only_finite_tokens_take_generation_fields(mode):
    with pytest.raises(pydantic.ValidationError, match='takes no other field'):
        _env({'task': {'tokens': {'mode': mode, 'genNumber': 1}}})


def test_finite_tokens_leave_unset_fields_to_cms():
    env = _env({'task': {'tokens': {'mode': 'finite', 'genInterval': 600}}})

    assert env.extensions is not None
    assert env.extensions.cms is not None
    assert env.extensions.cms.task is not None
    tokens = env.extensions.cms.task.tokens
    assert tokens is not None
    assert tokens.maxNumber is None


def test_a_typo_is_refused_rather_than_passed_through():
    with pytest.raises(pydantic.ValidationError, match='Extra inputs'):
        _env({'task': {'score_mode': 'max'}})


def test_a_dispatcher_carries_no_cms_settings():
    with pytest.raises(pydantic.ValidationError, match="'extensions' cannot be set"):
        Contest.model_validate(
            {'use_variants': True, 'extensions': {'cms': {'task': {}}}}
        )


def test_times_keep_their_offset_through_the_yaml_loader(tmp_path):
    # Unquoted, YAML reads these as timestamps rather than strings.
    path = tmp_path / 'contest.rbx.yml'
    path.write_text(
        'name: cms-contest\n'
        'extensions:\n'
        '  cms:\n'
        '    contest:\n'
        f'      start: {START}\n'
        '      stop: 2026-09-28T15:00:00Z\n'
    )

    contest = load_yaml_model(path, Contest)

    assert contest.extensions is not None
    assert contest.extensions.cms is not None
    cms_contest = contest.extensions.cms.contest
    assert cms_contest is not None
    assert cms_contest.start == datetime.datetime.fromisoformat(START)
    assert cms_contest.start.utcoffset() == datetime.timedelta(hours=-3)
    assert cms_contest.stop == datetime.datetime(
        2026, 9, 28, 15, tzinfo=datetime.timezone.utc
    )


def test_a_yaml_time_without_an_offset_is_refused(tmp_path):
    path = tmp_path / 'contest.rbx.yml'
    path.write_text(
        'name: cms-contest\n'
        'extensions:\n'
        '  cms:\n'
        '    contest:\n'
        '      start: 2026-09-28T08:00:00\n'
    )

    with pytest.raises(YamlValidationError):
        load_yaml_model(path, Contest)
