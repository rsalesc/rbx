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
import math
from typing import Annotated

import rich.markup
import typer

from rbx import annotations, console
from rbx.box import fields, package

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
        typer.echo(_dump_json(expanded))
        return
    for name, value in sorted(expanded.items()):
        # Both halves are setter-controlled YAML rendered as markup, so a var
        # named or valued with brackets would otherwise style the output or
        # blow up with a MarkupError.
        escaped_name = rich.markup.escape(name)
        escaped_value = rich.markup.escape(str(value))
        console.console.print(f'[item]{escaped_name}[/item] = {escaped_value}')


def _dump_json(expanded: fields.Vars) -> str:
    """Serialize the vars, refusing to emit anything `JSON.parse` would reject.

    `json.dumps` writes bare `Infinity`/`NaN` for a non-finite float, which is
    not JSON. The consumer is a spawned process reading stdout, so a clean
    non-zero exit is far more useful to it than a payload that fails to parse.
    """
    try:
        return json.dumps(expanded, allow_nan=False)
    except ValueError as e:
        offenders = sorted(
            name
            for name, value in expanded.items()
            if isinstance(value, float) and not math.isfinite(value)
        )
        detail = (
            f'non-finite values in {", ".join(offenders)}'
            if offenders
            else str(e)  # Not the non-finite case: say whatever json said.
        )
        console.console.print(
            f'[error]Cannot serialize the vars of this problem to JSON: '
            f'{rich.markup.escape(detail)}.[/error]'
        )
        raise typer.Exit(1) from None
