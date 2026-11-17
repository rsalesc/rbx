"""No judge rbx packages for runs several processes against one interactor yet
(CMS is #1043), so every packager refuses a fanout problem before the build."""

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
from rbx.box.schema import TaskType

PACKAGERS = [
    BocaPackager,
    DomjudgePackager,
    MojPackager,
    PkgPackager,
    PolygonPackager,
]


def _fanout_problem(testing_pkg) -> None:
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.set_interactor('interactor.cpp')
    testing_pkg.yml.interactor.processes = 3
    testing_pkg.save()


@pytest.mark.parametrize('packager_cls', PACKAGERS)
def test_refuses_a_fanout_problem_before_the_build(testing_pkg, packager_cls, capsys):
    _fanout_problem(testing_pkg)

    with mock.patch('rbx.box.builder.verify') as verify:
        with pytest.raises(typer.Exit):
            asyncio.run(packager_module.run_packager(packager_cls, verification=0))

    verify.assert_not_called()
    out = ' '.join(capsys.readouterr().out.split())
    assert f'Packager {packager_cls.name()} does not support' in out
    assert 'interactor.processes' in out
