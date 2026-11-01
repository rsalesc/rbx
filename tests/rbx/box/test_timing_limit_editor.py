"""`rbx time --edit`: the editor state, its key bindings, and the command."""

import asyncio
from unittest import mock

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput
from typer.testing import CliRunner

from rbx import utils
from rbx.box import cli, limits_info, package, timing_limit_editor
from rbx.box.schema import (
    LimitModifiers,
    LimitsProfile,
    TimingBound,
    TimingGroupOrigin,
    TimingGroupReport,
    TimingGroupUpperValidation,
    TimingMultipliers,
)
from rbx.box.testing import testing_package
from rbx.box.timing_limit_editor import LimitEditorState, prompt_limits_edit


def _profile() -> LimitsProfile:
    def report(languages, tl, slowest):
        return TimingGroupReport(
            languages=languages,
            timeLimit=tl,
            origin=TimingGroupOrigin.ESTIMATED,
            solutionCount=1,
            fastest=slowest,
            slowest=slowest,
            lowerBound=TimingBound(value=slowest * 2, solution='sols/ac.cpp'),
            upperValidation=TimingGroupUpperValidation(confirmed=['sols/tle.cpp']),
        )

    return LimitsProfile(
        timeLimit=1000,
        multipliers=TimingMultipliers(
            acToTimeLimit=2.0, timeLimitToTle=2.0, timeResolution=100
        ),
        modifiers={
            'cpp': LimitModifiers(time=1000),
            'java': LimitModifiers(time=2000),
        },
        groups=[report(['cpp'], 1000, 450), report(['java'], 2000, 950)],
        baseEstimate=report(['cpp', 'java'], 1000, 450),
    )


def test_rows_are_base_then_groups():
    state = LimitEditorState(_profile())
    assert [state.label(t) for t in state.targets] == ['(base)', 'cpp', 'java']
    assert state.step == 100


def test_step_snaps_to_the_resolution():
    state = LimitEditorState(_profile())
    state.move(1)
    state.step_by(1)
    assert state.time_limit(0) == 1100
    state.set_time_limit(1150)
    state.step_by(-1)
    assert state.time_limit(0) == 1100
    state.set_time_limit(1150)
    state.step_by(1)
    assert state.time_limit(0) == 1200
    assert state.profile.modifiers['cpp'].time == 1200


def test_step_never_goes_below_one_step():
    state = LimitEditorState(_profile())
    state.set_time_limit(100)
    state.step_by(-1)
    assert state.time_limit(None) == 100


def test_typing_sets_an_exact_value():
    state = LimitEditorState(_profile())
    state.move(2)
    for ch in '2345':
        state.type_key(ch)
    state.type_key('\x7f')
    state.commit_typed()
    assert state.time_limit(1) == 234
    assert state.typed is None


def test_revert_and_reset():
    state = LimitEditorState(_profile())
    state.move(1)
    state.set_time_limit(1500)
    state.revert()
    assert state.time_limit(0) == 1000
    assert not state.is_dirty()
    state.set_time_limit(1500)
    state.move(1)
    state.set_time_limit(2500)
    state.reset()
    assert state.profile == _profile()


def test_render_marks_hand_set_rows():
    state = LimitEditorState(_profile())
    state.move(1)
    state.set_time_limit(1300)
    text = ''.join(t for _, t in state.render_fragments())
    assert '1300 ms  (estimated 1000 ms)' in text
    assert text.count('❯') == 1


async def test_editor_steps_and_saves():
    with create_pipe_input() as inp:
        inp.send_text('\x1b[B')  # down -> cpp
        inp.send_text('++')  # 1000 -> 1200
        inp.send_text('\r')  # save
        result = await prompt_limits_edit(_profile(), input=inp, output=DummyOutput())
    assert result is not None
    assert result.groups[0].timeLimit == 1200
    assert result.groups[0].estimatedTimeLimit == 1000
    assert result.modifiers['cpp'].time == 1200


async def test_editor_typed_value_then_save():
    with create_pipe_input() as inp:
        inp.send_text('j')
        inp.send_text('j')  # java
        inp.send_text('1800\r')  # type + commit
        inp.send_text('\r')  # save
        result = await prompt_limits_edit(_profile(), input=inp, output=DummyOutput())
    assert result is not None
    assert result.groups[1].timeLimit == 1800


async def test_editor_cancel_returns_none():
    with create_pipe_input() as inp:
        inp.send_text('+q')
        result = await prompt_limits_edit(_profile(), input=inp, output=DummyOutput())
    assert result is None


def test_preview_renders_the_check_column():
    render = timing_limit_editor.build_preview(width=200)
    text = render(_profile()).value
    assert 'Preview' in text
    assert 'Check' in text


# --- the command -------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


@pytest.fixture(autouse=True)
def _restore_event_loop():
    # The CLI tests here go through `syncer`; leave a usable loop behind for
    # whatever runs next in the same process (see test_timing_dry.py).
    yield
    asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture(autouse=True)
def _skip_preset_check():
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


def _save(profile: LimitsProfile, name: str = 'local'):
    path = package.get_limits_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(utils.model_to_yaml(profile))
    return path


def _edit_to(time_limit: int):
    async def fake_prompt(profile, preview=None, **kwargs):
        state = LimitEditorState(profile)
        state.move(1)
        state.set_time_limit(time_limit)
        return state.profile

    return mock.patch.object(timing_limit_editor, 'prompt_limits_edit', fake_prompt)


def test_edit_writes_the_profile(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    path = _save(_profile())
    with _edit_to(1200):
        result = runner.invoke(cli.app, ['time', '-e'])
    assert result.exit_code == 0, result.output
    saved = limits_info.get_saved_limits_profile('local')
    assert saved.groups[0].timeLimit == 1200
    assert saved.groups[0].estimatedTimeLimit == 1000
    assert path.exists()
    # Raised above the estimate, so the slow solution is unverified now.
    assert 'rbx run -p local' in result.output


def test_edit_dry_writes_nothing(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    path = _save(_profile())
    before = path.read_text()
    with _edit_to(1200):
        result = runner.invoke(cli.app, ['time', '-e', '--dry'])
    assert result.exit_code == 0, result.output
    assert path.read_text() == before


def test_edit_without_a_profile_fails(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result = runner.invoke(cli.app, ['time', '-e', '-p', 'nope'])
    assert result.exit_code == 1
    assert 'rbx time -p nope' in result.output


def test_edit_refuses_a_profile_that_was_not_estimated(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _save(LimitsProfile(timeLimit=1000))
    result = runner.invoke(cli.app, ['time', '-e'])
    assert result.exit_code == 1
    assert 'was not estimated' in result.output


def test_edit_refuses_estimation_flags(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _save(_profile())
    result = runner.invoke(cli.app, ['time', '-e', '--auto', '-s', 'custom'])
    assert result.exit_code == 1
    assert '--strategy, --auto' in result.output
