import os
import pathlib
from typing import Any, Optional

from rbx import utils
from rbx.box import setter_config


def ref(text: Any) -> str:
    return f'[item]{text}[/item]'


def href(
    url: os.PathLike[str],
    text: Optional[str] = None,
    style: str = 'item',
    hyperlink: bool = True,
) -> str:
    custom_text = False
    if text is None:
        text = str(url)
    else:
        custom_text = True

    if not hyperlink:
        return f'[{style}]{text}[/{style}]'

    if not custom_text:
        if not setter_config.get_setter_config().hyperlinks:
            return f'[{style}]{text}[/{style}]'
        if os.environ.get('TERM') in ['vscode']:
            return f'[{style}]{text}[/{style}]'

    if isinstance(url, pathlib.Path):
        url = utils.abspath(url)

    url_str = str(url)
    if pathlib.Path(url_str).exists():
        url_str = f'file://{url_str}'
    return f'[{style}][link={url_str}]{text}[/link][/{style}]'


# What a formatted time or memory reads as when nothing was measured at all.
UNMEASURED = '-'


def get_formatted_memory(memory_in_bytes: int, mib_decimal_places: int = 0) -> str:
    if memory_in_bytes < 1024 * 1024:
        if memory_in_bytes < 1024:
            return f'{memory_in_bytes} B'
        return f'{memory_in_bytes / 1024:.0f} KiB'
    return f'{memory_in_bytes / (1024 * 1024):.{mib_decimal_places}f} MiB'


def get_formatted_time(time_in_ms: int) -> str:
    return f'{time_in_ms} ms'


def get_formatted_time_in_seconds(time_in_seconds: float) -> str:
    return f'{time_in_seconds:.1f} s'


def get_formatted_duration_in_seconds(time_in_seconds: float) -> str:
    """A duration that may span milliseconds to seconds, read at a useful scale.

    `get_formatted_time_in_seconds` fixes one decimal place, which is right for
    a whole run's judging time but renders every realistic checker time as
    `0.0 s`. Benchmarks compare durations several orders of magnitude apart, so
    the unit follows the value.

    Rounds rather than truncates: at the millisecond scale truncation is a
    visible lie (`0.0499 s` reading as `49 ms`). `solutions._get_evals_time_in_ms`
    truncates instead because it compares against a time *limit*, where rounding
    up could turn a pass into a fail. The branch reads the rounded milliseconds
    rather than the raw value, so `0.9999 s` reads `1.0 s` and never `1000 ms`.

    A duration that rounds to nothing is reported as `<1 ms`, so that it is not
    read as a measured zero. A negative duration would render with a leading
    `-`, colliding with `UNMEASURED` -- no sandbox clock produces one today, so
    it is not guarded against.
    """
    time_in_ms = round(time_in_seconds * 1000)
    if time_in_seconds > 0 and time_in_ms == 0:
        return '<1 ms'
    if time_in_ms < 1000:
        return get_formatted_time(time_in_ms)
    return get_formatted_time_in_seconds(time_in_seconds)
