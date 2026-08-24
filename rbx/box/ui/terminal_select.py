"""Keyboard selection and copying for terminal panes (#717).

The pane could only copy what the mouse had selected, which breaks down exactly
where it matters: a drag cannot reach output that overflows the scroll region,
and a logical line folded across rows came back with the fold breaks baked in.

`TerminalSelectMixin` adds two things on top of a `CommandPane`:

* `ctrl+y` copies the selection when there is one, and the **whole buffer** when
  there is not.
* `ctrl+v` opens a vim-style visual mode: motions move a cursor (with
  auto-scroll), `v`/`V` start a char- or line-wise selection, `y` copies.

Two properties carry the design.

First, all state is kept in *logical* coordinates -- `Offset(column, line_no)`
into `Buffer.lines`, the unfolded lines -- and never in viewport rows. Scrollback
only ever appends, so a command still printing cannot shift the indices under a
selection, and a resize reflows every folded row while leaving logical positions
untouched. `Buffer.line_to_fold` and `Buffer.folded_lines` map between the two
spaces when the view has to scroll.

Second, the mode publishes into Textual's `Screen.selections`, which the vendored
`Terminal._render_line` already reads. Highlighting and `get_selected_text()`
therefore come for free, and the vendored tree needs no changes.

Keys are intercepted ahead of `Terminal.on_key`, which otherwise forwards
everything to the pty -- that interception is what lets the mode work while a
command is still running.
"""

import re
from typing import List, Optional

from textual import events
from textual.geometry import Offset
from textual.selection import Selection

from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane

_WORD_RE = re.compile(r'\w+|[^\w\s]')

SELECT_SUBTITLE = '[b]v[/b] select  [b]y[/b] copy  [b]esc[/b] exit'

_EXIT_KEYS = frozenset({'escape', 'ctrl+v', 'ctrl+c'})
_COPY_KEYS = frozenset({'y', 'ctrl+y', 'enter'})


def _tidy(text: str) -> str:
    """Drop the padding a terminal buffer leaves on its lines."""
    lines = [line.rstrip() for line in text.split('\n')]
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


class TerminalSelectMixin:
    """Vim-style visual selection over a terminal pane's logical buffer.

    Mix in *ahead of* `CommandPane` so `on_key` runs before the key-forwarding
    path in `Terminal`.
    """

    _select_cursor: Optional[Offset] = None
    _select_anchor: Optional[Offset] = None
    _select_linewise: bool = False
    _select_desired_x: int = 0
    _select_pending_g: bool = False
    _select_was_anchored: bool = False

    # --- state -----------------------------------------------------------

    @property
    def in_select_mode(self) -> bool:
        """Is the visual selection mode active?"""
        return self._select_cursor is not None

    @property
    def select_cursor(self) -> Optional[Offset]:
        """Cursor position in logical `(column, line_no)` coordinates."""
        return self._select_cursor

    @property
    def _buffer(self):
        return self.state.scrollback_buffer

    def _lines(self) -> List[str]:
        return [line.content.plain for line in self._buffer.lines]

    def _line_text(self, line_no: int) -> str:
        lines = self._buffer.lines
        if 0 <= line_no < len(lines):
            return lines[line_no].content.plain
        return ''

    def can_select(self) -> bool:
        """Can a keyboard selection be started right now?

        Not while a full-screen child owns the display: the alternate buffer and
        the scrollback share the `line_no` space that selections are expressed
        in, so a selection there would be ambiguous, and the child should keep
        the key anyway.
        """
        return (
            self.allow_select
            and not self.state.alternate_screen
            and bool(self._buffer.lines)
        )

    # --- coordinate mapping ----------------------------------------------

    def _clamp(self, position: Offset) -> Offset:
        lines = self._buffer.lines
        if not lines:
            return Offset(0, 0)
        y = max(0, min(position.y, len(lines) - 1))
        x = max(0, min(position.x, max(0, len(self._line_text(y)) - 1)))
        return Offset(x, y)

    def _folded_row_of(self, position: Offset) -> int:
        """Map a logical position to the folded row that renders it."""
        buffer = self._buffer
        line_no = position.y
        if line_no >= len(buffer.line_to_fold):
            return max(0, buffer.height - 1)
        row = buffer.line_to_fold[line_no]
        consumed = 0
        folds = buffer.lines[line_no].folds
        for index, fold in enumerate(folds):
            length = len(fold.content)
            if position.x < consumed + length:
                return row + index
            consumed += length
        return row + max(0, len(folds) - 1)

    def _logical_of_row(self, row: int) -> Offset:
        """Map a folded row to the logical position of its first cell."""
        folded_lines = self._buffer.folded_lines
        if not folded_lines:
            return Offset(0, 0)
        row = max(0, min(row, len(folded_lines) - 1))
        fold = folded_lines[row]
        return Offset(fold.offset, fold.line_no)

    # --- mode -------------------------------------------------------------

    def enter_select_mode(self) -> None:
        # Start where you are looking: the top-left cell of the viewport.
        self._select_cursor = self._clamp(self._logical_of_row(self.scroll_offset.y))
        self._select_anchor = None
        self._select_linewise = False
        self._select_desired_x = self._select_cursor.x
        self._select_pending_g = False
        # Stop following the output, or a chatty command drags the view away
        # from the cursor mid-selection.
        self._select_was_anchored = not self._anchor_released
        self.release_anchor()
        self.add_class('-selecting')
        self._publish_selection()
        self.border_subtitle = SELECT_SUBTITLE

    def exit_select_mode(self, copy: bool = False) -> None:
        text = None
        if copy and self._select_cursor is not None:
            if self._select_anchor is None:
                # No anchor yet: `y` yanks the cursor line, as `yy` would.
                text = self._line_text(self._select_cursor.y).rstrip()
            else:
                text = self.screen.get_selected_text()
        self._select_cursor = None
        self._select_anchor = None
        self._select_linewise = False
        self._select_pending_g = False
        self.remove_class('-selecting')
        self.screen.clear_selection()
        if self._select_was_anchored:
            self._anchor_released = False
        if text:
            self.app.copy_to_clipboard(text)

    def _publish_selection(self) -> None:
        cursor = self._select_cursor
        if cursor is None:
            return
        anchor = self._select_anchor
        if anchor is None:
            # The one-cell highlight *is* the cursor: the pane has no other way
            # to draw one, since the pty cursor sits wherever the command left it.
            selection = Selection(cursor, cursor + Offset(1, 0))
        elif self._select_linewise:
            top, bottom = sorted((anchor.y, cursor.y))
            selection = Selection(
                Offset(0, top), Offset(len(self._line_text(bottom)), bottom)
            )
        else:
            start, end = sorted([anchor, cursor], key=lambda offset: offset.transpose)
            # `Selection.extract` slices with an exclusive end, and the cell
            # under the cursor is part of the selection.
            selection = Selection(start, end + Offset(1, 0))
        self.screen.selections = {self: selection}

    def _toggle_anchor(self, linewise: bool) -> None:
        if self._select_anchor is not None and self._select_linewise == linewise:
            self._select_anchor = None
        else:
            if self._select_anchor is None:
                self._select_anchor = self._select_cursor
            self._select_linewise = linewise
        self._publish_selection()

    # --- motions ----------------------------------------------------------

    def _move_to(self, position: Offset, sticky: bool = True) -> None:
        self._select_cursor = self._clamp(position)
        if sticky:
            self._select_desired_x = self._select_cursor.x
        self._publish_selection()
        self._scroll_to_cursor()

    def _move_rows(self, delta: int) -> None:
        assert self._select_cursor is not None
        row = self._folded_row_of(self._select_cursor) + delta
        target = self._logical_of_row(row)
        self._move_to(Offset(max(target.x, self._select_desired_x), target.y), False)

    def _scroll_to_cursor(self) -> None:
        assert self._select_cursor is not None
        row = self._folded_row_of(self._select_cursor)
        top = self.scroll_offset.y
        height = max(1, self.scrollable_content_region.height)
        # `immediate`, because the default defers the scroll until after the next
        # refresh -- the cursor would then be drawn off-screen for a frame, and a
        # burst of motions would each be waiting on a repaint they caused.
        if row < top:
            self.scroll_to(y=row, animate=False, immediate=True)
        elif row >= top + height:
            self.scroll_to(y=row - height + 1, animate=False, immediate=True)

    def _word_move(self, forward: bool) -> None:
        cursor = self._select_cursor
        assert cursor is not None
        starts = [
            match.start() for match in _WORD_RE.finditer(self._line_text(cursor.y))
        ]
        if forward:
            following = [start for start in starts if start > cursor.x]
            if following:
                self._move_to(Offset(following[0], cursor.y))
            elif cursor.y + 1 < len(self._buffer.lines):
                self._move_to(Offset(0, cursor.y + 1))
        else:
            preceding = [start for start in starts if start < cursor.x]
            if preceding:
                self._move_to(Offset(preceding[-1], cursor.y))
            elif cursor.y > 0:
                previous = [
                    match.start()
                    for match in _WORD_RE.finditer(self._line_text(cursor.y - 1))
                ]
                self._move_to(Offset(previous[-1] if previous else 0, cursor.y - 1))

    # --- keys -------------------------------------------------------------

    def _handle_select_key(self, key: str, character: Optional[str]) -> None:
        cursor = self._select_cursor
        assert cursor is not None
        pending_g = self._select_pending_g
        self._select_pending_g = False
        last_line = max(0, len(self._buffer.lines) - 1)
        height = max(1, self.scrollable_content_region.height)
        token = character if character and character.isprintable() else key

        if pending_g and token == 'g':
            self._move_to(Offset(0, 0))
            return
        if key in _EXIT_KEYS:
            self.exit_select_mode()
            return
        if token in _COPY_KEYS or key in _COPY_KEYS:
            self.exit_select_mode(copy=True)
            return
        if token == 'v':
            self._toggle_anchor(linewise=False)
            return
        if token == 'V':
            self._toggle_anchor(linewise=True)
            return
        if token == 'g':
            self._select_pending_g = True
            return
        if token == 'G':
            self._move_to(Offset(self._select_desired_x, last_line), False)
            return
        if token == 'h' or key == 'left':
            self._move_to(cursor - Offset(1, 0))
            return
        if token == 'l' or key == 'right':
            self._move_to(cursor + Offset(1, 0))
            return
        if token == 'j' or key == 'down':
            self._move_to(Offset(self._select_desired_x, cursor.y + 1), False)
            return
        if token == 'k' or key == 'up':
            self._move_to(Offset(self._select_desired_x, cursor.y - 1), False)
            return
        if token == '0' or key == 'home':
            self._move_to(Offset(0, cursor.y))
            return
        if token == '$' or key == 'end':
            self._move_to(Offset(len(self._line_text(cursor.y)), cursor.y))
            return
        if token == '^':
            text = self._line_text(cursor.y)
            self._move_to(Offset(len(text) - len(text.lstrip()), cursor.y))
            return
        if token == 'w':
            self._word_move(forward=True)
            return
        if token == 'b':
            self._word_move(forward=False)
            return
        if key == 'ctrl+d':
            self._move_rows(height // 2)
            return
        if key == 'ctrl+u':
            self._move_rows(-(height // 2))
            return
        if key == 'pagedown':
            self._move_rows(height)
            return
        if key == 'pageup':
            self._move_rows(-height)

    def copy_all(self) -> None:
        """Copy the whole buffer, as logical (unwrapped) lines."""
        extracted = self.get_selection(Selection(None, None))
        text = _tidy(extracted[0]) if extracted else ''
        if not text:
            self.app.notify('Nothing to copy.', severity='warning')
            return
        self.app.copy_to_clipboard(text)
        count = len(text.split('\n'))
        self.app.notify(f'Copied {count} line{"" if count == 1 else "s"}.')

    async def on_key(self, event: events.Key) -> None:
        if self.in_select_mode:
            event.stop()
            event.prevent_default()
            self._handle_select_key(event.key, event.character)
            return
        if event.key == 'ctrl+y':
            event.stop()
            event.prevent_default()
            selected = self.screen.get_selected_text()
            if selected:
                self.app.copy_to_clipboard(selected)
                self.screen.clear_selection()
            else:
                self.copy_all()
            return
        if event.key == 'ctrl+v' and self.can_select():
            event.stop()
            event.prevent_default()
            self.enter_select_mode()
            return
        await super().on_key(event)

    def selection_updated(self, selection: Optional[Selection]) -> None:
        super().selection_updated(selection)
        if self.in_select_mode:
            self.border_subtitle = SELECT_SUBTITLE


class SelectableCommandPane(TerminalSelectMixin, CommandPane):
    """A `CommandPane` with keyboard selection and copy-all."""

    DEFAULT_CSS = """
    SelectableCommandPane.-selecting {
        border: solid $success;
    }
    """
