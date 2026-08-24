"""Tests for copying and keyboard selection in the command pane (#717).

Two features share one mixin: `ctrl+y` copies the whole buffer when nothing is
selected, and `ctrl+v` opens a vim-style visual mode whose state lives in
*logical* (unfolded) coordinates -- which is what makes a wrapped line copy back
as the program wrote it, and what lets the selection reach content the mouse
cannot drag to.
"""

import asyncio
import sys
from typing import List

from textual.geometry import Offset
from textual.selection import Selection

from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui.command_app import CommandEntry, rbxCommandApp

_LONG_LINE = 'X' * 300


def _print(*lines: str):
    body = '\n'.join(f'print({line!r})' for line in lines)
    return [sys.executable, '-c', body]


async def _running_app(pilot, app, panes_expected: int = 1):
    for _ in range(100):
        await pilot.pause()
        await asyncio.sleep(0.05)
        panes = list(app.query(CommandPane))
        if len(panes) == panes_expected and all(
            p.return_code is not None for p in panes
        ):
            return panes
    raise AssertionError('commands did not finish in time')


def _make_app(*lines: str) -> rbxCommandApp:
    return rbxCommandApp(
        [CommandEntry(argvs=[_print(*lines)], name='a')], parallel=True
    )


async def _focus_pane(app, pilot, pane) -> None:
    app.set_focus(pane)
    await pilot.pause()


def _capture_clipboard(app) -> List[str]:
    """Record what the app copies, instead of poking at its private state."""
    copied: List[str] = []
    app.copy_to_clipboard = copied.append  # type: ignore[method-assign]
    return copied


async def test_ctrl_y_copies_the_whole_output_when_nothing_is_selected():
    app = _make_app('alpha', 'beta', 'gamma')
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)
        copied = _capture_clipboard(app)

        await pilot.press('ctrl+y')
        await pilot.pause()

        assert copied == ['alpha\nbeta\ngamma']


async def test_ctrl_y_still_copies_only_the_selection():
    app = _make_app('alpha', 'beta', 'gamma')
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)
        copied = _capture_clipboard(app)

        pane.screen.selections = {pane: Selection(Offset(0, 1), Offset(4, 1))}
        await pilot.pause()
        await pilot.press('ctrl+y')
        await pilot.pause()

        assert copied == ['beta']


async def test_ctrl_y_copies_a_wrapped_line_unwrapped():
    app = _make_app(_LONG_LINE)
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)
        copied = _capture_clipboard(app)
        # The line really is folded across several rows.
        assert len(pane.state.scrollback_buffer.folded_lines) > 1

        await pilot.press('ctrl+y')
        await pilot.pause()

        assert copied == [_LONG_LINE]


async def test_ctrl_v_enters_visual_mode_and_shows_a_cursor():
    app = _make_app('alpha', 'beta', 'gamma')
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)

        await pilot.press('ctrl+v')
        await pilot.pause()

        assert pane.in_select_mode
        assert pane.has_class('-selecting')
        # With no anchor yet the selection is a single cell -- that *is* the cursor.
        assert pane.screen.selections[pane] == Selection(Offset(0, 0), Offset(1, 0))


async def test_visual_mode_keys_do_not_reach_the_process():
    app = rbxCommandApp(
        [
            CommandEntry(
                argvs=[[sys.executable, '-u', '-c', "print('ready'); input()"]],
                name='a',
            )
        ],
        parallel=True,
    )
    async with app.run_test(size=(150, 40)) as pilot:
        # Wait until the command has printed, so there is a buffer to select in.
        for _ in range(100):
            await pilot.pause()
            await asyncio.sleep(0.05)
            panes = list(app.query(CommandPane))
            if panes and panes[0].state.scrollback_buffer.lines:
                break
        (pane,) = panes
        await _focus_pane(app, pilot, pane)

        await pilot.press('ctrl+v')
        for _ in range(5):
            await pilot.press('j')
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        text = '\n'.join(
            line.content.plain for line in pane.state.scrollback_buffer.lines
        )
        assert 'j' not in text


async def test_hjkl_and_arrows_both_move_the_cursor():
    app = _make_app('alpha', 'beta', 'gamma')
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)
        await pilot.press('ctrl+v')

        await pilot.press('j', 'l')
        await pilot.pause()
        assert pane.select_cursor == Offset(1, 1)

        await pilot.press('down', 'right')
        await pilot.pause()
        assert pane.select_cursor == Offset(2, 2)

        await pilot.press('up', 'left')
        await pilot.pause()
        assert pane.select_cursor == Offset(1, 1)

        await pilot.press('k', 'h')
        await pilot.pause()
        assert pane.select_cursor == Offset(0, 0)


async def test_charwise_selection_to_the_end_copies_the_tail():
    app = _make_app('alpha', 'beta', 'gamma')
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)
        copied = _capture_clipboard(app)

        await pilot.press('ctrl+v', 'j', 'v', 'G', '$', 'y')
        await pilot.pause()

        assert copied == ['beta\ngamma']
        assert not pane.in_select_mode
        assert not pane.screen.selections


async def test_linewise_selection_copies_the_unwrapped_logical_line():
    app = _make_app('alpha', _LONG_LINE, 'gamma')
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)
        copied = _capture_clipboard(app)

        await pilot.press('ctrl+v', 'j', 'V', 'y')
        await pilot.pause()

        assert copied == [_LONG_LINE]


async def test_moving_past_the_viewport_scrolls_the_pane():
    # One-liner on purpose: the sub-command Select renders the command string as
    # its label, so a multi-line `python -c` would grow it until the pane collapses.
    app = rbxCommandApp(
        [
            CommandEntry(
                argvs=[
                    [
                        sys.executable,
                        '-c',
                        "[print(f'line-{index}') for index in range(200)]",
                    ]
                ],
                name='a',
            )
        ],
        parallel=True,
    )
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)

        await pilot.press('ctrl+v')
        await pilot.pause()
        # The pane follows its output, so it starts parked at the bottom.
        bottom = pane.scroll_offset.y
        assert bottom > 0

        await pilot.press('g', 'g')
        await pilot.pause()
        assert pane.scroll_offset.y == 0
        assert pane.select_cursor == Offset(0, 0)

        await pilot.press('G')
        await pilot.pause()
        assert pane.scroll_offset.y == bottom
        assert pane.select_cursor.y == len(pane.state.scrollback_buffer.lines) - 1


async def test_escape_leaves_visual_mode_without_copying():
    app = _make_app('alpha', 'beta', 'gamma')
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)
        copied = _capture_clipboard(app)

        await pilot.press('ctrl+v', 'v', 'j', 'escape')
        await pilot.pause()

        assert not pane.in_select_mode
        assert not pane.screen.selections
        assert copied == []


async def test_y_without_an_anchor_copies_the_cursor_line():
    app = _make_app('alpha', 'beta', 'gamma')
    async with app.run_test(size=(150, 40)) as pilot:
        (pane,) = await _running_app(pilot, app)
        await _focus_pane(app, pilot, pane)
        copied = _capture_clipboard(app)

        await pilot.press('ctrl+v', 'j', 'y')
        await pilot.pause()

        assert copied == ['beta']
