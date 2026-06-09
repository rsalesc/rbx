import os
import re
import shutil
import subprocess
import sys

import pytest

from rbx.box.completion import _spec
from rbx.box.completion.engine import complete_to_string

# A valid bash completion line is `<type>,<value>` where type is one of the
# Click directive types. The real CLI (driven by Rich) appends a trailing
# show-cursor escape sequence (\x1b[?25h) on exit, which is NOT part of the
# completion protocol -- we filter to only protocol-shaped lines.
_BASH_LINE = re.compile(r'^(plain|file|dir),')


def _bash_lines(text: str) -> set:
    return {line for line in text.splitlines() if _BASH_LINE.match(line)}


def _rbx_argv():
    """Return an argv that invokes the real rbx CLI.

    Prefer the `rbx` console script on PATH (fast); fall back to running the
    app module via the current interpreter if it is not found.
    """
    exe = shutil.which('rbx')
    if exe:
        return [exe]
    return [sys.executable, '-c', 'from rbx.box.main import app; app()']


def _real_bash(comp_words: str, cword: int) -> set:
    env = dict(
        os.environ,
        _RBX_COMPLETE='complete_bash',
        _TYPER_COMPLETE_ARGS=comp_words,
        COMP_WORDS=comp_words,
        COMP_CWORD=str(cword),
    )
    out = subprocess.run(_rbx_argv(), env=env, capture_output=True, text=True)
    lines = _bash_lines(out.stdout)
    # Guard against vacuous parity (empty == empty): the real CLI must have
    # actually produced completions for the positions we test.
    assert lines, (
        f'real CLI produced no bash completions for {comp_words!r}@{cword}; '
        f'stdout={out.stdout!r} stderr={out.stderr!r}'
    )
    return lines


# ---------------------------------------------------------------------------
# 1) Shape + known entries for the root.
# ---------------------------------------------------------------------------


def test_root_bash_output_shape_and_known_entries(monkeypatch):
    monkeypatch.setenv('COMP_WORDS', 'rbx ')
    monkeypatch.setenv('COMP_CWORD', '1')
    text = complete_to_string('bash', _spec.SPEC)
    lines = [line for line in text.splitlines() if line]
    assert lines, 'expected non-empty bash completion output'
    # Every emitted line must follow the bash `<type>,<value>` directive format.
    for line in lines:
        assert _BASH_LINE.match(line), f'unexpected bash line format: {line!r}'
    assert 'plain,ui' in lines
    # Aliased commands are emitted as separate candidates, never comma-joined.
    assert 'plain,package' in lines
    assert 'plain,pkg' in lines
    assert 'plain,package, pkg' not in lines


def test_unknown_shell_emits_file_directive():
    assert complete_to_string('not-a-shell', _spec.SPEC) == 'file,\n'


# ---------------------------------------------------------------------------
# 2) Real-output parity: the fast bash output must equal the real CLI's,
#    line-set for line-set, for the same cursor position.
# ---------------------------------------------------------------------------


def test_root_command_names_are_split_not_comma_joined(monkeypatch):
    # The root has aliased commands ('build, b', ...). We intentionally diverge
    # from the real CLI here: each alias is its own candidate. Assert the real
    # CLI's comma-joined names, once split, are all present in our output.
    monkeypatch.setenv('_RBX_COMPLETE', 'complete_bash')
    monkeypatch.setenv('_TYPER_COMPLETE_ARGS', 'rbx ')
    monkeypatch.setenv('COMP_WORDS', 'rbx ')
    monkeypatch.setenv('COMP_CWORD', '1')
    fast = _bash_lines(complete_to_string('bash', _spec.SPEC))
    assert 'plain,build, b' not in fast  # never the raw joined form
    expected_split = set()
    for line in _real_bash('rbx ', 1):
        value = line.split(',', 1)[1]
        for name in value.split(','):
            expected_split.add('plain,' + name.strip())
    assert expected_split <= fast


def test_bash_parity_package_subcommand(monkeypatch):
    monkeypatch.setenv('_RBX_COMPLETE', 'complete_bash')
    monkeypatch.setenv('_TYPER_COMPLETE_ARGS', 'rbx package ')
    monkeypatch.setenv('COMP_WORDS', 'rbx package ')
    monkeypatch.setenv('COMP_CWORD', '2')
    fast = _bash_lines(complete_to_string('bash', _spec.SPEC))
    real = _real_bash('rbx package ', 2)
    assert fast == real
    # Sanity: this position really does complete the package subcommands.
    assert 'plain,polygon' in fast


@pytest.mark.parametrize(
    'comp_words,cword',
    [
        # Positions where the engine does NOT intentionally diverge from Typer:
        # alias-free subcommands, option names, and option values.
        ('rbx package ', 2),  # package's children have no aliases
        ('rbx package pol', 2),
        ('rbx pkg ', 2),  # descend via the 'pkg' alias, then alias-free children
        ('rbx package polygon --la', 3),  # option-name completion
        ('rbx tool convert --language ', 4),  # value completion (dynamic completer)
    ],
)
def test_bash_parity_various_positions(monkeypatch, comp_words, cword):
    monkeypatch.setenv('_RBX_COMPLETE', 'complete_bash')
    monkeypatch.setenv('_TYPER_COMPLETE_ARGS', comp_words)
    monkeypatch.setenv('COMP_WORDS', comp_words)
    monkeypatch.setenv('COMP_CWORD', str(cword))
    fast = _bash_lines(complete_to_string('bash', _spec.SPEC))
    real = _real_bash(comp_words, cword)
    assert fast == real
