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

import rich.console

from rbx.box.formatting import UNMEASURED, get_formatted_time_in_seconds
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


def timing_seconds(timing: Optional[RunTiming]) -> Optional[float]:
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
    return timing_seconds(eval.result.checker_timing)


def interactor_time_seconds(eval: Evaluation) -> Optional[float]:
    """The interactor's CPU seconds on this testcase, `None` if unmeasured.

    Unmeasured means the problem is not interactive, or the sandbox reported no
    clock. As with the checker, `None` must survive to the renderer.
    """
    return timing_seconds(eval.result.interactor_timing)


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


def _measurement(seconds: Optional[float]) -> str:
    """A duration in seconds, or the unmeasured marker when there is none.

    `None` never becomes `0.0 s` here: a checker that never ran and a checker
    that ran instantaneously read differently, and only the second is a claim
    about how long judging took.
    """
    if seconds is None:
        return UNMEASURED
    return get_formatted_time_in_seconds(seconds)


def _hilite(seconds: Optional[float]) -> str:
    return f'[hilite]{_measurement(seconds)}[/hilite]'


def print_solution_benchmark(
    console: rich.console.Console, bench: SolutionBenchmark
) -> None:
    """Print one solution's judging benchmark, under its report block.

    The console is passed in rather than taken from `rbx.console` so that the
    `--share` recording console gets these lines too.
    """
    slowest = bench.slowest_testcase
    breakdown = (
        f'{_hilite(slowest.solution_time_seconds)} solution'
        f' + {_hilite(slowest.checker_time_seconds)} checker'
    )
    totals = f'(checker: {_hilite(bench.total_checker_time_seconds)}'
    # The interactor is named only when there is one to name -- a batch problem
    # must not grow a term reading `- interactor` on every solution.
    if slowest.interactor_time_seconds is not None:
        breakdown += f', {_hilite(slowest.interactor_time_seconds)} interactor'
    if bench.total_interactor_time_seconds is not None:
        totals += f', interactor: {_hilite(bench.total_interactor_time_seconds)}'
    totals += ')'

    console.print(
        f'Benchmark: slowest test [item]{slowest.entry}[/item]'
        f' - {_hilite(slowest.judging_time_seconds)} judging ({breakdown})'
    )
    console.print(
        f'Total judging: {_hilite(bench.total_judging_time_seconds)} {totals}', end=''
    )
    if bench.partial:
        # A `--fail-fast` run stopped early, so every total above is a lower
        # bound rather than the cost of judging the whole testset.
        console.print(f' (over {bench.judged}/{bench.total_testcases} tests judged)')
    else:
        console.print()


def print_problem_benchmark(
    console: rich.console.Console, problem: ProblemBenchmark
) -> None:
    """Print the problem-wide extremes, at the end of the run report."""
    console.print('[status]Benchmark summary[/status]', end='')
    if problem.partial:
        console.print(' (partial -- some tests were not judged)', end='')
    console.print()
    console.print(
        f'Slowest solution to judge: {_hilite(problem.slowest_to_judge.total_judging_time_seconds)}'
        f', {problem.slowest_to_judge.solution.href()}'
    )
    # `most_checker_time` always names a winner, even when no solution measured
    # a checker at all -- an unmeasured winner is not a finding, so say nothing.
    if problem.most_checker_time.total_checker_time_seconds is not None:
        console.print(
            f'Most checker time: {_hilite(problem.most_checker_time.total_checker_time_seconds)}'
            f', {problem.most_checker_time.solution.href()}'
        )
    console.print(
        f'Slowest testcase to judge: {_hilite(problem.slowest_testcase.judging_time_seconds)}'
        f', [item]{problem.slowest_testcase.entry}[/item]'
    )
