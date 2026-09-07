"""Crash reporting for the Textual apps.

A crash inside a Textual app never reaches the handler in `rbx/box/main.py`.
Textual funnels every unhandled exception into `App._handle_exception`, which
renders a traceback into `_exit_renderables` and closes the app down itself --
the exception is consumed there and nothing propagates out of the CLI call. So
the apps have to report for themselves.
"""

from typing import Optional

from rich.text import Text


class CrashReportingMixin:
    """Write a crash report when a Textual app dies of an exception.

    Mix in *before* `App`, so `_handle_exception` runs on the way down to
    Textual's own. An app that recognizes an error and handles it -- as
    `rbxBaseApp` does for `RbxException` and `typer.Exit` -- returns before
    delegating, and so never reports: those are diagnostics, not crashes.
    """

    _crash_report_path: Optional[object] = None

    def _handle_exception(self, error: Exception) -> None:
        from rbx import crash

        self._crash_report_path = crash.report_crash(error)
        super()._handle_exception(error)  # type: ignore[misc]

    def _print_error_renderables(self) -> None:
        """Print the hint once the app is down and the terminal is back.

        Not appended to `_exit_renderables`: Textual prints only the first of
        those and collapses the rest into a "1 of N errors shown" note, so the
        hint would never be seen. This runs right after them, on the same
        console.
        """
        super()._print_error_renderables()  # type: ignore[misc]
        if self._crash_report_path is not None:
            self.error_console.print(  # type: ignore[attr-defined]
                Text(f'\nCrash report written to {self._crash_report_path}')
            )
            self._crash_report_path = None
