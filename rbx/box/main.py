# flake8: noqa

import asyncio
import os
import pathlib
import signal
import sys
import threading
import typer
from rich.console import Console
from types import FrameType


# TODO: do not install this handler when in dev mode
def _install_no_exception_handlers():
    # Setup asyncio exception handler to ignore all task exceptions.
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    def _ignore_task_exceptions(loop, context):
        exc = context.get('exception')

        # Completely suppress cancellation/keyboard interrupts
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            return

        # Optional: swallow ALL task exceptions
        # return

        # Otherwise let Python handle others normally
        loop.default_exception_handler(context)

    loop.set_exception_handler(_ignore_task_exceptions)

    # Setup excepthook to not print tracebacks for KeyboardInterrupt.
    old_excepthook = sys.excepthook

    def _ignore_keyboard_interrupt_tracebacks(exc_type, exc_value, traceback):
        if exc_type is KeyboardInterrupt:
            sys.exit(0)
        else:
            old_excepthook(exc_type, exc_value, traceback)

    sys.excepthook = _ignore_keyboard_interrupt_tracebacks


def _schedule_hard_kill():
    timer = threading.Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGKILL))
    timer.daemon = True
    timer.start()


def _abort():
    Console().show_cursor()
    _schedule_hard_kill()
    sys.exit(1)


def _finish_run(status: str) -> None:
    """Stamp the run this process started, if it started one.

    Looked up in `sys.modules` rather than imported: a process that never
    imported the run report never wrote a skeleton, and importing it now would
    make every `rbx --help` pay for the schema on its way out.
    """
    run_report = sys.modules.get('rbx.box.run_report')
    if run_report is not None:
        run_report.finish_run(run_report.ExitStatus(status))
    # Same for a stress session: `run_stress` finishes its own, so this only
    # catches what escaped it (a second Ctrl-C). Never raises.
    stress_manifest = sys.modules.get('rbx.box.stress_manifest')
    if stress_manifest is not None:
        stress_manifest.finish_open_session(status)


def exit_status_of(exc: BaseException) -> str:
    """How a run ended by `exc` ended, as an `ExitStatus` value."""
    if isinstance(exc, SystemExit):
        # Click turns Ctrl-C inside a command into exit code 130.
        if exc.code == 130:
            return 'interrupted'
        return 'ok' if exc.code in (0, None) else 'error'
    if isinstance(exc, (KeyboardInterrupt, typer.Abort)):
        return 'interrupted'
    if isinstance(exc, typer.Exit):
        return 'ok' if exc.exit_code == 0 else 'error'
    return 'error'


def run_app_cli():
    from rbx.box.cli import app as app_cli

    app_cli()


def app():
    from rbx.box.completion import entry

    if entry.handle_completion():
        return

    from rbx.box import git_utils

    if not git_utils.check_symlinks_cached(pathlib.Path.cwd()):
        from rbx import console
        from rbx.box.formatting import ref

        WINDOWS_GIT_URL = 'https://rbx.rsalesc.dev/intro/windows-git'

        console.console.print(
            '[error]Symlinks are not being preserved in the current git repository. '
            '[item]rbx[/item] heavily relies on the use of symlinking for caching and '
            'presetting. Features might break because of this[/error]'
        )
        console.console.print(
            f'[error]If you are on Windows, please see {ref(WINDOWS_GIT_URL)} for more information.[/error]'
        )
        console.console.print()

    _install_no_exception_handlers()
    from rbx.box.exception import RbxException

    try:
        # Stamped here, before the handlers below run: `_abort` schedules a hard
        # kill, and a stamp left for the outer `finally` could lose that race.
        # Click ends even a successful command with `SystemExit(0)`, so the
        # `except` is the common path and the `else` only a safety net.
        try:
            import nest_asyncio

            nest_asyncio.apply()

            run_app_cli()
        except BaseException as e:
            _finish_run(exit_status_of(e))
            raise
        else:
            _finish_run('ok')
    except (KeyboardInterrupt, typer.Abort):
        _abort()
    except SystemExit as e:
        if e.code == 130:
            _abort()
        else:
            raise
    except RbxException as e:
        print(str(e))
        sys.exit(1)
    except typer.Exit:
        # An intentional exit, not a crash. Click normally handles this one
        # itself, but it must never be reported if it does get this far.
        raise
    except BaseException as e:
        # A real crash. Leave a file behind before the traceback scrolls away,
        # then re-raise so it still renders exactly as it did before.
        #
        # This has to live here rather than in `sys.excepthook`: `Typer.__call__`
        # opens by overwriting that hook with its own, so anything installed
        # before the CLI runs is gone by the time it could fire. Typer re-raises
        # into this block instead.
        from rbx import crash

        path = crash.report_crash(e)
        if path is not None:
            print(f'Crash report written to {path}', file=sys.stderr)
        raise
    finally:
        Console().show_cursor()
