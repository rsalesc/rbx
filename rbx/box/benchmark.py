"""Benchmarking of the judging phase, behind `rbx run --benchmark`.

`rbx run` already reports how long each *solution* took. It says nothing about
how long *judging* took, and on a problem with a heavy checker the checker can
dominate the wall clock of a full run. This module turns the checker and
interactor timings that every evaluation now carries (see
`rbx.grading.steps.RunTiming`) into the two blocks `-b1` prints.

Every duration here is in seconds, and every name says so -- the renderer picks
between `formatting.get_formatted_time` (milliseconds) and
`formatting.get_formatted_time_in_seconds` on nothing but the name, and picking
the wrong one mislabels the unit instead of raising.

The timings themselves are captured unconditionally; the level only decides
whether anything is printed. See docs/plans/2026-08-28-run-benchmark-design.md.
"""

import dataclasses
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from rbx.box.schema import Solution
from rbx.box.testcase_schema import TestcaseEntry
from rbx.grading.steps import Evaluation, Outcome, RunTiming

if TYPE_CHECKING:
    # Imported only for typing -- `rbx.box.solutions` imports this module at
    # runtime, and importing it back here would close the cycle.
    from rbx.box.solutions import SolutionReportSkeleton


class BenchmarkLevel(Enum):
    """How much of a run to benchmark. Mirrors `VerificationLevel`."""

    NONE = 0
    SOLUTIONS = 1


def _timing_seconds(timing: Optional[RunTiming]) -> Optional[float]:
    """The measured CPU seconds, or `None` when the program was not measured.

    A `RunTiming` can exist with its clocks unset, so the inner `None` needs the
    same guard as the outer one. `None` is preserved rather than flattened to
    `0.0`: a checker that never ran and a checker that ran instantaneously are
    different facts, and only one of them may be printed as a measurement.
    """
    if timing is None:
        return None
    return timing.time


def checker_time_seconds(eval: Evaluation) -> Optional[float]:
    """The checker's CPU seconds on this testcase, `None` if unmeasured.

    Unmeasured means no checker ran (a communication problem may have none) or
    the sandbox reported no clock. It contributes nothing to a sum, but a caller
    that renders it on its own must keep the `None` rather than print `0.0 s`.
    """
    return _timing_seconds(eval.result.checker_timing)


def interactor_time_seconds(eval: Evaluation) -> Optional[float]:
    """The interactor's CPU seconds on this testcase, `None` if unmeasured.

    Unmeasured means the problem is not interactive, or the sandbox reported no
    clock. As with the checker, `None` must survive to the renderer.
    """
    return _timing_seconds(eval.result.interactor_timing)


def was_judged(eval: Evaluation) -> bool:
    """Whether this testcase actually ran.

    A `--fail-fast` run persists a `SKIPPED` evaluation for every testcase after
    the one that decided the verdict, with no time on it at all.
    """
    return eval.result.outcome != Outcome.SKIPPED and eval.log.time is not None


def judging_time_seconds(eval: Evaluation) -> Optional[float]:
    """Solution time + checker time + interactor time, in seconds.

    `None` when the solution itself was never timed: there is no judging time
    for a testcase that never ran. An unmeasured checker or interactor only
    contributes nothing to the sum -- it does not make the whole `None`.
    """
    if not was_judged(eval):
        return None
    # `was_judged` has already established that `log.time` is set, so the
    # fallback is unreachable -- it is kept only so that this arithmetic reads
    # uniformly with the two genuinely optional terms beside it.
    return (
        (eval.log.time or 0.0)
        + (checker_time_seconds(eval) or 0.0)
        + (interactor_time_seconds(eval) or 0.0)
    )


@dataclasses.dataclass
class TestcaseJudging:
    entry: TestcaseEntry
    judging_time_seconds: float
    solution_time_seconds: float
    # `None` means unmeasured. See `checker_time_seconds`.
    checker_time_seconds: Optional[float]
    interactor_time_seconds: Optional[float]


@dataclasses.dataclass
class SolutionBenchmark:
    solution: Solution
    slowest_testcase: TestcaseJudging
    total_judging_time_seconds: float
    # `None` when no judged testcase measured that program at all. A genuine
    # total of `0.0` is a measurement and stays `0.0`.
    total_checker_time_seconds: Optional[float]
    total_interactor_time_seconds: Optional[float]
    judged: int
    total_testcases: int

    @property
    def partial(self) -> bool:
        """Whether some testcases never ran, making every total a lower bound."""
        return self.judged < self.total_testcases


@dataclasses.dataclass
class ProblemBenchmark:
    slowest_to_judge: SolutionBenchmark
    most_checker_time: SolutionBenchmark
    slowest_testcase: TestcaseJudging
    partial: bool


def _total_seconds(values: List[Optional[float]]) -> Optional[float]:
    """Sum the measured values, or `None` if none of them was measured."""
    measured = [value for value in values if value is not None]
    if not measured:
        return None
    return sum(measured)


def build_solution_benchmark(
    solution: Solution,
    skeleton: 'SolutionReportSkeleton',
    evals: List[Evaluation],
) -> Optional[SolutionBenchmark]:
    """Aggregate one solution's evaluations, or None if none of them ran.

    Assumes ``evals`` is a prefix of ``skeleton.entries`` with no gaps -- the
    same assumption `_get_evals_per_group` documents, and true for the same
    reason: the reporters append in entry order, so a partial run is a prefix.
    A gap would pair every later evaluation with the wrong entry, and here that
    misnames the slowest testcase -- which is the one thing this report exists
    to name. A caller that can skip an entry must pass entries alongside their
    evaluations instead of relying on position.
    """
    judgings: List[TestcaseJudging] = []
    for eval, entry in zip(evals, skeleton.entries):
        total = judging_time_seconds(eval)
        if total is None:
            continue
        judgings.append(
            TestcaseJudging(
                entry=entry.group_entry,
                judging_time_seconds=total,
                # Unreachable fallback, as above: `judging_time_seconds`
                # returning non-None already implies `log.time` is set.
                solution_time_seconds=eval.log.time or 0.0,
                checker_time_seconds=checker_time_seconds(eval),
                interactor_time_seconds=interactor_time_seconds(eval),
            )
        )

    if not judgings:
        return None

    return SolutionBenchmark(
        solution=solution,
        slowest_testcase=max(judgings, key=lambda j: j.judging_time_seconds),
        total_judging_time_seconds=sum(j.judging_time_seconds for j in judgings),
        total_checker_time_seconds=_total_seconds(
            [j.checker_time_seconds for j in judgings]
        ),
        total_interactor_time_seconds=_total_seconds(
            [j.interactor_time_seconds for j in judgings]
        ),
        judged=len(judgings),
        # `evals` can be shorter than the skeleton mid-run, so the denominator
        # is the testset, not the list handed in.
        total_testcases=len(skeleton.entries),
    )


def build_problem_benchmark(
    benchmarks: List[SolutionBenchmark],
) -> Optional[ProblemBenchmark]:
    """Rank the per-solution benchmarks, or None if there are none to rank."""
    if not benchmarks:
        return None
    return ProblemBenchmark(
        slowest_to_judge=max(benchmarks, key=lambda b: b.total_judging_time_seconds),
        most_checker_time=max(
            benchmarks, key=lambda b: b.total_checker_time_seconds or 0.0
        ),
        slowest_testcase=max(
            (b.slowest_testcase for b in benchmarks),
            key=lambda j: j.judging_time_seconds,
        ),
        partial=any(b.partial for b in benchmarks),
    )
