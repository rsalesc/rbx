from typing import Optional

import rich.text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import RichLog


class ErrorModal(ModalScreen[None]):
    """Dismissible, scrollable modal that shows a formatted error message.

    Used by ``rbxBaseApp.show_error`` to surface ``RbxException`` output (e.g.
    a visualizer's compile/runtime failure) in full. Unlike a toast
    notification it preserves the captured ANSI styling and never truncates --
    the inner ``RichLog`` wraps long lines and scrolls when focused.
    """

    BINDINGS = [
        ('q', 'app.pop_screen', 'Close'),
        ('escape', 'app.pop_screen', 'Close'),
    ]

    def __init__(self, content: rich.text.Text, title: Optional[str] = 'Error'):
        super().__init__()
        self.content_text = content
        self._title = title

    def compose(self) -> ComposeResult:
        with Container(id='error-dialog'):
            log = RichLog(markup=False, wrap=True)
            if self._title:
                log.border_title = self._title
            yield log

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        log.write(self.content_text)
        log.focus()
