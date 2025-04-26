from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView

from rbx.box.testcase_extractors import (
    GenerationTestcaseEntry,
    extract_generation_testcases_from_groups,
)
from rbx.box.ui.widgets.file_log import FileLog


class TestExplorerScreen(Screen):
    BINDINGS = [('q', 'app.pop_screen', 'Quit')]

    def __init__(self):
        super().__init__()
        self._entries: List[GenerationTestcaseEntry] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Horizontal(id='test-explorer'):
            yield ListView(id='test-list')
            with Vertical(id='test-details'):
                yield FileLog(id='test-input')
                yield FileLog(id='test-output')

    async def on_mount(self):
        self.query_one('#test-list').border_title = 'Tests'
        self.query_one('#test-input').border_title = 'Input'
        self.query_one('#test-output').border_title = 'Output'

        await self._update_tests()

    def _update_selected_test(self, index: Optional[int]):
        if index is None:
            self.query_one('#test-input', FileLog).path = None
            self.query_one('#test-output', FileLog).path = None
            return
        entry = self._entries[index]
        self.query_one('#test-input', FileLog).path = entry.metadata.copied_to.inputPath
        self.query_one(
            '#test-output', FileLog
        ).path = entry.metadata.copied_to.outputPath

    async def _update_tests(self):
        self.watch(
            self.query_one('#test-list', ListView),
            'index',
            self._update_selected_test,
        )

        self._entries = await extract_generation_testcases_from_groups()

        test_names = [
            f'{entry.group_entry.group}/{entry.group_entry.index}'
            for entry in self._entries
        ]

        await self.query_one('#test-list', ListView).clear()
        await self.query_one('#test-list', ListView).extend(
            [ListItem(Label(name)) for name in test_names]
        )
