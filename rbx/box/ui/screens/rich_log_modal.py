from typing import Optional

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen

from rbx.box.ui.widgets.rich_log_box import RichLogBox


class RichLogModal(ModalScreen[None]):
    BINDINGS = [
        ('q', 'app.pop_screen', 'Close'),
        ('g', 'app.pop_screen', 'Close'),
    ]

    def __init__(self, log: str, title: Optional[str] = None):
        super().__init__()
        self._log = log
        self._title = title

    def compose(self) -> ComposeResult:
        with Container(id='rich-dialog'):
            box = RichLogBox(markup=True)
            if self._title:
                box.border_title = self._title
            yield box

    async def on_mount(self):
        self.query_one(RichLogBox).write(self._log)
