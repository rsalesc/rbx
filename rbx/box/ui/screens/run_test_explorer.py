import pathlib
from typing import Any, List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList

from rbx import console
from rbx.box import package, visualizers
from rbx.box.exception import RbxException
from rbx.box.schema import TaskType, Testcase
from rbx.box.solutions import SolutionReportSkeleton, SolutionSkeleton
from rbx.box.testcase_extractors import (
    GenerationTestcaseEntry,
    get_testcase_metadata_markup,
)
from rbx.box.ui.screens.test_list_search import EntryPredicate, TestListSearchMixin
from rbx.box.ui.utils.run_ui import (
    get_entries_options,
    get_run_testcase_metadata_markup,
    get_solution_evals,
    is_main_solution,
)
from rbx.box.ui.widgets.file_log import FileLog
from rbx.box.ui.widgets.rich_log_box import RichLogBox
from rbx.box.ui.widgets.test_output_box import TestcaseRenderingData
from rbx.box.ui.widgets.two_sided_test_output_box import TwoSidedTestBoxWidget
from rbx.grading.steps import Outcome


class RunTestExplorerScreen(TestListSearchMixin, Screen):
    BINDING_GROUP_TITLE = 'Run Test Explorer'
    BINDINGS = [
        ('q', 'app.pop_screen', 'Quit'),
        Binding('1', 'show_output', 'Show output', show=False),
        Binding('2', 'show_stderr', 'Show stderr', show=False),
        Binding('3', 'show_log', 'Show log', show=False),
        Binding('m', 'toggle_test_metadata', 'Toggle metadata', show=False),
        Binding('r', 'toggle_metadata', 'Toggle run metadata', show=False),
        Binding('s', 'toggle_side_by_side', 'Toggle sxs', show=False),
        Binding('v', 'open_visualizer', 'Open visualization', show=False),
        Binding('V', 'open_output_visualizer', 'Open output visualization', show=False),
        Binding('f', 'toggle_failing_only', 'Failing only', show=False),
    ]

    side_by_side: reactive[bool] = reactive(False)
    failing_only: reactive[bool] = reactive(False)
    diff_with_data: reactive[Optional[TestcaseRenderingData]] = reactive(
        default=None,
    )

    _option_entries: List[Optional[GenerationTestcaseEntry]]

    def __init__(
        self,
        skeleton: SolutionReportSkeleton,
        solution: SolutionSkeleton,
        diff_solution: Optional[SolutionSkeleton] = None,
    ):
        super().__init__()
        self.skeleton = skeleton
        self.solution = solution
        self.diff_solution = diff_solution
        self.set_reactive(RunTestExplorerScreen.side_by_side, diff_solution is not None)
        self._option_entries = []
        self._search_query: str = ''
        self._outcomes: dict = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Horizontal(id='test-explorer'):
            with Vertical(id='test-list-container'):
                yield self._search_input()
                yield OptionList(id='test-list')
            with Vertical(id='test-details'):
                yield RichLogBox(id='test-box-warning')
                yield FileLog(id='test-input')
                yield TwoSidedTestBoxWidget(id='test-output')
                yield RichLogBox(id='test-metadata')

    async def on_mount(self):
        self.title = str(self.solution.path)

        if is_main_solution(self.solution):
            self.title = f'[MAIN] {self.title}'

        if self.diff_solution is not None:
            self.title = f'{self.title} vs. {self.diff_solution.path}'

        self.query_one('#test-list').border_title = 'Tests'
        self.query_one('#test-input').border_title = 'Input'

        self._init_search_box()

        warning_box = self.query_one('#test-box-warning', RichLogBox)
        warning_box.markup = True
        warning_box.wrap = True
        if not self._is_interactive():
            warning_box.display = False
        elif not self.skeleton.capture_pipes:
            warning_box.write(
                '[yellow]Interactions are not captured. Use the [blue]rbx -cp ...[/blue] flag when running to capture them.[/yellow]'
            )
            warning_box.display = True

        # Ensure the output is show, even for interactive tests
        self.action_show_output()

        metadata = self.query_one('#test-metadata', RichLogBox)
        metadata.display = False
        metadata.border_title = 'Metadata'
        metadata.wrap = True
        metadata.markup = True
        metadata.clear().write('No test selected')

        # Precompute each entry's outcome once so filtering/searching never
        # re-reads ``.eval`` files on every keystroke.
        evals = get_solution_evals(self.skeleton, self.solution)
        self._outcomes = {
            (entry.group_entry.group, entry.group_entry.index): (
                eval.result.outcome if eval is not None else None
            )
            for entry, eval in zip(self.skeleton.entries, evals)
        }

        await self._update_tests()
        # The search box is the first focusable child; keep initial focus on the
        # list so key bindings (m/r/f/…) reach the screen, not the hidden Input.
        self.query_one('#test-list', OptionList).focus()

    def _is_interactive(self) -> bool:
        return package.find_problem_package_or_die().type == TaskType.COMMUNICATION

    def _get_rendering_data(
        self, solution: SolutionSkeleton, entry: GenerationTestcaseEntry
    ) -> TestcaseRenderingData:
        rendering_data = TestcaseRenderingData.from_one_path(
            self.skeleton.get_solution_entry_prefix(solution, entry.group_entry)
        )
        rendering_data.rich_content = get_run_testcase_metadata_markup(
            self.skeleton, solution, entry.group_entry
        )
        return rendering_data

    def _update_selected_test(self, index: Optional[int]):
        input = self.query_one('#test-input', FileLog)
        output = self.query_one('#test-output', TwoSidedTestBoxWidget)
        metadata = self.query_one('#test-metadata', RichLogBox)

        if index is None:
            input.path = None
            output.reset()
            metadata.clear().write('No test selected')
            return
        entry = self._option_entries[index]
        if entry is None:
            return
        input.path = entry.metadata.copied_to.inputPath
        output.data = self._get_rendering_data(self.solution, entry)

        metadata.clear()
        metadata.write(console.expand_markup(get_testcase_metadata_markup(entry)))

        if self.diff_solution is not None:
            self.diff_with_data = self._get_rendering_data(self.diff_solution, entry)
        else:
            self.diff_with_data = TestcaseRenderingData.from_one_path(
                entry.group_entry.get_prefix_path()
            )

    async def _update_tests(self):
        self.watch(
            self.query_one('#test-list', OptionList),
            'highlighted',
            self._update_selected_test,
        )
        self.rebuild_test_list()

    def _entry_outcome(self, entry: GenerationTestcaseEntry) -> Optional[Outcome]:
        return self._outcomes.get((entry.group_entry.group, entry.group_entry.index))

    def _compute_options(
        self, predicate: Optional[EntryPredicate]
    ) -> Tuple[List[Any], List[Optional[GenerationTestcaseEntry]]]:
        return get_entries_options(
            self.skeleton.entries,
            skeleton=self.skeleton,
            solution=self.solution,
            predicate=predicate,
        )

    def _extra_predicate(self) -> Optional[EntryPredicate]:
        if not self.failing_only:
            return None

        def predicate(entry: GenerationTestcaseEntry) -> bool:
            # Keep non-AC; a missing eval (incomplete run) is treated as not-AC.
            return self._entry_outcome(entry) != Outcome.ACCEPTED

        return predicate

    def _extra_filter_labels(self) -> List[str]:
        return ['failing only'] if self.failing_only else []

    def action_toggle_failing_only(self) -> None:
        self.failing_only = not self.failing_only

    def watch_failing_only(self, value: bool) -> None:
        if not self.is_mounted:
            return
        self.rebuild_test_list()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        event.stop()

    def has_diffable_solution(self) -> bool:
        return self.diff_solution is not None or package.get_main_solution() is not None

    def should_show_interaction(self) -> bool:
        pkg = package.find_problem_package_or_die()
        return pkg.type == TaskType.COMMUNICATION and self.skeleton.capture_pipes

    def action_show_output(self):
        if self.should_show_interaction():
            self.query_one('#test-output', TwoSidedTestBoxWidget).show_interaction()
        else:
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

    def action_toggle_test_metadata(self):
        metadata = self.query_one('#test-metadata', RichLogBox)
        metadata.display = not metadata.display

    async def action_open_visualizer(self):
        # TODO: should we figure out a way to pass output here too?
        input_path = self.query_one('#test-input', FileLog).path
        if input_path is None:
            self.app.notify('No test selected', severity='error')
            return
        try:
            await visualizers.run_ui_input_visualizer_for_testcase(
                Testcase(inputPath=input_path)
            )
        except RbxException as e:
            self.app.show_error(e)  # type: ignore[attr-defined]

    async def action_open_output_visualizer(self):
        input_path = self.query_one('#test-input', FileLog).path
        if input_path is None:
            self.app.notify('No test selected', severity='error')
            return
        two_sided = self.query_one('#test-output', TwoSidedTestBoxWidget)
        output_path = two_sided.data.output_path
        if output_path is None:
            self.app.notify('No output found to visualize', severity='error')
            return

        answer_path: Optional[pathlib.Path] = None
        if two_sided.diff_with_data is not None:
            answer_path = two_sided.diff_with_data.output_path

        try:
            await visualizers.run_ui_solution_visualizer_for_testcase(
                Testcase(inputPath=input_path, outputPath=output_path),
                answer_path=answer_path,
            )
        except RbxException as e:
            self.app.show_error(e)  # type: ignore[attr-defined]
