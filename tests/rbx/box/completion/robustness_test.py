"""Robustness tests: the fast completion path must NEVER crash the shell.

Every failure mode degrades to the shell-default ``file`` directive (so the
shell falls back to its own filename completion) and ``handle_completion()``
returns truthfully without raising.
"""

import subprocess
import sys

from rbx.box.completion import _spec, engine, entry

# ---------------------------------------------------------------------------
# entry.handle_completion() — env-driven dispatch never raises.
# ---------------------------------------------------------------------------


def test_unset_complete_var_returns_false_and_writes_nothing(monkeypatch, capsys):
    monkeypatch.delenv(entry.COMPLETE_VAR, raising=False)
    assert entry.handle_completion() is False
    assert capsys.readouterr().out == ''


def test_unknown_shell_returns_true_without_raising(monkeypatch, capsys):
    # powershell is not a Click-native shell. The only guarantee is that the
    # entry path returns True and does not raise -- the exact output is left
    # loose on purpose (if another test imported the heavy app and ran
    # `completion_init()`, Typer's PowerShell class gets registered globally and
    # the engine may emit real completions; otherwise it emits the file directive).
    monkeypatch.setenv(entry.COMPLETE_VAR, 'complete_powershell')
    monkeypatch.setenv('_TYPER_COMPLETE_ARGS', 'rbx ')
    monkeypatch.setenv('COMP_WORDS', 'rbx ')
    monkeypatch.setenv('COMP_CWORD', '1')
    assert entry.handle_completion() is True
    capsys.readouterr()  # drain; do not over-constrain the output


def test_bogus_shell_emits_file_directive(monkeypatch, capsys):
    # A name no shell class is ever registered for: `complete_to_string` always
    # takes its `base is None` branch and emits the shell-default file directive.
    monkeypatch.setenv(entry.COMPLETE_VAR, 'complete_bogus')
    monkeypatch.setenv('_TYPER_COMPLETE_ARGS', 'rbx ')
    monkeypatch.setenv('COMP_WORDS', 'rbx ')
    monkeypatch.setenv('COMP_CWORD', '1')
    assert entry.handle_completion() is True
    assert capsys.readouterr().out == 'file,\n'


def test_malformed_complete_args_does_not_raise(monkeypatch, capsys):
    # COMP_WORDS unset and COMP_CWORD points past the (empty) word list.
    monkeypatch.setenv(entry.COMPLETE_VAR, 'complete_bash')
    monkeypatch.delenv('_TYPER_COMPLETE_ARGS', raising=False)
    monkeypatch.delenv('COMP_WORDS', raising=False)
    monkeypatch.setenv('COMP_CWORD', '99')
    # Must not raise; the engine still produces *some* output (never an exception).
    assert entry.handle_completion() is True
    capsys.readouterr()  # drain whatever was written


def test_source_bash_writes_non_empty_script(monkeypatch, capsys):
    monkeypatch.setenv(entry.COMPLETE_VAR, 'source_bash')
    assert entry.handle_completion() is True
    out = capsys.readouterr().out
    assert out.strip(), 'expected a non-empty bash source script'
    assert 'complete ' in out or '_rbx_completion' in out


def test_forced_engine_failure_emits_file_directive(monkeypatch, capsys):
    # Monkeypatch the engine symbol imported by entry so resolution blows up;
    # the entry wrapper must swallow it and emit the shell-default fallback.
    def _boom(shell, spec):
        raise RuntimeError('forced failure')

    monkeypatch.setenv(entry.COMPLETE_VAR, 'complete_bash')
    monkeypatch.setattr(engine, 'complete_to_string', _boom)
    assert entry.handle_completion() is True
    assert capsys.readouterr().out == 'file,\n'


# ---------------------------------------------------------------------------
# engine.resolve() — pure resolver degrades to the file directive, never raises.
# ---------------------------------------------------------------------------


def test_resolve_malformed_spec_node_returns_file_directive():
    items = engine.resolve({}, ['x'], '')
    assert len(items) == 1
    assert items[0].value == ''
    assert items[0].type == 'file'


def test_resolve_nonexistent_deep_path_does_not_raise():
    items = engine.resolve(_spec.SPEC, ['nonexistent', 'deep', 'path'], '--xyz')
    assert isinstance(items, list)


# ---------------------------------------------------------------------------
# Subprocess: an exception inside completion still exits 0 with `file,` on
# stdout (mirrors the firewall-style child-process probe).
# ---------------------------------------------------------------------------

_PROBE = (
    'import os, sys\n'
    "os.environ['_RBX_COMPLETE'] = 'complete_bash'\n"
    "os.environ['_TYPER_COMPLETE_ARGS'] = 'rbx '\n"
    "os.environ['COMP_WORDS'] = 'rbx '\n"
    "os.environ['COMP_CWORD'] = '1'\n"
    # Force the resolution to fail to prove the shell still gets a safe answer.
    'from rbx.box.completion import engine\n'
    'def _boom(shell, spec):\n'
    "    raise RuntimeError('forced failure')\n"
    'engine.complete_to_string = _boom\n'
    'from rbx.box import main\n'
    'try:\n'
    '    main.app()\n'
    'except SystemExit as e:\n'
    '    sys.exit(e.code or 0)\n'
)


def test_subprocess_exception_exits_zero_with_file_directive():
    out = subprocess.run([sys.executable, '-c', _PROBE], capture_output=True, text=True)
    assert out.returncode == 0, f'expected exit 0, got {out.returncode}: {out.stderr}'
    assert out.stdout == 'file,\n'
