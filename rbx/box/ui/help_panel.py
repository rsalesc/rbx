from __future__ import annotations

from typing import Optional

from textual.binding import Binding
from textual.dom import DOMNode
from textual.widgets import HelpPanel, Input, TextArea


class HelpPanelMixin(DOMNode):
    """Adds a ``?`` binding that toggles Textual's built-in help panel.

    Lives at the app level (like ``VimNavMixin``) so the binding is available on
    every screen and shows up in the footer everywhere. The ``check_action``
    guard disables it while a text-editing widget is focused, so ``?`` still
    types literally into a focused ``Input``/``TextArea``.

    Subclasses ``DOMNode`` so Textual's ``_merge_bindings`` collects ``BINDINGS``
    when the mixin is combined with an ``App``.
    """

    BINDINGS = [
        Binding('question_mark', 'toggle_help_panel', 'Help', show=True),
    ]

    def check_action(
        self, action: str, parameters: tuple[object, ...]
    ) -> Optional[bool]:
        if action == 'toggle_help_panel':
            if isinstance(self.focused, (Input, TextArea)):
                # Returning None disables the binding and lets '?' type into
                # the focused text widget.
                return None
        return super().check_action(action, parameters)

    def action_toggle_help_panel(self) -> None:
        if self.screen.query(HelpPanel):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()
