"""Tests for terminal sizing in the command app's panes.

Regressions for the two bugs that made a background problem's output look
mangled once you switched to its tab: it had been rendered at the 80-column
fallback (hidden panes never got a pty winsize), and the reflow on reveal left
the scroll extents stale, so the tail of the output was unreachable.
"""

import asyncio
import sys

from textual.app import App, ComposeResult

from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui._vendor.toad.widgets.terminal import Terminal
from rbx.box.ui.command_app import CommandEntry, rbxCommandApp

_PRINT_WIDTH = [
    sys.executable,
    '-c',
    'import os; print(os.get_terminal_size().columns)',
]


def _pane_text(pane: CommandPane) -> str:
    return ' '.join(
        line.content.plain.strip() for line in pane.state.scrollback_buffer.lines
    ).strip()


async def _wait_for_commands(app, pilot, panes_expected: int) -> None:
    for _ in range(100):
        await pilot.pause()
        await asyncio.sleep(0.05)
        panes = list(app.query(CommandPane))
        if len(panes) == panes_expected and all(
            p.return_code is not None for p in panes
        ):
            return
    raise AssertionError('commands did not finish in time')


async def test_hidden_panes_run_at_the_visible_pane_width():
    # Only one pane is displayed at a time; the hidden ones have a zero-sized
    # region. They must still get a real pty winsize, or their commands render
    # at the 80-column fallback and look hard-wrapped once shown.
    app = rbxCommandApp(
        [
            CommandEntry(argv=_PRINT_WIDTH, name='a'),
            CommandEntry(argv=_PRINT_WIDTH, name='b'),
            CommandEntry(argv=_PRINT_WIDTH, name='c'),
        ],
        parallel=True,
    )
    async with app.run_test(size=(150, 40)) as pilot:
        await _wait_for_commands(app, pilot, panes_expected=3)

        panes = list(app.query(CommandPane))
        visible = [p for p in panes if p.display]
        assert len(visible) == 1
        expected_width = visible[0].scrollable_content_region.width
        assert expected_width > 80

        for pane in panes:
            assert pane.width == expected_width
            assert _pane_text(pane) == str(expected_width)


class _TerminalApp(App):
    CSS = 'Terminal { width: 1fr; height: 1fr; }'

    def compose(self) -> ComposeResult:
        yield Terminal()


async def test_resize_keeps_scroll_extents_in_sync():
    # A resize reflows the buffer, so the scrollable extents have to follow it.
    # When nothing is written afterwards (the command already finished), a stale
    # `virtual_size` scrolls an anchored terminal past the end of its output.
    app = _TerminalApp()
    async with app.run_test(size=(150, 20)) as pilot:
        terminal = app.query_one(Terminal)
        terminal.anchor()
        terminal.update_size(80, 20)
        await terminal.write('\r\n'.join('x' * 120 for _ in range(40)))
        await pilot.pause()
        assert terminal.virtual_size.height == terminal.state.scrollback_buffer.height

        terminal.update_size(150, 20)
        await pilot.pause()

        assert terminal.virtual_size.height == terminal.state.scrollback_buffer.height
        # The anchored view still ends on real content, not on blank space past it.
        rendered = [
            terminal.render_line(y).text.rstrip()
            for y in range(terminal.scrollable_content_region.height)
        ]
        assert any(rendered)
