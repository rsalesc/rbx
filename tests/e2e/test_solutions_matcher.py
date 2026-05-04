"""Unit tests for ``check_solutions``.

These tests build a fake on-disk ``.box/runs/`` tree (skeleton.yml +
``.eval`` files) using the real Pydantic models, so the matcher exercises
the same load path as production code.
"""

import pathlib
from typing import Dict, List

import pytest

from rbx import utils
from rbx.box.generation_schema import (
    GenerationMetadata,
    GenerationTestcaseEntry,
)
from rbx.box.schema import ExpectedOutcome
from rbx.box.solutions import (
    GroupSkeleton,
    SolutionReportSkeleton,
    SolutionSkeleton,
)
from rbx.box.testcase_schema import TestcaseEntry
from rbx.grading.steps import (
    CheckerResult,
    Evaluation,
    Outcome,
)
from rbx.grading.steps import (
    TestcaseIO as _TestcaseIO,
)
from rbx.grading.steps import (
    TestcaseLog as _TestcaseLog,
)
from tests.e2e.assertions import AssertionContext, check_solutions
from tests.e2e.spec import SolutionMatcher


def _ctx(root: pathlib.Path) -> AssertionContext:
    return AssertionContext(package_root=root, stdout='', stderr='')


def _eval(outcome: Outcome) -> Evaluation:
    return Evaluation(
        result=CheckerResult(outcome=outcome, message=''),
        testcase=_TestcaseIO(index=0),
        log=_TestcaseLog(),
    )


def _make_fake_runs_dir(
    package_root: pathlib.Path,
    verdicts: Dict[str, Dict[str, List[Outcome]]],
) -> None:
    """Build ``<package_root>/.box/runs/`` with a valid skeleton + .eval set.

    ``verdicts`` shape: ``{solution_path: {group_name: [outcome_per_idx, ...]}}``.
    All solutions must share the same group structure.
    """
    runs_dir = package_root / '.box' / 'runs'
    runs_dir.mkdir(parents=True, exist_ok=True)

    sol_paths = list(verdicts.keys())
    if not sol_paths:
        raise ValueError('verdicts must be non-empty')
    groups_for_first = verdicts[sol_paths[0]]
    group_names = list(groups_for_first.keys())

    # Build group skeletons (testcases are placeholders; only count matters
    # for our purposes).
    group_skeletons: List[GroupSkeleton] = []
    for gname in group_names:
        n = len(groups_for_first[gname])
        group_skeletons.append(
            GroupSkeleton(name=gname, score=0, deps=[], testcases=[])
        )
        # Note: skeleton.testcases not strictly needed here; the matcher
        # iterates groups and reads len(group.testcases). Populate it.
        # We mirror the per-group counts via Testcase placeholders.
        from rbx.box.schema import Testcase as _Testcase

        group_skeletons[-1].testcases = [
            _Testcase(inputPath=pathlib.Path(f'tests/{gname}/{i:03d}.in'))
            for i in range(n)
        ]

    # Build entries: one per (group, idx).
    entries: List[GenerationTestcaseEntry] = []
    for gname in group_names:
        n = len(groups_for_first[gname])
        for i in range(n):
            tc_entry = TestcaseEntry(group=gname, index=i)
            from rbx.box.schema import Testcase as _Testcase

            tc = _Testcase(inputPath=pathlib.Path(f'tests/{gname}/{i:03d}.in'))
            entries.append(
                GenerationTestcaseEntry(
                    group_entry=tc_entry,
                    subgroup_entry=tc_entry,
                    metadata=GenerationMetadata(
                        copied_to=tc,
                    ),
                )
            )

    sol_skeletons: List[SolutionSkeleton] = []
    for i, sol_path in enumerate(sol_paths):
        sol_runs_dir = (runs_dir / str(i)).resolve()
        sol_runs_dir.mkdir(parents=True, exist_ok=True)
        sol_skeletons.append(
            SolutionSkeleton(
                path=pathlib.Path(sol_path),
                outcome=ExpectedOutcome.ANY,
                runs_dir=sol_runs_dir,
            )
        )

        for gname, outcomes in verdicts[sol_path].items():
            (sol_runs_dir / gname).mkdir(parents=True, exist_ok=True)
            for idx, oc in enumerate(outcomes):
                eval_path = sol_runs_dir / gname / f'{idx:03d}.eval'
                eval_path.write_text(utils.model_to_yaml(_eval(oc)))

    skeleton = SolutionReportSkeleton(
        solutions=sol_skeletons,
        entries=entries,
        groups=group_skeletons,
        limits={},
        compiled_solutions={p: f'digest-{i}' for i, p in enumerate(sol_paths)},
        verification=4,  # FULL; arbitrary
    )
    (runs_dir / 'skeleton.yml').write_text(utils.model_to_yaml(skeleton))


# ---------------------------------------------------------------------------
# Bare-verdict / star-only forms
# ---------------------------------------------------------------------------


def test_bare_star_pass(tmp_path):
    _make_fake_runs_dir(
        tmp_path,
        {'sols/main.cpp': {'samples': [Outcome.ACCEPTED], 'main': [Outcome.ACCEPTED]}},
    )
    matcher = SolutionMatcher(star=ExpectedOutcome.ACCEPTED, entries={})
    check_solutions(_ctx(tmp_path), {'sols/main.cpp': matcher})


def test_bare_star_fail_reports_specifics(tmp_path):
    _make_fake_runs_dir(
        tmp_path,
        {
            'sols/main.cpp': {
                'samples': [Outcome.ACCEPTED],
                'main': [Outcome.WRONG_ANSWER],
            }
        },
    )
    matcher = SolutionMatcher(star=ExpectedOutcome.ACCEPTED, entries={})
    with pytest.raises(AssertionError) as exc:
        check_solutions(_ctx(tmp_path), {'sols/main.cpp': matcher})
    msg = str(exc.value)
    assert 'sols/main.cpp' in msg
    assert 'main' in msg
    assert 'ACCEPTED' in msg
    assert 'wrong-answer' in msg or 'WA' in msg or 'WRONG_ANSWER' in msg


# ---------------------------------------------------------------------------
# Per-group entries and overrides
# ---------------------------------------------------------------------------


def test_star_with_per_group_override(tmp_path):
    _make_fake_runs_dir(
        tmp_path,
        {
            'sols/wa.cpp': {
                'samples': [Outcome.ACCEPTED],
                'main': [Outcome.WRONG_ANSWER, Outcome.WRONG_ANSWER],
            }
        },
    )
    matcher = SolutionMatcher(
        star=ExpectedOutcome.WRONG_ANSWER,
        entries={'samples': ExpectedOutcome.ACCEPTED},
    )
    check_solutions(_ctx(tmp_path), {'sols/wa.cpp': matcher})


def test_per_group_only_pass(tmp_path):
    _make_fake_runs_dir(
        tmp_path,
        {
            'sols/x.cpp': {
                'samples': [Outcome.ACCEPTED],
                'main': [Outcome.WRONG_ANSWER],
            }
        },
    )
    matcher = SolutionMatcher(
        star=None,
        entries={
            'samples': ExpectedOutcome.ACCEPTED,
            'main': ExpectedOutcome.WRONG_ANSWER,
        },
    )
    check_solutions(_ctx(tmp_path), {'sols/x.cpp': matcher})


def test_unknown_group_raises(tmp_path):
    _make_fake_runs_dir(
        tmp_path,
        {'sols/main.cpp': {'samples': [Outcome.ACCEPTED]}},
    )
    matcher = SolutionMatcher(
        star=None, entries={'nonexistent': ExpectedOutcome.ACCEPTED}
    )
    with pytest.raises(AssertionError, match='nonexistent'):
        check_solutions(_ctx(tmp_path), {'sols/main.cpp': matcher})


# ---------------------------------------------------------------------------
# Per-test entries
# ---------------------------------------------------------------------------


def test_per_test_override_takes_precedence(tmp_path):
    # Group 'main' is declared WA at the group level, but per-test entry
    # ``main/0: ac`` overrides that for index 0; index 1 still satisfies the
    # group-level WA.
    _make_fake_runs_dir(
        tmp_path,
        {
            'sols/x.cpp': {
                'samples': [Outcome.ACCEPTED],
                'main': [Outcome.ACCEPTED, Outcome.WRONG_ANSWER],
            }
        },
    )
    matcher = SolutionMatcher(
        star=None,
        entries={
            'samples': ExpectedOutcome.ACCEPTED,
            'main': ExpectedOutcome.WRONG_ANSWER,
            'main/0': ExpectedOutcome.ACCEPTED,
        },
    )
    check_solutions(_ctx(tmp_path), {'sols/x.cpp': matcher})


def test_per_test_failure_reports_path(tmp_path):
    _make_fake_runs_dir(
        tmp_path,
        {'sols/main.cpp': {'samples': [Outcome.WRONG_ANSWER]}},
    )
    matcher = SolutionMatcher(
        star=None, entries={'samples/0': ExpectedOutcome.ACCEPTED}
    )
    with pytest.raises(AssertionError) as exc:
        check_solutions(_ctx(tmp_path), {'sols/main.cpp': matcher})
    msg = str(exc.value)
    assert 'samples/0' in msg
    assert 'sols/main.cpp' in msg


# ---------------------------------------------------------------------------
# Sparse coverage
# ---------------------------------------------------------------------------


def test_sparse_unmentioned_groups_ignored(tmp_path):
    # 'main' has WA but the matcher only asserts 'samples'.
    _make_fake_runs_dir(
        tmp_path,
        {
            'sols/x.cpp': {
                'samples': [Outcome.ACCEPTED],
                'main': [Outcome.WRONG_ANSWER],
            }
        },
    )
    matcher = SolutionMatcher(star=None, entries={'samples': ExpectedOutcome.ACCEPTED})
    check_solutions(_ctx(tmp_path), {'sols/x.cpp': matcher})


def test_sparse_per_test_only_does_not_check_group(tmp_path):
    # Only 'main/0' is asserted; 'main/1' and 'samples' can have any verdict.
    _make_fake_runs_dir(
        tmp_path,
        {
            'sols/x.cpp': {
                'samples': [Outcome.WRONG_ANSWER],
                'main': [Outcome.ACCEPTED, Outcome.WRONG_ANSWER],
            }
        },
    )
    matcher = SolutionMatcher(star=None, entries={'main/0': ExpectedOutcome.ACCEPTED})
    check_solutions(_ctx(tmp_path), {'sols/x.cpp': matcher})


# ---------------------------------------------------------------------------
# Unknown solution
# ---------------------------------------------------------------------------


def test_unknown_solution_raises(tmp_path):
    _make_fake_runs_dir(
        tmp_path,
        {'sols/main.cpp': {'samples': [Outcome.ACCEPTED]}},
    )
    matcher = SolutionMatcher(star=ExpectedOutcome.ACCEPTED, entries={})
    with pytest.raises(AssertionError, match='sols/missing.cpp'):
        check_solutions(_ctx(tmp_path), {'sols/missing.cpp': matcher})


# ---------------------------------------------------------------------------
# ExpectedOutcome.match() semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'outcome',
    [
        Outcome.WRONG_ANSWER,
        Outcome.RUNTIME_ERROR,
        Outcome.MEMORY_LIMIT_EXCEEDED,
        Outcome.OUTPUT_LIMIT_EXCEEDED,
        Outcome.TIME_LIMIT_EXCEEDED,
    ],
)
def test_incorrect_matches_all_failure_outcomes(tmp_path, outcome):
    _make_fake_runs_dir(
        tmp_path,
        {'sols/x.cpp': {'main': [outcome]}},
    )
    matcher = SolutionMatcher(star=ExpectedOutcome.INCORRECT, entries={})
    check_solutions(_ctx(tmp_path), {'sols/x.cpp': matcher})


def test_any_matches_any_outcome(tmp_path):
    _make_fake_runs_dir(
        tmp_path,
        {'sols/x.cpp': {'main': [Outcome.JUDGE_FAILED]}},
    )
    matcher = SolutionMatcher(star=ExpectedOutcome.ANY, entries={})
    check_solutions(_ctx(tmp_path), {'sols/x.cpp': matcher})


@pytest.mark.parametrize('outcome', [Outcome.ACCEPTED, Outcome.TIME_LIMIT_EXCEEDED])
def test_accepted_or_tle_matches_both(tmp_path, outcome):
    _make_fake_runs_dir(
        tmp_path,
        {'sols/x.cpp': {'main': [outcome]}},
    )
    matcher = SolutionMatcher(star=ExpectedOutcome.ACCEPTED_OR_TLE, entries={})
    check_solutions(_ctx(tmp_path), {'sols/x.cpp': matcher})


def test_accepted_or_tle_does_not_match_wa(tmp_path):
    _make_fake_runs_dir(
        tmp_path,
        {'sols/x.cpp': {'main': [Outcome.WRONG_ANSWER]}},
    )
    matcher = SolutionMatcher(star=ExpectedOutcome.ACCEPTED_OR_TLE, entries={})
    with pytest.raises(AssertionError):
        check_solutions(_ctx(tmp_path), {'sols/x.cpp': matcher})


# ---------------------------------------------------------------------------
# Group aggregation: 'worst' outcome is checked
# ---------------------------------------------------------------------------


def test_group_aggregation_uses_worst_outcome(tmp_path):
    # Group has [AC, WA]; group-level matcher 'ac' must fail because the
    # worst outcome (WA) does not match ACCEPTED.
    _make_fake_runs_dir(
        tmp_path,
        {'sols/x.cpp': {'main': [Outcome.ACCEPTED, Outcome.WRONG_ANSWER]}},
    )
    matcher = SolutionMatcher(star=None, entries={'main': ExpectedOutcome.ACCEPTED})
    with pytest.raises(AssertionError):
        check_solutions(_ctx(tmp_path), {'sols/x.cpp': matcher})
