import pathlib
from typing import Iterator

import pytest
from typer.testing import CliRunner

from rbx.box.testing import testing_package


@pytest.fixture
def preset_testing_pkg(
    request,
    pkg_from_resources: pathlib.Path,
) -> Iterator[testing_package.TestingPackage]:
    marker = request.node.get_closest_marker('preset_path')
    if marker is None:
        raise ValueError('preset_path marker not found')
    preset_path = pkg_from_resources / marker.args[0]
    with testing_package.TestingPackage(preset_path) as pkg:
        yield pkg


@pytest.mark.preset_path('problem')
@pytest.mark.resource_pkg('presets/default')
def test_default_preset_problem(preset_testing_pkg: testing_package.TestingPackage):
    from rbx.box.cli import app

    runner = CliRunner()

    # Test problem run
    result = runner.invoke(app, ['run'])
    print(result.stdout)
    assert result.exit_code == 0, 'rbx run failed'

    # Test problem unit tests
    result = runner.invoke(app, ['unit'])
    print(result.stdout)
    assert result.exit_code == 0, 'rbx unit failed'

    # Test problem build statement
    result = runner.invoke(app, ['st', 'b'])

    print(result.stdout)
    assert result.exit_code == 0, 'rbx st b failed'

    # Package to BOCA
    result = runner.invoke(app, ['pkg', 'boca'])
    print(result.stdout)
    assert result.exit_code == 0, 'rbx pkg boca failed'
