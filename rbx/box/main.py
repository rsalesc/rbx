# flake8: noqa

import asyncio
import os
import signal
import sys
import typer
from rich.console import Console
from types import FrameType


def _check_completions():
    if os.environ.get('_TYPER_COMPLETE_ARGS'):
        sys.exit(0)


def _ignore_task_exceptions(loop, context):
    exc = context.get('exception')

    # Completely suppress cancellation/keyboard interrupts
    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
        return

    # Optional: swallow ALL task exceptions
    # return

    # Otherwise let Python handle others normally
    loop.default_exception_handler(context)


def _abort():
    Console().show_cursor()
    sys.exit(1)


def run_app_cli():
    from rbx.box.cli import app as app_cli

    app_cli()


def app():
    # _check_completions()

    # TODO: do not install this handler when in dev mode
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_ignore_task_exceptions)

    from rbx.box.exception import RbxException

    try:
        import nest_asyncio

        nest_asyncio.apply()

        run_app_cli()
    except (KeyboardInterrupt, typer.Abort):
        _abort()
    except RbxException as e:
        print(str(e))
        sys.exit(1)
    finally:
        Console().show_cursor()
