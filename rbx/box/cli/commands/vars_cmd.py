"""`rbx vars`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.

This command is deliberately read-only: it loads `problem.rbx.yml` and
expands its vars, and touches nothing else. The VS Code extension spawns it
while the user edits, so anything that creates or locks the package cache
would make it unsafe to call. See
`docs/plans/2026-08-28-vscode-statement-var-hints-design.md`.
"""

import json
from typing import Annotated

import typer

from rbx import annotations, console
from rbx.box import package

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'vars',
    rich_help_panel='Configuration',
    help='Show the expanded vars of this problem.',
)
@package.within_problem
def vars_command(
    json_output: Annotated[
        bool,
        typer.Option(
            '--json',
            help='Print the vars as a JSON object of dotted keys.',
        ),
    ] = False,
):
    expanded = package.find_problem_package_or_die().expanded_vars
    if json_output:
        typer.echo(json.dumps(expanded))
        return
    for name, value in sorted(expanded.items()):
        console.console.print(f'[item]{name}[/item] = {value}')
