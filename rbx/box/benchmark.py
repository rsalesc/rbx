"""Benchmarking of the judging phase, behind `rbx run --benchmark`.

`rbx run` already reports how long each *solution* took. It says nothing about
how long *judging* took, and on a problem with a heavy checker the checker can
dominate the wall clock of a full run. This module turns the checker and
interactor timings that every evaluation now carries (see
`rbx.grading.steps.RunTiming`) into the two blocks `-b1` prints.

Every duration here is in seconds, and every name says so. The formatters in
`rbx.box.formatting` are told apart by nothing but their names -- one takes
milliseconds, the others seconds -- so a name that omits the unit invites a
caller to mislabel it, which nothing here would raise on.

The timings themselves are captured unconditionally; the level only decides
whether anything is printed. See docs/plans/2026-08-28-run-benchmark-design.md.
"""

import dataclasses
from enum import Enum
from typing import TYPE_CHECKING, Annotated, List, Optional

import rich.console
import typer

from rbx.box.formatting import UNMEASURED, get_formatted_duration_in_seconds
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


BENCHMARK_ISSUE_URL = 'https://github.com/rsalesc/rbx/issues/801'


def parse_level(value: int) -> BenchmarkLevel:
    """Turn the `-b` flag's int into a level, rejecting the unimplemented ones.

    `-b2` -- benchmarking test generation and validation -- is specified but not
    built. Rejecting it outright is deliberate: silently treating it as `-b1`
    would hand back a report that quietly omits half of what was asked for.
    """
    if value == 2:
        raise typer.BadParameter(
            'Benchmarking test generation and validation (-b2) is not implemented '
            f'yet. Follow {BENCHMARK_ISSUE_URL} for progress.'
        )
    try:
        return BenchmarkLevel(value)
    except ValueError:
        # The valid levels are read off the enum rather than spelled out -- a
        # second copy of the list is exactly what goes stale when a level lands.
        valid = ', '.join(str(level.value) for level in BenchmarkLevel)
        raise typer.BadParameter(
            f'Invalid benchmark level {value}. Valid levels are: {valid}.'
        ) from None


def _benchmark_autocompletion():
    # Indirect through a function so module load doesn't eagerly depend on
    # rbx.annotations (keeps this module's import surface decoupled; the import
    # is light either way).
    from rbx import annotations

    return annotations._adapt('benchmark_level')  # noqa: SLF001


BenchmarkParam = Annotated[
    int,
    typer.Option(
        '--benchmark',
        '-b',
        help='Benchmark level: 0 (off), 1 (benchmark the solution run).',
        default_factory=lambda: BenchmarkLevel.NONE.value,
        autocompletion=_benchmark_autocompletion(),
    ),
]


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

    `None` never becomes `0 ms` here: a checker that never ran and a checker
    that ran instantaneously read differently, and only the second is a claim
    about how long judging took.

    The adaptive formatter is the one that matters here: a checker routinely
    costs a few milliseconds, and a fixed decimal place would report the whole
    block as zeros.
    """
    if seconds is None:
        return UNMEASURED
    return get_formatted_duration_in_seconds(seconds)


def solution_benchmark_lines(bench: SolutionBenchmark) -> List[str]:
    """The markup lines of one solution's judging benchmark.

    Kept apart from the printing so that tests can assert over the markup --
    rich resolves an unknown style to nothing and prints no error, so a
    misspelled tag is invisible in rendered text.
    """
    slowest = bench.slowest_testcase
    # The breakdown names only the programs that were measured. An absent
    # checker is normal on a communication problem, and an absent interactor on
    # every other one, so a `- checker` term there is broken prose rather than a
    # finding. The totals line below still reports the missing measurement.
    terms = [f'{_measurement(slowest.solution_time_seconds)} solution']
    if slowest.checker_time_seconds is not None:
        terms.append(f'{_measurement(slowest.checker_time_seconds)} checker')
    if slowest.interactor_time_seconds is not None:
        terms.append(f'{_measurement(slowest.interactor_time_seconds)} interactor')
    # The headline is the sum of these terms, so they are joined as a sum.
    breakdown = ' + '.join(terms)

    # The totals, in contrast, always name the checker: on the problems where a
    # checker is expected, `checker: -` is the report that it went unmeasured.
    totals = [f'checker: {_measurement(bench.total_checker_time_seconds)}']
    if bench.total_interactor_time_seconds is not None:
        totals.append(
            f'interactor: {_measurement(bench.total_interactor_time_seconds)}'
        )

    total_line = (
        f'Total judging: {_measurement(bench.total_judging_time_seconds)}'
        f' ({", ".join(totals)})'
    )
    if bench.partial:
        # A `--fail-fast` run stopped early, so every total above is a lower
        # bound rather than the cost of judging the whole testset.
        total_line += f' (over {bench.judged}/{bench.total_testcases} tests judged)'

    return [
        f'Benchmark: slowest test [item]{slowest.entry}[/item]'
        f' - {_measurement(slowest.judging_time_seconds)} judging ({breakdown})',
        total_line,
    ]


def problem_benchmark_lines(problem: ProblemBenchmark) -> List[str]:
    """The markup lines of the problem-wide extremes."""
    header = '[status]Benchmark summary[/status]'
    if problem.partial:
        header += ' (partial -- some tests were not judged)'

    lines = [
        header,
        f'Slowest solution to judge: '
        f'{_measurement(problem.slowest_to_judge.total_judging_time_seconds)}'
        f', {problem.slowest_to_judge.solution.href()}',
    ]
    # `most_checker_time` always names a winner, even when no solution measured
    # a checker at all -- an unmeasured winner is not a finding, so say nothing.
    if problem.most_checker_time.total_checker_time_seconds is not None:
        lines.append(
            f'Most checker time: '
            f'{_measurement(problem.most_checker_time.total_checker_time_seconds)}'
            f', {problem.most_checker_time.solution.href()}'
        )
    lines.append(
        f'Slowest testcase to judge: '
        f'{_measurement(problem.slowest_testcase.judging_time_seconds)}'
        f', [item]{problem.slowest_testcase.entry}[/item]'
    )
    return lines


def print_solution_benchmark(
    console: rich.console.Console, bench: SolutionBenchmark
) -> None:
    """Print one solution's judging benchmark, under its report block.

    The console is passed in rather than taken from `rbx.console` so that the
    `--share` recording console gets these lines too.
    """
    for line in solution_benchmark_lines(bench):
        console.print(line)


def print_problem_benchmark(
    console: rich.console.Console, problem: ProblemBenchmark
) -> None:
    """Print the problem-wide extremes, at the end of the run report."""
    for line in problem_benchmark_lines(problem):
        console.print(line)
