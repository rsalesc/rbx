from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView

from rbx.box import package
from rbx.box.schema import TaskType
from rbx.box.solutions import SolutionReportSkeleton
from rbx.box.ui.screens.error import ErrorScreen
from rbx.box.ui.screens.run_test_explorer import RunTestExplorerScreen
from rbx.box.ui.screens.selector import SelectorScreen
from rbx.box.ui.utils.run_ui import get_skeleton, get_solution_markup, has_run
from rbx.box.ui.widgets.rich_log_box import RichLogBox


class RunExplorerScreen(Screen):
    BINDINGS = [('s', 'compare_with', 'Compare with')]

    skeleton: reactive[Optional[SolutionReportSkeleton]] = reactive(
        None, recompose=True
    )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        items = []
        if self.skeleton:
            items = [
                Label(get_solution_markup(self.skeleton, sol), markup=True)
                for i, sol in enumerate(self.skeleton.solutions)
            ]
        with Vertical():
            run_list = ListView(*[ListItem(item) for item in items], id='run-list')
            run_list.border_title = 'Runs'
            yield run_list

            tips = RichLogBox(id='run-tips')
            tips.markup = True
            tips.display = False
            tips.border_title = 'Tips'
            pkg = package.find_problem_package_or_die()
            if pkg.type == TaskType.COMMUNICATION:
                tips.display = True
                tips.write(
                    'This is an interactive problem.\nYou can use the [bold blue]rbx --capture run[/bold blue] command to capture the interaction between the processes and see them here.'
                )
            yield tips

    def on_mount(self):
        if not has_run():
            self.app.switch_screen(ErrorScreen('No runs found. Run `rbx run` first.'))
            return

        self.skeleton = get_skeleton()

    def on_list_view_selected(self, event: ListView.Selected):
        selected_index = event.list_view.index
        if selected_index is None:
            return
        if self.skeleton is None:
            return
        self.app.push_screen(
            RunTestExplorerScreen(
                self.skeleton, self.skeleton.solutions[selected_index]
            )
        )

    def action_compare_with(self):
        if self.skeleton is None:
            return
        list_view = self.query_one('#run-list', ListView)
        if list_view.index is None:
            return
        test_solution = self.skeleton.solutions[list_view.index]

        options = [
            ListItem(Label(f'{sol.path}', markup=False))
            for sol in self.skeleton.solutions
        ]

        def on_selected(index: Optional[int]):
            if index is None:
                return
            if self.skeleton is None:
                return
            base_solution = self.skeleton.solutions[index]
            self.app.push_screen(
                RunTestExplorerScreen(self.skeleton, test_solution, base_solution)
            )

        self.app.push_screen(
            SelectorScreen(options, title='Select a solution to compare against'),
            callback=on_selected,
        )
