"""What the Polygon packages carry for CMS's Polygon importer.

CMS (cms-dev, `cmscontrib/loaders/polygon.py`) runs `files/cms_conf.py` and
takes each contest problem's directory from the basename of its `url`.
"""

import pathlib
import types

import pytest
import typer

from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.packaging.polygon import xml_schema as polygon_schema
from rbx.box.packaging.polygon.packager import (
    PolygonContestPackager,
    PolygonPackager,
    ensure_cms_supports,
)
from rbx.box.schema import PointsScoring, ScoreType, TaskType, Testcase, TestcaseGroup
from rbx.box.scoring.dependencies import DependencyPolicy
from rbx.box.testcase_schema import TestcaseEntry


def _entries(tmp_path: pathlib.Path, groups):
    entries = []
    for group in groups:
        index = sum(entry.group_entry.group == group for entry in entries)
        path = tmp_path / group / f'{index}.in'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('1\n')
        entries.append(
            GenerationTestcaseEntry(
                group_entry=TestcaseEntry(group=group, index=index),
                subgroup_entry=TestcaseEntry(group=group, index=index),
                metadata=GenerationMetadata(copied_to=Testcase(inputPath=path)),
            )
        )
    return entries


def _datasets(conf: str):
    namespace = {}
    exec(conf, namespace)
    return namespace['datasets']


def test_cms_conf_scores_points_groups_with_their_deps(testing_pkg, tmp_path):
    testing_pkg.yml.scoring = ScoreType.POINTS
    testing_pkg.yml.testcases = [
        TestcaseGroup(name='samples'),
        TestcaseGroup(name='small', score=20),
        TestcaseGroup(name='medium', score=30, deps=['small']),
        # Transitive: `big` needs `medium`, which needs `small`.
        TestcaseGroup(name='big', score=50, deps=['medium']),
    ]
    testing_pkg.save()
    entries = _entries(tmp_path, ['samples', 'small', 'small', 'medium', 'big', 'big'])

    conf = PolygonPackager(testcase_entries=entries)._get_cms_conf()  # noqa: SLF001

    # CMS names tests by their 0-based index.
    assert _datasets(conf) == {
        'tests': {
            'score_type': 'GroupMin',
            'score_type_parameters': [
                [0, '^(000)$'],
                [20, '^(001|002)$'],
                [30, '^(003|001|002)$'],
                [50, '^(004|005|001|002|003)$'],
            ],
        }
    }


def test_cms_conf_follows_the_ladder_across_an_empty_group(testing_pkg, tmp_path):
    testing_pkg.yml.scoring = PointsScoring(dependencies=DependencyPolicy.LADDER)
    testing_pkg.yml.testcases = [
        TestcaseGroup(name='samples'),
        TestcaseGroup(name='small', score=20),
        # Built no tests: `big` must still chain down to `small` and `samples`.
        TestcaseGroup(name='medium', score=30),
        TestcaseGroup(name='big', score=50),
    ]
    testing_pkg.save()
    entries = _entries(tmp_path, ['samples', 'small', 'big'])

    conf = PolygonPackager(testcase_entries=entries)._get_cms_conf()  # noqa: SLF001

    assert _datasets(conf)['tests']['score_type_parameters'] == [
        [0, '^(000)$'],
        [20, '^(001|000)$'],
        [50, '^(002|000|001)$'],
    ]


def test_cms_conf_makes_binary_problems_all_or_nothing(testing_pkg, tmp_path):
    entries = _entries(tmp_path, ['main', 'main'])

    conf = PolygonPackager(testcase_entries=entries)._get_cms_conf()  # noqa: SLF001

    assert _datasets(conf) == {
        'tests': {
            'score_type': 'GroupMin',
            'score_type_parameters': [[100, '.*']],
        }
    }


def _built_problem(short_name: str):
    # `_get_problems` only reads the contest problem's short name.
    return types.SimpleNamespace(problem=types.SimpleNamespace(short_name=short_name))


def test_contest_problem_url_only_for_cms():
    built = [_built_problem('A')]

    plain = PolygonContestPackager()._get_problems(built)  # noqa: SLF001
    cms = PolygonContestPackager(cms=True)._get_problems(built)  # noqa: SLF001

    # The Codeforces taskbook rejects a `url` that is not an absolute URL.
    assert plain == [polygon_schema.ContestProblem(index='A', path='problems/A')]
    assert cms == [
        polygon_schema.ContestProblem(index='A', path='problems/A', url='problems/A')
    ]


def test_judging_io_attributes_are_hyphenated():
    xml = polygon_schema.Judging().to_xml()

    assert b'input-file=""' in xml
    assert b'output-file=""' in xml


def test_cms_refuses_interactive_problems(testing_pkg):
    interactive = testing_pkg.yml.model_copy(update={'type': TaskType.COMMUNICATION})

    # CMS's Polygon loader always creates batch tasks (#943).
    with pytest.raises(typer.Exit):
        ensure_cms_supports(interactive)
    ensure_cms_supports(testing_pkg.yml)
