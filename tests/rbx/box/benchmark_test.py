import pytest

from rbx.box import benchmark
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.grading.steps import Outcome, RunTiming
from tests.rbx.box.conftest import make_evaluation


def timed(outcome, *, time_ms, checker_ms=None, interactor_ms=None, index=0):
    """`make_evaluation`, plus the judging timings this module reads."""
    eval = make_evaluation(outcome, time_ms=time_ms, testcase_index=index)
    if checker_ms is not None:
        eval.result.checker_timing = RunTiming(time=checker_ms / 1000.0)
    if interactor_ms is not None:
        eval.result.interactor_timing = RunTiming(time=interactor_ms / 1000.0)
    return eval


def test_judging_time_sums_solution_checker_and_interactor():
    eval = timed(Outcome.ACCEPTED, time_ms=100, checker_ms=20, interactor_ms=5)
    assert benchmark.judging_time(eval) == pytest.approx(0.125)


def test_judging_time_is_none_when_the_solution_was_never_timed():
    # A skipped testcase must not report an instantaneous judging time.
    assert benchmark.judging_time(timed(Outcome.SKIPPED, time_ms=None)) is None


def test_judging_time_counts_an_unmeasured_checker_as_absent_not_zero():
    eval = timed(Outcome.TIME_LIMIT_EXCEEDED, time_ms=1000)
    assert benchmark.judging_time(eval) == pytest.approx(1.0)


def test_judging_time_tolerates_a_timing_with_no_clock_on_it():
    # `RunTiming` can exist with both clocks unset -- guard the inner `None`,
    # not just the outer one.
    eval = timed(Outcome.ACCEPTED, time_ms=100)
    eval.result.checker_timing = RunTiming()
    assert benchmark.judging_time(eval) == pytest.approx(0.1)


def test_judging_time_handles_a_communication_problem_without_a_checker():
    eval = timed(Outcome.ACCEPTED, time_ms=100, interactor_ms=30)
    assert eval.result.checker_timing is None
    assert benchmark.judging_time(eval) == pytest.approx(0.13)


def test_solution_benchmark_picks_the_slowest_testcase_to_judge(
    mock_skeleton, tmp_path
):
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 3})
    evals = [
        timed(Outcome.ACCEPTED, time_ms=100, checker_ms=10, index=0),
        # Slowest *judging*, though not the slowest solution run: the point of
        # the whole feature is that these two can disagree.
        timed(Outcome.ACCEPTED, time_ms=90, checker_ms=200, index=1),
        timed(Outcome.ACCEPTED, time_ms=150, checker_ms=5, index=2),
    ]

    bench = benchmark.build_solution_benchmark(solution, skeleton, evals)

    assert bench is not None
    assert bench.slowest.entry == skeleton.entries[1].group_entry
    assert bench.slowest.judging_time == pytest.approx(0.29)
    assert bench.slowest.checker_time == pytest.approx(0.2)
    assert bench.total_judging_time == pytest.approx(0.555)
    assert bench.total_checker_time == pytest.approx(0.215)
    assert bench.judged == 3
    assert bench.total == 3
    assert not bench.partial


def test_solution_benchmark_is_partial_when_testcases_were_skipped(
    mock_skeleton, tmp_path
):
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 3})
    evals = [
        timed(Outcome.WRONG_ANSWER, time_ms=100, checker_ms=10, index=0),
        timed(Outcome.SKIPPED, time_ms=None, index=1),
        timed(Outcome.SKIPPED, time_ms=None, index=2),
    ]

    bench = benchmark.build_solution_benchmark(solution, skeleton, evals)

    assert bench is not None
    assert bench.judged == 1
    assert bench.total == 3
    assert bench.partial


def test_solution_benchmark_counts_the_testset_not_the_evals_handed_in(
    mock_skeleton, tmp_path
):
    # Mid-run, only the finished evaluations are known, but the run is still
    # partial against the full testset.
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 3})

    bench = benchmark.build_solution_benchmark(
        solution, skeleton, [timed(Outcome.ACCEPTED, time_ms=100, index=0)]
    )

    assert bench is not None
    assert bench.judged == 1
    assert bench.total == 3
    assert bench.partial


def test_solution_benchmark_is_none_when_nothing_was_judged(mock_skeleton, tmp_path):
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 2})
    evals = [timed(Outcome.SKIPPED, time_ms=None, index=i) for i in range(2)]

    assert benchmark.build_solution_benchmark(solution, skeleton, evals) is None


def test_problem_benchmark_ranks_solutions(mock_skeleton, tmp_path):
    slow_judge = Solution(path=tmp_path / 'a.cpp', outcome=ExpectedOutcome.ACCEPTED)
    heavy_checker = Solution(path=tmp_path / 'b.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([slow_judge, heavy_checker], entries_per_group={'test': 2})
    per_solution = [
        benchmark.build_solution_benchmark(
            slow_judge,
            skeleton,
            [
                timed(Outcome.ACCEPTED, time_ms=500, checker_ms=1, index=i)
                for i in range(2)
            ],
        ),
        benchmark.build_solution_benchmark(
            heavy_checker,
            skeleton,
            [
                timed(Outcome.ACCEPTED, time_ms=10, checker_ms=300, index=i)
                for i in range(2)
            ],
        ),
    ]

    problem = benchmark.build_problem_benchmark([b for b in per_solution if b])

    assert problem is not None
    assert problem.slowest_to_judge.solution.path == slow_judge.path
    assert problem.most_checker_time.solution.path == heavy_checker.path
    # 500 ms of solution plus 1 ms of checker beats the heavy checker's
    # 10 ms + 300 ms.
    assert problem.slowest_testcase.judging_time == pytest.approx(0.501)


def test_problem_benchmark_is_none_without_any_solution_benchmarks():
    assert benchmark.build_problem_benchmark([]) is None
