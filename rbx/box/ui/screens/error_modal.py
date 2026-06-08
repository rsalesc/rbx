from typing import Optional

import rich.text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, RichLog


class ErrorModal(ModalScreen[None]):
    """Dismissible, scrollable modal that shows a formatted error message.

    Used by ``rbxBaseApp.show_error`` to surface ``RbxException`` output (e.g.
    a visualizer's compile/runtime failure, or an invalid problem/env YAML) in
    full. Unlike a toast notification it preserves the captured ANSI styling and
    never truncates -- the inner ``RichLog`` wraps long lines and scrolls when
    focused. A hint line shows how to dismiss it.
    """

    BINDINGS = [
        ('q', 'app.pop_screen', 'Close'),
        ('escape', 'app.pop_screen', 'Close'),
    ]

    DEFAULT_CSS = """
    ErrorModal {
        align: center middle;
    }
    ErrorModal #error-dialog {
        max-width: 100;
        width: 90%;
        height: auto;
        max-height: 90%;
    }
    ErrorModal #error-dialog RichLog {
        border: solid $error;
        border-title-color: $error;
        padding: 0 1;
        height: auto;
        max-height: 85%;
    }
    ErrorModal #error-hints {
        width: 1fr;
        text-align: center;
        color: $text-muted;
    }
    """

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
            yield Label('Press [b]q[/b] or [b]esc[/b] to close', id='error-hints')

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        log.write(self.content_text)
        log.focus()
