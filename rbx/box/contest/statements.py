from typing import Annotated, List, Optional

import syncer
import typer

from rbx import annotations, console
from rbx.box import cd, environment, package
from rbx.box.contest.build_contest_statements import build_statement
from rbx.box.contest.contest_package import (
    find_contest_package_or_die,
    within_contest,
)
from rbx.box.statements.schema import StatementType

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


@app.command('build, b', help='Build statements.')
@within_contest
@syncer.sync
async def build(
    verification: environment.VerificationParam,
    languages: Annotated[
        Optional[List[str]],
        typer.Option(
            default_factory=list,
            help='Languages to build statements for. If not specified, build statements for all available languages.',
        ),
    ],
    output: Annotated[
        Optional[StatementType],
        typer.Option(
            case_sensitive=False,
            help='Output type to be generated. If not specified, will infer from the conversion steps specified in the package.',
        ),
    ] = StatementType.PDF,
    samples: Annotated[
        bool,
        typer.Option(help='Whether to build the statement with samples or not.'),
    ] = True,
    editorial: Annotated[
        bool,
        typer.Option(help='Whether to add editorial blocks to the statements or not.'),
    ] = False,
):
    contest = find_contest_package_or_die()
    # At most run the validators, only in samples.
    if samples:
        from rbx.box import builder

        for problem in contest.problems:
            console.console.print(
                f'Processing problem [item]{problem.short_name}[/item]...'
            )
            with cd.new_package_cd(problem.get_path()):
                package.clear_package_cache()

                if not await builder.build(
                    verification=verification, groups=set(['samples']), output=None
                ):
                    console.console.print(
                        '[error]Failed to build statements with samples, aborting.[/error]'
                    )
                    raise typer.Exit(1)

    contest = find_contest_package_or_die()
    candidate_languages = languages
    if not candidate_languages:
        candidate_languages = sorted(set([st.language for st in contest.statements]))

    for language in candidate_languages:
        candidates_for_lang = [
            st for st in contest.statements if st.language == language
        ]
        if not candidates_for_lang:
            console.console.print(
                f'[error]No contest-level statement found for language [item]{language}[/item].[/error]',
            )
            raise typer.Exit(1)

        build_statement(
            candidates_for_lang[0],
            contest,
            output_type=output,
            use_samples=samples,
            is_editorial=editorial,
        )


@app.callback()
def callback():
    pass
