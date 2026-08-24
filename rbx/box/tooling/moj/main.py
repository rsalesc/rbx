from typing import Optional

import syncer
import typer

from rbx import annotations
from rbx.box.contest.contest_package import (
    find_contest_package_or_die,
    within_contest,
)

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


@app.command(
    'summary, sum',
    help='List the problems this contest would upload to MOJ, with their MOJ ids.',
)
@within_contest
@syncer.sync
async def summary_cmd(
    language: Optional[str] = typer.Option(
        None,
        '--language',
        '-l',
        help='If set, will report the title of the statement in the given language. '
        'Leave unset if you want to use the language of the topmost statement, '
        'which is the one `rbx package moj` would upload.',
        autocompletion=annotations._adapt('language'),  # noqa: SLF001
    ),
    porcelain: bool = typer.Option(
        False,
        '--porcelain',
        help='Print one tab-separated line per problem instead of a table, and '
        'send every warning to stderr. Meant for copying and for scripts.',
    ),
):
    from rbx.box.tooling.moj import summary

    contest = find_contest_package_or_die()
    await summary.print_moj_summary(
        contest, main_language=language, porcelain=porcelain
    )
