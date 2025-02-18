import dataclasses
import os
import pathlib
import resource
import signal
import stat
import sys
from time import monotonic
from typing import List, Optional


@dataclasses.dataclass()
class Options:
    output_file: str
    argv: List[str]
    chdir: Optional[str] = None
    stdin_file: Optional[str] = None
    stdout_file: Optional[str] = None
    stderr_file: Optional[str] = None
    time_limit: Optional[float] = None
    wall_time_limit: Optional[float] = None  # seconds
    memory_limit: Optional[int] = None  # kb, but passed in args as mb
    fs_limit: Optional[int] = None  # kb


def exit_with(code: int):
    sys.exit(code)


def parse_opts() -> Options:
    options = Options(output_file=sys.argv[1], argv=[])
    num_opts = 0
    while num_opts + 2 < len(sys.argv) and sys.argv[num_opts + 2].startswith('-'):
        # Process option
        opt = sys.argv[num_opts + 2]
        if opt.startswith('-t'):
            options.time_limit = float(opt[2:])
        elif opt.startswith('-w'):
            options.wall_time_limit = float(opt[2:])
        elif opt.startswith('-m'):
            options.memory_limit = int(opt[2:]) * 1024
        elif opt.startswith('-i'):
            options.stdin_file = opt[2:]
        elif opt.startswith('-o'):
            options.stdout_file = opt[2:]
        elif opt.startswith('-e'):
            options.stderr_file = opt[2:]
        elif opt.startswith('-c'):
            options.chdir = opt[2:]
        elif opt.startswith('-f'):
            options.fs_limit = int(opt[2:])
        else:
            raise Exception(f'Invalid option {opt}')
        num_opts += 1
    options.argv = sys.argv[num_opts + 2 :]
    return options


def get_memory_usage(ru: resource.struct_rusage) -> int:
    if sys.platform == 'darwin':
        return ru.ru_maxrss // 1024 + ru.ru_ixrss
    return ru.ru_maxrss + ru.ru_ixrss + ru.ru_idrss + ru.ru_isrss


def get_cpu_time(ru: resource.struct_rusage) -> float:
    return ru.ru_utime + ru.ru_stime


def _get_file_size(filename: Optional[str]) -> int:
    if filename is None:
        return 0
    path = pathlib.Path(filename)
    if not path.is_file():
        return 0
    return path.stat().st_size


def get_file_sizes(options: Options):
    return _get_file_size(options.stdout_file) + _get_file_size(options.stderr_file)


def set_rlimits(options: Options):
    if options.time_limit is not None:
        time_limit_in_ms = int(options.time_limit * 1000)
        rlimit_cpu = int((time_limit_in_ms + 999) // 1000)
        resource.setrlimit(resource.RLIMIT_CPU, (rlimit_cpu, rlimit_cpu + 1))
    if options.fs_limit is not None:
        fs_limit = options.fs_limit * 1024  # in bytes
        resource.setrlimit(resource.RLIMIT_FSIZE, (fs_limit + 1, fs_limit * 2))


def redirect_fds(options: Options):
    files = [options.stdin_file, options.stdout_file, options.stderr_file]

    for i, file in enumerate(files):
        if file is None:
            continue
        open_args = [
            os.O_WRONLY | os.O_TRUNC | os.O_CREAT,
            stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR,
        ]
        if i == 0:
            # stdin
            open_args = [os.O_RDONLY]
        fd = os.open(
            file,
            *open_args,
        )
        os.dup2(fd, i)
        os.close(fd)


def wait_and_finish(
    pid: int,
    options: Options,
    start_time: float,
    alarm_msg: Optional[List[Optional[str]]] = None,
):
    _, exitstatus, ru = os.wait4(pid, 0)
    wall_time = monotonic() - start_time
    cpu_time = get_cpu_time(ru)
    memory_used = get_memory_usage(ru)
    file_sizes = get_file_sizes(options)

    entries = []
    exitcode = os.waitstatus_to_exitcode(exitstatus)
    entries.append(f'exit-code: {exitcode}')
    if exitcode < 0:
        entries.append(f'exit-sig: {-exitcode}')

    status = set()
    if exitcode > 0:
        status.add('RE')
    if exitcode < 0:
        status.add('SG')
    if options.time_limit is not None and (
        cpu_time > options.time_limit or -exitcode == 24
    ):
        status.add('TO')
        cpu_time = max(cpu_time, options.time_limit)
    if options.wall_time_limit is not None and wall_time > options.wall_time_limit:
        status.add('WT')
        status.add('TO')
    if options.memory_limit is not None and memory_used > options.memory_limit:
        status.add('ML')
    if options.fs_limit is not None and file_sizes > options.fs_limit * 1024:
        status.add('OL')

    if status:
        status_str = ','.join(status)
        entries.append(f'status: {status_str}')

    if alarm_msg:
        alarm_str = ','.join(msg for msg in alarm_msg if msg is not None)
        if alarm_str:
            entries.append(f'alarm-msg: {alarm_str}')

    entries.append(f'time: {cpu_time:.3f}')
    entries.append(f'time-wall: {wall_time:.3f}')
    entries.append(f'mem: {memory_used}')
    entries.append(f'file: {file_sizes}')

    output_file = pathlib.Path(sys.argv[1])
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text('\n'.join(entries) + '\n')


def main():
    options = parse_opts()

    start_time = monotonic()
    sub_pid = os.fork()
    if sub_pid == 0:
        if options.chdir is not None:
            os.chdir(options.chdir)
        set_rlimits(options)
        redirect_fds(options)
        os.execvp(options.argv[0], options.argv)

    alarm_msg: List[Optional[str]] = [None]

    def handle_alarm(*args, **kwargs):
        nonlocal alarm_msg
        wall_time = monotonic() - start_time
        if options.wall_time_limit is not None and wall_time > options.wall_time_limit:
            alarm_msg[0] = 'wall timelimit'
            os.kill(sub_pid, 9)
            return
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        if options.time_limit is not None:
            cpu_time = get_cpu_time(ru)
            if cpu_time > options.time_limit:
                alarm_msg[0] = 'timelimit'
                os.kill(sub_pid, 9)
                return
        if options.memory_limit is not None:
            memory_used = get_memory_usage(ru)
            if memory_used > options.memory_limit:
                alarm_msg[0] = 'memorylimit'
                os.kill(sub_pid, 9)
                return

        signal.setitimer(signal.ITIMER_REAL, 0.3)

    signal.setitimer(signal.ITIMER_REAL, 0.3)
    signal.signal(signal.SIGALRM, handle_alarm)
    wait_and_finish(sub_pid, options, start_time, alarm_msg=alarm_msg)

    # Cancel alarm before exiting to avoid surprises.
    signal.setitimer(signal.ITIMER_REAL, 0)

    # Exit gracefully.
    sys.exit()


if __name__ == '__main__':
    main()
