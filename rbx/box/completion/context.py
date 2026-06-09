"""Shared, cheap helpers for building completion context. Must stay light."""

from pathlib import Path
from typing import Optional

_MARKERS = ('problem.rbx.yml', 'contest.rbx.yml')


def find_package_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from `start` (cwd if None) to find a package/contest root. No package load."""
    cur = Path.cwd() if start is None else start
    for d in [cur, *cur.parents]:
        if any((d / m).exists() for m in _MARKERS):
            return d
    return None
