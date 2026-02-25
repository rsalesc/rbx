from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, SelectionList
from textual.widgets.selection_list import Selection


class TabSelectorModal(ModalScreen[Optional[List[int]]]):
    BINDINGS = [
        ('escape', 'cancel', 'Cancel'),
        ('a', 'select_all', 'Select all'),
        ('n', 'deselect_all', 'Deselect all'),
    ]

    def __init__(self, tab_names: List[str]) -> None:
        super().__init__()
        self._tab_names = tab_names

    def compose(self) -> ComposeResult:
        with Container(id='tab-selector-dialog'):
            selection_list = SelectionList[int](
                *[
                    Selection(name, index, False)
                    for index, name in enumerate(self._tab_names)
                ],
                id='tab-selector-list',
            )
            selection_list.border_title = 'Select tabs'
            yield selection_list
            with Horizontal(id='tab-selector-buttons'):
                yield Button('Run', variant='primary', id='tab-selector-run')
                yield Button('Cancel', id='tab-selector-cancel')

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select_all(self) -> None:
        self.query_one('#tab-selector-list', SelectionList).select_all()

    def action_deselect_all(self) -> None:
        self.query_one('#tab-selector-list', SelectionList).deselect_all()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'tab-selector-run':
            selected = list(
                self.query_one('#tab-selector-list', SelectionList).selected
            )
            self.dismiss(selected)
        elif event.button.id == 'tab-selector-cancel':
            self.dismiss(None)
