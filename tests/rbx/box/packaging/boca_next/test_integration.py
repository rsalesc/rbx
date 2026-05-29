"""Phase 9 integration harness for the rbx_boca Layer-2 runtime.

These tests validate the runtime end-to-end. They are deliberately HERMETIC:
no gcc, no root, no real SUID safeexec, no real pipe.exe (this machine cannot
build/run SUID safeexec or compile C).

Manifest reading from the .pyz uses ``pkgutil.get_data`` (zip-safe, not
deprecated); verified by ``test_pyz_limits_end_to_end`` reading task.json /
language.json from inside a real archive with NO env override.
"""

import os
import subprocess
import sys
from pathlib import Path

from rbx_boca import entrypoints, manifest, sandbox, tasks

from tests.rbx.box.packaging.boca_next import _bundle

# --- stubs --------------------------------------------------------------------

# A stub `safeexec`: skip its own -flags, find the program after `--`, honor
# -i<file>/-o<file> redirection, exec the program, propagate its exit code.
_STUB_SAFEEXEC = """#!{python}
import os
import sys

argv = sys.argv[1:]
stdin_path = None
stdout_path = None
prog = None
i = 0
while i < len(argv):
    a = argv[i]
    if a == '--':
        prog = argv[i + 1:]
        break
    if a.startswith('-i'):
        stdin_path = a[2:]
    elif a.startswith('-o'):
        stdout_path = a[2:]
    # all other -flags are limits we ignore in the stub
    i += 1

if not prog:
    sys.exit(2)

if stdin_path:
    fd = os.open(stdin_path, os.O_RDONLY)
    os.dup2(fd, 0)
if stdout_path:
    fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(fd, 1)

os.execv(prog[0], prog)
"""

# A stub checker: `checker <input> <team_out> <expected_out>`; exit 0 if the
# team output equals the expected output, else 1 (mirrors a trivial diff checker).
_STUB_CHECKER = """#!{python}
import sys

_input, team, expected = sys.argv[1], sys.argv[2], sys.argv[3]
with open(team) as f:
    t = f.read().split()
with open(expected) as f:
    e = f.read().split()
sys.exit(0 if t == e else 1)
"""

# A trivial solution: read an int from stdin, print it doubled.
_SOLUTION = """import sys
n = int(sys.stdin.read().split()[0])
print(n * 2)
"""


def _write_exec(path: Path, text: str) -> Path:
    path.write_text(text.format(python=sys.executable))
    os.chmod(str(path), 0o755)
    return path


def _interpreted_language_json():
    return {
        'language': {
            'id': 'py3',
            'kind': 'interpreted',
            'compiler_argv': ['python3'],
            'run_argv': ['{interp}', '{exe}'],
            'syntax_check': False,
        },
        'limits': {'time_sec': 3, 'runs': 1, 'memory_mb': 256},
    }


# --- Task 9.1: zipapp bundle + limits e2e -------------------------------------


def test_pyz_limits_end_to_end(tmp_path):
    """A real .pyz reads its bundled manifests (no env override) and prints the
    limits. Proves zipimport + manifest reading works from a real archive."""
    pyz = _bundle.build_pyz(
        tmp_path,
        task_json={'task_type': 'batch', 'output_kb': 65536},
        language_json={
            'language': {
                'id': 'cpp',
                'kind': 'compiled_static',
                'compiler_argv': ['g++', '-o', '{exe}', '{src}'],
                'run_argv': ['{exe}'],
            },
            'limits': {'time_sec': 3, 'runs': 2, 'memory_mb': 256},
        },
    )
    result = subprocess.run(
        [str(pyz), 'limits'],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['3', '2', '256', '65536']


# --- Task 9.2: batch e2e via stub safeexec + interpreted solution -------------


def test_pyz_batch_compile_and_run_end_to_end(tmp_path):
    """compile -> run through the real .pyz under a stub safeexec, executing a
    real python solution. Proves the .pyz actually runs a solution sandboxed."""
    work = tmp_path / 'work'
    work.mkdir()
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    _write_exec(bindir / 'safeexec', _STUB_SAFEEXEC)

    pyz = _bundle.build_pyz(
        tmp_path,
        {'task_type': 'batch', 'output_kb': 65536},
        _interpreted_language_json(),
    )

    (work / 'sol.py').write_text(_SOLUTION)
    (work / 'in.txt').write_text('21\n')

    env = dict(os.environ)
    env['PATH'] = str(bindir) + os.pathsep + env.get('PATH', '')

    # compile sol.py -> run (writes shebang script).
    rc = subprocess.run(
        [str(pyz), 'compile', 'sol.py', 'run', '3', '256'],
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, rc.stderr
    assert (work / 'run').exists()

    # run run in.txt 3 1 256 65536 (solution exits 0 -> batch run exit 0).
    rc = subprocess.run(
        [str(pyz), 'run', 'run', 'in.txt', '3', '1', '256', '65536'],
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, rc.stderr
    # The solution wrote its doubled answer to stdout0 via stub safeexec -o.
    assert (work / 'stdout0').read_text().split() == ['42']


def test_compare_end_to_end_via_entrypoint(tmp_path):
    """compare e2e at the entrypoints.main level with an injected context using a
    real stub checker script. (Driven here rather than through the subprocess
    because load_context leaves checker_path best-effort for Layer 2.)"""
    checker = _write_exec(tmp_path / 'checker', _STUB_CHECKER)

    (tmp_path / 'in.txt').write_text('21\n')
    (tmp_path / 'team.out').write_text('42\n')
    (tmp_path / 'exp.out').write_text('42\n')
    (tmp_path / 'wrong.out').write_text('99\n')

    def _factory():
        lang = manifest.LanguageManifest(
            language=manifest.LanguageSpec.from_dict(
                _interpreted_language_json()['language']
            ),
            limits=manifest.LimitsConfig(time_sec=3, runs=1, memory_mb=256),
        )
        return tasks.RunContext(
            task=manifest.TaskConfig(task_type='batch', output_kb=65536),
            lang=lang,
            cwd=tmp_path,
            runner=lambda argv, **kw: subprocess.call(argv, **kw),
            safeexec=sandbox.SafeExec(path='/usr/bin/safeexec'),
            checker_path=checker,
        )

    ac = entrypoints.main(
        [
            'compare',
            str(tmp_path / 'team.out'),
            str(tmp_path / 'exp.out'),
            str(tmp_path / 'in.txt'),
        ],
        context_factory=_factory,
    )
    assert ac == 4  # AC: team == expected

    wa = entrypoints.main(
        [
            'compare',
            str(tmp_path / 'team.out'),
            str(tmp_path / 'wrong.out'),
            str(tmp_path / 'in.txt'),
        ],
        context_factory=_factory,
    )
    assert wa == 6  # WA: team != expected
