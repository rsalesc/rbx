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
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from rbx_boca import languages, sandbox, verdicts
from rbx_boca.manifest import LanguageManifest, TaskConfig

# BOCA compile/other-error exit code, mirrors run/cpp aborting when a submission
# is not statically linked (exit 47).
_OTHER_ERROR = 47

# Local filenames inside the sandbox cwd.
_STDIN = 'stdin0'


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


class BatchTask:
    """Standard batch task: compile a submission, run it once per test under
    safeexec, compare its stdout against the expected output via a checker."""

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
