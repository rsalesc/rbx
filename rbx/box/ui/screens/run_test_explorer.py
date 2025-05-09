from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView

from rbx.box import package
from rbx.box.solutions import SolutionReportSkeleton, SolutionSkeleton
from rbx.box.testcase_extractors import (
    GenerationTestcaseEntry,
    extract_generation_testcases,
)
from rbx.box.ui.utils.run_ui import (
    get_run_testcase_markup,
    get_run_testcase_metadata_markup,
)
from rbx.box.ui.widgets.file_log import FileLog
from rbx.box.ui.widgets.test_output_box import TestcaseRenderingData
from rbx.box.ui.widgets.two_sided_test_output_box import TwoSidedTestBoxWidget


class RunTestExplorerScreen(Screen):
    BINDINGS = [
        ('q', 'app.pop_screen', 'Quit'),
        ('1', 'show_output', 'Show output'),
        ('2', 'show_stderr', 'Show stderr'),
        ('3', 'show_log', 'Show log'),
        ('m', 'toggle_metadata', 'Toggle metadata'),
        ('s', 'toggle_side_by_side', 'Toggle sxs'),
    ]

    side_by_side: reactive[bool] = reactive(False)
    diff_with_data: reactive[Optional[TestcaseRenderingData]] = reactive(
        default=None,
    )

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
                yield TwoSidedTestBoxWidget(id='test-output')

    async def on_mount(self):
        self.query_one('#test-list').border_title = 'Tests'
        self.query_one('#test-input').border_title = 'Input'

        await self._update_tests()

    def _update_selected_test(self, index: Optional[int]):
        input = self.query_one('#test-input', FileLog)
        output = self.query_one('#test-output', TwoSidedTestBoxWidget)

        if index is None:
            input.path = None
            output.reset()
            return
        entry = self._entries[index]
        input.path = entry.metadata.copied_to.inputPath

        rendering_data = TestcaseRenderingData.from_one_path(
            self.solution.get_entry_prefix(entry.group_entry)
        )
        rendering_data.rich_content = get_run_testcase_metadata_markup(
            self.skeleton, self.solution, entry.group_entry
        )
        output.data = rendering_data

        self.diff_with_data = TestcaseRenderingData.from_one_path(
            entry.group_entry.get_prefix_path()
        )

    async def _update_tests(self):
        self.watch(
            self.query_one('#test-list', ListView),
            'index',
            self._update_selected_test,
        )

        self._entries = await extract_generation_testcases(self.skeleton.entries)

        test_markups = [
            get_run_testcase_markup(self.solution, entry.group_entry)
            for entry in self._entries
        ]

        await self.query_one('#test-list', ListView).clear()
        await self.query_one('#test-list', ListView).extend(
            [ListItem(Label(name, markup=True)) for name in test_markups]
        )

    def has_diffable_solution(self) -> bool:
        return package.get_main_solution() is not None

    def action_show_output(self):
        self.query_one('#test-output', TwoSidedTestBoxWidget).show_output()

    def action_show_stderr(self):
        self.query_one('#test-output', TwoSidedTestBoxWidget).show_stderr()

    def action_show_log(self):
        self.query_one('#test-output', TwoSidedTestBoxWidget).show_log()

    def action_toggle_metadata(self):
        self.query_one('#test-output', TwoSidedTestBoxWidget).toggle_metadata()

    def action_toggle_side_by_side(self):
        self.side_by_side = not self.side_by_side

    def watch_side_by_side(self, side_by_side: bool):
        widget = self.query_one('#test-output', TwoSidedTestBoxWidget)

        if side_by_side:
            if not self.has_diffable_solution():
                self.app.notify(
                    'Found no solution to compare against', severity='error'
                )
                return
            widget.diff_with_data = self.diff_with_data
        else:
            widget.diff_with_data = None

    def watch_diff_with_data(self, diff_with_data: Optional[TestcaseRenderingData]):
        if not self.has_diffable_solution():
            return
        if not self.side_by_side:
            return
        widget = self.query_one('#test-output', TwoSidedTestBoxWidget)
        widget.diff_with_data = diff_with_data
