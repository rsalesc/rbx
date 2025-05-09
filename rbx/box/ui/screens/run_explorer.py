from typing import Optional

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView

from rbx.box.solutions import SolutionReportSkeleton
from rbx.box.ui.screens.error import ErrorScreen
from rbx.box.ui.screens.run_test_explorer import RunTestExplorerScreen
from rbx.box.ui.utils.run_ui import get_skeleton, get_solution_markup, has_run


class RunExplorerScreen(Screen):
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
        yield ListView(*[ListItem(item) for item in items], id='run-list')

    def on_mount(self):
        if not has_run():
            self.app.switch_screen(ErrorScreen('No runs found. Run `rbx run` first.'))
            return

        self.query_one('#run-list', ListView).border_title = 'Runs'
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
