import asyncio
import time
from typing import Awaitable, Callable, Union, cast

from rich.console import RenderableType
from rich.measure import Measurement
from rich.text import Text


class CellSlot:
    def __init__(self, renderable: RenderableType = ''):
        self.renderable = renderable

    # forward measurement so column widths remain correct
    def __rich_measure__(self, console, options):
        return Measurement.get(console, options, self.renderable)

    # render whatever we currently point to
    def __rich_console__(self, console, options):
        yield self.renderable

    def update(self, renderable: RenderableType):
        self.renderable = renderable
        return self


class StableCell:
    """
    Drop-in replacement for CellSlot + FixedWidth.
    Keeps width constant, prevents wrapping, pads/truncates,
    and lets you swap .value every refresh.
    """

    def __init__(self, value: RenderableType, width: int, align: str = 'left'):
        self.width = width
        self.align = align  # "left" | "right" | "center"
        self.value = value  # assign Text or str

    # Tell Rich: this cell always measures to exactly width
    def __rich_measure__(self, console, options):
        return Measurement(self.width, self.width)

    def __rich_console__(self, console, options):
        # Convert once (avoid reparsing markup)
        t = self.value if isinstance(self.value, Text) else Text(str(self.value))

        # Truncate to width (no wrap)
        t.truncate(self.width, overflow='crop')

        # Pad to exact width
        pad = self.width - t.cell_len
        if pad > 0:
            if self.align == 'right':
                t = Text(' ' * pad) + t
            elif self.align == 'center':
                left = pad // 2
                right = pad - left
                t = Text(' ' * left) + t + Text(' ' * right)
            else:  # left
                t = t + Text(' ' * pad)

        yield t

    def update(self, value: RenderableType):
        self.value = value
        return self


class Throttling:
    """
    Throttles calls to a callable, ensuring it's only invoked if at least N seconds
    have passed since the last invocation. Supports both sync and async callables.
    """

    def __init__(
        self,
        func: Union[Callable[[], None], Callable[[], Awaitable[None]]],
        seconds: float,
    ):
        self.func = func
        self.seconds = seconds
        self.last_called: float | None = None
        self.is_async = asyncio.iscoroutinefunction(func)

    def __call__(self):
        if self.is_async:
            raise TypeError(
                "Cannot call async throttled function synchronously. Use 'await throttled()' instead."
            )
        now = time.time()
        if self.last_called is None or (now - self.last_called) >= self.seconds:
            self.last_called = now
            self.func()

    def __await__(self):
        return self._async_call().__await__()

    async def _async_call(self):
        if not self.is_async:
            raise TypeError(
                "Cannot await non-async throttled function. Use 'throttled()' instead."
            )
        now = time.time()
        if self.last_called is None or (now - self.last_called) >= self.seconds:
            self.last_called = now
            # Cast is safe because we checked self.is_async
            await cast(Callable[[], Awaitable[None]], self.func)()
