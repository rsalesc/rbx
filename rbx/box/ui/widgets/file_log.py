import pathlib
from typing import Optional

import aiofiles
from textual import work
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Log

BATCH_SIZE = 1024


class FileLog(Widget, can_focus=False):
    DEFAULT_CSS = """
    FileLog {
        border: solid $accent;
        height: 1fr;
        width: 1fr;
    }
    """

    path: reactive[Optional[pathlib.Path]] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Log()

    def on_mount(self):
        self.query_one(Log).auto_scroll = False
        self.query_one(Log).can_focus = False

    @work(exclusive=True)
    async def _load_file(self, path: pathlib.Path):
        log = self.query_one(Log)
        log.clear()
        path_str = str(path.relative_to(pathlib.Path.cwd()))
        self.border_subtitle = f'{path_str} (loading...)'

        async with aiofiles.open(path, 'r') as f:
            batch = []
            async for line in f:
                batch.append(line)
                if len(batch) >= BATCH_SIZE:
                    log.write(''.join(batch))
                    batch = []

            if batch:
                log.write(''.join(batch))

        self.border_subtitle = path_str

    async def watch_path(self, path: Optional[pathlib.Path]):
        log = self.query_one(Log)
        log.clear()

        if path is None:
            self.border_subtitle = '(no file selected)'
            return

        if not path.is_file():
            path_str = str(path.relative_to(pathlib.Path.cwd()))
            self.border_subtitle = f'{path_str} (does not exist)'
            return

        self._load_file(path)
