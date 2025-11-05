# flake8: noqa

import asyncio
import os
import signal
import sys
import threading
import typer
from rich.console import Console
from types import FrameType


def _check_completions():
    if os.environ.get('_TYPER_COMPLETE_ARGS'):
        sys.exit(0)


# TODO: do not install this handler when in dev mode
def _install_no_exception_handlers():
    # Setup asyncio exception handler to ignore all task exceptions.
    loop = asyncio.get_event_loop()

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


def run_app_cli():
    from rbx.box.cli import app as app_cli

    app_cli()


def app():
    # _check_completions()
    _install_no_exception_handlers()
    from rbx.box.exception import RbxException

    try:
        import nest_asyncio

        nest_asyncio.apply()

        run_app_cli()
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
    finally:
        Console().show_cursor()
