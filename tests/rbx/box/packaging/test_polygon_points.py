from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.packaging.polygon import xml_schema as polygon_schema
from rbx.box.packaging.polygon.packager import PolygonPackager
from rbx.box.schema import ScoreType, Testcase, TestcaseGroup
from rbx.box.testcase_schema import TestcaseEntry


def _entry(group: str, index: int) -> GenerationTestcaseEntry:
    return GenerationTestcaseEntry(
        group_entry=TestcaseEntry(group=group, index=index),
        subgroup_entry=TestcaseEntry(group=group, index=index),
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=f'{group}/{index}.in')
        ),
    )


ENTRIES = [
    _entry('samples', 0),
    _entry('small', 0),
    _entry('small', 1),
    _entry('big', 0),
]


def _set_points_groups(testing_pkg):
    testing_pkg.yml.scoring = ScoreType.POINTS
    testing_pkg.yml.testcases = [
        TestcaseGroup(name='samples'),
        TestcaseGroup(name='small', score=40),
        # `empty` has no built tests, so it and the dependency on it are dropped.
        TestcaseGroup(name='big', score=60, deps=['small', 'empty']),
        TestcaseGroup(name='empty', score=0),
    ]
    testing_pkg.save()


def test_points_problem_declares_groups(testing_pkg):
    _set_points_groups(testing_pkg)

    packager = PolygonPackager(testcase_entries=[])
    tests, groups = packager._get_tests_and_groups(ENTRIES)  # noqa: SLF001

    # The group's score sits on its last test, so the test points add up too.
    assert tests == [
        polygon_schema.Test(sample=True, group='samples', points=0.0),
        polygon_schema.Test(group='small', points=0.0),
        polygon_schema.Test(group='small', points=40.0),
        polygon_schema.Test(group='big', points=60.0),
    ]
    assert groups == [
        polygon_schema.Group(name='samples', points=0.0, feedback_policy='complete'),
        polygon_schema.Group(name='small', points=40.0),
        polygon_schema.Group(
            name='big',
            points=60.0,
            dependencies=[polygon_schema.Dependency(group='small')],
        ),
    ]


def test_binary_problem_declares_no_groups(testing_pkg):
    testing_pkg.yml.testcases = [
        TestcaseGroup(name='samples'),
        TestcaseGroup(name='small'),
        TestcaseGroup(name='big'),
    ]
    testing_pkg.save()

    packager = PolygonPackager(testcase_entries=[])
    tests, groups = packager._get_tests_and_groups(ENTRIES)  # noqa: SLF001

    assert tests == [
        polygon_schema.Test(sample=True),
        polygon_schema.Test(),
        polygon_schema.Test(),
        polygon_schema.Test(),
    ]
    assert groups == []
