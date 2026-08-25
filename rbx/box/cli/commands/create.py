"""`rbx create` and `rbx edit`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

import pathlib
from typing import Annotated, Optional

import typer

from rbx import annotations, config, console
from rbx.box import (
    creation,
    package,
)
from rbx.box.contest.contest_package import (
    find_contest_yaml,
)

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'edit, e',
    rich_help_panel='Configuration',
    help='Open problem.rbx.yml in your default editor.',
)
@package.within_problem
def edit():
    console.console.print('Opening problem definition in editor...')
    # Call this function just to raise exception in case we're no in
    # a problem package.
    package.find_problem()
    config.open_editor(package.find_problem_yaml() or pathlib.Path())


@app.command(
    'create, c',
    rich_help_panel='Management',
    help='Create a new problem package.',
)
def create(
    name: Annotated[
        str,
        typer.Option(
            help='Name of the problem to create, which will be used as the name of the new folder. '
            'A path relative to the current directory may be given (e.g. "problems/my-problem"), '
            'in which case the problem name is the basename ("my-problem").',
            prompt='What should the problem be named? You may also give a path relative to the current directory (e.g. "problems/my-problem" creates a problem named "my-problem" in that directory)',
        ),
    ],
    preset: Annotated[
        Optional[str], typer.Option(help='Preset to use when creating the problem.')
    ] = None,
    variant: Annotated[
        Optional[str],
        typer.Option(
            '--variant',
            '-v',
            help='Which template variant of the preset to use. Omit to use the '
            'canonical template, or to be prompted when the preset offers variants.',
        ),
    ] = None,
    local: Annotated[
        bool,
        typer.Option(
            '--local',
            help='Whether to use a preset from the local version of rbx, instead of the global one (not recommended).',
        ),
    ] = False,
):
    if find_contest_yaml() is not None:
        console.console.print(
            '[error]Cannot [item]rbx create[/item] a problem inside a contest.[/error]'
        )
        console.console.print(
            '[error]Instead, use [item]rbx contest add[/item] to add a problem to a contest.[/error]'
        )
        raise typer.Exit(1)

    creation.create(name, preset=preset, variant=variant, local=local)
