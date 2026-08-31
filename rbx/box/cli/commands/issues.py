"""`rbx issues`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when the command is invoked. A command added here needs a row there too.

Kept apart from `run.py` on purpose: this reads two YAML files and prints, and
sharing a module with `rbx run` would make it pay for the whole solution-running
import graph on every invocation.
"""

from typing import Annotated

import typer

from rbx import annotations, console
from rbx.box import issues, package
from rbx.box.issues import IssuesFormat

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'issues',
    rich_help_panel='Testing',
    help='Show what the last run revealed about the problem.',
)
@package.within_problem
def issues_cmd(
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
    try:
        report = issues.build_report(package.get_problem_runs_dir())
    except issues.UnsupportedReportVersion as exception:
        console.console.print(f'[error]{exception}[/error]')
        raise typer.Exit(1) from exception

    if format is IssuesFormat.JSON:
        # Straight to stdout, not through the themed console: this output is
        # parsed, and Rich would wrap and highlight it.
        print(issues.to_json(report))
        return

    issues.print_report(report, detailed=detailed)
