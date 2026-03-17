from typing import Optional, Sequence, Union

from rich.console import RenderableType
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList
from textual.widgets.option_list import Option


class SelectorScreen(ModalScreen[int]):
    BINDINGS = [('q', 'cancel', 'Cancel')]

    def __init__(
        self,
        options: Sequence[Union[str, RenderableType, Option, None]],
        title: Optional[str] = None,
    ):
        super().__init__()
        self.options = options
        self.modal_title = title

    def compose(self) -> ComposeResult:
        with Container(id='selector-dialog'):
            option_list = OptionList(*self.options)
            if self.modal_title:
                option_list.border_title = self.title
            yield option_list

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        event.stop()
        self.dismiss(event.option_index)

    def action_cancel(self):
        self.dismiss(None)
