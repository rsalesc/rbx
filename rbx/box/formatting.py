import os
import pathlib
from typing import Optional


def href(url: os.PathLike[str], text: Optional[str] = None, style: str = 'item') -> str:
    if text is None:
        text = str(url)
    if isinstance(url, pathlib.Path):
        url = url.resolve()
    return f'[{style}][link={url}]{text}[/link][/{style}]'


def get_formatted_memory(memory_in_bytes: int, mib_decimal_places: int = 0) -> str:
    if memory_in_bytes < 1024 * 1024:
        if memory_in_bytes < 1024:
            return f'{memory_in_bytes} B'
        return f'{memory_in_bytes / 1024:.0f} KiB'
    return f'{memory_in_bytes / (1024 * 1024):.{mib_decimal_places}f} MiB'


def get_formatted_time(time_in_ms: int) -> str:
    return f'{time_in_ms} ms'
