import pytest
import rich.console

from rbx.box import benchmark, formatting
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
    assert benchmark.judging_time_seconds(eval) == pytest.approx(0.125)


def test_judging_time_is_none_when_the_solution_was_never_timed():
    # A skipped testcase must not report an instantaneous judging time.
    assert benchmark.judging_time_seconds(timed(Outcome.SKIPPED, time_ms=None)) is None


def test_judging_time_counts_an_unmeasured_checker_as_absent_not_zero():
    eval = timed(Outcome.TIME_LIMIT_EXCEEDED, time_ms=1000)
    assert benchmark.checker_time_seconds(eval) is None
    assert benchmark.judging_time_seconds(eval) == pytest.approx(1.0)


def test_checker_time_is_none_when_the_timing_carries_no_clock():
    # `RunTiming` can exist with both clocks unset -- guard the inner `None`,
    # not just the outer one.
    eval = timed(Outcome.ACCEPTED, time_ms=100)
    eval.result.checker_timing = RunTiming()
    assert benchmark.checker_time_seconds(eval) is None
    assert benchmark.judging_time_seconds(eval) == pytest.approx(0.1)


def test_judging_time_handles_a_communication_problem_without_a_checker():
    eval = timed(Outcome.ACCEPTED, time_ms=100, interactor_ms=30)
    assert benchmark.checker_time_seconds(eval) is None
    assert benchmark.interactor_time_seconds(eval) == pytest.approx(0.03)
    assert benchmark.judging_time_seconds(eval) == pytest.approx(0.13)


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
    assert bench.slowest_testcase.entry == skeleton.entries[1].group_entry
    assert bench.slowest_testcase.judging_time_seconds == pytest.approx(0.29)
    assert bench.slowest_testcase.solution_time_seconds == pytest.approx(0.09)
    assert bench.slowest_testcase.checker_time_seconds == pytest.approx(0.2)
    assert bench.total_judging_time_seconds == pytest.approx(0.555)
    assert bench.total_checker_time_seconds == pytest.approx(0.215)
    assert bench.judged == 3
    assert bench.total_testcases == 3
    assert not bench.partial


def test_solution_benchmark_reports_no_checker_total_when_none_was_measured(
    mock_skeleton, tmp_path
):
    # A communication problem may have no checker at all. Reporting a total of
    # `0.0 s` would claim a measurement that was never taken.
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 2})
    evals = [
        timed(Outcome.ACCEPTED, time_ms=100, interactor_ms=10, index=i)
        for i in range(2)
    ]

    bench = benchmark.build_solution_benchmark(solution, skeleton, evals)

    assert bench is not None
    assert bench.total_checker_time_seconds is None
    assert bench.total_interactor_time_seconds == pytest.approx(0.02)


def test_solution_benchmark_keeps_a_genuine_zero_checker_total(mock_skeleton, tmp_path):
    # A checker that measurably took no time is a measurement, and must not be
    # confused with a checker that never ran.
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 2})
    evals = [
        timed(Outcome.ACCEPTED, time_ms=100, checker_ms=0, index=i) for i in range(2)
    ]

    bench = benchmark.build_solution_benchmark(solution, skeleton, evals)

    assert bench is not None
    assert bench.total_checker_time_seconds == pytest.approx(0.0)
    assert bench.total_checker_time_seconds is not None
    assert bench.total_interactor_time_seconds is None


def test_solution_benchmark_totals_only_the_measured_testcases(mock_skeleton, tmp_path):
    # A checker measured on some testcases and not others still has a total --
    # the unmeasured ones simply contribute nothing.
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 2})
    evals = [
        timed(Outcome.ACCEPTED, time_ms=100, checker_ms=40, index=0),
        timed(Outcome.ACCEPTED, time_ms=100, index=1),
    ]

    bench = benchmark.build_solution_benchmark(solution, skeleton, evals)

    assert bench is not None
    assert bench.total_checker_time_seconds == pytest.approx(0.04)


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
    assert bench.total_testcases == 3
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
    assert bench.total_testcases == 3
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
    assert problem.slowest_testcase.judging_time_seconds == pytest.approx(0.501)


def test_problem_benchmark_ranks_a_solution_with_no_checker_last(
    mock_skeleton, tmp_path
):
    # An unmeasured checker must not win `most_checker_time` by being `None`.
    with_checker = Solution(path=tmp_path / 'a.cpp', outcome=ExpectedOutcome.ACCEPTED)
    without = Solution(path=tmp_path / 'b.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([with_checker, without], entries_per_group={'test': 1})
    benchmarks = [
        benchmark.build_solution_benchmark(
            without, skeleton, [timed(Outcome.ACCEPTED, time_ms=10, index=0)]
        ),
        benchmark.build_solution_benchmark(
            with_checker,
            skeleton,
            [timed(Outcome.ACCEPTED, time_ms=10, checker_ms=50, index=0)],
        ),
    ]

    problem = benchmark.build_problem_benchmark([b for b in benchmarks if b])

    assert problem is not None
    assert problem.most_checker_time.solution.path == with_checker.path


def test_problem_benchmark_is_none_without_any_solution_benchmarks():
    assert benchmark.build_problem_benchmark([]) is None


def test_duration_under_a_second_is_rendered_in_milliseconds():
    # A checker routinely costs tens of milliseconds; one decimal place of
    # seconds would report every one of them as `0.0 s`.
    assert formatting.get_formatted_duration_in_seconds(0.048) == '48 ms'


def test_duration_under_a_second_rounds_to_the_nearest_millisecond():
    # Truncating would read `49 ms`, which is a visible lie at this scale.
    assert formatting.get_formatted_duration_in_seconds(0.0499) == '50 ms'


def test_duration_of_at_least_a_second_is_rendered_in_seconds():
    assert formatting.get_formatted_duration_in_seconds(1.02) == '1.0 s'


def test_duration_of_exactly_one_second_is_rendered_in_seconds():
    assert formatting.get_formatted_duration_in_seconds(1.0) == '1.0 s'


def render(printer, *args):
    """Render one of the report blocks into a throwaway recording console."""
    console = rich.console.Console(record=True, width=120)
    printer(console, *args)
    return console.export_text()


def solution_benchmark(mock_skeleton, tmp_path, evals, *, path='sol.cpp', total=None):
    """Build a `SolutionBenchmark` out of the evaluations a run would produce."""
    solution = Solution(path=tmp_path / path, outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton(
        [solution], entries_per_group={'test': total or len(evals)}
    )
    bench = benchmark.build_solution_benchmark(solution, skeleton, evals)
    assert bench is not None
    return bench


def test_solution_block_names_the_slowest_testcase_and_both_totals(
    mock_skeleton, tmp_path
):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [
            timed(Outcome.ACCEPTED, time_ms=100, checker_ms=10, index=0),
            timed(Outcome.ACCEPTED, time_ms=90, checker_ms=200, index=1),
            timed(Outcome.ACCEPTED, time_ms=150, checker_ms=5, index=2),
        ],
    )

    text = render(benchmark.print_solution_benchmark, bench)

    assert 'test/1' in text
    # 290 ms of judging, split into 90 ms of solution and 200 ms of checker.
    assert '290 ms' in text
    assert '90 ms' in text
    assert '200 ms' in text
    # Totals: 555 ms of judging, 215 ms of it in the checker.
    assert '555 ms' in text
    assert 'checker: 215 ms' in text


def test_solution_block_marks_a_partial_run_as_a_lower_bound(mock_skeleton, tmp_path):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.WRONG_ANSWER, time_ms=100, checker_ms=10, index=0)],
        total=3,
    )

    text = render(benchmark.print_solution_benchmark, bench)

    assert '1/3' in text


def test_solution_block_does_not_mark_a_complete_run(mock_skeleton, tmp_path):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, checker_ms=10, index=0)],
    )

    text = render(benchmark.print_solution_benchmark, bench)

    assert 'judged' not in text


def test_solution_block_omits_the_interactor_on_a_non_interactive_problem(
    mock_skeleton, tmp_path
):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, checker_ms=10, index=0)],
    )

    text = render(benchmark.print_solution_benchmark, bench)

    assert 'interactor' not in text


def test_solution_block_reports_the_interactor_when_there_is_one(
    mock_skeleton, tmp_path
):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [
            timed(Outcome.ACCEPTED, time_ms=100, interactor_ms=300, index=0),
            timed(Outcome.ACCEPTED, time_ms=100, interactor_ms=300, index=1),
        ],
    )

    text = render(benchmark.print_solution_benchmark, bench)

    # Once in the slowest testcase's breakdown, once in the totals.
    assert text.count('interactor') == 2
    assert '300 ms interactor' in text
    assert 'interactor: 600 ms' in text


def test_solution_block_renders_an_unmeasured_checker_total_as_a_dash(
    mock_skeleton, tmp_path
):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, interactor_ms=10, index=0)],
    )

    text = render(benchmark.print_solution_benchmark, bench)

    assert 'checker: -' in text
    assert 'checker: 0 ms' not in text


def test_solution_block_renders_a_genuine_zero_checker_total_as_a_measurement(
    mock_skeleton, tmp_path
):
    # A checker that measurably took no time is a measurement, and must not be
    # rendered like a checker that never ran.
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, checker_ms=0, index=0)],
    )

    text = render(benchmark.print_solution_benchmark, bench)

    assert 'checker: 0 ms' in text
    assert 'checker: -' not in text


def problem_benchmark(mock_skeleton, tmp_path):
    slow_judge = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=500, checker_ms=1, index=i) for i in range(2)],
        path='a.cpp',
    )
    heavy_checker = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [
            timed(Outcome.ACCEPTED, time_ms=10, checker_ms=300, index=i)
            for i in range(2)
        ],
        path='b.cpp',
    )
    problem = benchmark.build_problem_benchmark([slow_judge, heavy_checker])
    assert problem is not None
    return problem


def test_problem_block_names_both_extremes(mock_skeleton, tmp_path):
    text = render(
        benchmark.print_problem_benchmark, problem_benchmark(mock_skeleton, tmp_path)
    )

    # The solution paths are absolute, so a narrow console wraps them mid-name.
    unwrapped = text.replace('\n', '')
    assert 'a.cpp' in unwrapped
    assert 'b.cpp' in unwrapped
    assert 'test/0' in text
    assert '1.0 s' in text  # slowest to judge, 1002 ms
    assert '600 ms' in text  # most checker time
    assert '501 ms' in text  # slowest testcase


def test_problem_block_omits_the_checker_line_when_no_solution_had_a_checker(
    mock_skeleton, tmp_path
):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, index=0)],
        path='a.cpp',
    )
    problem = benchmark.build_problem_benchmark([bench])
    assert problem is not None
    assert problem.most_checker_time.total_checker_time_seconds is None

    text = render(benchmark.print_problem_benchmark, problem)

    assert 'checker' not in text
