"""The API upload scores a problem as the offline `problem.zip` does: same groups,
points and dependencies, and the same solutions tagged (or left out)."""

from unittest import mock

import pytest

from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.packaging.polygon import polygon_api as api
from rbx.box.packaging.polygon import upload
from rbx.box.packaging.polygon.statement_block_utils import process_statements
from rbx.box.schema import (
    ExpectedOutcome,
    PointsScoring,
    ScoreType,
    Solution,
    Testcase,
    TestcaseGroup,
)
from rbx.box.scoring.dependencies import Aggregation
from rbx.box.testcase_schema import TestcaseEntry


def _entry(group: str, index: int) -> GenerationTestcaseEntry:
    return GenerationTestcaseEntry(
        group_entry=TestcaseEntry(group=group, index=index),
        subgroup_entry=TestcaseEntry(group=group, index=index),
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=f'{group}/{index}.in')
        ),
    )


def _solution(outcome: ExpectedOutcome) -> Solution:
    return Solution(path='sols/a.cpp', outcome=outcome)


@pytest.mark.parametrize(
    'outcome,is_first,tag',
    [
        (ExpectedOutcome.ACCEPTED, True, api.SolutionTag.MA),
        (ExpectedOutcome.ACCEPTED, False, api.SolutionTag.OK),
        (ExpectedOutcome.ACCEPTED_OR_TLE, False, api.SolutionTag.TO),
        (ExpectedOutcome.WRONG_ANSWER, False, api.SolutionTag.WA),
        (ExpectedOutcome.TIME_LIMIT_EXCEEDED, False, api.SolutionTag.TL),
        (ExpectedOutcome.TLE_OR_MLE, False, api.SolutionTag.TM),
        (ExpectedOutcome.MEMORY_LIMIT_EXCEEDED, False, api.SolutionTag.ML),
        (ExpectedOutcome.RUNTIME_ERROR, False, api.SolutionTag.RE),
        (ExpectedOutcome.INCORRECT, False, api.SolutionTag.RJ),
        # Polygon judges a partial result OK, so the zip drops these; so does
        # the upload.
        (ExpectedOutcome.PARTIALLY_CORRECT, False, None),
        (ExpectedOutcome.ANY, False, None),
    ],
)
def test_solution_tags_match_the_offline_package(outcome, is_first, tag):
    assert upload._get_solution_tag(_solution(outcome), is_first=is_first) == tag  # noqa: SLF001


def test_partially_correct_solutions_are_not_uploaded(testing_pkg, capsys):
    testing_pkg.add_solution('sols/main.cpp', outcome='accepted').write_text(
        'int main(){}\n'
    )
    testing_pkg.add_solution('sols/half.cpp', outcome='partially correct').write_text(
        'int main(){}\n'
    )
    testing_pkg.save()
    problem = mock.Mock(name='RecordingProblem')
    problem.solutions.return_value = [
        api.Solution('main.cpp', 0, 0, 'cpp.g++17', 'MA'),
    ]

    upload._upload_solutions(problem, upload._build_upload_namespace([]))  # noqa: SLF001

    assert [c.args[0] for c in problem.save_solution.call_args_list] == ['main.cpp']
    assert 'PARTIALLY_CORRECT' in capsys.readouterr().out


def _points_groups(testing_pkg):
    testing_pkg.yml.scoring = PointsScoring()
    testing_pkg.yml.testcases = [
        TestcaseGroup(name='samples'),
        TestcaseGroup(name='small', score=40),
        TestcaseGroup(
            name='big', score=60, deps=['small'], aggregation=Aggregation.SUM
        ),
    ]
    testing_pkg.save()


def test_upload_scoring_mirrors_the_offline_groups(testing_pkg):
    _points_groups(testing_pkg)
    problem = mock.Mock(name='RecordingProblem')
    problem.tests.return_value = []
    # Polygon numbers the generated `big` tests after the manual ones, whatever
    # order the entries came in.
    landed = [
        (1, _entry('samples', 0)),
        (2, _entry('small', 0)),
        (3, _entry('small', 1)),
        (5, _entry('big', 1)),
        (4, _entry('big', 0)),
    ]

    upload._upload_scoring(problem, landed)  # noqa: SLF001

    problem.enable_points.assert_called_once_with(True)
    problem.enable_groups.assert_called_once_with('tests', True)
    assert problem.set_test_group.call_args_list == [
        mock.call('tests', 'samples', [1]),
        mock.call('tests', 'small', [2, 3]),
        mock.call('tests', 'big', [4, 5]),
    ]
    assert problem.save_test_group.call_args_list == [
        mock.call(
            'tests',
            'samples',
            points_policy=api.PointsPolicy.COMPLETE_GROUP,
            feedback_policy=api.FeedbackPolicy.COMPLETE,
            dependencies=[],
        ),
        mock.call(
            'tests',
            'small',
            points_policy=api.PointsPolicy.COMPLETE_GROUP,
            feedback_policy=api.FeedbackPolicy.ICPC,
            dependencies=[],
        ),
        mock.call(
            'tests',
            'big',
            points_policy=api.PointsPolicy.EACH_TEST,
            feedback_policy=api.FeedbackPolicy.POINTS,
            dependencies=['small'],
        ),
    ]
    # A `min` group's score sits on its last test; a `sum` group splits it.
    assert problem.save_test.call_args_list == [
        mock.call('tests', 1, None, test_points=0.0),
        mock.call('tests', 2, None, test_points=0.0),
        mock.call('tests', 3, None, test_points=40.0),
        mock.call('tests', 4, None, test_points=30.0),
        mock.call('tests', 5, None, test_points=30.0),
    ]


def test_upload_scoring_only_saves_points_that_changed(testing_pkg):
    _points_groups(testing_pkg)
    problem = mock.Mock(name='RecordingProblem')
    remote = [mock.Mock(index=1, points=0.0), mock.Mock(index=2, points=40.0)]
    problem.tests.return_value = remote

    upload._upload_scoring(  # noqa: SLF001
        problem, [(1, _entry('samples', 0)), (2, _entry('small', 0))]
    )

    problem.save_test.assert_not_called()


def test_upload_scoring_leaves_a_binary_problem_alone(testing_pkg):
    testing_pkg.yml.scoring = ScoreType.BINARY
    testing_pkg.save()
    problem = mock.Mock(name='RecordingProblem')

    upload._upload_scoring(problem, [(1, _entry('samples', 0))])  # noqa: SLF001

    assert problem.method_calls == []


def test_upload_scoring_warns_that_the_percent_mode_is_manual(testing_pkg, capsys):
    _points_groups(testing_pkg)
    testing_pkg.add_file('check.cpp').write_text(
        '#include "testlib.h"\nint main(){ quitp(50.0, "half"); }\n'
    )
    testing_pkg.set_checker('check.cpp')
    testing_pkg.save()
    problem = mock.Mock(name='RecordingProblem')
    problem.tests.return_value = []

    upload._upload_scoring(problem, [(1, _entry('samples', 0))])  # noqa: SLF001

    assert 'Treat points from checker as a percent' in capsys.readouterr().out


def test_upload_testcases_reports_where_each_test_landed(testing_pkg):
    for name in ('a', 'b', 'c'):
        testing_pkg.add_file(f'tests/{name}.in').write_text(f'{name}\n')
    testing_pkg.add_testgroup_with_manual_testcases(
        'main',
        testcases=[
            {'inputPath': 'tests/a.in'},
            {'inputPath': 'tests/b.in'},
            {'inputPath': 'tests/c.in'},
        ],
    )
    testing_pkg.save()
    problem = mock.Mock(name='RecordingProblem')
    # Polygon refuses `b` as a duplicate, so `c` takes its index.
    problem.save_test.side_effect = [
        None,
        api.PolygonRequestFailedException('Test coincides with test #1'),
        None,
    ]

    entries = upload._extracted_entries(None)  # noqa: SLF001
    landed = upload._upload_testcases(  # noqa: SLF001
        problem,
        upload._build_upload_namespace(entries),  # noqa: SLF001
        entries,
    )

    assert [(index, entry.group_entry.index) for index, entry in landed] == [
        (1, 0),
        (2, 2),
    ]


def test_a_problem_without_statements_uploads_none(testing_pkg):
    testing_pkg.save()
    callback = mock.Mock()

    process_statements(None, False, callback)

    callback.assert_not_called()
