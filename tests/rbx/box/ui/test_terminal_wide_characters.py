"""Wide characters in the terminal emulator, and what `ctrl+y` copies back.

Lines are stored as characters; the terminal moves its cursor in *cells*. A CJK
ideograph or an emoji is one character and two cells wide, so any program that
positions the cursor by column on such a line -- a `\\r` redraw, a progress bar,
`ESC[nG` -- used to land at the wrong index: the emulator padded the difference
with spaces that were never printed, or ate a character that was.

The output looked close enough on screen to miss; pasting it did not.
"""

import sys

import pytest

from rbx.box.ui import clipboard
from rbx.box.ui._vendor.toad.ansi import cell_span, cell_to_index, index_to_cell
from rbx.box.ui._vendor.toad.ansi._ansi import TerminalState
from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui.command_app import CommandEntry, rbxCommandApp

_WIDE = '日本語'
_EMOJI = '🎉'


async def _noop(text: str) -> None:
    pass


async def _write(text: str, width: int = 40) -> list[str]:
    """Feed `text` to a bare emulator and return its unfolded lines."""
    state = TerminalState(_noop, width=width, height=24)
    await state.write(text)
    return [line.content.plain for line in state.scrollback_buffer.lines]


# --- the conversions --------------------------------------------------------


@pytest.mark.parametrize(
    ('text', 'cell', 'expected'),
    [
        ('abc', 0, (0, 0)),
        ('abc', 2, (2, 0)),
        # Past the end: the caller has to pad the difference.
        ('abc', 5, (3, 2)),
        # Each ideograph is two cells, so cell 6 is the end of the line.
        (_WIDE, 6, (3, 0)),
        (_WIDE, 4, (2, 0)),
        (_WIDE, 7, (3, 1)),
        # A column inside a wide character resolves to that character.
        (_WIDE, 1, (0, 0)),
        (_EMOJI + 'ab', 2, (1, 0)),
        ('', 3, (0, 3)),
    ],
)
def test_cell_to_index(text, cell, expected):
    assert cell_to_index(text, cell) == expected


@pytest.mark.parametrize(
    ('text', 'cells', 'expected'),
    [
        ('abc', 2, 2),
        ('abc', 9, 3),
        (_WIDE, 2, 1),
        (_WIDE, 4, 2),
        # Rounds up: one column of a two-cell character covers all of it.
        (_WIDE, 1, 1),
        (_WIDE, 3, 2),
        ('abc', 0, 0),
    ],
)
def test_cell_span(text, cells, expected):
    assert cell_span(text, cells) == expected


def test_index_to_cell():
    assert index_to_cell(_WIDE, 0) == 0
    assert index_to_cell(_WIDE, 2) == 4
    assert index_to_cell('ab' + _EMOJI, 3) == 4


# --- the emulator -----------------------------------------------------------


async def test_absolute_column_after_wide_characters_is_not_padded():
    # ESC[7G is the column just past 日本語 (six cells). Indexing by character
    # put it three columns further out, and the gap came back as spaces.
    assert await _write(f'{_WIDE}\x1b[7GEND') == [f'{_WIDE}END']


async def test_carriage_return_overwrite_consumes_cells():
    # Two columns of 日 are overwritten, not two characters.
    assert await _write(f'{_WIDE}abc\rXY') == ['XY本語abc']


async def test_cursor_forward_counts_cells():
    assert await _write(f'{_WIDE}abc\r\x1b[4CZZ') == ['日本ZZabc']


async def test_erase_characters_blanks_the_cells_it_covered():
    # ECH of two cells clears 日 and leaves two spaces, so 本語 stays put.
    assert await _write(f'{_WIDE}abc\r\x1b[2X') == ['  本語abc']


async def test_writing_past_the_end_pads_to_the_right_column():
    # The emoji covers cells 0 and 1; ESC[6G asks for cell 5, so three columns
    # of padding stand between them -- counted in cells, not characters.
    assert await _write(f'{_EMOJI}\x1b[6Gx') == [f'{_EMOJI}   x']


async def test_a_redraw_of_a_wrapped_wide_line_hits_the_current_row():
    # The line folds every ten cells, so `\r` returns to the start of the last
    # row -- which is a fold-local cell offset, not a character one.
    wrapped = f'{_WIDE * 3}abc'
    assert await _write(f'{wrapped}\rXY', width=10) == [f'{_WIDE * 3}abXY']


async def test_reflow_keeps_wide_lines_intact():
    state = TerminalState(_noop, width=10, height=24)
    await state.write(f'{_WIDE * 3}abc')
    state.update_size(30, 24)
    state.update_size(8, 24)
    await state.write('!')

    lines = [line.content.plain for line in state.scrollback_buffer.lines]
    assert lines == [f'{_WIDE * 3}abc!']


async def test_a_line_of_wide_characters_survives_a_redraw():
    # What a spinner does: rewrite the same line, each frame a little different.
    frames = ''.join(f'\r⠋ {_WIDE} passo {index}' for index in range(3))
    assert await _write(frames) == [f'⠋ {_WIDE} passo 2']


# --- what actually reaches the clipboard ------------------------------------


async def test_ctrl_y_copies_redrawn_unicode_output_verbatim(monkeypatch):
    body = (
        'import sys\n'
        f'for frame in ["\\u280b {_WIDE} lendo", "\\u2714 {_WIDE} pronto"]:\n'
        '    sys.stdout.write("\\r" + frame)\n'
        'sys.stdout.write("\\n")\n'
    )
    app = rbxCommandApp(
        [CommandEntry(argvs=[[sys.executable, '-c', body]], name='a')],
        parallel=True,
    )
    async with app.run_test(size=(80, 30)) as pilot:
        pane = None
        for _ in range(100):
            await pilot.pause()
            panes = list(app.query(CommandPane))
            if panes and all(p.return_code is not None for p in panes):
                (pane,) = panes
                break
        assert pane is not None, 'command did not finish in time'

        app.set_focus(pane)
        await pilot.pause()
        copied: list[str] = []
        monkeypatch.setattr(clipboard, 'copy', lambda app, text: copied.append(text))

        await pilot.press('ctrl+y')
        await pilot.pause()

        assert copied == [f'✔ {_WIDE} pronto']
