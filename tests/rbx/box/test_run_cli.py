"""What `rbx run --fail-fast` hands to the runner and to the report.

The flag is three decisions taken in the command itself -- which predicate stops
a solution, whether the timing summary may still be drawn, and who gets told the
run was truncated -- so they are pinned here, where the wiring is, rather than
through a full run.
"""

import asyncio
from typing import Any, Dict, List, Tuple
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli
from rbx.box.solutions import fail_fast_abort_predicate
from rbx.box.testing import testing_package

FAIL_FAST_WARNING = 'should not be trusted for full validation of the problem'


def _flat(text: str) -> str:
    """Collapse the console's own wrapping, which lands mid-sentence."""
    return ' '.join(text.split())


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


async def _build_ok(*args, **kwargs):
    return True


class _Invocation:
    """The calls `run` made, once its heavy collaborators are stubbed out."""

    def __init__(self):
        self.run_solutions_kwargs: Dict[str, Any] = {}
        self.reports: List[Tuple[Any, Dict[str, Any]]] = []
        self.shared: List[Any] = []

    @property
    def shared_text(self) -> str:
        assert len(self.shared) == 1
        # The console wraps at its own width, so a warning long enough to be
        # worth printing is long enough to be broken across lines.
        return _flat(self.shared[0].export_text(clear=False))


def _invoke_run(runner: CliRunner, *args: str) -> Tuple[Any, _Invocation]:
    calls = _Invocation()

    async def run_solutions(**kwargs):
        calls.run_solutions_kwargs = kwargs
        return mock.MagicMock()

    async def print_run_report(result, console, verification, **kwargs):
        calls.reports.append((console, kwargs))
        return True

    def capture_and_share(console, **kwargs):
        calls.shared.append(console)

    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.cli.run_solutions', run_solutions),
        mock.patch('rbx.box.cli.print_run_report', print_run_report),
        mock.patch('rbx.box.sharing.capture_and_share', capture_and_share),
    ):
        result = runner.invoke(cli.app, ['run', *args])
    return result, calls


def test_fail_fast_hands_the_runner_its_predicate(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result, calls = _invoke_run(runner, '--ff')

    assert result.exit_code == 0, result.output
    assert calls.run_solutions_kwargs['abort_on'] is fail_fast_abort_predicate


def test_a_plain_run_stops_for_nothing(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result, calls = _invoke_run(runner)

    assert result.exit_code == 0, result.output
    assert calls.run_solutions_kwargs['abort_on'] is None


@pytest.mark.parametrize('flag', ['--fail-fast', '--ff'])
def test_both_spellings_of_the_flag_warn_and_drop_the_timing_summary(
    flag: str,
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result, calls = _invoke_run(runner, flag)

    assert result.exit_code == 0, result.output
    assert FAIL_FAST_WARNING in _flat(result.output)
    # Every line of that summary is an extreme over the solutions, and a
    # solution that stopped early is only timed on the testcases that ran.
    assert [kwargs['timing'] for _, kwargs in calls.reports] == [False]


def test_a_plain_run_keeps_the_timing_summary_and_says_nothing(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result, calls = _invoke_run(runner)

    assert result.exit_code == 0, result.output
    assert FAIL_FAST_WARNING not in _flat(result.output)
    assert [kwargs['timing'] for _, kwargs in calls.reports] == [True]


def test_the_shared_report_carries_the_warning(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    # The shared copy is the one that leaves this machine, and whoever reads it
    # never sees the terminal warning.
    result, calls = _invoke_run(runner, '--ff', '--share', 'text')

    assert result.exit_code == 0, result.output
    assert FAIL_FAST_WARNING in calls.shared_text
    # ...and it is shared with the summary dropped, same as the printed one.
    assert [kwargs['timing'] for _, kwargs in calls.reports] == [False, False]


def test_the_shared_report_of_a_plain_run_is_unchanged(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result, calls = _invoke_run(runner, '--share', 'text')

    assert result.exit_code == 0, result.output
    assert FAIL_FAST_WARNING not in calls.shared_text
