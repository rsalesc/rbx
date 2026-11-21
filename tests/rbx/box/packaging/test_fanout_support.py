"""Only CMS runs several processes against one interactor, so every packager
refuses a fanout problem before the build -- except Polygon's with `--cms`,
whose package CMS imports."""

import asyncio
from unittest import mock

import pytest
import typer
from typer.testing import CliRunner

from rbx.box.packaging import main as packaging_main
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
    assert 'rbx package polygon --cms' in out


def test_polygon_packages_a_fanout_problem_for_cms(testing_pkg):
    _fanout_problem(testing_pkg)

    with mock.patch('rbx.box.builder.verify', return_value=False) as verify:
        with pytest.raises(typer.Exit):
            asyncio.run(
                packager_module.run_packager(PolygonPackager, verification=0, cms=True)
            )

    # Past the gate: it got as far as the build (failed here on purpose).
    verify.assert_called_once()


@pytest.fixture
def runner() -> CliRunner:
    # The other tests' asyncio.run leaves no current loop, which syncer needs.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


def test_polygon_refuses_to_upload_a_fanout_problem(testing_pkg, runner):
    _fanout_problem(testing_pkg)

    with mock.patch.object(packaging_main, 'run_packager') as run_packager:
        result = runner.invoke(packaging_main.app, ['polygon', '--upload'])

    assert result.exit_code == 1
    run_packager.assert_not_called()
    assert 'Polygon cannot judge' in ' '.join(result.output.split())
