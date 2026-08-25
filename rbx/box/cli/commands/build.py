"""`rbx build`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

import syncer
import typer

from rbx import annotations
from rbx.box import (
    environment,
    package,
)

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'build, b', rich_help_panel='Deploying', help='Build all tests for the problem.'
)
@annotations.docs("""
    Builds the problem package.

    This command compiles all generators, validators, and checkers. Then it generates
    inputs using the generator script and validates them with the validator. Finally,
    it generates the outputs using the main solution.

    It is recommended to run this command before packaging the problem to ensure
    everything is up-to-date.
""")
@package.within_problem
@syncer.sync
async def build(
    verification: environment.VerificationParam,
    validate: bool = typer.Option(
        True,
        help='Whether to validate outputs for tests.',
    ),
    visualize: bool = typer.Option(
        False,
        help='Whether to build visualizations for inputs/outputs of tests.',
    ),
):
    from rbx.box import builder

    if not await builder.build(
        verification=verification, validate=validate, visualize=visualize
    ):
        raise typer.Exit(1)
