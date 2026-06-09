"""rbx ui shows a friendly error instead of crashing when there is no past run.

Regression for #554: entering the run explorer ('Explore results of a past
`rbx run`') with no ``skeleton.yml`` on disk used to raise ``FileNotFoundError``
from ``get_skeleton`` while constructing ``RunExplorerScreen``, crashing the
whole TUI. It now lands on the 'No runs found' ``ErrorScreen`` and keeps the
app alive.
"""

from unittest import mock

from rbx.box.ui.main import rbxApp
from rbx.box.ui.screens.error import ErrorScreen
from rbx.box.ui.screens.run_explorer import RunExplorerScreen


async def test_run_explorer_without_run_shows_error_screen(tmp_path):
    runs_dir = tmp_path / 'runs'
    runs_dir.mkdir()
    with mock.patch('rbx.box.package.get_problem_runs_dir', return_value=runs_dir):
        async with rbxApp().run_test() as pilot:
            app = pilot.app
            # Mirrors picking 'Explore results of a past `rbx run`' from the menu.
            app.show_screen(RunExplorerScreen)
            await pilot.pause()

            assert app.is_running
            assert isinstance(app.screen, ErrorScreen)
            assert 'No runs found' in app.screen.message
