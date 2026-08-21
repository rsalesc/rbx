"""How a violated upper bound sends the setter back to the picker.

A violation is evidence, not a verdict: the picker re-opens knowing what the
check found, and the setter regroups, keeps the limits anyway, or gives up. What
matters is which of those ends the loop, and what is left on disk afterwards.
"""

from typing import List, Optional
from unittest import mock

from rbx.box import timing, timing_group_picker, timing_validation


def _context(languages: List[str], upper: Optional[List] = None) -> mock.Mock:
    ctx = mock.Mock()
    ctx.console = mock.Mock()
    ctx.all_languages = languages
    ctx.can_prompt = len(languages) > 1
    ctx.upper_solutions = upper if upper is not None else [mock.Mock()]
    return ctx


def _assignment(force: bool = False) -> timing_group_picker.GroupAssignment:
    return timing_group_picker.GroupAssignment(numbers={'cpp': 1}, force=force)


def _picked(force: bool = False) -> timing._Picked:  # noqa: SLF001
    return timing._Picked(assignment=_assignment(force), force=force)  # noqa: SLF001


def _profile(time_limit: int = 1000) -> timing.TimingProfile:
    from rbx.box.schema import TimingMultipliers

    return timing.TimingProfile(
        timeLimit=time_limit,
        multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
    )


def _outcome(ok: bool) -> timing._ValidationOutcome:  # noqa: SLF001
    if ok:
        return timing._ValidationOutcome()  # noqa: SLF001
    return timing._ValidationOutcome(  # noqa: SLF001
        violating=[(mock.Mock(), 1200)]
    )


async def _run_loop(
    ctx,
    picks: List[Optional[timing._Picked]],  # noqa: SLF001
    outcomes: List[bool],
    auto: bool = False,
    skip_slow: bool = False,
):
    """Drive the loop with a scripted sequence of picks and check outcomes."""
    ctx.prompt = mock.AsyncMock(side_effect=picks)
    ctx.build = mock.Mock(side_effect=lambda *a, **kw: _profile())
    validated = []

    async def _validate(*args, **kwargs):
        return _outcome(
            outcomes[len(validated)] if len(validated) < len(outcomes) else True
        )

    async def _counting_validate(*args, **kwargs):
        outcome = await _validate(*args, **kwargs)
        validated.append(outcome)
        return outcome

    with (
        mock.patch('rbx.box.timing._validate_upper_bound', _counting_validate),
        mock.patch('rbx.box.timing._report_validation_outcome'),
    ):
        profile = await timing._estimate_and_validate(  # noqa: SLF001
            ctx,
            timing_validation.SlowKnowledge(),
            auto=auto,
            skip_slow=skip_slow,
            check=False,
            detailed=False,
            runs=0,
        )
    return profile, validated


async def test_a_passing_check_ends_the_loop_at_once():
    ctx = _context(['cpp', 'py'])
    profile, validated = await _run_loop(ctx, [_picked()], [True])
    assert profile is not None
    assert ctx.prompt.await_count == 1
    assert len(validated) == 1


async def test_a_violation_reopens_the_picker_and_the_repick_is_returned():
    ctx = _context(['cpp', 'py'])
    profile, validated = await _run_loop(ctx, [_picked(), _picked()], [False, True])
    assert profile is not None
    # Asked twice: the second time with the violation to override.
    assert ctx.prompt.await_count == 2
    assert ctx.prompt.await_args_list[0].kwargs['allow_force'] is False
    assert ctx.prompt.await_args_list[1].kwargs['allow_force'] is True
    assert len(validated) == 2


async def test_forcing_past_a_violation_stops_validating():
    ctx = _context(['cpp', 'py'])
    profile, validated = await _run_loop(
        ctx, [_picked(), _picked(force=True)], [False, True]
    )
    assert profile is not None
    assert ctx.prompt.await_count == 2
    # The second pick was an override, so nothing was checked again.
    assert len(validated) == 1
    assert ctx.build.call_args.kwargs['force'] is True


async def test_cancelling_the_picker_returns_nothing():
    ctx = _context(['cpp', 'py'])
    profile, _ = await _run_loop(ctx, [_picked(), None], [False])
    assert profile is None
    printed = ' '.join(str(call) for call in ctx.console.print.call_args_list)
    assert 'cancelled' in printed


async def test_a_violation_with_no_picker_warns_and_still_produces_a_profile():
    # --auto has no picker to go back to, so the violation is recorded and the
    # profile is written with it rather than lost.
    ctx = _context(['cpp', 'py'])
    profile, validated = await _run_loop(ctx, [_picked()], [False], auto=True)
    assert profile is not None
    assert len(validated) == 1
    assert ctx.build.call_args.kwargs['force'] is True
    printed = ' '.join(str(call) for call in ctx.console.print.call_args_list)
    assert 'upperValidation' in printed


async def test_a_single_language_problem_has_no_picker_either():
    ctx = _context(['cpp'])
    profile, _ = await _run_loop(ctx, [_picked()], [False])
    assert profile is not None
    assert ctx.build.call_args.kwargs['force'] is True


async def test_skip_slow_never_validates():
    ctx = _context(['cpp', 'py'])
    profile, validated = await _run_loop(ctx, [_picked()], [False], skip_slow=True)
    assert profile is not None
    assert validated == []


async def test_a_profile_with_nothing_to_check_is_returned_as_is():
    # No slow solutions, so there is no upper bound to validate against.
    ctx = _context(['cpp', 'py'], upper=[])
    profile, validated = await _run_loop(ctx, [_picked()], [False])
    assert profile is not None
    assert validated == []


async def _drive(ctx, picks, auto=False):
    return await timing._estimate_and_validate(  # noqa: SLF001
        ctx,
        timing_validation.SlowKnowledge(),
        auto=auto,
        skip_slow=False,
        check=False,
        detailed=False,
        runs=0,
    )


async def test_an_unbuildable_grouping_is_asked_about_again():
    # Nothing but the grouping can make a limit impossible, so the setter gets
    # to pick another one rather than being dropped out of the command.
    ctx = _context(['cpp', 'py'])
    ctx.prompt = mock.AsyncMock(side_effect=[_picked(), None])
    ctx.build = mock.Mock(return_value=None)
    profile = await _drive(ctx, None)
    assert profile is None
    assert ctx.prompt.await_count == 2
    # The second prompt offers the override, since the first grouping failed.
    assert ctx.prompt.await_args_list[1].kwargs['allow_force'] is True


async def test_an_unbuildable_grouping_with_no_picker_ends_the_loop():
    ctx = _context(['cpp', 'py'])
    ctx.prompt = mock.AsyncMock(return_value=_picked())
    ctx.build = mock.Mock(return_value=None)
    profile = await _drive(ctx, None, auto=True)
    assert profile is None
