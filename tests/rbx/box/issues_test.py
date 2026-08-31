"""Tests for the issue detectors.

Every detector is a pure function over a `RunState`, so these build one by hand
rather than running a package: no sandbox, no compilation, no fixture. That is
the point of the design -- the issue stack these replaced could only be
exercised by running a real package end to end.
"""

import json
import pathlib
import time
import typing
from unittest import mock

import pytest
import rich.console
import yaml

from rbx.box import run_report
from rbx.box.compilation_findings import CompilationWarning, SolutionCompilation
from rbx.box.issues import config_detectors, detectors, rendering, run_state, schema
from rbx.box.issues import config_state as config_state_module
from rbx.box.issues.contest import build_report
from rbx.box.run_report import RunGroupReport, RunReport, RunSolutionReport
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.grading.steps import Outcome


def make_state(
    solutions=None,
    compilation=None,
) -> run_state.RunState:
    return run_state.RunState(
        report=RunReport(solutions=solutions or []),
        skeleton=run_state.SkeletonView(compilation=compilation or []),
        runs_dir=pathlib.Path('.rbx/runs'),
        ran_at=time.time(),
    )


def solution(**kwargs) -> RunSolutionReport:
    defaults = dict(
        path='sol/main.cpp',
        index=0,
        expectedOutcome=ExpectedOutcome.ACCEPTED,
        outcome=Outcome.ACCEPTED,
        status='OK',
    )
    defaults.update(kwargs)
    return RunSolutionReport(**defaults)


def kinds(issues) -> list:
    return [issue.kind for issue in issues]


class TestUnmetExpectations:
    def test_reports_a_solution_that_missed_its_expectation(self):
        state = make_state(
            [
                solution(
                    path='sol/wa.cpp',
                    expectedOutcome=ExpectedOutcome.WRONG_ANSWER,
                    outcome=Outcome.ACCEPTED,
                    status='UNEXPECTED_VERDICTS',
                    matchesExpectation=False,
                    pooledMatchesExpectation=False,
                )
            ]
        )

        (issue,) = detectors.detect_unmet_expectations(state)

        assert issue == schema.UnmetExpectationIssue(
            solution='sol/wa.cpp',
            expected=ExpectedOutcome.WRONG_ANSWER,
            got=Outcome.ACCEPTED,
            status='UNEXPECTED_VERDICTS',
            failedGroups=[],
            pooledMatchesExpectation=False,
        )
        assert issue.severity == schema.IssueSeverity.ERROR

    def test_stays_quiet_when_the_expectation_was_met(self):
        assert detectors.detect_unmet_expectations(make_state([solution()])) == []

    def test_carries_the_pooled_result_so_a_met_expectation_is_not_accused(self):
        """A solution can fail only its per-group layer.

        Saying "expected INCORRECT, got WA" there names the one expectation that
        actually held, which is why the flag has to survive to the renderer.
        """
        state = make_state(
            [
                solution(
                    path='sol/grp.cpp',
                    expectedOutcome=ExpectedOutcome.INCORRECT,
                    outcome=Outcome.WRONG_ANSWER,
                    status='UNEXPECTED_VERDICTS',
                    matchesExpectation=False,
                    pooledMatchesExpectation=True,
                    failedGroups=['big'],
                )
            ]
        )

        (issue,) = detectors.detect_unmet_expectations(state)

        assert issue.pooledMatchesExpectation
        assert issue.failedGroups == ['big']

    def test_leaves_an_unexpected_score_to_its_own_detector(self):
        """Otherwise one failure is reported twice, in two different words."""
        state = make_state(
            [
                solution(
                    status='UNEXPECTED_SCORE',
                    matchesExpectation=False,
                    score=40,
                    maxScore=100,
                    expectedScore=(80, 100),
                )
            ]
        )

        assert detectors.detect_unmet_expectations(state) == []
        assert kinds(detectors.detect_unexpected_scores(state)) == ['unexpected_score']


class TestUnexpectedScores:
    def test_reports_the_declared_range(self):
        state = make_state(
            [
                solution(
                    status='UNEXPECTED_SCORE',
                    matchesExpectation=False,
                    score=40,
                    maxScore=100,
                    expectedScore=(80, 100),
                )
            ]
        )

        (issue,) = detectors.detect_unexpected_scores(state)

        assert issue.score == 40
        assert issue.maxScore == 100
        assert issue.expectedScore == (80, 100)

    def test_says_nothing_without_a_declared_range(self):
        """With no range there is nothing to say that the verdict does not."""
        state = make_state(
            [solution(status='UNEXPECTED_SCORE', matchesExpectation=False, score=40)]
        )

        assert detectors.detect_unexpected_scores(state) == []


class TestCompilation:
    def test_reports_a_failure_as_an_error(self):
        state = make_state(
            compilation=[
                SolutionCompilation(
                    path=pathlib.Path('sol/bad.cpp'),
                    outcome=ExpectedOutcome.ACCEPTED,
                    status='FAILED',
                    log=pathlib.Path('compilation/0.log'),
                    reason="'g++' was not found",
                )
            ]
        )

        (issue,) = detectors.detect_compilation(state)

        assert issue.kind == 'compilation_failed'
        assert issue.severity == schema.IssueSeverity.ERROR
        assert issue.reason == "'g++' was not found"

    def test_reports_warnings_as_a_warning(self):
        state = make_state(
            compilation=[
                SolutionCompilation(
                    path=pathlib.Path('sol/warn.cpp'),
                    outcome=ExpectedOutcome.ACCEPTED,
                    status='WARNINGS',
                    log=pathlib.Path('compilation/1.log'),
                    warnings=[
                        CompilationWarning(
                            file='sol/warn.cpp', line=12, flag='-Wall', msg='unused'
                        )
                    ],
                )
            ]
        )

        (issue,) = detectors.detect_compilation(state)

        assert issue.kind == 'compilation_warnings'
        assert issue.severity == schema.IssueSeverity.WARNING
        assert len(issue.warnings) == 1

    def test_finds_a_solution_that_never_reached_the_report(self):
        """A solution that failed to compile is absent from the run entirely.

        It is filtered out of the skeleton's `solutions`, so the compilation
        record is the only trace of it -- which is exactly why this detector
        reads the skeleton instead of the report.
        """
        state = make_state(
            solutions=[],
            compilation=[
                SolutionCompilation(
                    path=pathlib.Path('sol/bad.cpp'),
                    outcome=ExpectedOutcome.ACCEPTED,
                    status='FAILED',
                    log=pathlib.Path('compilation/0.log'),
                )
            ],
        )

        assert kinds(detectors.detect_all(state)) == ['compilation_failed']


class TestTimingRisk:
    def test_flags_a_solution_slow_only_within_double_tl(self):
        state = make_state(
            [
                solution(
                    path='sol/slow.cpp',
                    expectedOutcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
                    outcome=Outcome.TIME_LIMIT_EXCEEDED,
                    runUnderDoubleTl=True,
                    doubleTlVerdicts=[Outcome.ACCEPTED],
                    groups=[RunGroupReport(name='main', runUnderDoubleTl=True)],
                )
            ]
        )

        (issue,) = detectors.detect_borderline_tle(state)

        assert issue.groups == ['main']
        assert issue.doubleTlVerdicts == [Outcome.ACCEPTED]
        # The run itself passed -- which is the whole reason this needs saying.
        assert state.report.solutions[0].matchesExpectation

    def test_pools_hidden_verdicts_up_from_the_groups(self):
        state = make_state(
            [
                solution(
                    groups=[
                        RunGroupReport(
                            name='main',
                            unexpectedNoTleVerdicts=[Outcome.WRONG_ANSWER],
                        ),
                        RunGroupReport(name='clean'),
                    ]
                )
            ]
        )

        (issue,) = detectors.detect_hidden_verdicts(state)

        # Only the group that actually hid something.
        assert issue.groups == ['main']
        assert issue.verdicts == [Outcome.WRONG_ANSWER]

    def test_flags_a_passing_solution_close_to_the_limit(self):
        state = make_state([solution(maxTime=0.95, timeLimit=1.0)])

        (issue,) = detectors.detect_tight_time_margin(state)

        assert issue.maxTime == 0.95
        assert issue.timeLimit == 1.0

    def test_leaves_a_comfortable_solution_alone(self):
        state = make_state([solution(maxTime=0.2, timeLimit=1.0)])

        assert detectors.detect_tight_time_margin(state) == []

    def test_never_flags_a_solution_declared_slow(self):
        """A solution declared slow is supposed to sit against the limit."""
        state = make_state(
            [
                solution(
                    expectedOutcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
                    outcome=Outcome.TIME_LIMIT_EXCEEDED,
                    maxTime=1.0,
                    timeLimit=1.0,
                )
            ]
        )

        assert detectors.detect_tight_time_margin(state) == []

    def test_needs_a_time_limit_to_compare_against(self):
        """A sanitized run enforces none, so there is no margin to speak of."""
        state = make_state([solution(maxTime=9.0, timeLimit=None)])

        assert detectors.detect_tight_time_margin(state) == []

    def test_collects_untuned_limits_into_one_issue(self):
        state = make_state(
            [
                solution(path='sol/a.cpp', untunedLimitsSuspected=True),
                solution(path='sol/b.cpp', untunedLimitsSuspected=True),
                solution(path='sol/c.cpp'),
            ]
        )

        (issue,) = detectors.detect_untuned_limits(state)

        assert issue.affectedSolutions == ['sol/a.cpp', 'sol/b.cpp']

    def test_says_nothing_when_no_solution_suspects_the_limits(self):
        assert detectors.detect_untuned_limits(make_state([solution()])) == []


class TestDetectAll:
    def test_puts_errors_before_warnings(self):
        state = make_state(
            [
                solution(path='sol/tight.cpp', maxTime=0.95, timeLimit=1.0),
                solution(
                    path='sol/wa.cpp',
                    expectedOutcome=ExpectedOutcome.WRONG_ANSWER,
                    status='UNEXPECTED_VERDICTS',
                    matchesExpectation=False,
                    pooledMatchesExpectation=False,
                ),
            ]
        )

        issues = detectors.detect_all(state)

        assert kinds(issues) == ['unmet_expectation', 'tight_time_margin']

    def test_a_clean_run_has_no_issues(self):
        assert detectors.detect_all(make_state([solution()])) == []


class TestLoadRunState:
    def _write(self, runs_dir: pathlib.Path, report: RunReport) -> None:
        run_report.write_report(run_report.report_path(runs_dir), report)

    def test_reads_a_report_back_off_disk(self, tmp_path: pathlib.Path):
        self._write(tmp_path, RunReport(solutions=[solution(path='sol/a.cpp')]))

        state = run_state.load_run_state(tmp_path)

        assert state is not None
        assert [s.path for s in state.report.solutions] == ['sol/a.cpp']

    def test_a_missing_report_means_never_run(self, tmp_path: pathlib.Path):
        assert run_state.load_run_state(tmp_path) is None
        assert build_report(tmp_path).neverRun

    def test_a_corrupt_report_reads_as_never_run(self, tmp_path: pathlib.Path):
        """The report is rewritten per solution, so it can be caught mid-write."""
        run_report.report_path(tmp_path).write_text('{[not yaml')

        assert run_state.load_run_state(tmp_path) is None

    def test_refuses_a_report_from_a_newer_rbx(self, tmp_path: pathlib.Path):
        path = run_report.report_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump({'version': run_report.REPORT_VERSION + 1, 'solutions': []})
        )

        with pytest.raises(run_state.UnsupportedReportVersion):
            run_state.load_run_state(tmp_path)

    def test_tolerates_a_missing_skeleton(self, tmp_path: pathlib.Path):
        self._write(tmp_path, RunReport(solutions=[solution()]))

        state = run_state.load_run_state(tmp_path)

        assert state is not None
        assert state.skeleton.compilation == []

    def test_reads_compilation_findings_off_the_skeleton(self, tmp_path: pathlib.Path):
        self._write(tmp_path, RunReport())
        (tmp_path / run_state.SKELETON_FILENAME).write_text(
            yaml.safe_dump(
                {
                    'compilation': [
                        {
                            'path': 'sol/bad.cpp',
                            'outcome': 'accepted',
                            'status': 'FAILED',
                            'log': 'compilation/0.log',
                        }
                    ]
                }
            )
        )

        state = run_state.load_run_state(tmp_path)

        assert state is not None
        assert [c.path for c in state.skeleton.compilation] == [
            pathlib.Path('sol/bad.cpp')
        ]

    def test_report_records_where_relative_paths_hang_off(self, tmp_path: pathlib.Path):
        self._write(tmp_path, RunReport())

        assert build_report(tmp_path).runsDir == str(tmp_path)


class TestSkeletonViewDoesNotDrift:
    def test_parses_a_real_skeleton(self):
        """`SkeletonView` is a narrow read of a model it does not import.

        That is deliberate -- importing `solutions` would cost `rbx issues` the
        whole box -- but it means nothing else stops the two disagreeing. So
        assert the field is really there, and really means what is read here.
        """
        from rbx.box.solutions import SolutionReportSkeleton

        field = SolutionReportSkeleton.model_fields['compilation']
        view_field = run_state.SkeletonView.model_fields['compilation']

        assert field.annotation == view_field.annotation


class TestPublishedReportFields:
    def test_untuned_limits_rides_the_report(self):
        """The detector cannot re-derive this, so the report must carry it."""
        assert 'untunedLimitsSuspected' in RunSolutionReport.model_fields

    def test_time_limit_rides_the_report(self):
        assert 'timeLimit' in RunSolutionReport.model_fields

    def test_both_are_additive_and_default_off(self):
        """Additive fields must not change how an existing report reads."""
        entry = RunSolutionReport(
            path='sol/a.cpp',
            index=0,
            expectedOutcome=ExpectedOutcome.ACCEPTED,
            status='OK',
        )

        assert entry.untunedLimitsSuspected is False
        assert entry.timeLimit is None


class TestRendering:
    """The wording lives in one place, so it is asserted in one place.

    These replace the two `FailedToCompileSolutionIssue` message tests that used
    to live in `solutions_test.py`: the messages moved here when the rendering
    left the issue stack.
    """

    def test_a_compile_failure_names_the_reason(self):
        issue = schema.CompilationFailedIssue(
            solution='sols/wa.py',
            reason="'python3' was not found",
            log=pathlib.Path('compilation/0.log'),
        )

        assert 'python3' in rendering.summarize(issue)

    def test_a_compile_failure_without_a_reason_still_reads(self):
        issue = schema.CompilationFailedIssue(
            solution='sols/wa.py', log=pathlib.Path('compilation/0.log')
        )

        assert rendering.summarize(issue) == 'failed to compile'

    def test_never_names_a_pooled_expectation_that_held(self):
        """Saying "expected INCORRECT, got WA" accuses the layer that worked."""
        issue = schema.UnmetExpectationIssue(
            solution='sol/grp.cpp',
            expected=ExpectedOutcome.INCORRECT,
            got=Outcome.WRONG_ANSWER,
            status='UNEXPECTED_VERDICTS',
            failedGroups=['big'],
            pooledMatchesExpectation=True,
        )

        summary = rendering.summarize(issue)

        assert 'INCORRECT' not in summary
        assert 'big' in summary

    def test_names_the_pooled_expectation_when_it_is_the_one_that_failed(self):
        issue = schema.UnmetExpectationIssue(
            solution='sol/wa.cpp',
            expected=ExpectedOutcome.WRONG_ANSWER,
            got=Outcome.ACCEPTED,
            status='UNEXPECTED_VERDICTS',
            pooledMatchesExpectation=False,
        )

        summary = rendering.summarize(issue)

        assert 'WRONG_ANSWER' in summary
        assert 'ACCEPTED' in summary

    def test_a_log_link_resolves_against_the_runs_dir(self):
        """The stored path is relative, so on its own it points nowhere."""
        issue = schema.CompilationFailedIssue(
            solution='sols/wa.py', log=pathlib.Path('compilation/0.log')
        )

        lines = rendering.explain(issue, runs_dir='/pkg/.rbx/runs')

        assert any('/pkg/.rbx/runs/compilation/0.log' in line for line in lines)

    def test_every_kind_has_a_summary_and_a_severity(self):
        """A new kind must not fall through to 'unknown issue'."""
        samples = [
            schema.UnmetExpectationIssue(
                solution='s', expected=ExpectedOutcome.ACCEPTED, status='OK'
            ),
            schema.UnexpectedScoreIssue(
                solution='s', score=1, maxScore=2, expectedScore=(2, 2)
            ),
            schema.CompilationFailedIssue(solution='s', log=pathlib.Path('a.log')),
            schema.CompilationWarningsIssue(solution='s', log=pathlib.Path('a.log')),
            schema.BorderlineTleIssue(solution='s'),
            schema.HiddenVerdictIssue(solution='s'),
            schema.TightTimeMarginIssue(solution='s', maxTime=1.0, timeLimit=1.0),
            schema.UntunedLimitsIssue(),
            schema.NoAcceptedSolutionIssue(),
            schema.NoValidatorIssue(),
            schema.NoSamplesIssue(),
            schema.EmptyTestGroupIssue(group='big'),
            schema.MissingStatementLanguageIssue(),
            schema.ExplanationMissingLanguageIssue(
                sample=0, path=pathlib.Path('a.rbx.tex')
            ),
        ]

        # Every member of the union is covered.
        assert {type(sample) for sample in samples} == set(
            typing.get_args(typing.get_args(schema.Issue)[0])
        )
        for sample in samples:
            assert rendering.summarize(sample) != 'unknown issue'
            assert sample.severity in tuple(schema.IssueSeverity)

    def test_humanizes_a_missing_timestamp_as_never(self):
        assert rendering.humanize_since(None) == 'never'

    def test_humanizes_a_recent_run(self):
        assert rendering.humanize_since(time.time() - 5) == 'just now'
        assert rendering.humanize_since(time.time() - 260) == '4m ago'


class TestJsonOutput:
    def test_carries_a_version_and_the_severity_of_each_issue(self):
        report = schema.IssueReport(
            ranAt=1.0,
            issues=[schema.UntunedLimitsIssue(affectedSolutions=['sol/a.cpp'])],
        )

        payload = json.loads(rendering.to_json(report))

        assert payload['version'] == schema.ISSUES_FORMAT_VERSION
        assert payload['issues'][0]['kind'] == 'untuned_limits'
        # Published, so a client keeps no table of which kinds are which.
        assert payload['issues'][0]['severity'] == 'warning'

    def test_a_never_run_package_says_so_rather_than_looking_clean(self):
        payload = json.loads(rendering.to_json(schema.IssueReport(neverRun=True)))

        assert payload['neverRun'] is True
        assert payload['issues'] == []

    def test_round_trips_through_the_discriminated_union(self):
        report = schema.IssueReport(
            issues=[
                schema.UnmetExpectationIssue(
                    solution='sol/wa.cpp',
                    expected=ExpectedOutcome.WRONG_ANSWER,
                    got=Outcome.ACCEPTED,
                    status='UNEXPECTED_VERDICTS',
                    pooledMatchesExpectation=False,
                )
            ]
        )

        parsed = schema.IssueReport.model_validate(
            json.loads(rendering.to_json(report))
        )

        assert parsed == report


class TestContestHint:
    """The contest table shows one issue per problem, so it has to say how to
    see the rest -- but only when there is a rest to see."""

    def _render(self, rows, detailed=False) -> str:
        recorder = rich.console.Console(record=True, width=200)
        with mock.patch.object(rendering.console, 'console', recorder):
            rendering.print_contest_report(rows, detailed=detailed)
        return recorder.export_text()

    def _row_with_issues(self) -> schema.ContestIssueRow:
        return schema.ContestIssueRow(
            short_name='A',
            name='paths',
            report=schema.IssueReport(
                ranAt=time.time(),
                issues=[schema.UntunedLimitsIssue(affectedSolutions=['sol/a.cpp'])],
            ),
        )

    def test_points_at_detailed_when_a_problem_has_issues(self):
        assert 'rbx contest issues -d' in self._render([self._row_with_issues()])

    def test_stays_quiet_when_every_problem_is_clean(self):
        row = schema.ContestIssueRow(
            short_name='A', name='clean', report=schema.IssueReport(ranAt=time.time())
        )

        assert 'rbx contest issues -d' not in self._render([row])

    def test_stays_quiet_when_nothing_has_been_run(self):
        row = schema.ContestIssueRow(
            short_name='A', name='fresh', report=schema.IssueReport(neverRun=True)
        )

        assert 'rbx contest issues -d' not in self._render([row])

    def test_does_not_point_at_a_flag_the_reader_already_passed(self):
        assert 'rbx contest issues -d' not in self._render(
            [self._row_with_issues()], detailed=True
        )


class TestIssueFamily:
    """`family` is computed, not declared -- the same rule `severity` follows,
    so a client splitting run findings from config ones reads a field rather
    than keeping its own table of which kind belongs where."""

    def test_config_issues_carry_the_config_family(self):
        issue = schema.NoAcceptedSolutionIssue()

        assert issue.family == schema.IssueFamily.CONFIG
        assert issue.severity == schema.IssueSeverity.ERROR

    def test_run_issues_carry_the_run_family(self):
        issue = schema.UntunedLimitsIssue(affectedSolutions=['sol/a.cpp'])

        assert issue.family == schema.IssueFamily.RUN

    def test_family_and_severity_are_both_serialized(self):
        payload = schema.NoValidatorIssue().model_dump()

        assert payload['kind'] == 'config_no_validator'
        assert payload['family'] == 'config'
        assert payload['severity'] == 'warning'

    def test_config_kinds_round_trip_through_the_union(self):
        report = schema.IssueReport(
            issues=[
                schema.MissingStatementLanguageIssue(missing=['pt']),
                schema.EmptyTestGroupIssue(group='big'),
                schema.ExplanationMissingLanguageIssue(
                    sample=0,
                    path=pathlib.Path('tests/samples/000.rbx.tex'),
                    missing=['pt'],
                ),
            ]
        )

        parsed = schema.IssueReport.model_validate_json(report.model_dump_json())

        assert parsed.issues == report.issues

    def test_the_format_version_records_the_neverrun_change(self):
        # Not for the new kinds -- the union carries those. For `neverRun`, which
        # no longer implies an empty list, so a v1 reader short-circuiting on it
        # would silently drop every config finding.
        assert schema.ISSUES_FORMAT_VERSION == 2


def config_solution(path: str, outcome: ExpectedOutcome) -> Solution:
    return Solution(path=pathlib.Path(path), outcome=outcome)


def config_state(**kwargs) -> config_state_module.ConfigState:
    """A package with nothing wrong with it, overridden per test.

    Built by hand, like every `RunState` above: a config detector reads counts
    and names, so exercising one needs no package on disk.
    """
    defaults = dict(
        solutions=[config_solution('sol/ac.cpp', ExpectedOutcome.ACCEPTED)],
        has_validator=True,
        group_test_counts={'samples': 2, 'main': 10},
        sample_count=2,
        statement_languages=['en'],
    )
    defaults.update(kwargs)
    return config_state_module.ConfigState(**defaults)


class TestConfigDetectors:
    def test_a_healthy_package_produces_nothing(self):
        assert config_detectors.detect_all_config(config_state()) == []

    def test_flags_a_package_with_no_accepted_solution(self):
        state = config_state(
            solutions=[config_solution('sol/wa.cpp', ExpectedOutcome.WRONG_ANSWER)]
        )

        (issue,) = config_detectors.detect_no_accepted_solution(state)

        assert issue.kind == 'config_no_accepted_solution'
        assert issue.severity == schema.IssueSeverity.ERROR

    def test_accepted_or_tle_still_pins_down_a_correct_output(self):
        state = config_state(
            solutions=[config_solution('sol/ac.cpp', ExpectedOutcome.ACCEPTED_OR_TLE)]
        )

        assert config_detectors.detect_no_accepted_solution(state) == []

    def test_a_package_with_no_solutions_at_all_is_flagged(self):
        state = config_state(solutions=[])

        assert len(config_detectors.detect_no_accepted_solution(state)) == 1

    def test_flags_a_missing_validator(self):
        state = config_state(has_validator=False)

        (issue,) = config_detectors.detect_no_validator(state)

        assert issue.kind == 'config_no_validator'
        assert issue.severity == schema.IssueSeverity.WARNING

    def test_flags_a_package_with_no_samples(self):
        (issue,) = config_detectors.detect_no_samples(config_state(sample_count=0))

        assert issue.kind == 'config_no_samples'

    def test_reports_one_issue_per_empty_group(self):
        state = config_state(group_test_counts={'samples': 2, 'big': 0, 'huge': 0})

        issues = config_detectors.detect_empty_test_groups(state)

        assert [issue.group for issue in issues] == ['big', 'huge']

    def test_an_empty_samples_group_is_only_reported_as_no_samples(self):
        # Saying both "no samples" and "group samples has no tests" makes one
        # mistake look like two.
        state = config_state(
            sample_count=0, group_test_counts={'samples': 0, 'main': 1}
        )

        assert config_detectors.detect_empty_test_groups(state) == []
        assert len(config_detectors.detect_no_samples(state)) == 1

    def test_flags_a_problem_with_no_statement_at_all(self):
        (issue,) = config_detectors.detect_missing_statement_languages(
            config_state(statement_languages=[])
        )

        assert issue.hasNoStatements
        assert issue.missing == []

    def test_flags_a_contest_language_the_problem_has_no_statement_for(self):
        state = config_state(statement_languages=['en'], contest_languages=['en', 'pt'])

        (issue,) = config_detectors.detect_missing_statement_languages(state)

        assert issue.missing == ['pt']
        assert not issue.hasNoStatements

    def test_says_nothing_about_languages_outside_a_contest(self):
        # A standalone problem shipping only English is not missing Portuguese;
        # rbx has no way to know which languages were wanted.
        state = config_state(statement_languages=['en'], contest_languages=[])

        assert config_detectors.detect_missing_statement_languages(state) == []

    def test_flags_an_explanation_missing_a_language(self):
        state = config_state(
            statement_languages=['en', 'pt'],
            explanation_languages={0: ['en']},
            explanation_paths={0: pathlib.Path('tests/samples/000.rbx.tex')},
        )

        (issue,) = config_detectors.detect_explanation_languages(state)

        assert issue.sample == 0
        assert issue.missing == ['pt']

    def test_an_explanation_covering_every_language_is_fine(self):
        state = config_state(
            statement_languages=['en', 'pt'],
            explanation_languages={0: ['pt', 'en']},
            explanation_paths={0: pathlib.Path('tests/samples/000.rbx.tex')},
        )

        assert config_detectors.detect_explanation_languages(state) == []

    def test_a_language_agnostic_explanation_is_never_checked(self):
        # Such a sample never enters `explanation_languages` at all: one file
        # covers every language by construction.
        state = config_state(statement_languages=['en', 'pt'])

        assert config_detectors.detect_explanation_languages(state) == []

    def test_detect_all_config_puts_errors_first(self):
        state = config_state(
            solutions=[config_solution('sol/wa.cpp', ExpectedOutcome.WRONG_ANSWER)],
            has_validator=False,
        )

        issues = config_detectors.detect_all_config(state)

        assert [issue.severity for issue in issues] == [
            schema.IssueSeverity.ERROR,
            schema.IssueSeverity.WARNING,
        ]

    def test_every_config_detector_is_registered(self):
        """A detector nobody listed in CONFIG_DETECTORS never runs."""
        defined = {
            value
            for name, value in vars(config_detectors).items()
            if name.startswith('detect_') and name != 'detect_all_config'
        }

        assert defined == set(config_detectors.CONFIG_DETECTORS)


class TestConfigRendering:
    def _render(self, report, detailed=False) -> str:
        recorder = rich.console.Console(record=True, width=200)
        with mock.patch.object(rendering.console, 'console', recorder):
            rendering.print_report(report, detailed=detailed)
        return recorder.export_text()

    def test_words_the_two_missing_statement_cases_apart(self):
        assert (
            rendering.summarize(
                schema.MissingStatementLanguageIssue(hasNoStatements=True)
            )
            == 'the problem has no statement'
        )
        assert (
            rendering.summarize(
                schema.MissingStatementLanguageIssue(missing=['pt', 'es'])
            )
            == 'no statement for language(s): pt, es'
        )

    def test_names_the_group_that_is_empty(self):
        assert 'big' in rendering.summarize(schema.EmptyTestGroupIssue(group='big'))

    def test_a_never_run_problem_still_shows_its_config_findings(self):
        """The change `ISSUES_FORMAT_VERSION` 2 records.

        Suppressing these behind "not run yet" would hide them from exactly the
        reader who has not run anything and most needs to know the package is
        not ready to be run.
        """
        report = schema.IssueReport(neverRun=True, issues=[schema.NoValidatorIssue()])

        out = self._render(report)

        assert 'no validator' in out
        assert 'not run yet' in out

    def test_a_never_run_problem_with_nothing_wrong_reads_as_before(self):
        out = self._render(schema.IssueReport(neverRun=True))

        assert 'This problem has not been run yet.' in out
        assert 'rbx run' in out

    def test_a_never_run_headline_counts_the_config_findings(self):
        report = schema.IssueReport(
            neverRun=True,
            issues=[schema.NoAcceptedSolutionIssue(), schema.NoValidatorIssue()],
        )

        out = self._render(report)

        assert '1 error(s)' in out
        assert '1 warning(s)' in out

    def test_detailed_explains_why_an_accepted_solution_matters(self):
        report = schema.IssueReport(issues=[schema.NoAcceptedSolutionIssue()])

        out = self._render(report, detailed=True)

        assert 'unverified' in out

    def test_json_publishes_the_family_of_each_issue(self):
        report = schema.IssueReport(issues=[schema.NoValidatorIssue()])

        payload = json.loads(rendering.to_json(report))

        assert payload['version'] == 2
        assert payload['issues'][0]['family'] == 'config'
        assert payload['issues'][0]['severity'] == 'warning'
