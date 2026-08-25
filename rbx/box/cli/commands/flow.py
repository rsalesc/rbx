"""`rbx on` and `rbx each`, which run other commands across a contest.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

import inspect
from typing import Annotated

import typer

from rbx import annotations
from rbx.box.contest import main as contest

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'on',
    help=(
        'Run a command in the context of a problem (or a set of problems) of a '
        'contest. Chain commands with `::` to queue them.'
    ),
    context_settings={
        'allow_extra_args': True,
        'ignore_unknown_options': True,
        'allow_interspersed_args': False,
    },
)
@annotations.docs(
    'Runs a command in the context of one problem (or a set of problems) of a '
    'contest.\n\n'
    + contest.PROBLEM_SELECTOR_DOCS
    + '\n\n'
    + inspect.cleandoc("""
    Like [`rbx each`](#rbx-each), commands can be chained with `::`:

    ```bash
    rbx on A..C build :: run -s
    ```

    A single command on a single problem runs directly in your terminal; anything
    else opens the TUI. Since flags after the problem selector belong to the chained
    commands, `-k`/`--keep-going` has to come first: `rbx on -k A build :: run`.
    """)
)
def on(
    ctx: typer.Context,
    problems: Annotated[
        str,
        typer.Argument(
            autocompletion=annotations._adapt('problem'),  # noqa: SLF001
            help=contest.PROBLEM_SELECTOR_HELP,
        ),
    ],
    keep_going: bool = contest.KEEP_GOING_OPTION,
) -> None:
    contest.on(ctx, problems, keep_going=keep_going)


@app.command(
    'each',
    help=(
        'Run a command for each problem in the contest. '
        'Chain commands with `::` to queue them.'
    ),
    context_settings={
        'allow_extra_args': True,
        'ignore_unknown_options': True,
        'allow_interspersed_args': False,
    },
)
@annotations.docs("""
    Runs a command for each problem in the contest, in a TUI with one tab per problem.

    Chain several commands with `::` to queue them all at once, in order:

    ```bash
    rbx each build :: package build
    ```

    Each problem runs its whole chain before the next problem starts. If a command in
    a chain fails, the rest of that problem's chain is skipped -- pass
    `-k`/`--keep-going` to run it anyway. Other problems are unaffected either way.

    Commands you type into the TUI later are queued too, but they always run, even
    after a failure.
""")
def each(ctx: typer.Context, keep_going: bool = contest.KEEP_GOING_OPTION) -> None:
    contest.each(ctx, keep_going=keep_going)
