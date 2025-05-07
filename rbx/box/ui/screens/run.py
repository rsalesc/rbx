import pathlib
from typing import Optional, Set

import textual
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Center, Grid
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, SelectionList
from textual.widgets.selection_list import Selection

from rbx import console
from rbx.box import package
from rbx.box.schema import Solution
from rbx.box.solutions import (
    EvaluationItem,
    SolutionReportSkeleton,
    get_evals_formatted_time,
    get_testcase_markup_verdict,
)
from rbx.box.ui.captured_log import LogDisplay, LogDisplayState
from rbx.box.ui.screens.command import CommandScreen
from rbx.grading.steps import Evaluation


def _build_solution_selection_label(sol: Solution) -> Text:
    main = package.get_main_solution()
    outcome = sol.outcome if main is None or main.path != sol.path else 'MAIN'

    style = sol.outcome.style()
    text = Text(f'{sol.path}')
    text.append(f' {outcome}', style=style)
    return text


class SolutionReportScreen(Screen):
    skeleton: SolutionReportSkeleton

    BINDINGS = [('q', 'app.pop_screen', 'Back')]

    def __init__(
        self,
        skeleton: SolutionReportSkeleton,
        log_display_state: Optional[LogDisplayState] = None,
    ):
        super().__init__()
        self.skeleton = skeleton
        self.log_display_state = log_display_state

    def compose(self) -> ComposeResult:
        textual.log(self.skeleton)
        yield Header()
        yield Footer()
        with Grid(id='report-grid'):
            for _ in self.skeleton.solutions:
                yield DataTable(
                    cursor_type='row', cursor_foreground_priority='renderable'
                )
        if self.log_display_state is not None:
            yield LogDisplay(id='build-output')

    def on_mount(self):
        # self.query_one(
        #     '#build-output', Container
        # ).border_title = 'Test generation and validation'
        for solution, table in zip(
            self.skeleton.solutions,
            self.query(DataTable),
        ):
            table.border_title = str(solution.path)
            table.border_subtitle = _build_solution_selection_label(solution)
            table.add_columns('group', 'test', '?', 'time')

            for group in self.skeleton.groups:
                for i, tc in enumerate(group.testcases):
                    table.add_row(group.name, i, '', '', key=str(tc.inputPath))

        self.query_one(DataTable).focus()

        if self.log_display_state is not None:
            self.query_one(LogDisplay).load(self.log_display_state)

    async def process(self, item: EvaluationItem, eval: Evaluation):
        sol_idx_in_skeleton = self.skeleton.find_solution_skeleton_index(item.solution)
        assert sol_idx_in_skeleton is not None
        group = self.skeleton.find_group_skeleton(item.testcase_entry.group)
        assert group is not None
        tc = group.testcases[item.testcase_entry.index]

        textual.log(len(list(self.query(DataTable))), sol_idx_in_skeleton)
        table = self.query(DataTable)[sol_idx_in_skeleton]
        row_idx = table.get_row_index(str(tc.inputPath))

        table.update_cell_at(
            Coordinate(row=row_idx, column=2),
            get_testcase_markup_verdict(eval),
            update_width=True,
        )
        table.update_cell_at(
            Coordinate(row=row_idx, column=3),
            get_evals_formatted_time([eval]),
            update_width=True,
        )


class RunScreen(Screen):
    BINDINGS = [('q', 'app.pop_screen', 'Back')]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Center(id='run-settings'):
            pkg = package.find_problem_package_or_die()
            solutions = package.get_solutions()
            yield SelectionList[pathlib.Path](
                *(
                    Selection(_build_solution_selection_label(sol), sol.path, True)
                    for sol in solutions
                ),
                id='run-sols',
            )
            yield SelectionList[str](
                *(
                    Selection(testgroup.name, testgroup.name, initial_state=True)
                    for testgroup in pkg.testcases
                ),
                id='run-testgroups',
            )
            yield SelectionList[str](
                Selection(
                    'Generate expected outputs and run checker',
                    'check',
                    initial_state=True,
                ),
                id='run-config',
            )
            yield Button('Run')

    def on_mount(self):
        sols = self.query_one('#run-sols', SelectionList)
        sols.border_title = 'Select solutions to run'
        sols.focus()

        testgroups = self.query_one('#run-testgroups', SelectionList)
        testgroups.border_title = 'Select which testgroups to execute'

        config = self.query_one('#run-config', SelectionList)
        config.border_title = 'Configure the execution'

    def on_screen_resume(self):
        self.query_one('#run-sols', SelectionList).focus()

    async def on_button_pressed(self, _: Button.Pressed):
        await self.action_run()

    async def _run_solutions(self, tracked_solutions: Set[str], check: bool):
        main_solution = package.get_main_solution()
        if check and main_solution is None:
            console.console.print(
                '[warning]No main solution found, running without checkers.[/warning]'
            )
            check = False

        self.app.switch_screen(CommandScreen(['rbx', 'run']))

    async def action_run(self):
        sols = self.query_one('#run-sols', SelectionList)
        config = self.query_one('#run-config', SelectionList)

        tracked_solutions = set(str(sol) for sol in sols.selected)
        check = 'check' in config.selected

        await self._run_solutions(tracked_solutions, check)
