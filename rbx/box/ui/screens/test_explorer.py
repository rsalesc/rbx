from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, RichLog

from rbx import console
from rbx.box import package, visualizers
from rbx.box.exception import RbxException
from rbx.box.schema import TaskType, Testcase
from rbx.box.testcase_extractors import (
    GenerationTestcaseEntry,
    extract_generation_testcases_from_groups,
    get_testcase_metadata_markup,
)
from rbx.box.ui.utils.run_ui import get_entries_options
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
        ('v', 'open_visualizer', 'Open visualization'),
    ]

    _option_entries: List[Optional[GenerationTestcaseEntry]]

    def __init__(self):
        super().__init__()
        self._option_entries = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Horizontal(id='test-explorer'):
            with Vertical(id='test-list-container'):
                yield OptionList(id='test-list')
            with Vertical(id='test-details'):
                yield RichLogBox(id='test-box-warning')
                yield FileLog(id='test-input')
                yield TestBoxWidget(id='test-output')
                yield RichLogBox(id='test-metadata')

    async def on_mount(self):
        self.query_one('#test-list').border_title = 'Tests'
        self.query_one('#test-input').border_title = 'Input'

        warning_box = self.query_one('#test-box-warning', RichLogBox)
        warning_box.markup = True
        warning_box.wrap = True
        if not self._is_interactive():
            warning_box.display = False
        else:
            warning_box.write(
                console.expand_markup(
                    '[warning]This is an interactive problem.\n'
                    'Interactions are not captured by default. Use the [item]rbx -cp ...[/item] flag when running to capture them.[/warning]'
                )
            )
            warning_box.display = True

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

    def _is_interactive(self) -> bool:
        return package.find_problem_package_or_die().type == TaskType.COMMUNICATION

    def _update_selected_test(self, index: Optional[int]):
        input = self.query_one('#test-input', FileLog)
        output = self.query_one('#test-output', TestBoxWidget)
        metadata = self.query_one('#test-metadata', RichLog)

        if index is None:
            input.path = None
            output.reset()
            metadata.clear().write('No test selected')
            return
        entry = self._option_entries[index]
        if entry is None:
            return
        input.path = entry.metadata.copied_to.inputPath

        assert entry.metadata.copied_to.outputPath is not None
        output.data = TestcaseRenderingData.from_one_path(
            entry.metadata.copied_to.outputPath
        )

        metadata.clear()
        metadata.write(console.expand_markup(get_testcase_metadata_markup(entry)))

    async def _update_tests(self):
        self.watch(
            self.query_one('#test-list', OptionList),
            'highlighted',
            self._update_selected_test,
        )

        entries = await extract_generation_testcases_from_groups()
        options, self._option_entries = get_entries_options(entries)

        option_list = self.query_one('#test-list', OptionList)
        option_list.clear_options()
        option_list.add_options(options)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        event.stop()

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

    async def action_open_visualizer(self):
        input_path = self.query_one('#test-input', FileLog).path
        if input_path is None:
            self.app.notify('No test selected', severity='error')
            return
        try:
            await visualizers.run_ui_input_visualizer_for_testcase(
                Testcase(
                    inputPath=input_path,
                    outputPath=self.query_one(
                        '#test-output', TestBoxWidget
                    ).data.output_path,
                )
            )
        except RbxException as e:
            self.app.notify(e.plain(), severity='error', markup=False)
