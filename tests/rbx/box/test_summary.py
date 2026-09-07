import json
import pathlib
from unittest import mock

import pytest
import rich.console

from rbx.box import summary as summary_module
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.issues import rendering
from rbx.box.issues import schema as issues_schema
from rbx.box.schema import (
    CodeItem,
    ExpectedOutcome,
    Package,
    Solution,
    TaskType,
    Testcase,
)
from rbx.box.summary import (
    SUMMARY_FORMAT_VERSION,
    ContestProblemSummary,
    ProblemFlags,
    ProblemSummary,
    TestcaseCounts,
    count_testcases,
    get_contest_problem_summary,
    get_outcome_bucket,
    get_problem_flags,
    get_problem_summary,
    get_solution_counts,
    print_checks_section,
    summary_to_json,
)
from rbx.box.testcase_schema import TestcaseEntry


def _make_entry(group: str = 'tests', index: int = 0) -> GenerationTestcaseEntry:
    return GenerationTestcaseEntry(
        group_entry=TestcaseEntry(group=group, index=index),
        subgroup_entry=TestcaseEntry(group=group, index=index),
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=pathlib.Path(f'{group}/{index}.in')),
        ),
    )


def _make_solution(
    outcome: ExpectedOutcome = ExpectedOutcome.ACCEPTED,
    path: str = 'sol.cpp',
) -> Solution:
    return Solution(path=pathlib.Path(path), outcome=outcome)


def _make_package(**kwargs) -> Package:
    defaults = {
        'name': 'test-problem',
        'timeLimit': 2000,
        'memoryLimit': 256,
    }
    defaults.update(kwargs)
    return Package(**defaults)


class TestCountTestcases:
    def test_empty(self):
        result = count_testcases([])
        assert result == TestcaseCounts(samples=0, hidden=0)

    def test_only_samples(self):
        entries = [_make_entry('samples', i) for i in range(3)]
        result = count_testcases(entries)
        assert result == TestcaseCounts(samples=3, hidden=0)

    def test_only_hidden(self):
        entries = [_make_entry('tests', i) for i in range(5)]
        result = count_testcases(entries)
        assert result == TestcaseCounts(samples=0, hidden=5)

    def test_mixed(self):
        entries = [
            _make_entry('samples', 0),
            _make_entry('samples', 1),
            _make_entry('tests', 0),
            _make_entry('corner', 0),
            _make_entry('random', 0),
        ]
        result = count_testcases(entries)
        assert result == TestcaseCounts(samples=2, hidden=3)


class TestGetOutcomeBucket:
    @pytest.mark.parametrize(
        'outcome,expected',
        [
            (ExpectedOutcome.ACCEPTED, ExpectedOutcome.ACCEPTED),
            (ExpectedOutcome.ACCEPTED_OR_TLE, ExpectedOutcome.ACCEPTED),
            (ExpectedOutcome.WRONG_ANSWER, ExpectedOutcome.WRONG_ANSWER),
            (ExpectedOutcome.INCORRECT, ExpectedOutcome.WRONG_ANSWER),
            (ExpectedOutcome.TIME_LIMIT_EXCEEDED, ExpectedOutcome.TIME_LIMIT_EXCEEDED),
            (ExpectedOutcome.TLE_OR_RTE, ExpectedOutcome.TIME_LIMIT_EXCEEDED),
            (ExpectedOutcome.RUNTIME_ERROR, ExpectedOutcome.RUNTIME_ERROR),
            (ExpectedOutcome.MEMORY_LIMIT_EXCEEDED, ExpectedOutcome.RUNTIME_ERROR),
            (ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED, ExpectedOutcome.RUNTIME_ERROR),
            (ExpectedOutcome.JUDGE_FAILED, ExpectedOutcome.RUNTIME_ERROR),
            (ExpectedOutcome.COMPILATION_ERROR, ExpectedOutcome.RUNTIME_ERROR),
        ],
    )
    def test_known_outcomes(self, outcome, expected):
        assert get_outcome_bucket(outcome) == expected

    def test_any_returns_none(self):
        assert get_outcome_bucket(ExpectedOutcome.ANY) is None


class TestGetSolutionCountsExact:
    def test_empty(self):
        result = get_solution_counts([])
        assert all(v == 0 for v in result.values())
        # All ExpectedOutcome values should be keys.
        for outcome in ExpectedOutcome:
            assert outcome in result

    def test_counts_by_exact_outcome(self):
        solutions = [
            _make_solution(ExpectedOutcome.ACCEPTED, 'a.cpp'),
            _make_solution(ExpectedOutcome.ACCEPTED, 'b.cpp'),
            _make_solution(ExpectedOutcome.WRONG_ANSWER, 'wa.cpp'),
            _make_solution(ExpectedOutcome.ANY, 'any.cpp'),
        ]
        result = get_solution_counts(solutions)
        assert result[ExpectedOutcome.ACCEPTED] == 2
        assert result[ExpectedOutcome.WRONG_ANSWER] == 1
        assert result[ExpectedOutcome.ANY] == 1
        assert result[ExpectedOutcome.RUNTIME_ERROR] == 0


class TestGetSolutionCountsBucketed:
    def test_basic_bucketing(self):
        solutions = [
            _make_solution(ExpectedOutcome.ACCEPTED, 'a.cpp'),
            _make_solution(ExpectedOutcome.ACCEPTED_OR_TLE, 'b.cpp'),
            _make_solution(ExpectedOutcome.INCORRECT, 'c.cpp'),
            _make_solution(ExpectedOutcome.MEMORY_LIMIT_EXCEEDED, 'd.cpp'),
        ]
        result = get_solution_counts(solutions, bucketize=True)
        assert result[ExpectedOutcome.ACCEPTED] == 2
        assert result[ExpectedOutcome.WRONG_ANSWER] == 1
        assert result[ExpectedOutcome.RUNTIME_ERROR] == 1
        assert result[ExpectedOutcome.TIME_LIMIT_EXCEEDED] == 0

    def test_any_excluded_from_buckets(self):
        solutions = [
            _make_solution(ExpectedOutcome.ACCEPTED, 'a.cpp'),
            _make_solution(ExpectedOutcome.ANY, 'any.cpp'),
        ]
        result = get_solution_counts(solutions, bucketize=True)
        assert result[ExpectedOutcome.ACCEPTED] == 1
        # ANY should not be counted in any bucket.
        total_bucketed = sum(result.values())
        assert total_bucketed == 1

    def test_only_four_bucket_keys(self):
        result = get_solution_counts([], bucketize=True)
        assert set(result.keys()) == {
            ExpectedOutcome.ACCEPTED,
            ExpectedOutcome.WRONG_ANSWER,
            ExpectedOutcome.TIME_LIMIT_EXCEEDED,
            ExpectedOutcome.RUNTIME_ERROR,
        }


class TestGetProblemFlags:
    def test_defaults(self):
        pkg = _make_package()
        flags = get_problem_flags(pkg)
        assert flags == ProblemFlags(
            is_interactive=False, has_validator=False, has_custom_checker=False
        )

    def test_interactive(self):
        pkg = _make_package(type=TaskType.COMMUNICATION)
        flags = get_problem_flags(pkg)
        assert flags.is_interactive is True

    def test_validator(self):
        pkg = _make_package(validator=CodeItem(path=pathlib.Path('validator.cpp')))
        flags = get_problem_flags(pkg)
        assert flags.has_validator is True

    def test_checker(self):
        from rbx.box.schema import Checker

        pkg = _make_package(checker=Checker(path=pathlib.Path('checker.cpp')))
        flags = get_problem_flags(pkg)
        assert flags.has_custom_checker is True


class TestGetProblemSummary:
    def test_basic(self):
        pkg = _make_package(name='a-plus-b')
        solutions = [
            _make_solution(ExpectedOutcome.ACCEPTED, 'ac.cpp'),
            _make_solution(ExpectedOutcome.WRONG_ANSWER, 'wa.cpp'),
        ]
        entries = [_make_entry('samples', 0), _make_entry('tests', 0)]

        result = get_problem_summary(pkg, solutions, entries, short_name='A')

        assert isinstance(result, ProblemSummary)
        assert result.name == 'a-plus-b'
        assert result.short_name == 'A'
        assert result.time_limit_ms == 2000
        assert result.memory_limit_mb == 256
        assert result.testcase_counts == TestcaseCounts(samples=1, hidden=1)
        assert result.flags.is_interactive is False
        assert result.solution_counts[ExpectedOutcome.ACCEPTED] == 1
        assert result.solution_counts[ExpectedOutcome.WRONG_ANSWER] == 1
        assert len(result.solutions) == 2

    def test_no_short_name(self):
        pkg = _make_package()
        result = get_problem_summary(pkg, [], [])
        assert result.short_name is None


class TestGetContestProblemSummary:
    def test_basic(self):
        pkg = _make_package(name='sum')
        solutions = [
            _make_solution(ExpectedOutcome.ACCEPTED, 'ac.cpp'),
            _make_solution(ExpectedOutcome.ANY, 'any.cpp'),
            _make_solution(ExpectedOutcome.INCORRECT, 'wa.cpp'),
        ]
        entries = [_make_entry('samples', 0), _make_entry('tests', 0)]

        result = get_contest_problem_summary(pkg, solutions, entries, short_name='B')

        assert isinstance(result, ContestProblemSummary)
        assert result.short_name == 'B'
        assert result.name == 'sum'
        assert result.total_solutions == 3
        # ANY is excluded from buckets, so only 2 counted.
        total_bucketed = sum(result.solution_counts_bucketed.values())
        assert total_bucketed == 2
        assert result.solution_counts_bucketed[ExpectedOutcome.ACCEPTED] == 1
        assert result.solution_counts_bucketed[ExpectedOutcome.WRONG_ANSWER] == 1


class TestSummaryJson:
    """`rbx summary --format json`, the contract a tool reads."""

    def _summary(self) -> ProblemSummary:
        return get_problem_summary(
            _make_package(name='a-plus-b'),
            [_make_solution(ExpectedOutcome.ACCEPTED, 'ac.cpp')],
            [_make_entry('samples', 0)],
        )

    def test_carries_the_summary_and_the_checks_together(self):
        payload = json.loads(
            summary_to_json(self._summary(), [issues_schema.NoValidatorIssue()])
        )

        assert payload['version'] == SUMMARY_FORMAT_VERSION
        assert payload['summary']['name'] == 'a-plus-b'
        assert payload['issues'][0]['kind'] == 'config_no_validator'

    def test_publishes_the_family_so_a_tool_need_not_infer_it(self):
        payload = json.loads(
            summary_to_json(self._summary(), [issues_schema.NoValidatorIssue()])
        )

        assert payload['issues'][0]['family'] == 'config'
        assert payload['issues'][0]['severity'] == 'warning'

    def test_a_clean_package_carries_an_empty_list(self):
        payload = json.loads(summary_to_json(self._summary(), []))

        assert payload['issues'] == []

    def test_its_version_is_independent_of_the_issues_one(self):
        # The `ProblemSummary` shape and the `Issue` shape change for unrelated
        # reasons; one number for both would make each bump lie about the other.
        assert SUMMARY_FORMAT_VERSION != issues_schema.ISSUES_FORMAT_VERSION


class TestChecksSection:
    def _render(self, config_issues, detailed=False) -> str:
        recorder = rich.console.Console(record=True, width=200)
        with mock.patch.object(summary_module.console, 'console', recorder):
            print_checks_section(config_issues, detailed=detailed)
        return recorder.export_text()

    def test_prints_nothing_at_all_when_there_is_nothing_to_say(self):
        # Not even a heading: an empty `Checks` block reads as a section that
        # failed to load, rather than as a package with nothing wrong.
        assert self._render([]) == ''

    def test_lists_each_finding_under_a_heading(self):
        out = self._render(
            [issues_schema.NoValidatorIssue(), issues_schema.NoSamplesIssue()]
        )

        assert 'Checks' in out
        assert 'no validator' in out
        assert 'no samples' in out

    def test_words_a_finding_exactly_as_rbx_issues_does(self):
        issue = issues_schema.NoAcceptedSolutionIssue()

        assert rendering.summarize(issue) in self._render([issue])

    def test_detailed_expands_a_finding(self):
        out = self._render([issues_schema.NoAcceptedSolutionIssue()], detailed=True)

        assert 'unverified' in out
