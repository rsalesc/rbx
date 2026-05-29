"""Batch/Interactive orchestration: wires together the runtime modules.

This is the Layer-2 glue. Each *task type* (batch, interactive) exposes the
three BOCA lifecycle hooks -- ``compile``, ``run``, ``compare`` -- by composing
the already-built, already-tested primitives in :mod:`rbx_boca.languages`,
:mod:`rbx_boca.sandbox` and :mod:`rbx_boca.verdicts`.

Everything a task needs is bundled in :class:`RunContext`, and every external
effect (subprocess execution, safeexec, static-link checking, fifo creation) is
injected so the orchestration can be unit-tested without real subprocesses.

stdlib-only, Python 3.8 compatible.
"""

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from rbx_boca import languages, sandbox, verdicts
from rbx_boca.manifest import LanguageManifest, TaskConfig

# BOCA compile/other-error exit code, mirrors run/cpp aborting when a submission
# is not statically linked (exit 47).
_OTHER_ERROR = 47

# BOCA run-phase judge-error exit code (JUDGE_ERROR=4 in interactor_run.sh).
# Used when pipe.exe fails or pipe.log is missing/malformed.
_JUDGE_ERROR = 4

# Local filenames inside the sandbox cwd.
_STDIN = 'stdin0'
_STDOUT = 'stdout0'
_FIFO_IN = 'fifo.in'
_FIFO_OUT = 'fifo.out'
_PIPE_LOG = 'pipe.log'

# First line of team output that carries an interactor (testlib) verdict.
_TESTLIB_RE = re.compile(r'^testlib exitcode\s+(-?\d+)\s*$')


def _default_static_link_ok(exe: Path) -> bool:
    """Run `file <exe>` and look for 'statically linked'. Mirrors the run-time
    static-link guard in BOCA's run/cpp template."""
    try:
        out = subprocess.run(
            ['file', str(exe)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout.decode('utf-8', 'replace')
    except OSError:
        return False
    return 'statically linked' in out


@dataclass
class RunContext:
    """Everything the task orchestration needs, with all effects injectable.

    Real runs build this from parsed manifests + resolved asset paths; unit
    tests construct it directly with fake ``runner`` / ``safeexec`` /
    ``static_link_ok`` / ``make_fifos`` callables so no subprocess ever runs.
    """

    task: TaskConfig
    lang: LanguageManifest
    cwd: Path
    # Runs an argv, returns the process exit code. Used for compiler steps,
    # the checker, syntax checks and (interactive) the pipe.exe orchestrator.
    runner: Callable[..., int]
    # Configured safeexec executor (its .path is already resolved).
    safeexec: sandbox.SafeExec
    uid: int = 65534
    gid: int = 65534
    chroot: Optional[str] = None
    cache_dir: Path = field(default_factory=lambda: Path('.'))
    # Already-resolved asset binaries (NativeAsset.ensure happens in Phase 9).
    checker_path: Optional[Path] = None
    interactor_path: Optional[Path] = None
    pipe_path: Optional[Path] = None
    # Re-entrant sentinel argv that launches the interactor under safeexec.
    # Phase 7/8 wire the real value; injected directly in unit tests.
    interactor_launch_argv: List[str] = field(default_factory=list)
    # Injectable static-link checker (default: `file <exe>` grep).
    static_link_ok: Callable[[Path], bool] = _default_static_link_ok
    # Injectable fifo creator (default: os.mkfifo the two interactive fifos).
    make_fifos: Optional[Callable[[], None]] = None

    @property
    def spec(self):
        return self.lang.language


def _read_testlib_code(path: Path) -> Optional[int]:
    """Return the integer from the first `testlib exitcode N` line, or None."""
    try:
        text = path.read_text()
    except OSError:
        return None
    for line in text.splitlines():
        m = _TESTLIB_RE.match(line.strip())
        if m:
            return int(m.group(1))
    return None


def _compare(ctx: 'RunContext', args: List[str]) -> int:
    """Shared compare logic for batch and interactive tasks.

    args = [team_output, expected_output, input_file].

    If the team output carries a `testlib exitcode N` marker (written by
    InteractiveTask.run), trust it directly and skip the checker. Otherwise
    invoke the checker as `checker input team_output expected_output` and map
    its exit. BatchTask never writes that marker, so it always runs the checker.
    """
    team_output, expected_output, input_file = args[0], args[1], args[2]

    testlib_code = _read_testlib_code(Path(team_output))
    if testlib_code is not None:
        return verdicts.compare_verdict(testlib_code=testlib_code, checker_exit=None)

    # No testlib marker: we are about to invoke the checker. If its path was
    # never wired, fail loudly instead of exec'ing a program named "None".
    if ctx.checker_path is None:
        print('checker_path not configured', file=sys.stderr)
        return _OTHER_ERROR

    checker_exit = ctx.runner(
        [str(ctx.checker_path), input_file, team_output, expected_output]
    )
    return verdicts.compare_verdict(testlib_code=None, checker_exit=checker_exit)


class BaseTask:
    """Shared lifecycle hooks for every task type.

    ``compile`` (build the submission) and ``compare`` (map a verdict) are
    identical for batch and interactive problems, so they live here. Only
    ``run`` differs, and each subclass provides its own implementation.
    """

    def compile(self, ctx: RunContext, *, src: str, exe: str, basename: str) -> int:
        spec = ctx.spec
        interp = ''
        if spec.kind == 'interpreted':
            interp = languages.resolve_compiler(spec)
        plan = languages.build_compile_plan(
            spec, src=src, exe=exe, basename=basename, interp=interp
        )

        # Interpreted: write the shebang'd script + optional syntax pre-check.
        # NOTE: Layer-2 placement choice -- compile steps run directly via
        # ctx.runner (not wrapped in safeexec). The sandbox wrapping of the
        # compiler is an integration concern (Phase 9); unit tests assert on
        # the bare compiler argv.
        if plan.write_script is not None:
            source_path, exe_path = plan.write_script
            contents = (ctx.cwd / source_path).read_text()
            target = ctx.cwd / exe_path
            target.write_text((plan.shebang or '') + '\n' + contents)
            os.chmod(str(target), 0o755)

        if plan.syntax_check_argv is not None:
            rc = ctx.runner(plan.syntax_check_argv)
            if rc != 0:
                return rc

        # jvm jar: write the Main-Class manifest BEFORE the `jar cfm` step that
        # references it. Mirrors BOCA run/java writing Manifest.txt with
        # `Main-Class: <klass>` prior to invoking jar.
        if plan.manifest_class is not None:
            (ctx.cwd / 'Manifest.txt').write_text(
                'Main-Class: {}\n'.format(plan.manifest_class)
            )

        # Compiled / jvm: optional source rename, then each compiler step.
        if plan.rename is not None:
            src_from, src_to = plan.rename
            os.replace(str(ctx.cwd / src_from), str(ctx.cwd / src_to))

        for step in plan.steps:
            rc = ctx.runner(step)
            if rc != 0:
                return rc

        # Static-link guard (compiled_static): mirrors run/cpp aborting with 47.
        if plan.static_link_check and not ctx.static_link_ok(ctx.cwd / exe):
            return _OTHER_ERROR

        return 0

    def compare(self, ctx: RunContext, args: List[str]) -> int:
        return _compare(ctx, args)


class BatchTask(BaseTask):
    """Standard batch task: compile a submission, run it once per test under
    safeexec, compare its stdout against the expected output via a checker."""

    def run(self, ctx: RunContext, args: List[str]) -> int:
        # BOCA run argv: basename inputfile timelimit repetitions memory out_kb
        basename, inputfile, timelimit, repetitions, memory, outputsize_kb = (
            args[0],
            args[1],
            int(args[2]),
            int(args[3]),
            int(args[4]),
            int(args[5]),
        )
        spec = ctx.spec

        # Point the sandbox stdin at the test input by copying it to stdin0.
        (ctx.cwd / _STDIN).write_text(Path(inputfile).read_text())

        run_extra = {}
        if spec.kind == 'interpreted':
            run_extra['interp'] = languages.resolve_compiler(spec)
        program = languages.build_run_argv(
            spec, exe=basename, memory_mb=memory, **run_extra
        )

        spec_se = sandbox.profile_for(
            spec.kind,
            'run',
            cpu_sec=timelimit,
            memory_mb=memory,
            nruns=repetitions,
            out_kb=outputsize_kb,
            uid=ctx.uid,
            gid=ctx.gid,
            chroot=ctx.chroot,
            overrides=spec.sandbox_overrides,
        )
        raw = ctx.safeexec.run(spec_se, program)
        return verdicts.batch_run_exit(raw)


class InteractiveTask(BaseTask):
    """Interactive task: solution and interactor talk over a pair of fifos,
    bridged by pipe.exe. The interactor's verdict (testlib code) is recorded
    into stdout0 so the (shared) compare step can read it without a checker."""

    # Notify-fd token pipe.exe substitutes with a real fd at runtime
    # (interactor_run.sh:45/47 `__FD__`). Emitted literally; never substituted.
    _FD_TOKEN = '__FD__'

    def build_pipe_argv(self, ctx: RunContext, args: List[str]) -> List[str]:
        """Construct the pipe.exe argv for an interactive run.

        Structurally mirrors rbx/resources/packagers/boca/interactor_run.sh:44-47:

            pipe.exe -i fifo.in -o fifo.out -e <sol stderr> -E interactor.stderr --
                <safeexec solution -ofifo.out -ififo.in -D__FD__ ...>
                = <launch> __interactor_launcher__ <ittime> __FD__ -- <interactor> stdin0 stdout0

        ``ittime = timelimit + 1`` (interactor_run.sh:13 adds 1s of wall slack).
        pipe.exe substitutes the literal ``__FD__`` tokens with real fds.
        """
        # BOCA run argv: basename inputfile timelimit repetitions memory out_kb
        basename, _inputfile, timelimit, repetitions, memory, outputsize_kb = (
            args[0],
            args[1],
            int(args[2]),
            int(args[3]),
            int(args[4]),
            int(args[5]),
        )
        spec = ctx.spec

        # Solution program, run under safeexec with fifo redirection + notify fd.
        run_extra = {}
        if spec.kind == 'interpreted':
            run_extra['interp'] = languages.resolve_compiler(spec)
        program = languages.build_run_argv(
            spec, exe=basename, memory_mb=memory, **run_extra
        )
        spec_se = sandbox.profile_for(
            spec.kind,
            'run',
            cpu_sec=timelimit,
            memory_mb=memory,
            nruns=repetitions,
            out_kb=outputsize_kb,
            uid=ctx.uid,
            gid=ctx.gid,
            chroot=ctx.chroot,
            stdin=_FIFO_IN,
            stdout=_FIFO_OUT,
            overrides=spec.sandbox_overrides,
        )
        solution_cmd = sandbox.build_safeexec_argv(
            spec_se,
            program,
            safeexec=ctx.safeexec.path,
            notify=self._FD_TOKEN,
        )

        # Interactor side: re-enter this bundle under the watchdog/RLIMIT_AS cap.
        # ittime = wall TL + 1 (interactor_run.sh:13).
        ittime = timelimit + 1
        interactor_cmd = list(ctx.interactor_launch_argv) + [
            '__interactor_launcher__',
            str(ittime),
            self._FD_TOKEN,
            '--',
            str(ctx.interactor_path),
            _STDIN,
            _STDOUT,
        ]

        pipe_argv = [
            str(ctx.pipe_path),
            '-i',
            _FIFO_IN,
            '-o',
            _FIFO_OUT,
            '-e',
            spec_se.stderr,
            '-E',
            'interactor.stderr',
            '--',
        ]
        pipe_argv += solution_cmd
        pipe_argv += ['=']
        pipe_argv += interactor_cmd
        return pipe_argv

    def run(self, ctx: RunContext, args: List[str]) -> int:
        # Fail loudly if the interactive assets were never wired, instead of
        # building a pipe argv that exec's a program named "None".
        if ctx.interactor_path is None or ctx.pipe_path is None:
            print('interactor_path/pipe_path not configured', file=sys.stderr)
            return _JUDGE_ERROR

        # Copy the test input into stdin0 so the interactor (which is invoked
        # with `stdin0 stdout0`) reads the actual test data. Mirrors the batch
        # path's stdin0 population; the interactor argv passes the literal
        # 'stdin0' filename (matching bash interactor_run.sh), so the file must
        # exist with the real input contents.
        inputfile = args[1]
        (ctx.cwd / _STDIN).write_text(Path(inputfile).read_text())

        # Make the bidirectional fifos (stubbable for unit tests).
        make_fifos = (
            ctx.make_fifos
            if ctx.make_fifos is not None
            else (lambda: self._default_make_fifos(ctx))
        )
        make_fifos()

        pipe_argv = self.build_pipe_argv(ctx, args)

        # If pipe.exe itself fails, treat it as a judge error (mirrors BOCA's
        # interactor_run.sh returning JUDGE_ERROR=4 on pipe.exe failure).
        pipe_rc = ctx.runner(pipe_argv)
        if pipe_rc != 0:
            return _JUDGE_ERROR

        # Parse pipe.log and apply the ordered interactive decision logic. A
        # missing, short, or garbage log (which would crash PipeLog.parse) is
        # also a judge error, matching interactor_run.sh's invalid-tag handling.
        try:
            log = verdicts.PipeLog.parse((ctx.cwd / _PIPE_LOG).read_text())
        except (ValueError, OSError):
            return _JUDGE_ERROR
        decision = verdicts.interactive_run_decision(
            log.first_tag, log.solution_status, log.interactor_status
        )

        # Record the interactor verdict for the compare step (no checker run).
        if decision.testlib_code is not None:
            (ctx.cwd / _STDOUT).write_text(
                'testlib exitcode {}\n'.format(decision.testlib_code)
            )

        return decision.run_exit

    def _default_make_fifos(self, ctx: RunContext) -> None:
        for name in (_FIFO_IN, _FIFO_OUT):
            path = ctx.cwd / name
            if path.exists():
                path.unlink()
            os.mkfifo(str(path))
