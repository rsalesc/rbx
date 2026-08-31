from typing import Annotated, List, Optional, Tuple

import syncer
import typer

from rbx import annotations, console
from rbx.box import (
    cd,
    environment,
    estimation_checksum,
    limits_info,
    package_utils,
)
from rbx.box.contest.build_contest_statements import (
    StatementBuildIssue,
    StatementFailedIssue,
    build_document,
    build_statement,
)
from rbx.box.contest.contest_package import (
    find_contest_package_or_die,
    get_selected_variant_id,
    within_contest,
)
from rbx.box.contest.schema import ContestProblem
from rbx.box.exception import describe_exception
from rbx.box.formatting import href
from rbx.box.sanitizers import issue_stack
from rbx.box.schema import expand_any_vars
from rbx.box.statements.schema import StatementKind, StatementType

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)
# Parallel app for contest-level tutorials (editorials), mounted as `tutorials,
# tut`. Reuses the same build pipeline as statements (StatementKind.TUTORIALS).
tutorials_app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


def built_rule_title(kind: StatementKind, variant_id: Optional[str]) -> str:
    """The summary rule title, naming the contest variant when one is selected
    so it is clear which `build/variants/<id>/` subtree the artifacts landed in."""
    if variant_id is None:
        return f'Built {kind.value}'
    return f'Built {kind.value} (variant: {variant_id})'


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
    partial: bool = False,
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

        # Collected and reported once, naming the problems, rather than warned
        # per problem: a contest has a dozen of these, and the same three-line
        # warning repeated a dozen times buries the build log it precedes.
        stale = []
        for problem in eligible_problems:
            with cd.new_package_cd(problem.get_path()):
                package_utils.clear_package_cache()
                if estimation_checksum.check_profile(profile, light_only=True):
                    stale.append(problem.short_name)
        if stale:
            console.console.print(
                f'[warning]The time limit saved in profile [item]{profile}[/item] is '
                f'stale for [item]{", ".join(stale)}[/item]: the solutions it was '
                f'estimated from have changed since it was estimated.[/warning]'
            )
            console.console.print(
                f'[warning]Re-run [item]rbx time -p {profile}[/item] in those '
                f'problems to refresh it.[/warning]'
            )

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

    # Documents are selectable by name just like statements, so a run that names
    # only documents is legitimate -- bail out only when nothing at all matched.
    valid_documents = (
        [doc for doc in contest.expanded_documents if should_process(doc)]
        if build_documents
        else []
    )

    if not valid_statements and not valid_documents:
        what = f'{kind.singular} or document' if build_documents else str(kind.singular)
        console.console.print(
            f'[error]No {what} found according to the specified criteria.[/error]',
        )
        raise typer.Exit(1)

    # TODO: possibly check the problem configuration for samples too
    samples = samples and any(st.samples for st in valid_statements)

    # At most run the validators, only in samples.
    problems_of_interest: Optional[List[ContestProblem]] = None
    failed_problems: List[ContestProblem] = []
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
                        failed_problems.append(problem)
                    else:
                        problems_of_interest.append(problem)
                except Exception:
                    issue_stack.add_issue(StatementBuildIssue(problem))
                    failed_problems.append(problem)

    if profile is not None and problems_of_interest is None:
        problems_of_interest = eligible_problems

    built_statements = []
    built_documents = []
    failed_statements: List[Tuple[str, str]] = []

    with limits_info.use_profile(profile, when=lambda: profile is not None):
        for statement in valid_statements:
            # Each statement builds in isolation: one that fails must never stop
            # the others, so a broken `en` cannot keep `pt` from being built.
            if failed_problems and not partial:
                # Those problems were dropped from `problems_of_interest`, so
                # building now would silently emit a document missing them.
                # Refuse up-front rather than shipping a short statement.
                dropped = ', '.join(p.short_name for p in failed_problems)
                reason = (
                    f'samples failed for problem(s) {dropped}; pass --partial to '
                    f'build without them'
                )
                console.console.print(
                    f'[error]Skipping {kind.singular} '
                    f'[item]{statement.name}[/item]: {reason}[/error]'
                )
                issue_stack.add_issue(StatementFailedIssue(statement.name, reason))
                failed_statements.append((statement.name, reason))
                continue
            try:
                built_statements.append(
                    (
                        statement,
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
                            partial=partial,
                        ),
                    )
                )
            except Exception as exc:
                reason = describe_exception(exc)
                console.console.print(
                    f'[error]Failed to build {kind.singular} '
                    f'[item]{statement.name}[/item]: {reason}[/error]'
                )
                issue_stack.add_issue(StatementFailedIssue(statement.name, reason))
                failed_statements.append((statement.name, reason))

        # Documents (infosheets etc.) don't join problem statements or samples,
        # but may read problem metadata (e.g. an info sheet's limits table), so
        # pass the eligible problems and resolve their limits under the active
        # profile (hence inside the use_profile block).
        for document in valid_documents:
            try:
                built_documents.append(
                    (
                        document,
                        await build_document(
                            document,
                            contest,
                            problems_of_interest=eligible_problems,
                            output_type=output,
                            custom_vars=expand_any_vars(
                                annotations.parse_dictionary_items(vars)
                            ),
                        ),
                    )
                )
            except Exception as exc:
                reason = describe_exception(exc)
                console.console.print(
                    f'[error]Failed to build document '
                    f'[item]{document.name}[/item]: {reason}[/error]'
                )
                issue_stack.add_issue(StatementFailedIssue(document.name, reason))
                failed_statements.append((document.name, reason))

    console.console.rule(title=built_rule_title(kind, get_selected_variant_id()))
    for statement, built_path in built_statements:
        console.console.print(
            f'[item]{statement.name} {statement.language}[/item] -> {href(built_path)}'
        )
    for document, built_path in built_documents:
        console.console.print(
            f'[item]{document.name} {document.language}[/item] (document) -> {href(built_path)}'
        )

    if failed_statements:
        console.console.rule(title=f'Failed {kind.value}')
        for name, reason in failed_statements:
            console.console.print(f'[error]{name}[/error]: {reason}')

    if failed_problems:
        # The statements that could be built were built, but samples are missing
        # for some problem, so the command as a whole did not succeed.
        console.console.print(
            f'[error]Failed to build samples for [item]{len(failed_problems)}[/item] '
            'problem(s), check the report above.[/error]'
        )

    if failed_statements or failed_problems:
        raise typer.Exit(1)


@app.command('build, b', help='Build statements.')
@within_contest
@syncer.sync
async def build(
    verification: environment.VerificationParam,
    names: Annotated[
        Optional[List[str]],
        typer.Argument(
            help='Names of statements or documents to build.',
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
    partial: Annotated[
        bool,
        typer.Option(
            '--partial',
            help='Build a statement even if some of its problems fail, omitting them. Without this, a problem that fails makes its statement fail.',
        ),
    ] = False,
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
        partial=partial,
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
    partial: Annotated[
        bool,
        typer.Option(
            '--partial',
            help='Build a statement even if some of its problems fail, omitting them. Without this, a problem that fails makes its statement fail.',
        ),
    ] = False,
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
        partial=partial,
    )


@tutorials_app.callback()
def tutorials_callback():
    pass
