import subprocess
import sys
from typing import List

import pytest
import typer.main
from typer.testing import CliRunner

from rbx.box.cli import ENTRIES, app
from rbx.box.completion.generate import help_panel


def _modules_after(code: str) -> List[str]:
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        encoding='utf-8',
    )
    assert result.returncode == 0, result.stderr
    modules = result.stdout.splitlines()
    assert modules, (
        f'expected the helper to print the imported modules: {result.stderr}'
    )
    return modules


def _fresh_group():
    """A click group off a fresh conversion, so nothing is resolved yet."""
    return typer.main.get_command(app)


def test_importing_the_cli_imports_no_command_implementation():
    """`rbx --help` and shell completion pay for the whole command surface
    otherwise -- the point of the lazy registration table."""
    modules = set(
        _modules_after('import sys; import rbx.box.cli; print("\\n".join(sys.modules))')
    )

    heavy = {
        'pydantic',
        'rich',
        'yaml',
        'rbx.box.package',
        'rbx.box.schema',
        'rbx.box.compile',
        'rbx.box.solutions',
        'rbx.box.environment',
        'rbx.config',
        'rbx.utils',
    }
    assert not (modules & heavy)
    assert not [m for m in modules if m.startswith('rbx.box.cli.commands')]


def test_rendering_the_root_help_imports_no_command_implementation():
    modules = set(
        _modules_after(
            'import sys\n'
            'from typer.testing import CliRunner\n'
            'from rbx.box.cli import app\n'
            'result = CliRunner().invoke(app, ["--help"])\n'
            'assert result.exit_code == 0, result.output\n'
            'assert "stress" in result.output, result.output\n'
            'print("\\n".join(sys.modules))\n'
        )
    )
    assert not [m for m in modules if m.startswith('rbx.box.cli.commands')]
    assert 'rbx.box.package' not in modules


def test_invoking_a_command_imports_only_its_own_module():
    modules = set(
        _modules_after(
            'import sys\n'
            'from typer.testing import CliRunner\n'
            'from rbx.box.cli import app\n'
            'CliRunner().invoke(app, ["stress", "--help"])\n'
            'print("\\n".join(sys.modules))\n'
        )
    )
    assert 'rbx.box.cli.commands.stress' in modules
    # Unrelated commands stay out: this is what keeps a new command from
    # raising the startup cost of every other one.
    assert 'rbx.box.cli.commands.time_cmd' not in modules
    assert 'rbx.box.cli.commands.manage' not in modules


@pytest.mark.parametrize('entry', ENTRIES, ids=lambda e: e.name)
def test_table_matches_what_the_target_declares(entry):
    """The table carries the help `--help` renders without importing anything.

    Nothing else pins the two together, so a `help=` edited in the command
    module would otherwise silently stop showing up.
    """
    group = _fresh_group()
    command = group.get_command(None, entry.name)

    assert command is not None, f'{entry.name} did not resolve'
    assert command.name == entry.name
    assert command.hidden == entry.hidden
    if not entry.hidden:
        assert (command.short_help or command.help or None) == entry.help
        assert help_panel(command) == entry.rich_help_panel


def test_aliases_resolve_to_the_registered_command():
    group = _fresh_group()

    assert group.get_command(None, 'b').name == 'build, b'
    assert group.get_command(None, 'pkg').name == 'package, pkg'
    # 't' is claimed by both 'time, t' and 'testcases, tc, t'; registration
    # order decides, exactly as it did when Typer built the group eagerly.
    assert group.get_command(None, 't').name == 'time, t'


def test_unknown_command_is_still_suggested_against():
    result = CliRunner().invoke(app, ['stres'])

    assert result.exit_code != 0
    assert 'Did you mean' in result.output
    assert 'stress' in result.output


def test_materialize_all_resolves_every_entry_in_order():
    group = _fresh_group()
    group.materialize_all()

    assert list(group.commands) == [entry.name for entry in ENTRIES]
