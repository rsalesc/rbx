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

# Each scenario lands the cursor on a different completer position so the probe
# exercises the real fast-path for every wired completer (issue #575). The pair
# is (full command line in COMP_WORDS, COMP_CWORD index of the word completed).
SCENARIOS = [
    ('rbx ', '1'),  # subcommand names (no dynamic completer)
    ('rbx run ', '2'),  # solutions completer (file-union)
    ('rbx run --outcome ', '3'),  # outcome completer
    ('rbx irun --testcase ', '3'),  # testgroup completer
    ('rbx build --verification-level ', '3'),  # verification_level completer
    ('rbx time --profile ', '3'),  # profile completer
    ('rbx stress --finder ', '3'),  # solutions completer (file-union)
    ('rbx -C ', '2'),  # contest_variant completer
    ('rbx on ', '2'),  # problem completer
]


def _modules_after_completion(comp_args: str, cword: str) -> set:
    # Child process: set completion env, trigger the completion path, print the
    # imported modules. The module list is emitted on stderr after a marker so it
    # never mixes with the completion output written to stdout.
    probe = (
        'import os, sys\n'
        "os.environ['_RBX_COMPLETE'] = 'complete_bash'\n"
        f'os.environ[{"_TYPER_COMPLETE_ARGS"!r}] = {comp_args!r}\n'
        f'os.environ[{"COMP_WORDS"!r}] = {comp_args!r}\n'
        f'os.environ[{"COMP_CWORD"!r}] = {cword!r}\n'
        'from rbx.box import main\n'
        'try:\n'
        '    main.app()\n'
        'except SystemExit:\n'
        '    pass\n'
        "sys.stderr.write('MODULES_START\\n')\n"
        'sys.stderr.write(chr(10).join(sorted(sys.modules)))\n'
    )
    out = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True)
    # The module list is emitted on stderr to avoid mixing with completion stdout.
    _, _, mods = out.stderr.partition('MODULES_START\n')
    return set(mods.splitlines())


@pytest.mark.parametrize('comp_args,cword', SCENARIOS)
def test_completion_path_imports_nothing_heavy(comp_args, cword):
    mods = _modules_after_completion(comp_args, cword)
    leaked = [m for m in DENYLIST if any(x == m or x.startswith(m + '.') for x in mods)]
    assert not leaked, f'{comp_args!r} imported heavy modules: {leaked}'
