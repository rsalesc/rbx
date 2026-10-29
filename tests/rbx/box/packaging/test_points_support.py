"""A judge that scores all or nothing refuses a points problem before the build,
and warns about a binary problem whose checker awards `quitp` points."""

import asyncio
from unittest import mock

import pytest
import typer

from rbx.box.packaging import packager as packager_module
from rbx.box.packaging.boca.packager import BocaPackager
from rbx.box.packaging.domjudge.packager import DomjudgePackager
from rbx.box.packaging.moj.packager import MojPackager
from rbx.box.packaging.pkg.packager import PkgPackager
from rbx.box.packaging.polygon.packager import PolygonPackager
from rbx.box.schema import ScoreType

QUITP_CHECKER = '#include "testlib.h"\nint main(){ quitp(50.0, "half"); }\n'

ALL_OR_NOTHING = [BocaPackager, DomjudgePackager, PkgPackager]


def _points_problem(testing_pkg) -> None:
    testing_pkg.yml.scoring = ScoreType.POINTS
    testing_pkg.add_testgroup_with_manual_testcases('samples', [])
    testing_pkg.add_testgroup_with_manual_testcases('full', [])
    testing_pkg.yml.testcases[-1].score = 100
    testing_pkg.save()


@pytest.mark.parametrize('packager_cls', ALL_OR_NOTHING)
def test_refuses_a_points_problem_before_the_build(testing_pkg, packager_cls, capsys):
    _points_problem(testing_pkg)

    with mock.patch('rbx.box.builder.verify') as verify:
        with pytest.raises(typer.Exit):
            asyncio.run(packager_module.run_packager(packager_cls, verification=0))

    verify.assert_not_called()
    assert 'scored by points' in capsys.readouterr().out


@pytest.mark.parametrize('packager_cls', [PolygonPackager, MojPackager])
def test_judges_with_points_accept_a_points_problem(testing_pkg, packager_cls):
    _points_problem(testing_pkg)

    packager_module.check_points_support(packager_cls, testing_pkg.yml)


@pytest.mark.parametrize('packager_cls', ALL_OR_NOTHING)
def test_warns_about_a_quitp_checker_on_a_binary_problem(
    testing_pkg, packager_cls, capsys
):
    testing_pkg.add_file('check.cpp').write_text(QUITP_CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.save()

    packager_module.check_points_support(packager_cls, testing_pkg.yml)

    out = capsys.readouterr().out
    assert 'quitp' in out
    assert packager_cls.name() in out


def test_the_builtin_checker_draws_no_warning(testing_pkg, capsys):
    # testlib declares `quitp` itself, so only the checker as written is read.
    testing_pkg.save()

    packager_module.check_points_support(DomjudgePackager, testing_pkg.yml)

    assert 'quitp' not in capsys.readouterr().out
