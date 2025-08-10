from typing import Annotated, List, Optional

import syncer
import typer

from rbx import annotations, console
from rbx.box import cd, environment, package
from rbx.box.contest.build_contest_statements import (
    StatementBuildIssue,
    build_statement,
)
from rbx.box.contest.contest_package import (
    find_contest_package_or_die,
    within_contest,
)
from rbx.box.contest.schema import ContestStatement
from rbx.box.formatting import href
from rbx.box.sanitizers import issue_stack
from rbx.box.schema import expand_any_vars
from rbx.box.statements.schema import StatementType

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


@app.command('build, b', help='Build statements.')
@within_contest
@syncer.sync
async def build(
    verification: environment.VerificationParam,
    names: Annotated[
        Optional[List[str]],
        typer.Argument(
            help='Names of statements to build.',
        ),
    ] = None,
    languages: Annotated[
        Optional[List[str]],
        typer.Option(
            help='Languages to build statements for. If not specified, build statements for all available languages.',
        ),
    ] = None,
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
    vars: Annotated[
        Optional[List[str]],
        typer.Option(
            '--vars',
            help='Variables to be used in the statements.',
        ),
    ] = None,
    install_tex: Annotated[
        bool,
        typer.Option(help='Whether to install missing LaTeX packages.'),
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

                try:
                    if not await builder.build(
                        verification=verification, groups=set(['samples']), output=None
                    ):
                        issue_stack.add_issue(StatementBuildIssue(problem))
                except Exception:
                    issue_stack.add_issue(StatementBuildIssue(problem))

    contest = find_contest_package_or_die()

    candidate_languages = set(languages or [])
    candidate_names = set(names or [])

    def should_process(st: ContestStatement) -> bool:
        if candidate_languages and st.language not in candidate_languages:
            return False
        if candidate_names and st.name not in candidate_names:
            return False
        return True

    valid_statements = [st for st in contest.expanded_statements if should_process(st)]

    if not valid_statements:
        console.console.print(
            '[error]No statement found according to the specified criteria.[/error]',
        )
        raise typer.Exit(1)

    built_statements = []

    for statement in valid_statements:
        built_statements.append(
            build_statement(
                statement,
                contest,
                output_type=output,
                use_samples=samples,
                install_tex=install_tex,
                custom_vars=expand_any_vars(annotations.parse_dictionary_items(vars)),
            )
        )

    console.console.rule(title='Built statements')
    for statement, built_path in zip(valid_statements, built_statements):
        console.console.print(
            f'[item]{statement.name} {statement.language}[/item] -> {href(built_path)}'
        )


@app.callback()
def callback():
    pass
