"""Compiles and runs a submission whose *filename* is hostile to the shell.

The judge materializes the source under the name the contestant sent, so `l(1).py` --
the mark a browser sticks on a repeated download -- reaches these templates verbatim and
flows into BIN. Upstream mojtools took a Compilation Error from exactly that name
(cd-moj/mojtools@2be585e); the fixture below walks the same path rbx's templates take,
including the `printf 'BIN=%q'` build-and-test.sh uses to write `binfile.sh`.
"""

import pathlib
import shlex
import subprocess

import pytest

from rbx.config import get_default_app_path

HOSTILE = 'OlaMundo(1).py'
SOURCE = 'print(input().strip().upper())\n'


def _template(language: str, script: str) -> str:
    return (
        get_default_app_path() / 'packagers' / 'moj' / 'scripts' / language / script
    ).read_text()


@pytest.fixture
def jail(tmp_path: pathlib.Path):
    """A stand-in for MOJ's jail, wired the way build-and-test.sh wires the real one:
    compile in a writable dir, carry BIN across in `binfile.sh`, then run."""
    rwdir = tmp_path / 'rwdir'
    rwdir.mkdir()

    def compile_and_run(filename: str, source: str, stdin: str):
        (rwdir / filename).write_text(source)

        compile_out = tmp_path / 'compile.out'
        compile_sh = tmp_path / 'compile.sh'
        compile_sh.write_text(
            _template('py', 'compile.sh')
            .replace('{{rbxFlags}}', '')
            .replace('/tmp/rwdir', str(rwdir))
            .replace('/tmp/stderrlog', str(tmp_path / 'compile.err'))
            .replace('/tmp/out', str(compile_out))
        )
        compiled = subprocess.run(['bash', str(compile_sh)], capture_output=True)
        if compiled.returncode != 0:
            return compiled, compile_out.read_text(), None

        # build-and-test.sh: the BIN line becomes a `source`d assignment, escaped.
        bin_name = compile_out.read_text().partition('BIN=')[2].strip('\n')
        (rwdir / 'binfile.sh').write_text(
            f'BIN={shlex.quote(bin_name)}\nMOJ_MEMLIMITMB=256\nMOJ_STACKKB=131072\n'
        )

        run_out = tmp_path / 'run.out'
        (tmp_path / 'in').write_text(stdin)
        run_sh = tmp_path / 'run.sh'
        run_sh.write_text(
            _template('py', 'run.sh')
            .replace('/tmp/dir', str(rwdir))
            .replace('/tmp/stderrlog', str(tmp_path / 'run.err'))
            .replace('/tmp/in', str(tmp_path / 'in'))
            .replace('/tmp/out', str(run_out))
        )
        ran = subprocess.run(['bash', str(run_sh)], capture_output=True)
        assert ran.returncode == 0, (tmp_path / 'run.err').read_text()
        return compiled, compile_out.read_text(), run_out.read_text()

    return compile_and_run


def test_python_submission_with_a_browser_mangled_name_compiles_and_runs(jail):
    _, compile_out, run_out = jail(HOSTILE, SOURCE, 'ola\n')

    # BIN carries the parentheses through untouched -- and, quoted, they stay data.
    assert compile_out == f'BIN={HOSTILE}\n'
    assert run_out == 'OLA\n'


def test_python_submission_with_a_spaced_name_compiles_and_runs(jail):
    _, compile_out, run_out = jail('minha sol.py', SOURCE, 'ola\n')

    assert compile_out == 'BIN=minha sol.py\n'
    assert run_out == 'OLA\n'


def test_a_syntax_error_is_still_a_compilation_error(jail):
    compiled, compile_out, run_out = jail(HOSTILE, 'def (\n', '')

    # The hostile name must not turn a broken submission into a passing one.
    assert compiled.returncode != 0
    assert 'BIN=' not in compile_out
    assert run_out is None
