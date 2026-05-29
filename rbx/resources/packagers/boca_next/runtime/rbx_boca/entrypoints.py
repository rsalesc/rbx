"""BOCA entry-point dispatcher for the Layer-2 runtime.

BOCA invokes lifecycle scripts by filename (``compile``, ``run``, ``compare``,
``limits``, ``tests``). In Layer 2 those filenames are thin wrappers that exec
``python -m rbx_boca <entry> ...`` with the entry name passed as ``argv[0]``.
This module maps that entry name to the right :mod:`rbx_boca.tasks` hook.

A re-entrant ``__interactor_launcher__`` entry is also handled here: pipe.exe
spawns the interactor through this same binary so the launcher can install the
RLIMIT_AS cap and process-group watchdog before exec'ing the real interactor.

The whole module is stdlib-only and Python 3.8 compatible. Every external
effect lives behind ``load_context`` so the dispatcher itself is unit-testable
with an injected ``context_factory``.
"""

import importlib.resources
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

from rbx_boca import interactor_launcher, sandbox
from rbx_boca.manifest import LanguageManifest, TaskConfig
from rbx_boca.tasks import BatchTask, InteractiveTask, RunContext

# Re-entrant sentinel entry name: pipe.exe execs this binary with the sentinel
# as argv[0] so the interactor is launched under the watchdog/RLIMIT_AS cap.
_INTERACTOR_LAUNCHER = '__interactor_launcher__'

# Returned for an unrecognized BOCA entry name.
_UNKNOWN_ENTRY = 2

_TASK_JSON = 'task.json'
_LANGUAGE_JSON = 'language.json'


def _read_bundle_file(name: str) -> str:
    """Read a bundled manifest file.

    Honors ``RBX_BOCA_BUNDLE_DIR`` (used by tests and by the packaged layout
    when the manifests sit beside the runtime). Otherwise falls back to the
    manifests bundled inside the ``rbx_boca`` package (Layer 1 places them
    there).
    """
    override = os.environ.get('RBX_BOCA_BUNDLE_DIR')
    if override:
        return (Path(override) / name).read_text()
    return importlib.resources.read_text('rbx_boca', name)


def _default_runner(argv: List[str], **kwargs) -> int:
    return subprocess.call(argv, **kwargs)


def _resolve_safeexec_path() -> str:
    """Best-effort safeexec path. Phase 9 / Layer 1 wire the real NativeAsset
    path; here we fall back to PATH lookup or the conventional location."""
    return shutil.which('safeexec') or '/usr/bin/safeexec'


def load_context() -> RunContext:
    """Default ``context_factory``: parse the bundled manifests and build a real
    :class:`RunContext`.

    Asset paths (checker/interactor/pipe) and ``interactor_launch_argv`` are
    left best-effort here; Phase 9 finalizes the interactive wiring. The unit
    tests never exercise this -- they inject a fake ``context_factory``.
    """
    task = TaskConfig.from_json(_read_bundle_file(_TASK_JSON))
    lang = LanguageManifest.from_json(_read_bundle_file(_LANGUAGE_JSON))
    safeexec = sandbox.SafeExec(path=_resolve_safeexec_path(), runner=_default_runner)
    return RunContext(
        task=task,
        lang=lang,
        cwd=Path.cwd(),
        runner=_default_runner,
        safeexec=safeexec,
    )


def _dispatch_interactor_launcher(rest: List[str]) -> int:
    if len(rest) < 3 or rest[2] != '--':
        raise ValueError("expected '--' separator before interactor argv")
    ittime = int(rest[0])
    notify_fd = int(rest[1])
    interactor_argv = rest[3:]
    # launch() replaces this process via execv, so it never returns; the 0 below
    # is only reached in tests that stub launch out.
    interactor_launcher.launch(interactor_argv, ittime=ittime, notify_fd=notify_fd)
    return 0


def main(
    argv: List[str], *, context_factory: Optional[Callable[[], RunContext]] = None
) -> int:
    entry = argv[0]
    rest = argv[1:]

    # Re-entrant interactor launcher: no manifests / context required.
    if entry == _INTERACTOR_LAUNCHER:
        return _dispatch_interactor_launcher(rest)

    ctx = (context_factory or load_context)()
    task = BatchTask() if ctx.task.task_type == 'batch' else InteractiveTask()

    if entry == 'compile':
        # BOCA: sourcename=rest[0], basename=rest[1]. Keep exe == basename for
        # Layer 2. timelimit=rest[2] / memory=rest[3] are available but unused.
        return task.compile(ctx, src=rest[0], exe=rest[1], basename=rest[1])
    if entry == 'run':
        return task.run(ctx, rest)
    if entry == 'compare':
        return task.compare(ctx, rest)
    if entry == 'limits':
        print(ctx.lang.limits.time_sec)
        print(ctx.lang.limits.runs)
        print(ctx.lang.limits.memory_mb)
        print(ctx.task.output_kb)
        return 0
    if entry == 'tests':
        return 0

    print('unknown entry: {!r}'.format(entry), file=sys.stderr)
    return _UNKNOWN_ENTRY
