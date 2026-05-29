import fcntl
import os
import resource
import signal
import time
from typing import Sequence, Tuple

# bash `ulimit -v 1024000` caps virtual address space (RLIMIT_AS) at this many
# KiB. Python's resource.setrlimit expects bytes, so we convert.
_ADDRESS_SPACE_LIMIT_KIB = 1024000

# After SIGTERM, the watchdog waits this many seconds before SIGKILL.
_KILL_GRACE_SECONDS = 5


def address_space_limit() -> int:
    """Return the RLIMIT_AS cap in bytes (bash `ulimit -v 1024000`, in KiB)."""
    return _ADDRESS_SPACE_LIMIT_KIB * 1024


def watchdog_timeout(ittime: int) -> Tuple[int, int]:
    """Return (term_after_seconds, kill_after_seconds) for the watchdog.

    After ``ittime`` seconds send SIGTERM to the process group; ``_KILL_GRACE_SECONDS``
    seconds later send SIGKILL.
    """
    return (ittime, _KILL_GRACE_SECONDS)


def launch(interactor_argv: Sequence[str], *, ittime: int, notify_fd: int) -> None:
    """Replace this process with the interactor, under an RLIMIT_AS cap and a
    process-group watchdog. Mirrors interactor_run.sh runit_wrapper.sh.

    Verified by Phase 9 integration tests (fd-inheritance / killpg semantics are
    pure syscall behavior, not unit-testable).
    """
    limit = address_space_limit()
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    # Ensure notify_fd survives execv into the interactor: the interactor must
    # inherit it and hold the pipe open until it exits, so pipe.exe's epoll sees
    # HUP only when the interactor is done.
    flags = fcntl.fcntl(notify_fd, fcntl.F_GETFD)
    fcntl.fcntl(notify_fd, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)

    term_after, kill_after = watchdog_timeout(ittime)

    if os.fork() == 0:
        # Watchdog child. CLOSE its copy of notify_fd (the `exec {fd}>&-`
        # analogue) — critical so the watchdog does not keep the pipe open and
        # block pipe.exe's HUP detection.
        try:
            os.close(notify_fd)
        except OSError:
            pass
        time.sleep(term_after)
        try:
            os.killpg(0, signal.SIGTERM)
        except ProcessLookupError:
            pass
        time.sleep(kill_after)
        try:
            os.killpg(0, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os._exit(0)

    # Parent: become the interactor. Same pid/pgid, so the watchdog's
    # killpg(0, ...) targets this group. notify_fd (now non-cloexec) is inherited
    # and stays open until the interactor exits.
    os.execv(interactor_argv[0], list(interactor_argv))
