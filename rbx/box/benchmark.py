"""Benchmarking of the judging phase, behind `rbx run --benchmark`.

`rbx run` already reports how long each *solution* took. It says nothing about
how long *judging* took, and on a problem with a heavy checker the checker can
dominate the wall clock of a full run. This module turns the checker and
interactor timings that every evaluation now carries (see
`rbx.grading.steps.RunTiming`) into the two blocks `-b1` prints.

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


def _timing_seconds(timing: Optional[RunTiming]) -> float:
    """An unmeasured program contributes nothing, rather than a zero.

    A `RunTiming` can exist with its clocks unset, so the inner `None` needs
    the same guard as the outer one.
    """
    if timing is None or timing.time is None:
        return 0.0
    return timing.time


def checker_time(eval: Evaluation) -> float:
    return _timing_seconds(eval.result.checker_timing)


def interactor_time(eval: Evaluation) -> float:
    return _timing_seconds(eval.result.interactor_timing)


def was_judged(eval: Evaluation) -> bool:
    """Whether this testcase actually ran.

    A `--fail-fast` run persists a `SKIPPED` evaluation for every testcase after
    the one that decided the verdict, with no time on it at all.
    """
    return eval.result.outcome != Outcome.SKIPPED and eval.log.time is not None


def judging_time(eval: Evaluation) -> Optional[float]:
    """Solution time + checker time + interactor time, in seconds.

    `None` when the solution itself was never timed: there is no judging time
    for a testcase that never ran.
    """
    if not was_judged(eval):
        return None
    return (eval.log.time or 0.0) + checker_time(eval) + interactor_time(eval)


@dataclasses.dataclass
class TestcaseJudging:
    entry: TestcaseEntry
    judging_time: float
    solution_time: float
    checker_time: float
    interactor_time: float


@dataclasses.dataclass
class SolutionBenchmark:
    solution: Solution
    slowest: TestcaseJudging
    total_judging_time: float
    total_checker_time: float
    total_interactor_time: float
    judged: int
    total: int

    @property
    def partial(self) -> bool:
        """Whether some testcases never ran, making every total a lower bound."""
        return self.judged < self.total


@dataclasses.dataclass
class ProblemBenchmark:
    slowest_to_judge: SolutionBenchmark
    most_checker_time: SolutionBenchmark
    slowest_testcase: TestcaseJudging
    partial: bool


def build_solution_benchmark(
    solution: Solution,
    skeleton: 'SolutionReportSkeleton',
    evals: List[Evaluation],
) -> Optional[SolutionBenchmark]:
    """Aggregate one solution's evaluations, or None if none of them ran."""
    judgings: List[TestcaseJudging] = []
    for eval, entry in zip(evals, skeleton.entries):
        total = judging_time(eval)
        if total is None:
            continue
        judgings.append(
            TestcaseJudging(
                entry=entry.group_entry,
                judging_time=total,
                solution_time=eval.log.time or 0.0,
                checker_time=checker_time(eval),
                interactor_time=interactor_time(eval),
            )
        )

    if not judgings:
        return None

    return SolutionBenchmark(
        solution=solution,
        slowest=max(judgings, key=lambda j: j.judging_time),
        total_judging_time=sum(j.judging_time for j in judgings),
        total_checker_time=sum(j.checker_time for j in judgings),
        total_interactor_time=sum(j.interactor_time for j in judgings),
        judged=len(judgings),
        # `evals` can be shorter than the skeleton mid-run, so the denominator
        # is the testset, not the list handed in.
        total=len(skeleton.entries),
    )


def build_problem_benchmark(
    benchmarks: List[SolutionBenchmark],
) -> Optional[ProblemBenchmark]:
    if not benchmarks:
        return None
    return ProblemBenchmark(
        slowest_to_judge=max(benchmarks, key=lambda b: b.total_judging_time),
        most_checker_time=max(benchmarks, key=lambda b: b.total_checker_time),
        slowest_testcase=max(
            (b.slowest for b in benchmarks), key=lambda j: j.judging_time
        ),
        partial=any(b.partial for b in benchmarks),
    )
