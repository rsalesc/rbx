import subprocess
import sys

import pytest

DENYLIST = [
    'textual',
    'mechanize',
    'bs4',
    'lxml',
    'git',
    'agents',
    'prompt_toolkit',
    'questionary',
    'rbx.box.cli',
    'rbx.box.solutions',
    'rbx.box.packaging',
]

# Child process: set completion env, trigger TODAY's completion path, print
# imported modules. The module list is emitted on stderr after a marker so it
# never mixes with the completion output written to stdout.
_PROBE = (
    'import os, sys\n'
    "os.environ['_RBX_COMPLETE'] = 'complete_bash'\n"
    "os.environ['_TYPER_COMPLETE_ARGS'] = 'rbx '\n"
    "os.environ['COMP_WORDS'] = 'rbx '\n"
    "os.environ['COMP_CWORD'] = '1'\n"
    'from rbx.box import main\n'
    'try:\n'
    '    main.app()\n'
    'except SystemExit:\n'
    '    pass\n'
    "sys.stderr.write('MODULES_START\\n')\n"
    'sys.stderr.write(chr(10).join(sorted(sys.modules)))\n'
)


def _modules_after_completion() -> set:
    out = subprocess.run([sys.executable, '-c', _PROBE], capture_output=True, text=True)
    # The module list is emitted on stderr to avoid mixing with completion stdout.
    _, _, mods = out.stderr.partition('MODULES_START\n')
    return set(mods.splitlines())


@pytest.mark.xfail(
    strict=True,
    reason='completion still imports the full CLI until the fast path lands',
)
def test_completion_path_imports_nothing_heavy():
    mods = _modules_after_completion()
    leaked = [m for m in DENYLIST if any(x == m or x.startswith(m + '.') for x in mods)]
    assert not leaked, f'completion path imported heavy modules: {leaked}'
