from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList

from rbx import console
from rbx.box.ui.screens.error import ErrorScreen
from rbx.box.ui.screens.run_test_explorer import RunTestExplorerScreen
from rbx.box.ui.screens.selector import SelectorScreen
from rbx.box.ui.utils.run_ui import get_skeleton, get_solution_markup
from rbx.box.ui.widgets.rich_log_box import RichLogBox


class RunExplorerScreen(Screen):
    BINDINGS = [('s', 'compare_with', 'Compare with')]

    def __init__(self):
        super().__init__()
        self.skeleton = get_skeleton()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        items = []
        if self.skeleton:
            for i, sol in enumerate(self.skeleton.solutions):
                if i > 0:
                    items.append(None)
                items.append(
                    console.expand_markup(get_solution_markup(self.skeleton, sol))
                )
        with Vertical():
            run_list = OptionList(*items, id='run-list')
            run_list.border_title = 'Runs'
            yield run_list

            tips = RichLogBox(id='run-tips')
            tips.markup = True
            tips.display = False
            tips.border_title = 'Tips'
            yield tips

    def on_mount(self):
        if not self.skeleton:
            self.app.switch_screen(ErrorScreen('No runs found. Run `rbx run` first.'))
            return

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        event.stop()
        selected_index = event.option_index
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
        option_list = self.query_one('#run-list', OptionList)
        if option_list.highlighted is None:
            return
        test_solution = self.skeleton.solutions[option_list.highlighted]

        options = [f'{sol.path}' for sol in self.skeleton.solutions]

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
