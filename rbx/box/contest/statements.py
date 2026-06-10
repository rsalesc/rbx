from typing import Annotated, List, Optional

import syncer
import typer

from rbx import annotations, console
from rbx.box import cd, environment, limits_info, package_utils
from rbx.box.contest.build_contest_statements import (
    StatementBuildIssue,
    build_document,
    build_statement,
)
from rbx.box.contest.contest_package import (
    find_contest_package_or_die,
    within_contest,
)
from rbx.box.contest.schema import ContestProblem
from rbx.box.formatting import href
from rbx.box.sanitizers import issue_stack
from rbx.box.schema import expand_any_vars
from rbx.box.statements.schema import StatementKind, StatementType

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)
# Parallel app for contest-level tutorials (editorials), mounted as `tutorials,
# tut`. Reuses the same build pipeline as statements (StatementKind.TUTORIALS).
tutorials_app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


async def _execute_build(
    *,
    verification: environment.VerificationParam,
    names: Optional[List[str]],
    languages: Optional[List[str]],
    validate: bool,
    output: StatementType,
    samples: bool,
    vars: Optional[List[str]],
    install_tex: bool,
    profile: Optional[str],
    kind: StatementKind,
    build_documents: bool,
) -> None:
    """Shared body of ``rbx contest st b`` / ``rbx contest tut b``.

    Builds the contest's ``statements`` or ``tutorials`` (per ``kind``), joining
    each problem's matching entry. Contest ``documents`` (infosheets) are emitted
    only on the statements command (``build_documents``), never the tutorials one.
    """
    contest = find_contest_package_or_die()

    eligible_problems: List[ContestProblem] = list(contest.problems)
    if profile is not None:
        eligible_problems = []
        for problem in contest.problems:
            saved = limits_info.get_saved_limits_profile(
                profile, root=problem.get_path()
            )
            if saved is None:
                console.console.print(
                    f'[warning]Skipping problem [item]{problem.short_name}[/item]: timing profile [item]{profile}[/item] is not defined for it.[/warning]'
                )
                continue
            eligible_problems.append(problem)
        if not eligible_problems:
            console.console.print(
                f'[error]No problems in this contest define the timing profile [item]{profile}[/item].[/error]'
            )
            raise typer.Exit(1)

    candidate_languages = set(languages or [])
    candidate_names = set(names or [])

    def should_process(st) -> bool:
        if candidate_languages and st.language not in candidate_languages:
            return False
        if candidate_names and st.name not in candidate_names:
            return False
        return True

    all_statements = (
        contest.expanded_tutorials
        if kind == StatementKind.TUTORIALS
        else contest.expanded_statements
    )
    valid_statements = [st for st in all_statements if should_process(st)]

    if not valid_statements:
        console.console.print(
            f'[error]No {kind.singular} found according to the specified criteria.[/error]',
        )
        raise typer.Exit(1)

    # TODO: possibly check the problem configuration for samples too
    samples = samples and any(st.samples for st in valid_statements)

    # At most run the validators, only in samples.
    problems_of_interest: Optional[List[ContestProblem]] = None
    if samples:
        from rbx.box.testcase_sample_utils import build_samples

        problems_of_interest = []
        for problem in eligible_problems:
            console.console.print(
                f'Processing problem [item]{problem.short_name}[/item]...'
            )
            with cd.new_package_cd(problem.get_path()):
                package_utils.clear_package_cache()

                try:
                    if not await build_samples(verification, validate):
                        issue_stack.add_issue(StatementBuildIssue(problem))
                    else:
                        problems_of_interest.append(problem)
                except Exception:
                    issue_stack.add_issue(StatementBuildIssue(problem))

    if profile is not None and problems_of_interest is None:
        problems_of_interest = eligible_problems

    built_statements = []
    built_documents = []
    valid_documents = (
        [doc for doc in contest.expanded_documents if should_process(doc)]
        if build_documents
        else []
    )

    with limits_info.use_profile(profile, when=lambda: profile is not None):
        for statement in valid_statements:
            built_statements.append(
                await build_statement(
                    statement,
                    contest,
                    problems_of_interest=problems_of_interest,
                    output_type=output,
                    use_samples=samples,
                    install_tex=install_tex,
                    custom_vars=expand_any_vars(
                        annotations.parse_dictionary_items(vars)
                    ),
                    kind=kind,
                )
            )

        # Documents (infosheets etc.) don't join problem statements or samples,
        # but may read problem metadata (e.g. an info sheet's limits table), so
        # pass the eligible problems and resolve their limits under the active
        # profile (hence inside the use_profile block).
        for document in valid_documents:
            built_documents.append(
                await build_document(
                    document,
                    contest,
                    problems_of_interest=eligible_problems,
                    output_type=output,
                    custom_vars=expand_any_vars(
                        annotations.parse_dictionary_items(vars)
                    ),
                )
            )

    console.console.rule(title=f'Built {kind.value}')
    for statement, built_path in zip(valid_statements, built_statements):
        console.console.print(
            f'[item]{statement.name} {statement.language}[/item] -> {href(built_path)}'
        )
    for document, built_path in zip(valid_documents, built_documents):
        console.console.print(
            f'[item]{document.name} {document.language}[/item] (document) -> {href(built_path)}'
        )


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
    validate: Annotated[
        bool,
        typer.Option(help='Whether to validate outputs for testcases or not.'),
    ] = True,
    output: Annotated[
        StatementType,
        typer.Option(
            case_sensitive=False,
            help='Output type to be generated.',
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
    profile: Annotated[
        Optional[str],
        typer.Option(
            '-p',
            '--profile',
            help='Timing profile to render statements against. Problems missing this profile are skipped with a warning.',
            autocompletion=annotations._adapt('profile'),  # noqa: SLF001
        ),
    ] = None,
):
    await _execute_build(
        verification=verification,
        names=names,
        languages=languages,
        validate=validate,
        output=output,
        samples=samples,
        vars=vars,
        install_tex=install_tex,
        profile=profile,
        kind=StatementKind.STATEMENTS,
        build_documents=True,
    )


@app.callback()
def callback():
    pass


@tutorials_app.command('build, b', help='Build tutorials (editorials).')
@within_contest
@syncer.sync
async def build_tutorials(
    verification: environment.VerificationParam,
    names: Annotated[
        Optional[List[str]],
        typer.Argument(
            help='Names of tutorials to build.',
        ),
    ] = None,
    languages: Annotated[
        Optional[List[str]],
        typer.Option(
            help='Languages to build tutorials for. If not specified, build tutorials for all available languages.',
        ),
    ] = None,
    validate: Annotated[
        bool,
        typer.Option(help='Whether to validate outputs for testcases or not.'),
    ] = True,
    output: Annotated[
        StatementType,
        typer.Option(
            case_sensitive=False,
            help='Output type to be generated.',
        ),
    ] = StatementType.PDF,
    samples: Annotated[
        bool,
        typer.Option(help='Whether to build the tutorial with samples or not.'),
    ] = True,
    vars: Annotated[
        Optional[List[str]],
        typer.Option(
            '--vars',
            help='Variables to be used in the tutorials.',
        ),
    ] = None,
    install_tex: Annotated[
        bool,
        typer.Option(help='Whether to install missing LaTeX packages.'),
    ] = False,
    profile: Annotated[
        Optional[str],
        typer.Option(
            '-p',
            '--profile',
            help='Timing profile to render tutorials against. Problems missing this profile are skipped with a warning.',
        ),
    ] = None,
):
    await _execute_build(
        verification=verification,
        names=names,
        languages=languages,
        validate=validate,
        output=output,
        samples=samples,
        vars=vars,
        install_tex=install_tex,
        profile=profile,
        kind=StatementKind.TUTORIALS,
        build_documents=False,
    )


@tutorials_app.callback()
def tutorials_callback():
    pass
