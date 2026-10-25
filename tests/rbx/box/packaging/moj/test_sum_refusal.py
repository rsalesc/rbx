import pytest
import typer

from rbx.box.packaging.moj import packager as moj_packager
from rbx.box.schema import Package, PointsScoring, TestcaseGroup


def _package(**scoring) -> Package:
    return Package(
        name='prob',
        timeLimit=1000,
        memoryLimit=256,
        scoring=PointsScoring(**scoring),
        testcases=[
            TestcaseGroup(name='samples'),
            TestcaseGroup(name='big', score=100),
        ],
    )


def test_min_groups_are_packaged():
    moj_packager._refuse_sum_groups(_package())  # noqa: SLF001


def test_sum_groups_are_refused():
    # MOJ pays a group all or nothing, so per-test shares cannot be expressed.
    with pytest.raises(typer.Exit):
        moj_packager._refuse_sum_groups(_package(aggregation='sum'))  # noqa: SLF001
