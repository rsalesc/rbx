from dataclasses import dataclass
from typing import List, Optional


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
    spec: SafeExecSpec, program: List[str], *, safeexec: str = 'safeexec'
) -> List[str]:
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
    argv += list(program)
    return argv
