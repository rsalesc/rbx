"""`rbx stats`, `rbx fix` and `rbx wizard`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

import typer

from rbx import annotations
from rbx.box import (
    cd,
)

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'stats',
    rich_help_panel='Management',
    help='Show stats about current and related packages.',
)
@cd.within_closest_package
def stats(
    transitive: bool = typer.Option(
        False,
        '--transitive',
        '-t',
        help='Show stats about all reachable packages.',
    ),
):
    from rbx.box import stats

    if transitive:
        stats.print_reachable_package_stats()
    else:
        stats.print_package_stats()


@app.command(
    'fix',
    rich_help_panel='Management',
    help='Format files of the current package.',
)
@cd.within_closest_wrapper
def fix(print_diff: bool = typer.Option(False, '--print-diff', '-p')):
    from rbx.box import linting

    linting.fix_package(print_diff=print_diff)


@app.command(
    'wizard',
    rich_help_panel='Management',
    help='Run the wizard.',
)
@cd.within_closest_package
def wizard():
    from rbx.box.wizard.server import run_server

    run_server()
