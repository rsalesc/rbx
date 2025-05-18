from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView


class SelectorScreen(ModalScreen[int]):
    BINDINGS = [('q', 'cancel', 'Cancel')]

    def __init__(self, options: List[ListItem], title: Optional[str] = None):
        super().__init__()
        self.options = options
        self.title = title

    def compose(self) -> ComposeResult:
        with Container(id='selector-dialog'):
            list_view = ListView(*self.options)
            if self.title:
                list_view.border_title = self.title
            yield list_view

    def on_list_view_selected(self, event: ListView.Selected):
        self.dismiss(event.list_view.index)

    def action_cancel(self):
        self.dismiss(None)
