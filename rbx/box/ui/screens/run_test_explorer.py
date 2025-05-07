from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView

from rbx.box.solutions import SolutionReportSkeleton, SolutionSkeleton
from rbx.box.testcase_extractors import (
    GenerationTestcaseEntry,
    extract_generation_testcases,
)
from rbx.box.ui.widgets.file_log import FileLog
from rbx.box.ui.widgets.test_output_box import TestBoxWidget, TestcaseRenderingData


class RunTestExplorerScreen(Screen):
    BINDINGS = [
        ('q', 'app.pop_screen', 'Quit'),
        ('1', 'show_output', 'Show output'),
        ('2', 'show_stderr', 'Show stderr'),
        ('3', 'show_log', 'Show log'),
        ('m', 'toggle_metadata', 'Toggle metadata'),
    ]

    def __init__(self, skeleton: SolutionReportSkeleton, solution: SolutionSkeleton):
        super().__init__()
        self.skeleton = skeleton
        self.solution = solution
        self._entries: List[GenerationTestcaseEntry] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Horizontal(id='test-explorer'):
            with Vertical(id='test-list-container'):
                yield ListView(id='test-list')
            with Vertical(id='test-details'):
                yield FileLog(id='test-input')
                yield TestBoxWidget(id='test-output')

    async def on_mount(self):
        self.query_one('#test-list').border_title = 'Tests'
        self.query_one('#test-input').border_title = 'Input'

        await self._update_tests()

    def _update_selected_test(self, index: Optional[int]):
        input = self.query_one('#test-input', FileLog)
        output = self.query_one('#test-output', TestBoxWidget)

        if index is None:
            input.path = None
            output.reset()
            return
        entry = self._entries[index]
        input.path = entry.metadata.copied_to.inputPath

        output.data = TestcaseRenderingData.from_one_path(
            self.solution.get_entry_prefix(entry.group_entry)
        )

    async def _update_tests(self):
        self.watch(
            self.query_one('#test-list', ListView),
            'index',
            self._update_selected_test,
        )

        self._entries = await extract_generation_testcases(self.skeleton.entries)

        test_names = [
            f'{entry.group_entry.group}/{entry.group_entry.index}'
            for entry in self._entries
        ]

        await self.query_one('#test-list', ListView).clear()
        await self.query_one('#test-list', ListView).extend(
            [ListItem(Label(name)) for name in test_names]
        )

    def action_show_output(self):
        self.query_one('#test-output', TestBoxWidget).show_output()

    def action_show_stderr(self):
        self.query_one('#test-output', TestBoxWidget).show_stderr()

    def action_show_log(self):
        self.query_one('#test-output', TestBoxWidget).show_log()

    def action_toggle_metadata(self):
        self.query_one('#test-output', TestBoxWidget).toggle_metadata()
