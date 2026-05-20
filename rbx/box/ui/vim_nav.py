from __future__ import annotations

import inspect
from typing import Optional

from textual.binding import Binding
from textual.dom import DOMNode
from textual.widgets import Input, TextArea

# Maps a logical direction to (cursor action, scroll fallback action).
_DIRECTION_ACTIONS = {
    'down': ('cursor_down', 'scroll_down'),
    'up': ('cursor_up', 'scroll_up'),
    'left': ('cursor_left', 'scroll_left'),
    'right': ('cursor_right', 'scroll_right'),
}


class VimNavMixin(DOMNode):
    """Adds Vim-style hjkl navigation as an app-level fallback.

    Maps h/j/k/l onto the focused widget's existing ``cursor_*`` actions, falling
    back to ``scroll_*``. The bindings live at the app level (the last link in
    Textual's binding chain), so any widget that binds these letters wins. They are
    disabled while a text-editing widget is focused, so typing is never hijacked.

    Subclasses ``DOMNode`` so Textual's ``_merge_bindings`` (which only collects
    ``BINDINGS`` from ``DOMNode`` subclasses in the MRO) picks up the hjkl bindings
    when the mixin is combined with an ``App`` or ``Screen``.
    """

    BINDINGS = [
        Binding('j', 'vim_move("down")', 'Down', show=False),
        Binding('k', 'vim_move("up")', 'Up', show=False),
        Binding('h', 'vim_move("left")', 'Left', show=False),
        Binding('l', 'vim_move("right")', 'Right', show=False),
    ]

    def check_action(self, action: str, parameters: tuple) -> Optional[bool]:
        if action == 'vim_move':
            focused = self.focused
            if focused is None or isinstance(focused, (Input, TextArea)):
                # Returning None disables the binding and lets the key fall through
                # (e.g. so it types into a focused Input).
                return None
        return super().check_action(action, parameters)

    async def action_vim_move(self, direction: str) -> None:
        focused = self.focused
        if focused is None:
            return
        cursor_action, scroll_action = _DIRECTION_ACTIONS[direction]
        method = getattr(focused, f'action_{cursor_action}', None)
        if method is None:
            method = getattr(focused, f'action_{scroll_action}', None)
        if method is None:
            return
        result = method()
        if inspect.isawaitable(result):
            await result
