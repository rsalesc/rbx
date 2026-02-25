from __future__ import annotations

from dataclasses import dataclass
from typing import List, NamedTuple, Optional

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Label, ListItem, ListView


class MenuItem(NamedTuple):
    """An entry in a Menu."""

    description: str
    action: str
    key: Optional[str] = None


class _MenuOptionLabel(Label):
    ALLOW_SELECT = False


class MenuOption(ListItem):
    ALLOW_SELECT = False

    def __init__(self, description: str, key: Optional[str]) -> None:
        self._description = description
        self._key = key
        super().__init__()

    def compose(self) -> ComposeResult:
        yield _MenuOptionLabel(self._key or ' ', id='key')
        yield _MenuOptionLabel(self._description, id='description')


class Menu(ListView, can_focus=True):
    BINDINGS = [Binding('escape', 'dismiss', 'Dismiss')]

    DEFAULT_CSS = """
    Menu {
        width: auto;
        height: auto;
        max-width: 100%;
        overlay: screen;
        position: absolute;
        color: $foreground;
        background: $panel;
        border: round $accent;
        constrain: inside inside;
        padding: 0;

        & > MenuOption {
            layout: horizontal;
            width: 1fr;
            padding: 0 1;
            height: auto !important;
            overflow: auto;
            #description {
                color: $text 80%;
                width: 1fr;
            }
            #key {
                padding-right: 1;
                text-style: bold;
            }
        }

        &:blur {
            background-tint: transparent;
            & > ListItem.-highlight {
                color: $block-cursor-blurred-foreground;
                background: $block-cursor-blurred-background 30%;
                text-style: $block-cursor-blurred-text-style;
            }
        }

        &:focus {
            background-tint: transparent;
            & > ListItem.-highlight {
                color: $block-cursor-blurred-foreground;
                background: $block-cursor-blurred-background;
                text-style: $block-cursor-blurred-text-style;
            }
        }
    }
    """

    @dataclass
    class OptionSelected(Message):
        menu: Menu
        action: str

    @dataclass
    class Dismissed(Message):
        menu: Menu

    def __init__(self, options: List[MenuItem], *args, **kwargs) -> None:
        self._options = options
        self._dismissed = False
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        self.extend(MenuOption(item.description, item.key) for item in self._options)

    async def _activate_index(self, index: int) -> None:
        if self._dismissed or index < 0 or index >= len(self._options):
            return
        action = self._options[index].action
        self.post_message(self.OptionSelected(self, action))

    def _dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.post_message(self.Dismissed(self))

    async def action_dismiss(self) -> None:
        self._dismiss()

    async def on_blur(self) -> None:
        self._dismiss()

    @on(events.Key)
    async def _on_key(self, event: events.Key) -> None:
        for index, option in enumerate(self._options):
            if option.key is not None and event.key == option.key:
                self.index = index
                event.stop()
                await self._activate_index(index)
                break

    @on(ListView.Selected)
    async def _on_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if event.index is not None:
            await self._activate_index(event.index)
