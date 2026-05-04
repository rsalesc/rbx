"""Unit tests for the e2e runner's failure-message format."""

import pathlib

import pytest

from tests.e2e.runner import run_step
from tests.e2e.spec import Step


def test_run_step_failure_message_includes_all_diagnostics(tmp_path: pathlib.Path):
    # ``--no-such-flag`` is rejected by Typer with a non-zero exit code and
    # emits diagnostic text on stderr/stdout. Asserting expect_exit=0 forces
    # the mismatch path.
    step = Step(cmd='--no-such-flag', expect_exit=0)
    scenario_path = tmp_path / 'fixture-name' / 'e2e.rbx.yml'
    scenario_path.parent.mkdir()
    scenario_path.write_text('scenarios: []\n')

    with pytest.raises(AssertionError) as excinfo:
        run_step(scenario_path, 'my-scenario', step, cwd=tmp_path)

    msg = str(excinfo.value)
    # Package (fixture) name and scenario name appear in the bracketed prefix.
    assert 'fixture-name' in msg
    assert 'my-scenario' in msg
    # The step command is repr'd in the message.
    assert '--no-such-flag' in msg
    # Expected vs actual exit codes are surfaced.
    assert 'expected 0' in msg
    assert 'exited' in msg
    # stdout/stderr labels are present so a developer can read the output.
    assert 'stdout:' in msg
    assert 'stderr:' in msg


def test_run_step_succeeds_when_exit_code_matches(tmp_path: pathlib.Path):
    # Typer's ``--help`` exits 0; with expect_exit=0 the call should not raise.
    step = Step(cmd='--help', expect_exit=0)
    scenario_path = tmp_path / 'fx' / 'e2e.rbx.yml'
    scenario_path.parent.mkdir()
    scenario_path.write_text('scenarios: []\n')

    run_step(scenario_path, 'help-works', step, cwd=tmp_path)


def test_run_step_wraps_files_exist_failure_with_context(tmp_path: pathlib.Path):
    # ``--help`` exits 0 so the exit-code check passes; the missing-file
    # assertion should then fail with the wrapped runner context.
    from tests.e2e.spec import Expect

    step = Step(
        cmd='--help',
        expect_exit=0,
        expect=Expect(files_exist=['build/this-does-not-exist']),
    )
    scenario_path = tmp_path / 'fixture-name' / 'e2e.rbx.yml'
    scenario_path.parent.mkdir()
    scenario_path.write_text('scenarios: []\n')

    with pytest.raises(AssertionError) as excinfo:
        run_step(scenario_path, 'my-scenario', step, cwd=tmp_path)

    msg = str(excinfo.value)
    assert 'fixture-name' in msg
    assert 'my-scenario' in msg
    assert '--help' in msg
    # The inner assertion message names the missing pattern.
    assert 'build/this-does-not-exist' in msg
    assert 'no file matched' in msg


def test_run_step_skips_empty_assertions(tmp_path: pathlib.Path):
    # Default ``Expect`` has all empty/None fields; should not raise.
    step = Step(cmd='--help', expect_exit=0)
    scenario_path = tmp_path / 'fx' / 'e2e.rbx.yml'
    scenario_path.parent.mkdir()
    scenario_path.write_text('scenarios: []\n')

    run_step(scenario_path, 'noop', step, cwd=tmp_path)
