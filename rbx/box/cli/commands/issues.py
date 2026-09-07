"""`rbx issues`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when the command is invoked. A command added here needs a row there too.

Kept apart from `run.py` on purpose: sharing a module with `rbx run` would make
it pay for the whole solution-running import graph on every invocation.

It is no longer the near-instant command it was, though. Config checks need a
loaded package and the extracted testcases, which is the cost `rbx summary`
already pays. Gating them behind a flag was rejected: a flag defaulting to off
means the two commands disagree about the same package by default, and the
setter who most needs "you have no accepted solution" is the least likely to
have found the flag. See docs/plans/2026-08-31-config-issues-design.md.
"""

from typing import Annotated

import syncer
import typer

from rbx import annotations, console
from rbx.box import issues, package
from rbx.box.issues import IssuesFormat

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'issues',
    rich_help_panel='Testing',
    help='Show what is wrong with the problem, before and after a run.',
)
@package.within_problem
@syncer.sync
async def issues_cmd(
    detailed: Annotated[
        bool,
        typer.Option(
            '--detailed',
            '-d',
            help='Explain each issue instead of summarizing it in one line.',
        ),
    ] = False,
    format: Annotated[
        IssuesFormat,
        typer.Option(
            '--format',
            help='How to print the issues. Use `json` to consume them from a tool.',
        ),
    ] = IssuesFormat.RICH,
):
    config_state = await issues.collect_config_state(
        package.find_problem_package_or_die()
    )
    try:
        report = issues.build_report(
            package.get_problem_runs_dir(), config_state=config_state
        )
    except issues.UnsupportedReportVersion as exception:
        console.console.print(f'[error]{exception}[/error]')
        raise typer.Exit(1) from exception

    if format is IssuesFormat.JSON:
        # Straight to stdout, not through the themed console: this output is
        # parsed, and Rich would wrap and highlight it.
        print(issues.to_json(report))
        return

    issues.print_report(report, detailed=detailed)
