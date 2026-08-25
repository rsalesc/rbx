"""What `rbx run -p` / `rbx irun --profile` select, and what an unknown one costs.

The flag is a per-command spelling of the root callback's `-p`: it picks which
`.limits/<name>.yml` the solutions are run against. What is pinned here is that
the profile is active by the time solutions run, that its absence changes
nothing, and that a name the package does not define stops the command before
anything is built.
"""

import asyncio
from typing import Any, Dict, Tuple
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli, limits_info, package, schema
from rbx.box.testing import testing_package
from rbx.utils import model_to_yaml


@pytest.fixture
def runner() -> CliRunner:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


@pytest.fixture(autouse=True)
def _skip_preset_check():
    # The root Typer callback checks the active preset's compatibility, which is
    # unrelated to the wiring under test and fails for the bare testing package.
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


@pytest.fixture(autouse=True)
def _clean_profile():
    # The profile lives in a context var that the CLI sets; a test that sets it
    # must not decide what the next one sees.
    token = limits_info.profile_var.set(None)
    yield
    limits_info.profile_var.reset(token)


def _write_profile(name: str) -> None:
    path = package.get_limits_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model_to_yaml(schema.LimitsProfile(timeLimit=2500)))


async def _build_ok(*args, **kwargs):
    return True


def _invoke_run(runner: CliRunner, *args: str) -> Tuple[Any, Dict[str, Any]]:
    """`rbx run`, with the build and the run itself stubbed out."""
    calls: Dict[str, Any] = {}

    async def run_solutions(*positional, **kwargs):
        calls['profile'] = limits_info.get_active_profile()
        calls['kwargs'] = kwargs
        result = mock.MagicMock()
        result.close = mock.AsyncMock()
        return result

    async def print_run_report(*positional, **kwargs):
        return True

    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.cli.commands.run.run_solutions', run_solutions),
        mock.patch('rbx.box.cli.commands.run.print_run_report', print_run_report),
    ):
        result = runner.invoke(cli.app, ['run', *args])
    return result, calls


def _invoke_irun(runner: CliRunner, *args: str) -> Tuple[Any, Dict[str, Any]]:
    """`rbx irun -t 0/0`, with the run itself stubbed out.

    A testcase is named because a bare `rbx irun` reads testcases from the
    terminal, which has nothing to do with which profile is active.
    """
    calls: Dict[str, Any] = {}

    async def run_and_print_interactive_solutions(*positional, **kwargs):
        calls['profile'] = limits_info.get_active_profile()

    with mock.patch(
        'rbx.box.cli.commands.run.run_and_print_interactive_solutions',
        run_and_print_interactive_solutions,
    ):
        result = runner.invoke(cli.app, ['irun', '-t', '0/0', *args])
    return result, calls


def test_no_flag_runs_against_the_package_limits(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    """The behaviour every existing `rbx run` has: the flag's absence must not
    change which limits the solutions are run against."""
    result, calls = _invoke_run(runner)

    assert result.exit_code == 0, result.output
    assert calls['profile'] is None


def test_a_profile_is_active_while_the_solutions_run(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    _write_profile('boca')

    result, calls = _invoke_run(runner, '-p', 'boca')

    assert result.exit_code == 0, result.output
    assert calls['profile'] == 'boca'


def test_the_short_and_long_spellings_agree(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    _write_profile('boca')

    short_result, short_calls = _invoke_run(runner, '-p', 'boca')
    long_result, long_calls = _invoke_run(runner, '--profile', 'boca')

    assert short_result.exit_code == long_result.exit_code == 0
    assert short_calls['profile'] == long_calls['profile'] == 'boca'

    # Nothing else the command decides is decided differently. Compared by
    # identity where the value is one (the progress bar, the runner object).
    def comparable(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return {
            k: type(v) if k in ('progress', 'runner') else v for k, v in kwargs.items()
        }

    assert comparable(short_calls['kwargs']) == comparable(long_calls['kwargs'])


def test_the_command_flag_means_the_same_as_the_root_flag(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    """`rbx run -p boca` and `rbx -p boca run` are two spellings of one thing."""
    _write_profile('boca')

    root_result, root_calls = _invoke_run_with_root_flag(runner, 'boca')
    command_result, command_calls = _invoke_run(runner, '-p', 'boca')

    assert root_result.exit_code == command_result.exit_code == 0
    assert root_calls['profile'] == command_calls['profile'] == 'boca'


def _invoke_run_with_root_flag(
    runner: CliRunner, profile: str
) -> Tuple[Any, Dict[str, Any]]:
    calls: Dict[str, Any] = {}

    async def run_solutions(*positional, **kwargs):
        calls['profile'] = limits_info.get_active_profile()
        result = mock.MagicMock()
        result.close = mock.AsyncMock()
        return result

    async def print_run_report(*positional, **kwargs):
        return True

    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.cli.commands.run.run_solutions', run_solutions),
        mock.patch('rbx.box.cli.commands.run.print_run_report', print_run_report),
    ):
        result = runner.invoke(cli.app, ['-p', profile, 'run'])
    return result, calls


def test_an_unknown_profile_is_refused_before_anything_is_built(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    """Falling back to the package limits would run the solutions against limits
    the setter did not ask for, and the run would look like it worked."""
    result, calls = _invoke_run(runner, '-p', 'bcoa')

    assert result.exit_code != 0
    assert 'bcoa' in result.output
    # Nothing ran.
    assert calls == {}


def test_irun_takes_the_long_spelling_only(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    """`-p` is `--print` in `irun`, and stealing it would silently change what an
    existing `rbx irun -p` does."""
    _write_profile('boca')

    result, calls = _invoke_irun(runner, '-v4', '--profile', 'boca')

    assert result.exit_code == 0, result.output
    assert calls['profile'] == 'boca'


def test_irun_p_still_prints(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result, calls = _invoke_irun(runner, '-v4', '-p')

    assert result.exit_code == 0, result.output
    assert calls['profile'] is None
    # The warning shown only when outputs are *not* printed to the terminal.
    assert 'Outputs will be written to files' not in result.output


def test_irun_refuses_an_unknown_profile(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result, calls = _invoke_irun(runner, '-v4', '--profile', 'bcoa')

    assert result.exit_code != 0
    assert 'bcoa' in result.output
    assert calls == {}
