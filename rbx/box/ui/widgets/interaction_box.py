import asyncio
import pathlib
from typing import Optional

import rich.text
from textual import work
from textual.reactive import reactive

from rbx.box import testcase_utils
from rbx.box.ui.widgets.rich_log_box import RichLogBox

BATCH_SIZE = 1024


class InteractionBox(RichLogBox):
    DEFAULT_CSS = """
    InteractionBox {
        border: solid $accent;
        height: 1fr;
        width: 1fr;
    }
    """

    path: reactive[Optional[pathlib.Path]] = reactive(None)

    def on_mount(self):
        super().on_mount()
        self.auto_scroll = False
        self.can_focus = False

    @work(exclusive=True)
    async def _load_file(self, path: pathlib.Path):
        self.clear()
        path_str = str(path.relative_to(pathlib.Path.cwd()))
        self.border_subtitle = f'{path_str} (loading...)'

        interaction = await asyncio.to_thread(testcase_utils.parse_interaction, path)

        for entry in interaction.entries:
            if entry.pipe == 0:
                self.write(rich.text.Text(entry.data.rstrip(), style='green'))
            else:
                self.write(rich.text.Text(entry.data.rstrip()))

        self.border_subtitle = path_str

    async def watch_path(self, path: Optional[pathlib.Path]):
        self.clear()

        if path is None:
            self.border_subtitle = '(no file selected)'
            return

        if not path.is_file():
            path_str = str(path.relative_to(pathlib.Path.cwd()))
            self.border_subtitle = f'{path_str} (does not exist)'
            return

        self._load_file(path)
