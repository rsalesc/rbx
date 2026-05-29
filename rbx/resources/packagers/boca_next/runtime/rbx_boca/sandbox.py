import dataclasses
import subprocess
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass(frozen=True)
class SafeExecSpec:
    runs: int
    cpu_sec: int
    wall_sec: int
    mem_kb: int
    out_kb: int
    fds: int
    n: int  # safeexec -n process limit (1 for compiled, 0 for jvm/interpreted/compile)
    procs: Optional[int]  # safeexec -u procs-per-user (jvm/interpreted only)
    uid: int
    gid: int
    chdir: str
    chroot: Optional[str]
    stdin: Optional[str]
    stdout: str
    stderr: str


def build_safeexec_argv(
    spec: SafeExecSpec,
    program: List[str],
    *,
    safeexec: str = 'safeexec',
    notify: Optional[str] = None,
) -> List[str]:
    """Build the safeexec argv for ``program``.

    ``notify`` (interactive only) emits ``-D<notify>``: safeexec's notify-fd
    option. The interactive runner passes the literal ``__FD__`` token here,
    which pipe.exe substitutes with a real fd number at runtime (mirrors
    interactor_run.sh:45 ``-D__FD__``). Do NOT substitute it yourself.
    """
    argv = [safeexec, f'-r{spec.runs}', f'-t{spec.cpu_sec}', f'-T{spec.wall_sec}']
    argv += [f'-d{spec.mem_kb}', f'-m{spec.mem_kb}', f'-f{spec.out_kb}']
    argv += [f'-F{spec.fds}', f'-n{spec.n}']
    if spec.procs is not None:
        argv.append(f'-u{spec.procs}')
    argv += [f'-U{spec.uid}', f'-G{spec.gid}', f'-C{spec.chdir}']
    if spec.chroot is not None:
        argv.append(f'-R{spec.chroot}')
    if spec.stdin is not None:
        argv.append(f'-i{spec.stdin}')
    argv += [f'-o{spec.stdout}', f'-e{spec.stderr}']
    if notify is not None:
        argv.append(f'-D{notify}')
    argv.append('--')
    argv += list(program)
    return argv


_KNOWN_KINDS = ('compiled_static', 'jvm_jar', 'interpreted')
_KNOWN_PHASES = ('run', 'compile')

_JVM_MEM_KB = 20000000
_JVM_RUN_OUT_KB = 20000
_COMPILE_OUT_KB = 50000


def profile_for(
    kind: str,
    phase: str,
    *,
    cpu_sec: int,
    memory_mb: int,
    nruns: int = 1,
    out_kb: int = 0,
    uid: int,
    gid: int,
    chdir: str = '.',
    chroot: Optional[str] = None,
    stdin: Optional[str] = None,
    stdout: str = 'stdout0',
    stderr: str = 'stderr0',
    overrides: Optional[dict] = None,
) -> SafeExecSpec:
    if kind not in _KNOWN_KINDS:
        raise ValueError(f'unknown kind: {kind!r}')
    if phase not in _KNOWN_PHASES:
        raise ValueError(f'unknown phase: {phase!r}')

    mem_kb = memory_mb * 1000

    if phase == 'run':
        wall_sec = cpu_sec * 4
        run_stdin = 'stdin0' if stdin is None else stdin
        if kind == 'compiled_static':
            spec = SafeExecSpec(
                runs=nruns,
                cpu_sec=cpu_sec,
                wall_sec=wall_sec,
                mem_kb=mem_kb,
                out_kb=out_kb,
                fds=10,
                n=1,
                procs=None,
                uid=uid,
                gid=gid,
                chdir=chdir,
                chroot=chroot,
                stdin=run_stdin,
                stdout=stdout,
                stderr=stderr,
            )
        elif kind == 'jvm_jar':
            spec = SafeExecSpec(
                runs=nruns,
                cpu_sec=cpu_sec,
                wall_sec=wall_sec,
                mem_kb=_JVM_MEM_KB,
                out_kb=_JVM_RUN_OUT_KB,
                fds=256,
                n=0,
                procs=256,
                uid=uid,
                gid=gid,
                chdir=chdir,
                chroot=chroot,
                stdin=run_stdin,
                stdout=stdout,
                stderr=stderr,
            )
        else:  # interpreted
            spec = SafeExecSpec(
                runs=nruns,
                cpu_sec=cpu_sec,
                wall_sec=wall_sec,
                mem_kb=mem_kb,
                out_kb=out_kb,
                fds=256,
                n=0,
                procs=256,
                uid=uid,
                gid=gid,
                chdir=chdir,
                chroot=chroot,
                stdin=run_stdin,
                stdout=stdout,
                stderr=stderr,
            )
    else:  # compile
        # BOCA compile scripts set BOTH the CPU limit (-t) and the wall
        # limit (-T) to 2x the timelimit (compile/cpp:96,132).
        cpu_sec = cpu_sec * 2
        wall_sec = cpu_sec
        if kind == 'jvm_jar':
            spec = SafeExecSpec(
                runs=1,
                cpu_sec=cpu_sec,
                wall_sec=wall_sec,
                mem_kb=_JVM_MEM_KB,
                out_kb=_COMPILE_OUT_KB,
                fds=256,
                n=0,
                procs=256,
                uid=uid,
                gid=gid,
                chdir=chdir,
                chroot=chroot,
                stdin=None,
                stdout=stdout,
                stderr=stderr,
            )
        else:  # compiled_static & interpreted
            spec = SafeExecSpec(
                runs=1,
                cpu_sec=cpu_sec,
                wall_sec=wall_sec,
                mem_kb=mem_kb,
                out_kb=_COMPILE_OUT_KB,
                fds=1000,
                n=0,
                procs=None,
                uid=uid,
                gid=gid,
                chdir=chdir,
                chroot=chroot,
                stdin=None,
                stdout=stdout,
                stderr=stderr,
            )

    if overrides:
        spec = dataclasses.replace(spec, **overrides)
    return spec


def _default_runner(argv: List[str], **kwargs) -> int:
    return subprocess.call(argv, **kwargs)


class SafeExec:
    def __init__(
        self,
        path: str = 'safeexec',
        runner: Optional[Callable[..., int]] = None,
    ) -> None:
        self.path = path
        self.runner = runner if runner is not None else _default_runner

    def run(self, spec: SafeExecSpec, program: List[str], **kwargs) -> int:
        argv = build_safeexec_argv(spec, program, safeexec=self.path)
        return self.runner(argv, **kwargs)
