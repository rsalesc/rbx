"""`rbx ui`, `rbx diff`, `rbx serve` -- everything that opens the TUI.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

import pathlib

import typer

from rbx import annotations
from rbx.box import (
    package,
)
from rbx.box.vscode import extension as vscode_extension

app = typer.Typer(cls=annotations.AliasGroup)


@app.command('ui', help='Show an UI for exploring testcases of the current problem.')
@package.within_problem
def ui():
    from rbx.box.ui import main as ui_pkg

    ui_pkg.start()
    # After the UI, not before: a fullscreen TUI wipes anything printed ahead of
    # it, so a startup hint is a hint nobody sees.
    vscode_extension.print_outdated_hint()


@app.command('diff', hidden=True)
def diff(path1: pathlib.Path, path2: pathlib.Path):
    from rbx.box.ui import main as ui_pkg

    ui_pkg.start_differ(path1, path2)


@app.command('serve', hidden=True)
def serve():
    from textual_serve.server import Server

    server = Server('rbx ui', port=8081)
    server.serve()
