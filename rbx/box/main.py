# flake8: noqa

import os
import signal
import sys
import typer
from rich.console import Console
from types import FrameType


def _check_completions():
    if os.environ.get('_TYPER_COMPLETE_ARGS'):
        sys.exit(0)


def _keyboard_interrupt_handler(signum: int, frame: FrameType | None):
    Console().show_cursor()
    raise typer.Abort()  # pyright: ignore[reportUndefinedVariable]


def app():
    # _check_completions()

    # TODO: do not install this handler when in dev mode
    signal.signal(signal.SIGINT, _keyboard_interrupt_handler)

    from rbx.box.exception import RbxException

    try:
        import nest_asyncio

        nest_asyncio.apply()
        from rbx.box.cli import app as app_cli

        app_cli()
    except RbxException as e:
        print(str(e))
        sys.exit(1)
