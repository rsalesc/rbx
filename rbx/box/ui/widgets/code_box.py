import pathlib
from typing import Optional

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog


def detect_language(path: pathlib.Path) -> str:
    ext = path.suffix.lower().lstrip('.')
    if ext in {'py', 'pyw'}:
        return 'python'
    if ext in {'cpp', 'cc', 'cxx', 'hpp', 'hxx', 'h'}:
        return 'cpp'
    if ext in {'java'}:
        return 'java'
    if ext in {'kt', 'kts'}:
        return 'kotlin'
    if ext in {
        'json',
        'yml',
        'yaml',
        'toml',
        'ini',
        'md',
        'sh',
        'bash',
        'zsh',
        'js',
        'ts',
    }:
        return ext
    return 'text'


class CodeBox(Widget, can_focus=False):
    path: reactive[Optional[pathlib.Path]] = reactive(None)

    def __init__(self):
        super().__init__()

    def compose(self) -> ComposeResult:
        log = RichLog()
        log.border_title = 'Review'
        yield log

    async def watch_path(self, path: Optional[pathlib.Path]):
        log = self.query_one(RichLog)
        log.clear()
        if path is None:
            return
        code = path.read_text()
        lang = detect_language(path)
        md = Markdown(f'```{lang}\n{code}\n```', code_theme='monokai')
        log.write(md)
