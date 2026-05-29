from typing import Tuple

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
