"""`rbx time --run-all` keeps what the extra run found in the limits profile.

The verdicts live in a `runs` section of their own, after `solutions`: they are
not what the limit was computed from, but they are part of what the profile says
about the package at that limit.
"""

import pathlib
from typing import List
from unittest import mock

import pytest
import yaml

from rbx.box import limits_info, timing
from rbx.box.schema import (
    EstimationSolutionTiming,
    ExpectedOutcome,
    InferenceRole,
    LimitsProfile,
    LimitsProfileRun,
    Solution,
)
from rbx.box.solutions import SolutionOutcomeStatus
from rbx.box.testing import testing_package
from rbx.grading.steps import Outcome
from tests.rbx.box.conftest import make_evaluation
from tests.rbx.box.test_timing_run_all_cli import _compute


def _run(path: str = 'sols/wa.cpp', **kwargs) -> LimitsProfileRun:
    fields = dict(
        path=path,
        language='cpp',
        timeLimit=1000,
        expectedOutcome=ExpectedOutcome.WRONG_ANSWER,
        outcome=Outcome.WRONG_ANSWER,
        matchesExpectation=True,
        time=120,
    )
    fields.update(kwargs)
    return LimitsProfileRun(**fields)


def test_the_runs_go_in_their_own_section_after_the_solutions():
    profile = LimitsProfile(
        timeLimit=1000,
        solutions=[
            EstimationSolutionTiming(
                path='sols/ac.cpp', language='cpp', role=InferenceRole.LOWER, time=300
            )
        ],
        runs=[_run()],
    )

    text = limits_info.profile_to_yaml(profile)

    assert text.index(limits_info.SOLUTIONS_HEADER) < text.index(
        limits_info.RUNS_HEADER
    )
    assert text.endswith(
        limits_info.RUNS_HEADER + 'runs:\n'
        '- {path: sols/wa.cpp, language: cpp, timeLimit: 1000, '
        'expectedOutcome: WRONG_ANSWER, outcome: wrong-answer, '
        'matchesExpectation: true, time: 120}\n'
    )


def test_the_runs_section_reads_back():
    profile = LimitsProfile(
        timeLimit=1000,
        runs=[_run(), _run('sols/slow.cpp', time=None, complete=False)],
    )

    loaded = LimitsProfile.model_validate(
        yaml.safe_load(limits_info.profile_to_yaml(profile))
    )

    assert loaded == profile


def test_a_profile_without_runs_has_no_runs_section():
    text = limits_info.profile_to_yaml(LimitsProfile(timeLimit=1000))

    assert 'runs' not in text


async def _record(
    solution: Solution, evals, status: SolutionOutcomeStatus, limit: int
) -> List[LimitsProfileRun]:
    result = mock.Mock()
    result.skeleton.entries = [object() for _ in evals]
    with (
        mock.patch(
            'rbx.box.timing.consume_and_key_evaluation_items',
            return_value={
                str(solution.path): {
                    'main': [mock.AsyncMock(return_value=e) for e in evals]
                }
            },
        ),
        mock.patch(
            'rbx.box.timing.get_solution_outcome_report',
            return_value=mock.Mock(status=status),
        ),
        mock.patch('rbx.box.timing.find_language_name', return_value='cpp'),
    ):
        return await timing._record_runs(  # noqa: SLF001
            result, [solution], {'cpp': limit}
        )


async def test_each_solution_is_recorded_with_its_worst_verdict_and_slowest_time():
    solution = Solution(
        path=pathlib.Path('sols/wa.cpp'),
        language='cpp',
        outcome=ExpectedOutcome.WRONG_ANSWER,
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=200),
        make_evaluation(Outcome.WRONG_ANSWER, time_ms=50),
    ]

    runs = await _record(solution, evals, SolutionOutcomeStatus.OK, 1500)

    assert runs == [_run(timeLimit=1500, time=200)]


async def test_a_run_cut_short_is_marked_incomplete():
    solution = Solution(
        path=pathlib.Path('sols/wa.cpp'),
        language='cpp',
        outcome=ExpectedOutcome.ACCEPTED,
    )
    evals = [
        make_evaluation(Outcome.WRONG_ANSWER, time_ms=50),
        make_evaluation(Outcome.SKIPPED, time_ms=None),
    ]

    runs = await _record(
        solution, evals, SolutionOutcomeStatus.UNEXPECTED_VERDICTS, 1000
    )

    assert runs == [
        _run(
            expectedOutcome=ExpectedOutcome.ACCEPTED,
            matchesExpectation=False,
            time=50,
            complete=False,
        )
    ]


def _recording(records: List[LimitsProfileRun], ok: bool = True) -> mock.AsyncMock:
    async def run_remaining(*args, recorded=None, **kwargs):
        recorded.extend(records)
        return ok

    return mock.AsyncMock(side_effect=run_remaining)


def _saved(tmp_path: pathlib.Path) -> LimitsProfile:
    return LimitsProfile.model_validate(
        yaml.safe_load((tmp_path / 'local.yml').read_text())
    )


async def test_the_profile_is_rewritten_with_the_runs(
    tmp_path: pathlib.Path, testing_pkg: testing_package.TestingPackage
):
    await _compute(tmp_path, run_all=True, run_remaining=_recording([_run()]))

    saved = _saved(tmp_path)
    assert saved.timeLimit == 1000
    assert saved.runs == [_run()]


async def test_a_failing_run_is_still_recorded(
    tmp_path: pathlib.Path, testing_pkg: testing_package.TestingPackage
):
    import typer

    bad = _run(matchesExpectation=False, outcome=Outcome.ACCEPTED)
    with pytest.raises(typer.Exit):
        await _compute(
            tmp_path, run_all=True, run_remaining=_recording([bad], ok=False)
        )

    assert _saved(tmp_path).runs == [bad]


async def test_without_run_all_the_profile_has_no_runs(
    tmp_path: pathlib.Path, testing_pkg: testing_package.TestingPackage
):
    await _compute(tmp_path, run_all=False)

    assert _saved(tmp_path).runs is None


async def test_a_dry_run_records_nothing(
    tmp_path: pathlib.Path, testing_pkg: testing_package.TestingPackage
):
    await _compute(tmp_path, run_all=True, run_remaining=_recording([_run()]), dry=True)

    assert not (tmp_path / 'local.yml').exists()
