import difflib
import pathlib
from typing import Optional, Tuple

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog


def compute_diff(file1: pathlib.Path, file2: pathlib.Path) -> str:
    lines1 = file1.read_text().splitlines(keepends=True)
    lines2 = file2.read_text().splitlines(keepends=True)
    return ''.join(difflib.ndiff(lines1, lines2))


class DiffBox(Widget, can_focus=False):
    paths: reactive[Optional[Tuple[pathlib.Path, pathlib.Path]]] = reactive(None)

    def __init__(self):
        super().__init__()

    def compose(self) -> ComposeResult:
        md = RichLog()
        md.border_title = 'Differ'
        yield md

    async def watch_paths(self, paths: Optional[Tuple[pathlib.Path, pathlib.Path]]):
        log = self.query_one(RichLog)
        log.clear()
        if paths is None:
            return
        file1, file2 = paths
        md = Markdown(
            f'```diff\n{compute_diff(file1, file2)}\n```', code_theme='monokai'
        )
        log.write(md)
