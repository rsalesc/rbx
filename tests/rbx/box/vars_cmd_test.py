import json
import pathlib
import re

import pytest
from typer.testing import CliRunner

from rbx.box.cli import app
from rbx.box.testing import testing_package

runner = CliRunner()


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _plain(output: str) -> str:
    """Drop the styling Rich adds, leaving the text the setter would read."""
    return _ANSI.sub('', output)


def _with_vars(pkg: testing_package.TestingPackage, vars) -> None:
    """Give the package these vars, and a preset the CLI will accept.

    `TestingPreset` writes its `preset.rbx.yml` without a `min_version`, which
    the root callback refuses before any command runs.
    """
    pkg.preset.yml.min_version = '1.0.0'
    pkg.preset.save()
    pkg.set_vars(vars)


@pytest.mark.test_pkg('problems/interactive')
def test_vars_json_dumps_expanded_dotted_keys(pkg_from_testdata: pathlib.Path):
    result = runner.invoke(app, ['vars', '--json'])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {'N.min': 1, 'N.max': 1000000}


@pytest.mark.test_pkg('problems/interactive')
def test_vars_json_creates_no_cache_dir(pkg_from_testdata: pathlib.Path):
    """The extension spawns this while the user types; it must stay read-only.

    `get_problem_cache_dir` is what mkdirs the cache; nothing on the
    `rbx vars` path may reach it.
    """
    from rbx.box.package import get_problem_cache_path

    cache = get_problem_cache_path(pkg_from_testdata)
    assert not cache.exists()

    result = runner.invoke(app, ['vars', '--json'])

    assert result.exit_code == 0, result.output
    assert not cache.exists()


@pytest.mark.test_pkg('problems/interactive')
def test_vars_prints_readable_output_without_json(pkg_from_testdata: pathlib.Path):
    result = runner.invoke(app, ['vars'])

    assert result.exit_code == 0, result.output
    assert 'N.max = 1000000' in _plain(result.output)
    assert 'N.min = 1' in _plain(result.output)


def test_vars_does_not_render_markup_in_var_values(
    testing_pkg: testing_package.TestingPackage,
):
    """Var values are setter YAML, not markup.

    Rich would style `[bold]...[/bold]` away and raise on `[/nope]`, so both
    have to survive to the output verbatim.
    """
    _with_vars(
        testing_pkg,
        {
            'styled': '[bold]weight[/bold]',
            'broken': 'a [/nope] b',
        },
    )

    result = runner.invoke(app, ['vars'])

    assert result.exit_code == 0, result.output
    assert 'styled = [bold]weight[/bold]' in _plain(result.output)
    assert 'broken = a [/nope] b' in _plain(result.output)


def test_vars_json_fails_cleanly_on_non_finite_var(
    testing_pkg: testing_package.TestingPackage,
):
    """`json.dumps` would emit bare `Infinity`, which `JSON.parse` rejects.

    The extension degrades on a non-zero exit, so failing is right; what it
    must not do is hand back a payload that cannot be parsed.
    """
    _with_vars(testing_pkg, {'huge': 'py`float("inf")`'})

    result = runner.invoke(app, ['vars', '--json'])

    assert result.exit_code == 1, result.output
    assert 'Infinity' not in result.output
    assert 'huge' in _plain(result.output)
