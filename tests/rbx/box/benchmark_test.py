import pytest
import typer

from rbx.box import benchmark, formatting, sharing
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


def test_duration_that_rounds_up_to_a_second_is_rendered_in_seconds():
    # Branching on the raw value would render `1000 ms` beside a sibling's
    # `1.0 s`, which reads as two scales for the same duration.
    assert formatting.get_formatted_duration_in_seconds(0.9999) == '1.0 s'


def test_duration_below_a_millisecond_is_not_rendered_as_a_measured_zero():
    assert formatting.get_formatted_duration_in_seconds(0.0004) == '<1 ms'


def test_duration_of_zero_is_rendered_as_a_measured_zero():
    assert formatting.get_formatted_duration_in_seconds(0.0) == '0 ms'


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

    breakdown, totals = benchmark.solution_benchmark_lines(bench)

    # 290 ms of judging, split into 90 ms of solution and 200 ms of checker.
    assert 'test/1' in breakdown
    assert '290 ms judging (90 ms solution + 200 ms checker)' in breakdown
    # Totals: 555 ms of judging, 215 ms of it in the checker.
    assert totals == 'Total judging: 555 ms (checker: 215 ms)'


def test_solution_block_marks_a_partial_run_as_a_lower_bound(mock_skeleton, tmp_path):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.WRONG_ANSWER, time_ms=100, checker_ms=10, index=0)],
        total=3,
    )

    _, totals = benchmark.solution_benchmark_lines(bench)

    assert totals.endswith('(over 1/3 tests judged)')


def test_solution_block_does_not_mark_a_complete_run(mock_skeleton, tmp_path):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, checker_ms=10, index=0)],
    )

    _, totals = benchmark.solution_benchmark_lines(bench)

    assert 'judged' not in totals


def test_solution_block_omits_the_interactor_on_a_non_interactive_problem(
    mock_skeleton, tmp_path
):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, checker_ms=10, index=0)],
    )

    lines = benchmark.solution_benchmark_lines(bench)

    assert not any('interactor' in line for line in lines)


def test_solution_block_omits_the_checker_term_when_there_was_no_checker(
    mock_skeleton, tmp_path
):
    # A communication problem may have no checker at all. Naming it in the sum
    # would read `+ - checker`, which is broken prose rather than a finding --
    # the totals line reports the missing measurement instead.
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, interactor_ms=30, index=0)],
    )

    breakdown, totals = benchmark.solution_benchmark_lines(bench)

    assert '130 ms judging (100 ms solution + 30 ms interactor)' in breakdown
    assert 'checker' not in breakdown
    assert 'checker: -' in totals


def test_solution_block_reports_the_interactor_when_there_is_one(
    mock_skeleton, tmp_path
):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [
            timed(
                Outcome.ACCEPTED, time_ms=100, checker_ms=5, interactor_ms=300, index=0
            ),
            timed(
                Outcome.ACCEPTED, time_ms=100, checker_ms=5, interactor_ms=300, index=1
            ),
        ],
    )

    breakdown, totals = benchmark.solution_benchmark_lines(bench)

    # Every term of the headline is summed into it, so all of them are joined
    # with `+` rather than the interactor reading as an aside.
    assert (
        '405 ms judging (100 ms solution + 5 ms checker + 300 ms interactor)'
        in breakdown
    )
    assert totals == 'Total judging: 810 ms (checker: 10 ms, interactor: 600 ms)'


def test_solution_block_renders_an_unmeasured_checker_total_as_a_dash(
    mock_skeleton, tmp_path
):
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, interactor_ms=10, index=0)],
    )

    _, totals = benchmark.solution_benchmark_lines(bench)

    assert 'checker: -' in totals
    assert 'checker: 0 ms' not in totals


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

    _, totals = benchmark.solution_benchmark_lines(bench)

    assert 'checker: 0 ms' in totals
    assert 'checker: -' not in totals


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
    lines = benchmark.problem_benchmark_lines(
        problem_benchmark(mock_skeleton, tmp_path)
    )

    slowest, most_checker, slowest_testcase = lines[1:]
    assert slowest.startswith('Slowest solution to judge: 1.0 s,')
    assert 'a.cpp' in slowest
    assert most_checker.startswith('Most checker time: 600 ms,')
    assert 'b.cpp' in most_checker
    assert slowest_testcase == 'Slowest testcase to judge: 501 ms, [item]test/0[/item]'


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

    lines = benchmark.problem_benchmark_lines(problem)

    assert not any('checker' in line for line in lines)


def test_the_blocks_styles_resolve_against_the_report_theme(mock_skeleton, tmp_path):
    # Rich resolves an unknown style to nothing and prints no error, so a
    # misspelled tag passes every assertion over plain text. Render through the
    # themed console the `--share` path uses and read the styles back, so that
    # a `[hilte]` or an unbalanced tag fails here.
    bench = solution_benchmark(
        mock_skeleton,
        tmp_path,
        [timed(Outcome.ACCEPTED, time_ms=100, checker_ms=10, index=0)],
        path='a.cpp',
    )
    problem = benchmark.build_problem_benchmark([bench])
    assert problem is not None
    console = sharing.recording_console(width=400)

    benchmark.print_solution_benchmark(console, bench)
    benchmark.print_problem_benchmark(console, problem)
    styled = console.export_text(styles=True)

    # `Style.render` reproduces exactly the escapes the export carries, so this
    # pins the styled text to the *theme's* style rather than to whatever the
    # console falls back to when a tag does not resolve.
    assert console.get_style('item').render('test/0') in styled
    assert console.get_style('status').render('Benchmark summary') in styled


def test_parse_level_accepts_the_implemented_levels():
    assert benchmark.parse_level(0) == benchmark.BenchmarkLevel.NONE
    assert benchmark.parse_level(1) == benchmark.BenchmarkLevel.SOLUTIONS


def test_parse_level_rejects_b2_and_points_at_the_tracking_issue():
    with pytest.raises(typer.BadParameter) as exc:
        benchmark.parse_level(2)
    assert '801' in str(exc.value)


def test_parse_level_rejects_nonsense():
    with pytest.raises(typer.BadParameter):
        benchmark.parse_level(7)
