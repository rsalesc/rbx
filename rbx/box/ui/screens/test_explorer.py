from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, RichLog

from rbx.box import package
from rbx.box.schema import TaskType
from rbx.box.testcase_extractors import (
    GenerationTestcaseEntry,
    extract_generation_testcases_from_groups,
)
from rbx.box.ui.utils.run_ui import get_metadata_markup
from rbx.box.ui.widgets.file_log import FileLog
from rbx.box.ui.widgets.rich_log_box import RichLogBox
from rbx.box.ui.widgets.test_output_box import TestBoxWidget, TestcaseRenderingData


class TestExplorerScreen(Screen):
    BINDINGS = [
        ('q', 'app.pop_screen', 'Quit'),
        ('m', 'toggle_metadata', 'Toggle metadata'),
        ('1', 'show_output', 'Show output'),
        ('2', 'show_stderr', 'Show stderr'),
        ('3', 'show_log', 'Show log'),
    ]

    def __init__(self):
        super().__init__()
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
                yield RichLogBox(id='test-metadata')

    async def on_mount(self):
        self.query_one('#test-list').border_title = 'Tests'
        self.query_one('#test-input').border_title = 'Input'

        # Ensure either output or interaction is visible.
        self.action_show_output()

        metadata = self.query_one('#test-metadata', RichLogBox)
        metadata.display = False
        metadata.border_title = 'Metadata'
        metadata.wrap = True
        metadata.markup = True
        metadata.clear().write('No test selected')
        await self._update_tests()

    def action_toggle_metadata(self):
        metadata = self.query_one('#test-metadata', RichLogBox)
        metadata.display = not metadata.display

    def _update_selected_test(self, index: Optional[int]):
        input = self.query_one('#test-input', FileLog)
        output = self.query_one('#test-output', TestBoxWidget)
        metadata = self.query_one('#test-metadata', RichLog)

        if index is None:
            input.path = None
            output.reset()
            metadata.clear().write('No test selected')
            return
        entry = self._entries[index]
        input.path = entry.metadata.copied_to.inputPath

        assert entry.metadata.copied_to.outputPath is not None
        output.data = TestcaseRenderingData.from_one_path(
            entry.metadata.copied_to.outputPath
        )

        metadata.clear()
        metadata.write(get_metadata_markup(entry))

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

    def is_interactive(self) -> bool:
        pkg = package.find_problem_package_or_die()
        return pkg.type == TaskType.COMMUNICATION

    def action_show_output(self):
        if self.is_interactive():
            self.query_one('#test-output', TestBoxWidget).show_interaction()
        else:
            self.query_one('#test-output', TestBoxWidget).show_output()

    def action_show_stderr(self):
        self.query_one('#test-output', TestBoxWidget).show_stderr()

    def action_show_log(self):
        self.query_one('#test-output', TestBoxWidget).show_log()
