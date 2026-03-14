from typing import List

from rich.console import Console
from rich.live import Live


def hold_lives(console: Console) -> List[Live]:
    old_stack = list(console._live_stack)  # noqa: SLF001
    for live in old_stack[::-1]:
        live.stop()
    assert len(console._live_stack) == 0  # noqa: SLF001
    return old_stack
