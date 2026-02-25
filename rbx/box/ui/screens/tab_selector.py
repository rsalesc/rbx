from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, SelectionList
from textual.widgets.selection_list import Selection


class TabSelectorModal(ModalScreen[Optional[List[int]]]):
    BINDINGS = [
        ('escape', 'cancel', 'Cancel'),
        ('c', 'confirm', 'Confirm'),
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
            yield Label(
                '[b]c[/b] confirm  [b]esc[/b] cancel  '
                '[b]a[/b] select all  [b]n[/b] deselect all',
                id='tab-selector-hints',
            )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_confirm(self) -> None:
        selected = list(self.query_one('#tab-selector-list', SelectionList).selected)
        self.dismiss(selected)

    def action_select_all(self) -> None:
        self.query_one('#tab-selector-list', SelectionList).select_all()

    def action_deselect_all(self) -> None:
        self.query_one('#tab-selector-list', SelectionList).deselect_all()
