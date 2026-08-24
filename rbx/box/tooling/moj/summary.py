"""The problems a contest would upload to MOJ, and the ids they would land on.

Every column is resolved the way `rbx package moj` resolves it -- the title
through `moj_statement.get_display_title`, the id through
`upload.build_problem_id` over the packager's own `package_basename()` -- so the
table is a preview of the upload rather than a second guess at it.

Nothing here builds a package or talks to the judge. The one thing that can need
a live session is the org: without `extensions.moj.org` the ids fall back to your
login, and reading it costs a `moj whoami` (see `upload.resolve_org`).
"""

from typing import List, Optional

from pydantic import BaseModel
from rich.table import Table

from rbx import console
from rbx.box import cd, package_utils
from rbx.box.contest.schema import Contest, ContestProblem
from rbx.box.packaging.moj import statement as moj_statement
from rbx.box.packaging.moj import upload
from rbx.box.packaging.moj.packager import MojPackager


class MojProblemSummary(BaseModel):
    """One row: what a problem in this contest becomes on MOJ."""

    short_name: str
    title: Optional[str] = None
    problem_id: Optional[str] = None
    color: Optional[str] = None
    color_name: Optional[str] = None
    # Set when the problem could not be read at all. The row is still emitted:
    # a listing that silently drops a problem reads as a contest that has one
    # fewer problem than it does.
    error: Optional[str] = None


def summarize_problem(
    problem: ContestProblem,
    org: str,
    main_language: Optional[str] = None,
) -> MojProblemSummary:
    """Summarize the problem rbx has already `cd`'d into."""
    return MojProblemSummary(
        short_name=problem.short_name,
        title=moj_statement.get_display_title(main_language),
        problem_id=upload.build_problem_id(org, MojPackager.package_basename()),
        color=problem.hex_color,
        color_name=problem.color_name,
    )


async def collect_moj_summary(
    contest: Contest, main_language: Optional[str] = None
) -> List[MojProblemSummary]:
    org, is_personal = await upload.resolve_org()
    if is_personal:
        # The same warning `rbx package moj --upload` gives, and for the same
        # reason: every id below is invisible to everyone but you, and hearing
        # that from a co-setter is worse than hearing it here.
        console.console.print(
            f'[warning]No `extensions.moj.org` is set, so these problems would go '
            f'to the [item]{org}[/item] org -- your private personal org, which '
            f'nobody else can see.[/warning]\n'
            f'[warning]Set `extensions.moj.org` in your `env.rbx.yml` to upload '
            f'them somewhere shared.[/warning]'
        )

    res: List[MojProblemSummary] = []
    for problem in contest.problems:
        try:
            with cd.new_package_cd(problem.get_path()):
                package_utils.clear_package_cache()
                res.append(summarize_problem(problem, org, main_language))
        except Exception as e:
            # The helpers print their own actionable error before raising (an
            # ambiguous title, a missing statement in the requested language), so
            # this adds the one thing they cannot know: which problem it was
            # about. Reported and skipped rather than fatal -- one unreadable
            # problem should not hide the ids of every other one.
            console.console.print(
                f'[error]Failed to summarize problem '
                f'[item]{problem.short_name}[/item].[/error]'
            )
            res.append(
                MojProblemSummary(short_name=problem.short_name, error=str(e) or None)
            )
    return res


def _color_cell(entry: MojProblemSummary) -> str:
    if entry.color is None:
        return '[dim]-[/dim]'
    name = entry.color_name or 'unknown'
    return f'[{entry.color}]●[/{entry.color}] {name} [dim]{entry.color}[/dim]'


def render_moj_summary(contest: Contest, entries: List[MojProblemSummary]) -> Table:
    table = Table(title=f'MOJ upload summary: {contest.name}')
    table.add_column('#', justify='center', style='bold cyan')
    table.add_column('Title', style='bold')
    table.add_column('MOJ problem')
    table.add_column('Color')

    for entry in entries:
        if entry.error is not None:
            table.add_row(
                entry.short_name, '[error]failed to read[/error]', '[dim]-[/dim]', ''
            )
            continue
        table.add_row(
            entry.short_name,
            entry.title,
            entry.problem_id,
            _color_cell(entry),
        )

    return table


async def print_moj_summary(contest: Contest, main_language: Optional[str] = None):
    entries = await collect_moj_summary(contest, main_language=main_language)
    console.console.print(render_moj_summary(contest, entries))
