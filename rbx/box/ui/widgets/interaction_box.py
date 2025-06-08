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

    def _show_raw_text(self, path: pathlib.Path):
        path_str = str(path.relative_to(pathlib.Path.cwd()))
        self.write(
            rich.text.Text(
                'Showing raw interaction file because the interaction text is not parseable.\n'
                'This might usually happen when the processes do not communicate properly.\n',
                style='red',
            )
        )
        self.write(rich.text.Text(path.read_text()))
        self.border_subtitle = f'{path_str} (raw file)'

    @work(exclusive=True)
    async def _load_file(self, path: pathlib.Path):
        self.clear()
        path_str = str(path.relative_to(pathlib.Path.cwd()))
        self.border_subtitle = f'{path_str} (loading...)'

        try:
            interaction = await asyncio.to_thread(
                testcase_utils.parse_interaction, path
            )
        except testcase_utils.TestcaseInteractionParsingError:
            self._show_raw_text(path)
            return

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
