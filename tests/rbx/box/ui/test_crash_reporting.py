"""A crash inside a Textual app still leaves a crash report behind.

Textual funnels every unhandled exception into `App._handle_exception`, which
renders a traceback and closes the app down itself. The exception is consumed
there, so it never reaches the handler in `rbx/box/main.py` -- which is why
`rbx ui` used to die without writing anything.
"""

import pathlib

import pytest
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label

from rbx import crash
from rbx.box.exception import RbxException
from rbx.box.ui.crash_reporting import CrashReportingMixin
from rbx.box.ui.main import rbxApp
from rbx.box.ui.review_app import rbxReviewApp
from rbx.box.ui.screens.error_modal import ErrorModal


class _CrashOnMountScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Label('loading')

    def on_mount(self) -> None:
        raise KeyError('some-missing-key')


class _RbxErrorOnMountScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Label('loading')

    def on_mount(self) -> None:
        exc = RbxException()
        exc.print('problem.rbx.yml: 1 validation error')
        raise exc


@pytest.fixture
def crashes_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    app_path = tmp_path / 'app'
    monkeypatch.setattr('rbx.utils.get_app_path', lambda: app_path)
    return app_path / crash.CRASHES_DIR_NAME


def _reports(crashes_dir: pathlib.Path):
    if not crashes_dir.is_dir():
        return []
    return [path for path in crashes_dir.glob('*.md') if not path.is_symlink()]


async def test_crash_in_the_ui_writes_a_report(crashes_dir: pathlib.Path):
    with pytest.raises(KeyError):
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(_CrashOnMountScreen())
            await pilot.pause()

    reports = _reports(crashes_dir)
    assert len(reports) == 1
    report = reports[0].read_text()
    assert 'exception: "KeyError"' in report
    assert 'some-missing-key' in report


async def test_the_report_path_is_shown_on_the_way_out(
    crashes_dir: pathlib.Path, capsys: pytest.CaptureFixture
):
    """The hint has to be printed, not appended to `_exit_renderables`.

    Textual prints only the first of those and collapses the rest into a
    "1 of N errors shown" note, so an appended hint is never seen.
    """
    with pytest.raises(KeyError):
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(_CrashOnMountScreen())
            await pilot.pause()

    err = capsys.readouterr().err
    assert 'Crash report written to' in err
    assert _reports(crashes_dir)[0].name in err


async def test_a_handled_rbx_error_is_not_a_crash(crashes_dir: pathlib.Path):
    """`RbxException` opens the modal and never reaches the reporting mixin."""
    async with rbxApp().run_test() as pilot:
        app = pilot.app
        await app.push_screen(_RbxErrorOnMountScreen())
        await pilot.pause()

        assert isinstance(app.screen, ErrorModal)

    assert _reports(crashes_dir) == []


def test_every_textual_app_reports():
    """A new app that forgets the mixin would crash silently, as `rbx ui` did."""
    from rbx.box.tooling.boca.ui.app import BocaRunsApp
    from rbx.box.ui.command_app import rbxCommandApp
    from rbx.box.ui.main import rbxDifferApp
    from rbx.box.ui.run_picker import RunPickerApp

    for app_cls in (
        rbxApp,
        rbxDifferApp,
        rbxReviewApp,
        RunPickerApp,
        rbxCommandApp,
        BocaRunsApp,
    ):
        assert issubclass(app_cls, CrashReportingMixin), app_cls.__name__
