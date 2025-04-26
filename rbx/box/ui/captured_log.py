import asyncio
import copy
import dataclasses
import fcntl
import os
import pty
import re
import signal
import struct
import termios
from typing import Callable, List, Optional, Tuple

import pyte
import textual
from pyte.screens import Char
from rich.color import ColorParseError
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip


class PyteDisplay:
    lines: List[List[Segment]]

    def __init__(self, lines):
        self.lines = lines

    @property
    def virtual_height(self):
        return len(self.lines)


@dataclasses.dataclass
class LogDisplayState:
    screen: pyte.Screen
    exitcode: Optional[int]


@dataclasses.dataclass
class Emulator:
    communicate_task: asyncio.Task
    send_task: asyncio.Task
    wait_task: asyncio.Task
    pid: int
    callback: Optional[Callable] = None

    def disconnect(self):
        self.communicate_task.cancel()
        self.send_task.cancel()
        self.wait_task.cancel()
        try:
            os.kill(self.pid, signal.SIGTERM)
        except OSError:
            # Process does not exist anymore.
            pass


class LogDisplay(ScrollView, can_focus=True):
    DEFAULT_CSS = """
    LogDisplay {
        background: $background;
    }
    """
    emulator: Optional[Emulator]
    exitcode: Optional[int]

    def __init__(
        self,
        default_colors: Optional[str] = 'textual',
        max_lines: int = 1000,
        name: Optional[str] = None,
        id: Optional[str] = None,
        classes: Optional[str] = None,
    ):
        super().__init__(name=name, id=id, classes=classes)

        self.emulator = None
        self.default_colors = default_colors
        if default_colors == 'textual':
            self.textual_colors = self.detect_textual_colors()

        self.virtual_size = Size(80, max_lines)
        self._max_lines = max_lines
        self._display = PyteDisplay([Text()])
        self._screen = pyte.Screen(self.virtual_size.width, self._max_lines)
        self.stream = pyte.Stream(self._screen)

        self.recv_queue = asyncio.Queue()
        self.send_queue = asyncio.Queue()
        self.exitcode = None

    def _resize(self):
        self.virtual_size = Size(
            width=self.size.width - 2,  # Account for scroll bar.
            height=self.virtual_size.height,
        )
        self._screen.resize(self._max_lines, self.virtual_size.width)

    async def on_resize(self, _event: events.Resize):
        if self.emulator is None:
            return

        # Update only width.
        self.virtual_size = Size(
            width=self.size.width - 2,  # Account for scroll bar.
            height=self.virtual_size.height,
        )
        await self.send_queue.put(
            ['set_size', self._max_lines, self.virtual_size.width]
        )
        self._screen.resize(self._max_lines, self.virtual_size.width)
        self.update_display()

    def update_display(self):
        lines: List[List[Segment]] = []
        for y in range(self._screen.lines):
            line = self._screen.buffer[y]
            line_segments = []
            accumulated_text = []
            for x in range(self._screen.columns):
                char: Char = line[x]
                if x > 0 and (not self.char_style_cmp(char, line[x - 1])):
                    text = ''.join(accumulated_text)
                    line_segments.append(
                        Segment(text, style=self.char_rich_style(line[x - 1]))
                    )
                    accumulated_text = []
                accumulated_text.append(char.data)
            if accumulated_text:
                text = ''.join(accumulated_text)
                line_segments.append(
                    Segment(
                        text, style=self.char_rich_style(line[self._screen.columns - 1])
                    )
                )
            lines.append(line_segments)

        # Remove empty lines from the back.
        while lines:
            last_line = lines[-1]
            text = ''.join(seg.text for seg in last_line)
            if text.strip():
                break
            lines.pop()

        self._display = PyteDisplay(lines)
        self.virtual_size = Size(
            width=self.size.width - 2,  # Account for possible vertical scrollbar.
            height=self._display.virtual_height,
        )
        self.refresh()

    def disconnect(self):
        if self.emulator is None:
            return
        cb = self.emulator.callback
        self.emulator.disconnect()
        self.emulator = None
        self.recv_queue = asyncio.Queue()
        self.send_queue = asyncio.Queue()
        if cb is not None:
            cb()
        self.recv_task.cancel()

    def on_unmount(self):
        self.disconnect()

    async def recv(self):
        while True:
            msg = await self.recv_queue.get()
            cmd = msg[0]
            if cmd == 'setup':
                await self.send_queue.put(
                    [
                        'set_size',
                        self.virtual_size.height,
                        self.virtual_size.width,
                    ]
                )
            elif cmd == 'stdout':
                chars = msg[1]
                self.stream.feed(chars)
                self.update_display()
            elif cmd == 'disconnect':
                self.disconnect()

    def char_rich_style(self, char: Char) -> Style:
        """Returns a rich.Style from the pyte.Char."""

        foreground = self.detect_color(char.fg)
        background = self.detect_color(char.bg)
        if self.default_colors == 'textual':
            if background == 'default':
                background = self.textual_colors['background']
            if foreground == 'default':
                foreground = self.textual_colors['foreground']

        style: Optional[Style]
        try:
            style = Style(
                color=foreground,
                bgcolor=background,
                bold=char.bold,
            )
        except ColorParseError as error:
            textual.log.warning('color parse error:', error)
            style = None

        return style or Style()

    def char_style_cmp(self, given: Char, other: Char) -> bool:
        """Compares two pyte.Chars and returns if these are the same.

        Returns:
            True    if char styles are the same
            False   if char styles differ
        """

        if (
            given.fg == other.fg
            and given.bg == other.bg
            and given.bold == other.bold
            and given.italics == other.italics
            and given.underscore == other.underscore
            and given.strikethrough == other.strikethrough
            and given.reverse == other.reverse
            and given.blink == other.blink
        ):
            return True

        return False

    def char_style_default(self, char: Char) -> bool:
        """Returns True if the given char has a default style."""

        if (
            char.fg == 'default'
            and char.bg == 'default'
            and char.bold is False
            and char.italics is False
            and char.underscore is False
            and char.strikethrough is False
            and char.reverse is False
            and char.blink is False
        ):
            return True

        return False

    def detect_color(self, color: str) -> str:
        """Tries to detect the correct Rich-Color based on a color name.

        * Returns #<color> if <color> is a hex-definition without "#"
        * Fixes wrong ANSI color names.

        Examples:
          * htop is using "brown" => not an ANSI color
        """

        if color == 'brown':
            return 'yellow'

        if color == 'brightblack':
            # fish tabbing through recommendations
            return '#808080'
        if color == 'brightwhite':
            return '#FFFFFF'

        if re.match('[0-9a-f]{6}', color, re.IGNORECASE):
            return f'#{color}'

        return color

    def detect_textual_colors(self) -> dict:
        """Returns the currently used colors of textual depending on dark-mode."""

        return self.app.current_theme.to_color_system().generate()

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        y += scroll_y
        if y >= len(self._display.lines):
            return Strip.blank(self.size.width)
        line = self._display.lines[y]
        strip = Strip(line).crop(scroll_x, scroll_x + self.size.width)
        return strip

    def export(self):
        return LogDisplayState(screen=copy.copy(self._screen), exitcode=self.exitcode)

    def load(self, state: LogDisplayState):
        self.disconnect()
        self._screen = state.screen
        self.stream = pyte.Stream(self._screen)
        self.exitcode = state.exitcode
        self.update_display()

    async def capture(self, argv: List[str]) -> int:
        self.exitcode = None
        self.recv_task = asyncio.create_task(self.recv())

        loop = asyncio.get_running_loop()
        send_queue = self.recv_queue
        recv_queue = self.send_queue
        event = asyncio.Event()

        pid, fd = pty.fork()
        if pid == 0:  # Child
            os.execvp(argv[0], argv)

        pout = os.fdopen(fd, 'w+b', 0)
        data: Optional[str] = None

        self._resize()

        def on_output():
            nonlocal data
            try:
                data = pout.read(65536).decode()  # Read non-blocking.
            except Exception:
                data = None
                loop.remove_reader(pout)
            event.set()

        async def cleanup(wait_tp: Optional[Tuple[int, int]] = None):
            if self.exitcode is not None:
                return
            try:
                loop.remove_reader(pout)
                if wait_tp is None:
                    wait_tp = os.waitpid(pid, os.WNOHANG)
                _, exitstatus = wait_tp
                exitcode = os.waitstatus_to_exitcode(exitstatus)
                self.exitcode = exitcode
            except ChildProcessError:
                self.exitcode = -1
            await send_queue.put(['disconnect', 1])

        async def communicate():
            await send_queue.put(['setup', {}])

            while True:
                msg = await recv_queue.get()
                if msg[0] == 'set_size':
                    winsize = struct.pack('HH', msg[1], msg[2])
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

        async def send():
            while True:
                await event.wait()
                event.clear()
                if data is None:
                    await cleanup()
                else:
                    await send_queue.put(['stdout', data])

        async def wait():
            while True:
                try:
                    if (wait_tp := os.waitpid(pid, os.WNOHANG)) != (0, 0):
                        await cleanup(wait_tp)
                except ChildProcessError:
                    break
                await asyncio.sleep(0.5)

        finish = asyncio.Event()
        self.emulator = Emulator(
            asyncio.create_task(communicate()),
            asyncio.create_task(send()),
            asyncio.create_task(wait()),
            pid=pid,
            callback=lambda: finish.set(),
        )
        loop.add_reader(pout, on_output)
        await finish.wait()
        assert self.exitcode is not None
        return self.exitcode
