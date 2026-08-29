import json
import pathlib
import re
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box.cli import app
from rbx.box.testing import testing_package

runner = CliRunner()


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _plain(output: str) -> str:
    """Drop the styling, leaving the text the setter would read.

    The console disables Rich's highlighter, but it still emits SGR codes for
    the `item` style and for its own `info` default style.
    """
    return _ANSI.sub('', output)


@pytest.fixture(autouse=True)
def _skip_preset_check():
    # The root Typer callback checks the active preset's compatibility, which is
    # unrelated to the wiring under test and fails for the bare testing package.
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


@pytest.mark.test_pkg('problems/interactive')
def test_vars_json_dumps_expanded_dotted_keys(pkg_from_testdata: pathlib.Path):
    result = runner.invoke(app, ['vars', '--json'])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {'N.min': '1', 'N.max': '1000000'}


def test_vars_json_preserves_ints_too_large_for_a_double(
    testing_pkg: testing_package.TestingPackage,
):
    """The whole reason values cross as strings.

    `10**18 + 7` is a plausible bound and is not representable as an IEEE
    double: emitted as a JSON number, `JSON.parse` would hand the extension
    `1000000000000000000` and it would badge a wrong value with full
    confidence. Rendering in Python keeps every digit.
    """
    testing_pkg.set_vars({'MOD': 'py`10**18 + 7`'})

    result = runner.invoke(app, ['vars', '--json'])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {'MOD': '1000000000000000007'}


def test_vars_json_renders_values_as_jinja_would(
    testing_pkg: testing_package.TestingPackage,
):
    """The badge predicts what the statement will show, so it must match Jinja.

    Notably a bool is `True`/`False` here, not the `1`/`0` that
    `render_var_on_command_line` produces -- that spelling is about testlib and
    jngen argument parsing, not about what `\\VAR{flag}` renders to.
    """
    testing_pkg.set_vars(
        {
            'flag': True,
            'off': False,
            'ratio': 1.5,
            'label': 'foo',
        }
    )

    result = runner.invoke(app, ['vars', '--json'])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        'flag': 'True',
        'off': 'False',
        'ratio': '1.5',
        'label': 'foo',
    }


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
    testing_pkg.set_vars(
        {
            'styled': '[bold]weight[/bold]',
            'broken': 'a [/nope] b',
        }
    )

    result = runner.invoke(app, ['vars'])

    assert result.exit_code == 0, result.output
    assert 'styled = [bold]weight[/bold]' in _plain(result.output)
    assert 'broken = a [/nope] b' in _plain(result.output)


def test_vars_json_fails_cleanly_on_non_finite_var(
    testing_pkg: testing_package.TestingPackage,
):
    """An infinite bound is a package bug, so it is surfaced rather than badged.

    `str(float('inf'))` would serialize fine now that values cross as strings,
    but `inf` is never a bound a setter meant to write. The extension degrades
    on a non-zero exit, so failing is the useful answer; what it must not do is
    quietly hand back a badge reading `inf`.
    """
    testing_pkg.set_vars({'huge': 'py`float("inf")`'})

    result = runner.invoke(app, ['vars', '--json'])

    assert result.exit_code == 1, result.output
    assert 'Infinity' not in result.output
    assert 'huge' in _plain(result.output)


@pytest.mark.test_pkg('problems/interactive')
def test_render_evaluates_filters_for_the_text_target(pkg_from_testdata: pathlib.Path):
    result = runner.invoke(
        app, ['vars', '--render', '--target', 'text'], input='N.max | sci\nN.max\n'
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        'N.max | sci': '10⁶',
        'N.max': '1000000',
    }


@pytest.mark.test_pkg('problems/interactive')
def test_render_spells_the_same_expression_differently_per_target(
    pkg_from_testdata: pathlib.Path,
):
    """The whole reason `--target` exists: same rules, different spelling."""
    result = runner.invoke(
        app, ['vars', '--render', '--target', 'latex'], input='N.max | sci\n'
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {'N.max | sci': '10^{6}'}


@pytest.mark.test_pkg('problems/interactive')
def test_render_reaches_the_vars_namespace_too(pkg_from_testdata: pathlib.Path):
    """`\\VAR{N.max}` is shorthand for `\\VAR{vars.N.max}`; both must render."""
    result = runner.invoke(app, ['vars', '--render'], input='vars.N.max | sci\n')

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {'vars.N.max | sci': '10⁶'}


@pytest.mark.test_pkg('problems/interactive')
def test_render_omits_an_expression_it_cannot_evaluate(pkg_from_testdata: pathlib.Path):
    """Absent, not an error: the extension draws no badge and moves on."""
    result = runner.invoke(
        app,
        ['vars', '--render', '--target', 'text'],
        input='N.max | nosuchfilter\nN.typo\nN.max\n',
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {'N.max': '1000000'}


@pytest.mark.test_pkg('problems/interactive')
def test_render_reports_what_it_dropped_on_stderr(pkg_from_testdata: pathlib.Path):
    """Dropping silently would make a bug in a filter undiagnosable.

    stdout carries the JSON map, so the diagnosis goes to stderr, where it
    cannot corrupt what the extension parses.
    """
    result = runner.invoke(app, ['vars', '--render'], input='N.max | nosuchfilter\n')

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {}
    assert 'nosuchfilter' in _plain(result.stderr)


@pytest.mark.test_pkg('problems/interactive')
def test_render_with_no_expressions_is_an_empty_object(pkg_from_testdata: pathlib.Path):
    result = runner.invoke(app, ['vars', '--render'], input='')

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {}


@pytest.mark.test_pkg('problems/interactive')
def test_render_asks_once_for_a_repeated_expression(pkg_from_testdata: pathlib.Path):
    """A statement repeats a bound; the map is keyed by expression regardless.

    The keys come back in order of first appearance -- not that a consumer of a
    JSON object should care, but the docstring promises it, so it is pinned.
    """
    result = runner.invoke(
        app, ['vars', '--render'], input='N.max | sci\n\n  N.min  \nN.max | sci\n'
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert parsed == {'N.max | sci': '10⁶', 'N.min': '1'}
    assert list(parsed) == ['N.max | sci', 'N.min']


@pytest.mark.test_pkg('problems/interactive')
def test_render_refuses_to_be_combined_with_json(pkg_from_testdata: pathlib.Path):
    """Two different output shapes; picking one silently would mislead."""
    result = runner.invoke(app, ['vars', '--render', '--json'], input='N.max\n')

    assert result.exit_code == 1, result.output


@pytest.mark.test_pkg('problems/interactive')
def test_render_creates_no_cache_dir(pkg_from_testdata: pathlib.Path):
    """Rendering pulls in the statements module; it must stay read-only too."""
    from rbx.box.package import get_problem_cache_path

    cache = get_problem_cache_path(pkg_from_testdata)
    assert not cache.exists()

    result = runner.invoke(app, ['vars', '--render'], input='N.max | sci\n')

    assert result.exit_code == 0, result.output
    assert not cache.exists()
