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
            help='Print the vars as a JSON object of dotted keys and string values.',
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
    """Serialize the vars as a flat map of dotted name to *display string*.

    Every value crosses as a JSON string holding the text the statement would
    show, never as a JSON number. The only consumer -- the VS Code extension --
    wants display text and never does arithmetic on these, and a JSON number
    cannot carry the text losslessly: `JSON.parse` produces IEEE doubles, so
    `10**18 + 7` (a plausible bound) would come back as `1000000000000000000`
    and the extension would badge a *wrong* value with full confidence, and
    `10**21` would come back spelled `1e+21`. Rendering here is exact for
    arbitrarily large ints and keeps float formatting out of the boundary.

    `str` is the right renderer because it is what Jinja itself calls on a
    value with no filter, so the badge shows exactly what an unfiltered
    `\\VAR{...}` will (a filtered one renders differently by design -- the
    badge answers "what number is this?", not "what will this typeset as"):
    an `int` becomes its full decimal expansion, a `str` itself, a `float` its
    `repr`, and a `bool` `True`/`False`. Note that last one is deliberately
    *not* the `1`/`0` of `fields.render_var_on_command_line`: that spelling
    exists for testlib/jngen argument parsing, not for statement display.
    """
    offenders = sorted(
        name
        for name, value in expanded.items()
        if isinstance(value, float) and not math.isfinite(value)
    )
    if offenders:
        # `str(float('inf'))` is a perfectly good JSON string, so this no longer
        # has to be rejected -- but an infinite bound is a package bug, and the
        # consumer degrades cleanly on a non-zero exit, so keep surfacing it.
        detail = (
            f'{offenders[0]} has a non-finite value'
            if len(offenders) == 1
            else f'{", ".join(offenders)} have non-finite values'
        )
        console.console.print(
            f'[error]Cannot serialize the vars of this problem to JSON: '
            f'{rich.markup.escape(detail)}.[/error]'
        )
        raise typer.Exit(1)
    return json.dumps({name: str(value) for name, value in expanded.items()})
