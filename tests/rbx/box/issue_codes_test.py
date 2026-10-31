"""Issue codes, the thresholds that tune them and the lists that silence them."""

import pathlib
import re
import time
import typing
from unittest import mock

import pydantic
import pytest
import rich.console

from rbx.box import run_report
from rbx.box.contest.schema import Contest
from rbx.box.environment import Environment
from rbx.box.issue_codes import (
    DOCS_URL,
    IgnoreRule,
    IssueCode,
    IssuesConfig,
    IssueThresholds,
    docs_url,
    glob_matches,
)
from rbx.box.issues import config_detectors, detectors, rendering, run_state, schema
from rbx.box.issues import config_state as config_state_module
from rbx.box.issues.contest import build_report
from rbx.box.issues.settings import merge_ignored
from rbx.box.run_report import RunReport, RunSolutionReport
from rbx.box.schema import ExpectedOutcome, Package, Solution
from rbx.grading.steps import Outcome

DOCS_PAGE = pathlib.Path(__file__).parents[3] / 'docs' / 'issues.md'


def make_state(solutions, sanitized=False, thresholds=None) -> run_state.RunState:
    return run_state.RunState(
        report=RunReport(solutions=solutions),
        skeleton=run_state.SkeletonView(sanitized=sanitized),
        runs_dir=pathlib.Path('.rbx/runs'),
        ran_at=time.time(),
        thresholds=thresholds or IssueThresholds(),
    )


def solution(**kwargs) -> RunSolutionReport:
    defaults = dict(
        path='sol/main.cpp',
        index=0,
        expectedOutcome=ExpectedOutcome.ACCEPTED,
        outcome=Outcome.ACCEPTED,
        status='OK',
        complete=True,
    )
    defaults.update(kwargs)
    return RunSolutionReport(**defaults)


def config_state(**kwargs) -> config_state_module.ConfigState:
    defaults = dict(
        solutions=[Solution(path=pathlib.Path('sol/ac.cpp'), outcome='accepted')],
        has_validator=True,
        group_test_counts={'samples': 2},
        sample_count=2,
        statement_languages=['en'],
    )
    defaults.update(kwargs)
    return config_state_module.ConfigState(**defaults)


def package(**kwargs) -> Package:
    return Package(name='prob', timeLimit=1000, memoryLimit=256, **kwargs)


def issue_classes():
    return typing.get_args(typing.get_args(schema.Issue)[0])


class TestCodes:
    def test_every_kind_maps_to_exactly_one_code_and_back(self):
        kinds = {cls.model_fields['kind'].default for cls in issue_classes()}

        assert set(schema.KIND_TO_CODE) == kinds
        assert sorted(schema.KIND_TO_CODE.values()) == sorted(IssueCode)

    def test_codes_are_kebab_case(self):
        for code in IssueCode:
            assert re.fullmatch(r'[a-z]+(-[a-z]+)*', code.value)

    def test_the_code_lands_in_the_json(self):
        issue = schema.NoValidatorIssue()

        assert issue.model_dump(mode='json')['code'] == 'no-validator'

    def test_every_code_has_a_section_on_the_docs_page(self):
        """The console points at this page, so no code may be missing from it."""
        text = DOCS_PAGE.read_text()

        for code in IssueCode:
            assert f'## `{code.value}`' in text, code.value

    def test_docs_url_anchors_the_code(self):
        assert docs_url(IssueCode.NO_SAMPLES) == f'{DOCS_URL}#no-samples'


class TestIgnoreConfig:
    def test_problem_accepts_known_codes(self):
        pkg = package(issues={'ignore': ['no-validator', 'noisy-stderr']})

        assert pkg.issues.ignore == [IssueCode.NO_VALIDATOR, IssueCode.NOISY_STDERR]

    def test_problem_rejects_an_unknown_code(self):
        """A typo must not silently silence nothing."""
        with pytest.raises(pydantic.ValidationError):
            package(issues={'ignore': ['no-validatr']})

    def test_contest_accepts_the_same_block(self):
        contest = Contest(name='contest', issues={'ignore': ['no-samples']})

        assert contest.issues.ignore == [IssueCode.NO_SAMPLES]

    def test_problem_codes_add_to_the_contest_ones(self):
        contest = Contest(
            name='contest', issues={'ignore': ['no-samples', 'no-validator']}
        )
        pkg = package(issues={'ignore': ['no-validator', 'noisy-stderr']})

        assert merge_ignored(contest, pkg) == [
            IgnoreRule(code=IssueCode.NO_SAMPLES),
            IgnoreRule(code=IssueCode.NO_VALIDATOR),
            IgnoreRule(code=IssueCode.NOISY_STDERR),
        ]

    def test_outside_a_contest_only_the_problem_counts(self):
        pkg = package(issues={'ignore': ['no-samples']})

        assert merge_ignored(None, pkg) == [IgnoreRule(code=IssueCode.NO_SAMPLES)]

    def test_defaults_to_nothing_ignored(self):
        assert package().issues == IssuesConfig()


class TestThresholdConfig:
    def test_environment_defaults(self):
        thresholds = Environment().issues.thresholds

        assert thresholds.testsetSizeMb == 200
        assert thresholds.testcaseInputSizeMb == 20
        assert thresholds.testcaseAnswerSizeMb == 20
        assert thresholds.acceptedTotalTimeSeconds == 60
        assert thresholds.stderrSizeMb == 1

    def test_environment_overrides(self):
        env = Environment(issues={'thresholds': {'testsetSizeMb': 50}})

        assert env.issues.thresholds.testset_size_bytes == 50 * 1024 * 1024
        assert env.issues.thresholds.acceptedTotalTimeSeconds == 60

    def test_rejects_a_non_positive_threshold(self):
        with pytest.raises(pydantic.ValidationError):
            IssueThresholds(acceptedTotalTimeSeconds=0)

    def test_rejects_an_unknown_threshold(self):
        with pytest.raises(pydantic.ValidationError):
            IssueThresholds(testSize=1)

    def test_stderr_threshold_is_tunable(self):
        state = make_state([solution()], thresholds=IssueThresholds(stderrSizeMb=0.001))
        state.stderr = {
            0: run_state.StderrArtifact(path=pathlib.Path('0/a.err'), size=2048)
        }

        assert [i.code for i in detectors.detect_noisy_stderr(state)] == [
            IssueCode.NOISY_STDERR
        ]


class TestSlowAcceptedSolution:
    def test_flags_an_accepted_solution_over_budget(self):
        state = make_state([solution(totalTime=61.5)])

        issues = detectors.detect_slow_accepted_solutions(state)

        assert issues == [
            schema.SlowAcceptedSolutionIssue(
                solution='sol/main.cpp', totalTime=61.5, threshold=60
            )
        ]

    def test_the_budget_itself_is_fine(self):
        state = make_state([solution(totalTime=60)])

        assert detectors.detect_slow_accepted_solutions(state) == []

    def test_honours_the_threshold(self):
        state = make_state(
            [solution(totalTime=11)],
            thresholds=IssueThresholds(acceptedTotalTimeSeconds=10),
        )

        assert len(detectors.detect_slow_accepted_solutions(state)) == 1

    def test_skips_an_incomplete_run(self):
        """A sum over part of the testset understates the total."""
        state = make_state([solution(totalTime=500, complete=False)])

        assert detectors.detect_slow_accepted_solutions(state) == []

    def test_skips_a_sanitized_run(self):
        state = make_state([solution(totalTime=500)], sanitized=True)

        assert detectors.detect_slow_accepted_solutions(state) == []

    @pytest.mark.parametrize(
        'expected',
        [ExpectedOutcome.ACCEPTED_OR_TLE, ExpectedOutcome.TIME_LIMIT_EXCEEDED],
    )
    def test_skips_solutions_not_declared_accepted(self, expected):
        state = make_state(
            [
                solution(
                    totalTime=500,
                    expectedOutcome=expected,
                    outcome=Outcome.TIME_LIMIT_EXCEEDED,
                )
            ]
        )

        assert detectors.detect_slow_accepted_solutions(state) == []

    def test_runs_as_part_of_detect_all(self):
        state = make_state([solution(totalTime=500)])

        assert [i.code for i in detectors.detect_all(state)] == [
            IssueCode.SLOW_ACCEPTED_SOLUTION
        ]


class TestLargeTestset:
    MB = 1024 * 1024

    def test_flags_inputs_and_answers_together(self):
        state = config_state(
            testset_input_bytes=150 * self.MB, testset_answer_bytes=60 * self.MB
        )

        assert config_detectors.detect_large_testset(state) == [
            schema.LargeTestsetIssue(
                inputBytes=150 * self.MB,
                answerBytes=60 * self.MB,
                thresholdBytes=200 * self.MB,
            )
        ]

    def test_the_budget_itself_is_fine(self):
        state = config_state(testset_input_bytes=200 * self.MB, testset_answer_bytes=0)

        assert config_detectors.detect_large_testset(state) == []

    def test_silent_when_nothing_is_built(self):
        assert config_detectors.detect_large_testset(config_state()) == []

    def test_honours_the_threshold(self):
        state = config_state(
            testset_input_bytes=30 * self.MB,
            testset_answer_bytes=0,
            thresholds=IssueThresholds(testsetSizeMb=50),
        )

        assert config_detectors.detect_large_testset(state) == []

    def test_measures_the_built_files(self, tmp_path: pathlib.Path):
        from rbx.box.generation_schema import (
            GenerationMetadata,
            GenerationTestcaseEntry,
        )
        from rbx.box.schema import Testcase
        from rbx.box.testcase_schema import TestcaseEntry

        def entry(i: int, in_size: int, ans_size: int) -> GenerationTestcaseEntry:
            inp = tmp_path / f'{i}.in'
            ans = tmp_path / f'{i}.ans'
            inp.write_bytes(b'x' * in_size)
            ans.write_bytes(b'y' * ans_size)
            return GenerationTestcaseEntry(
                group_entry=TestcaseEntry(group='main', index=i),
                subgroup_entry=TestcaseEntry(group='main', index=i),
                metadata=GenerationMetadata(
                    copied_to=Testcase(inputPath=inp, outputPath=ans)
                ),
            )

        unbuilt = GenerationTestcaseEntry(
            group_entry=TestcaseEntry(group='main', index=9),
            subgroup_entry=TestcaseEntry(group='main', index=9),
            metadata=GenerationMetadata(
                copied_to=Testcase(inputPath=tmp_path / 'missing.in')
            ),
        )

        sizes = config_state_module._measure_testcases(  # noqa: SLF001
            [entry(0, 10, 3), entry(1, 5, 0), unbuilt]
        )

        assert sizes == [
            config_state_module.TestcaseSize(
                input_path=tmp_path / '0.in',
                input_bytes=10,
                answer_path=tmp_path / '0.ans',
                answer_bytes=3,
            ),
            config_state_module.TestcaseSize(
                input_path=tmp_path / '1.in',
                input_bytes=5,
                answer_path=tmp_path / '1.ans',
                answer_bytes=0,
            ),
        ]
        assert config_state_module._measure_testset(sizes) == (15, 3)  # noqa: SLF001

    def test_measures_nothing_when_nothing_is_built(self):
        assert config_state_module._measure_testcases([]) == []  # noqa: SLF001
        assert config_state_module._measure_testset([]) == (None, None)  # noqa: SLF001


def built_case(i: int, input_mb: float, answer_mb: float):
    mb = 1024 * 1024
    return config_state_module.TestcaseSize(
        input_path=pathlib.Path(f'build/tests/main/{i:03}.in'),
        input_bytes=int(input_mb * mb),
        answer_path=pathlib.Path(f'build/tests/main/{i:03}.ans'),
        answer_bytes=int(answer_mb * mb),
    )


class TestLargeTestcase:
    MB = 1024 * 1024

    def test_names_the_largest_input_and_counts_the_rest(self):
        state = config_state(
            testcase_sizes=[
                built_case(0, 21, 1),
                built_case(1, 30, 1),
                built_case(2, 5, 1),
            ]
        )

        assert config_detectors.detect_large_testcases(state) == [
            schema.LargeTestcaseIssue(
                file='input',
                path=pathlib.Path('build/tests/main/001.in'),
                size=30 * self.MB,
                count=2,
                thresholdBytes=20 * self.MB,
            )
        ]

    def test_reports_inputs_and_answers_apart(self):
        state = config_state(
            testcase_sizes=[built_case(0, 25, 1), built_case(1, 1, 25)]
        )

        issues = config_detectors.detect_large_testcases(state)

        assert [(i.file, i.path.name) for i in issues] == [
            ('input', '000.in'),
            ('answer', '001.ans'),
        ]

    def test_the_budget_itself_is_fine(self):
        state = config_state(testcase_sizes=[built_case(0, 20, 20)])

        assert config_detectors.detect_large_testcases(state) == []

    def test_silent_when_nothing_is_built(self):
        assert config_detectors.detect_large_testcases(config_state()) == []

    def test_honours_each_threshold(self):
        state = config_state(
            testcase_sizes=[built_case(0, 3, 3)],
            thresholds=IssueThresholds(testcaseInputSizeMb=2, testcaseAnswerSizeMb=5),
        )

        assert [i.file for i in config_detectors.detect_large_testcases(state)] == [
            'input'
        ]

    def test_is_worded(self):
        issue = schema.LargeTestcaseIssue(
            file='answer',
            path=pathlib.Path('build/tests/main/001.ans'),
            size=30 * self.MB,
            count=3,
            thresholdBytes=20 * self.MB,
        )

        summary = rendering.summarize(issue)
        assert summary.startswith('answer [item]build/tests/main/001.ans[/item] is ')
        assert 'and 2 more' in summary
        assert 'per answer' in summary


class TestBuildReportIgnores:
    def _write_run(self, runs_dir: pathlib.Path) -> None:
        run_report.write_report(
            run_report.report_path(runs_dir),
            RunReport(solutions=[solution(totalTime=500)]),
        )

    def test_ignored_issues_move_aside(self, tmp_path: pathlib.Path):
        self._write_run(tmp_path)

        report = build_report(
            tmp_path,
            config_state=config_state(has_validator=False),
            ignore=[IssueCode.NO_VALIDATOR],
        )

        assert [i.code for i in report.issues] == [IssueCode.SLOW_ACCEPTED_SOLUTION]
        assert [i.code for i in report.ignored] == [IssueCode.NO_VALIDATOR]
        assert report.warnings() == report.issues

    def test_ignoring_an_error_stops_it_counting(self, tmp_path: pathlib.Path):
        report = build_report(
            tmp_path,
            config_state=config_state(solutions=[]),
            ignore=[IssueCode.NO_ACCEPTED_SOLUTION],
        )

        assert report.errors() == []

    def test_thresholds_reach_the_run_detectors(self, tmp_path: pathlib.Path):
        self._write_run(tmp_path)

        report = build_report(
            tmp_path, thresholds=IssueThresholds(acceptedTotalTimeSeconds=1000)
        )

        assert report.issues == []

    def test_ignored_lands_in_the_json(self, tmp_path: pathlib.Path):
        report = build_report(
            tmp_path,
            config_state=config_state(has_validator=False),
            ignore=[IssueCode.NO_VALIDATOR],
        )

        data = report.model_dump(mode='json')

        assert data['issues'] == []
        assert [i['code'] for i in data['ignored']] == ['no-validator']


class TestScopedIgnoreRules:
    def test_accepts_codes_and_rules_side_by_side(self):
        config = IssuesConfig.model_validate(
            {
                'ignore': [
                    'no-samples',
                    {'code': 'borderline-tle', 'on': 'sols/slow-*.cpp', 'reason': 'r'},
                ]
            }
        )

        assert config.rules() == [
            IgnoreRule(code=IssueCode.NO_SAMPLES),
            IgnoreRule(code=IssueCode.BORDERLINE_TLE, on='sols/slow-*.cpp', reason='r'),
        ]

    def test_rejects_on_for_a_whole_problem_code(self):
        with pytest.raises(pydantic.ValidationError, match='problem as a whole'):
            IgnoreRule(code=IssueCode.NO_SAMPLES, on='x')

    @pytest.mark.parametrize('on', ['', '  ', '/abs/sols/a.cpp'])
    def test_rejects_an_empty_or_absolute_on(self, on):
        with pytest.raises(pydantic.ValidationError, match='relative to the problem'):
            IgnoreRule(code=IssueCode.BORDERLINE_TLE, on=on)

    def test_rejects_an_unknown_key(self):
        with pytest.raises(pydantic.ValidationError):
            IssuesConfig.model_validate(
                {'ignore': [{'code': 'borderline-tle', 'solution': 'x'}]}
            )

    @pytest.mark.parametrize(
        'pattern, subject, expected',
        [
            ('sols/slow-*.cpp', 'sols/slow-a.cpp', True),
            ('sols/*.cpp', 'sols/deep/a.cpp', False),
            ('sols/**/*.cpp', 'sols/deep/a.cpp', True),
            ('sols/**/*.cpp', 'sols/a.cpp', True),
            ('./sols/a.cpp', 'sols/a.cpp', True),
            ('sols/a?.cpp', 'sols/ab.cpp', True),
            ('sols/[ab].cpp', 'sols/c.cpp', False),
            ('main/*', 'main/3', True),
            ('small', 'smaller', False),
        ],
    )
    def test_globs_like_solution_entries(self, pattern, subject, expected):
        assert glob_matches(pattern, subject) is expected

    def test_matches_the_solution_path_glob(self, tmp_path):
        """The same pattern means the same files to `Path.glob` and to a rule."""
        for name in ('sols/a.cpp', 'sols/deep/b.cpp'):
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text('')
        for pattern in ('sols/*.cpp', 'sols/**/*.cpp', 'sols/*/*.cpp'):
            globbed = {
                p.relative_to(tmp_path).as_posix()
                for p in tmp_path.glob(pattern)
                if p.is_file()
            }
            assert {
                s for s in ('sols/a.cpp', 'sols/deep/b.cpp') if glob_matches(pattern, s)
            } == globbed

    def test_silences_only_the_matching_solution(self, tmp_path: pathlib.Path):
        run_report.write_report(
            run_report.report_path(tmp_path),
            RunReport(
                solutions=[
                    solution(path='sols/slow-ok.cpp', index=0, totalTime=500),
                    solution(path='sols/main.cpp', index=1, totalTime=500),
                ]
            ),
        )
        rule = IgnoreRule(
            code=IssueCode.SLOW_ACCEPTED_SOLUTION, on='sols/slow-*.cpp', reason='r'
        )

        report = build_report(tmp_path, ignore=[rule])

        assert [schema.subject_of(i) for i in report.issues] == ['sols/main.cpp']
        assert [schema.subject_of(i) for i in report.ignored] == ['sols/slow-ok.cpp']
        assert report.ignoredBy == [rule]

    def test_a_plain_code_still_silences_everything(self, tmp_path: pathlib.Path):
        run_report.write_report(
            run_report.report_path(tmp_path),
            RunReport(
                solutions=[
                    solution(path='sols/a.cpp', index=0, totalTime=500),
                    solution(path='sols/b.cpp', index=1, totalTime=500),
                ]
            ),
        )

        report = build_report(tmp_path, ignore=[IssueCode.SLOW_ACCEPTED_SOLUTION])

        assert report.issues == []
        assert (
            report.ignoredBy == [IgnoreRule(code=IssueCode.SLOW_ACCEPTED_SOLUTION)] * 2
        )

    def test_subjects_by_kind(self):
        from rbx.box.linters.asset_kind import AssetKind
        from rbx.box.run_validation import UnhitBound
        from rbx.box.testset_findings import DuplicateTest

        assert schema.subject_of(schema.BorderlineTleIssue(solution='s.cpp')) == 's.cpp'
        assert (
            schema.subject_of(
                schema.AssetCompilationWarningsIssue(
                    path='gens/g.cpp',
                    assetKind=AssetKind.GENERATOR,
                    log=pathlib.Path('x'),
                )
            )
            == 'gens/g.cpp'
        )
        assert schema.subject_of(schema.EmptyTestGroupIssue(group='big')) == 'big'
        assert (
            schema.subject_of(
                schema.BoundsNotHitIssue(
                    group=None, bounds=[UnhitBound(name='N', missing=['max'])]
                )
            )
            is None
        )
        assert (
            schema.subject_of(
                schema.DuplicateTestIssue(
                    duplicate=DuplicateTest(
                        test='main/3 (gen 5)',
                        of='main/1',
                        reason='input',
                        name='main/3',
                    )
                )
            )
            == 'main/3'
        )
        # A record from before `name` existed falls back to the display form.
        assert (
            schema.subject_of(
                schema.DuplicateTestIssue(
                    duplicate=DuplicateTest(
                        test='main/4 (gen 7)', of='main/2', reason='input'
                    )
                )
            )
            == 'main/4'
        )
        assert schema.subject_of(schema.NoValidatorIssue()) is None

    def test_flags_a_rule_that_matches_nothing(self):
        rule = IgnoreRule(code=IssueCode.BORDERLINE_TLE, on='sols/gone.cpp')
        state = config_state(stale_ignore_rules=[rule])

        (issue,) = config_detectors.detect_stale_ignore_rules(state)

        assert issue.code == IssueCode.STALE_IGNORE_RULE
        assert issue.severity == schema.IssueSeverity.WARNING
        assert issue.rule == rule
        assert 'sols/gone.cpp' in rendering.summarize(issue)


class TestStaleRuleCollection:
    async def test_collects_rules_matching_nothing_declared(self, testing_pkg):
        testing_pkg.add_solution('sols/slow.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
        testing_pkg.add_file('sols/slow.cpp').write_text('')
        # On disk, but no longer declared: a rule for it silences nothing.
        testing_pkg.add_file('sols/dropped.cpp').write_text('')
        testing_pkg.add_file('gens/gen.cpp').write_text('')
        testing_pkg.add_testgroup_from_glob('small', 'tests/*.in')
        stale_solution = {'code': 'borderline-tle', 'on': 'sols/renamed-*.cpp'}
        dropped_solution = {'code': 'borderline-tle', 'on': 'sols/dropped.cpp'}
        stale_file = {'code': 'linter-warnings', 'on': 'gens/old.cpp'}
        stale_group = {'code': 'empty-test-group', 'on': 'big*'}
        testing_pkg.yml.issues = IssuesConfig.model_validate(
            {
                'ignore': [
                    'no-samples',
                    {'code': 'borderline-tle', 'on': 'sols/slow.cpp'},
                    {'code': 'linter-warnings', 'on': 'gens/*.cpp'},
                    {'code': 'empty-test-group', 'on': 'small'},
                    {'code': 'duplicate-test', 'on': 'small/9'},
                    stale_solution,
                    dropped_solution,
                    stale_file,
                    stale_group,
                ]
            }
        )
        testing_pkg.save()

        state = await config_state_module.collect_config_state(testing_pkg.yml)

        assert state.stale_ignore_rules == [
            IgnoreRule.model_validate(rule)
            for rule in (stale_solution, dropped_solution, stale_file, stale_group)
        ]


class TestRunReportTotals:
    def test_new_fields_are_additive(self):
        entry = RunSolutionReport(
            path='a', index=0, expectedOutcome=ExpectedOutcome.ACCEPTED, status='OK'
        )

        assert entry.totalTime is None
        assert entry.complete is False


@pytest.fixture
def captured():
    """Prints into a recorder; call `.export_text()` for what was printed."""
    recorder = rich.console.Console(record=True, width=200)
    with mock.patch.object(rendering.console, 'console', recorder):
        yield recorder


class TestRendering:
    def _report(self, **kwargs) -> schema.IssueReport:
        return schema.IssueReport(neverRun=False, ranAt=time.time(), **kwargs)

    def test_each_line_carries_its_code(self, captured):
        rendering.print_report(self._report(issues=[schema.NoValidatorIssue()]))

        out = captured.export_text()
        assert '(no-validator)' in out

    def test_the_docs_link_follows_the_list(self, captured):
        rendering.print_report(self._report(issues=[schema.NoValidatorIssue()]))

        out = captured.export_text()
        assert out.rstrip().endswith(DOCS_URL)

    def test_no_docs_link_when_there_is_nothing_to_explain(self, captured):
        rendering.print_report(self._report())

        assert DOCS_URL not in captured.export_text()

    def test_ignored_issues_are_counted_not_shown(self, captured):
        rendering.print_report(
            self._report(
                issues=[schema.NoSamplesIssue()], ignored=[schema.NoValidatorIssue()]
            )
        )

        out = captured.export_text()
        assert 'has no validator' not in out
        assert '1 more silenced by issues.ignore (no-validator)' in out

    def test_show_ignored_lists_them_marked(self, captured):
        rendering.print_report(
            self._report(ignored=[schema.NoValidatorIssue()]), show_ignored=True
        )

        out = captured.export_text()
        assert '(ignored no-validator)' in out

    def test_new_kinds_are_worded(self):
        assert rendering.summarize(
            schema.SlowAcceptedSolutionIssue(
                solution='s', totalTime=74.25, threshold=60
            )
        ) == ('took 74.2s over the whole testset (budget 60s)')
        assert 'budget' in rendering.summarize(
            schema.LargeTestsetIssue(
                inputBytes=21 * 1024 * 1024,
                answerBytes=6 * 1024 * 1024,
                thresholdBytes=20 * 1024 * 1024,
            )
        )
