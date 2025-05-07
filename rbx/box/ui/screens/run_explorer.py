from typing import Optional

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView

from rbx import utils
from rbx.box import package
from rbx.box.solutions import SolutionReportSkeleton
from rbx.box.ui.screens.error import ErrorScreen
from rbx.box.ui.screens.run_test_explorer import RunTestExplorerScreen


def _has_run() -> bool:
    return (package.get_problem_runs_dir() / 'skeleton.yml').is_file()


def _get_skeleton() -> SolutionReportSkeleton:
    skeleton_path = package.get_problem_runs_dir() / 'skeleton.yml'
    return utils.model_from_yaml(
        SolutionReportSkeleton,
        skeleton_path.read_text(),
    )


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
                Label(f'{i}. {sol.path}')
                for i, sol in enumerate(self.skeleton.solutions)
            ]
        yield ListView(*[ListItem(item) for item in items], id='run-list')

    def on_mount(self):
        if not _has_run():
            self.app.switch_screen(ErrorScreen('No runs found. Run `rbx run` first.'))
            return

        self.query_one('#run-list').border_title = 'Runs'

        self.skeleton = _get_skeleton()

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
