from __future__ import annotations

from collections import defaultdict
from itertools import groupby
from operator import itemgetter
from typing import Optional

from rich import box
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.dom import DOMNode
from textual.widgets import Input, TextArea
from textual.widgets._key_panel import BindingsTable, KeyPanel


class _TitledBindingsTable(BindingsTable):
    """A ``BindingsTable`` that only renders titled binding groups.

    Textual's stock panel dumps *every* active binding, including the obvious
    built-in navigation the focused widget and the screen contribute (arrow
    keys, page up/down, enter, tab, copy). Those namespaces declare no
    ``BINDING_GROUP_TITLE``, so we skip them entirely and keep only the groups
    we deliberately titled: our screens plus the app-level ``Global`` section.

    Adapted from
    ``textual.widgets._key_panel.BindingsTable.render_bindings_table`` (textual
    8.0.0); the sole behavioral change is the ``continue`` that drops untitled
    namespaces.
    """

    def render_bindings_table(self) -> Table:
        bindings = self.screen.active_bindings.values()

        key_style = self.get_component_rich_style('bindings-table--key')
        divider_transparent = (
            self.get_component_styles('bindings-table--divider').color.a == 0
        )
        table = Table(
            padding=(0, 0),
            show_header=False,
            box=box.SIMPLE if divider_transparent else box.HORIZONTALS,
            border_style=self.get_component_rich_style('bindings-table--divider'),
        )
        table.add_column('', justify='right')

        header_style = self.get_component_rich_style('bindings-table--header')
        description_style = self.get_component_rich_style('bindings-table--description')

        def render_description(binding: Binding) -> Text:
            """Render description text from a binding."""
            text = Text.from_markup(
                binding.description, end='', style=description_style
            )
            if binding.tooltip:
                if binding.description:
                    text.append(' ')
                text.append(binding.tooltip, 'dim')
            return text

        get_key_display = self.app.get_key_display
        previous_namespace: object = None
        for namespace, _bindings in groupby(bindings, key=itemgetter(0)):
            table_bindings = list(_bindings)
            if not table_bindings:
                continue
            if not namespace.BINDING_GROUP_TITLE:
                # Skip untitled namespaces (built-in widget/screen navigation).
                continue

            title = Text(namespace.BINDING_GROUP_TITLE, end='')
            title.stylize(header_style)
            table.add_row('', title)

            action_to_bindings: defaultdict[str, list[tuple[Binding, bool, str]]]
            action_to_bindings = defaultdict(list)
            for _, binding, enabled, tooltip in table_bindings:
                if not binding.system:
                    action_to_bindings[binding.action].append(
                        (binding, enabled, tooltip)
                    )

            for multi_bindings in action_to_bindings.values():
                binding = multi_bindings[0][0]
                keys_display = ' '.join(
                    dict.fromkeys(  # Remove duplicates while preserving order
                        get_key_display(binding) for binding, _, _ in multi_bindings
                    )
                )
                table.add_row(
                    Text(keys_display, style=key_style),
                    render_description(binding),
                )
            if namespace != previous_namespace:
                table.add_section()

            previous_namespace = namespace

        return table


class RbxHelpPanel(KeyPanel):
    """The ``?`` help panel: a ``KeyPanel`` that hides untitled binding groups."""

    def compose(self) -> ComposeResult:
        yield _TitledBindingsTable(shrink=True, expand=False)


class HelpPanelMixin(DOMNode):
    """Adds a ``?`` binding that toggles the rbx help panel.

    Lives at the app level (like ``VimNavMixin``) so the binding is available on
    every screen and shows up in the footer everywhere. The ``check_action``
    guard disables it while a text-editing widget is focused, so ``?`` still
    types literally into a focused ``Input``/``TextArea``.

    The panel is ``RbxHelpPanel`` (a ``KeyPanel`` subclass) rather than Textual's
    stock ``HelpPanel`` so it can hide the obvious built-in navigation bindings
    that have no ``BINDING_GROUP_TITLE``.

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
        existing = self.screen.query(RbxHelpPanel)
        if existing:
            existing.remove()
        else:
            self.screen.mount(RbxHelpPanel())
