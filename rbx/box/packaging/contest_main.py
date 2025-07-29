import pathlib
import tempfile
from typing import Optional, Type

import syncer
import typer

from rbx import annotations, console
from rbx.box import cd, environment, limits_info, package
from rbx.box.contest import build_contest_statements, contest_package
from rbx.box.packaging.packager import (
    BaseContestPackager,
    BasePackager,
    BuiltContestStatement,
    BuiltProblemPackage,
    ContestZipper,
    run_packager,
)

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


async def run_contest_packager(
    contest_packager_cls: Type[BaseContestPackager],
    packager_cls: Type[BasePackager],
    verification: environment.VerificationParam,
    **kwargs,
):
    contest = contest_package.find_contest_package_or_die()

    if limits_info.get_saved_limits_profile(contest_packager_cls.name()) is not None:
        console.console.print(
            f'[warning]Using saved limits profile for [item]{contest_packager_cls.name()}[/item].[/warning]'
        )

    # Build problem-level packages.
    built_packages = []
    for problem in contest.problems:
        console.console.print(
            f'Processing problem [item]{problem.short_name}[/item]...'
        )
        with cd.new_package_cd(problem.get_path()):
            package.clear_package_cache()
            package_path = await run_packager(
                packager_cls, verification=verification, **kwargs
            )
            built_packages.append(
                BuiltProblemPackage(
                    path=problem.get_path() / package_path,
                    package=package.find_problem_package_or_die(),
                    problem=problem,
                )
            )

    # Build statements.
    packager = contest_packager_cls(**kwargs)
    statement_types = packager.statement_types()
    built_statements = []

    with limits_info.use_profile(contest_packager_cls.name()):
        for statement_type in statement_types:
            languages = packager.languages()
            for language in languages:
                statement = packager.get_statement_for_language(language)
                statement_path = build_contest_statements.build_statement(
                    statement, contest, statement_type
                )
                built_statements.append(
                    BuiltContestStatement(statement, statement_path, statement_type)
                )

    console.console.print(f'Packaging contest for [item]{packager.name()}[/item]...')

    # Build contest-level package.
    with tempfile.TemporaryDirectory() as td, limits_info.use_profile(
        contest_packager_cls.name()
    ):
        result_path = packager.package(
            built_packages, pathlib.Path('build'), pathlib.Path(td), built_statements
        )

    console.console.print(
        f'[success]Created contest package for [item]{packager.name()}[/item] at [item]{result_path}[/item]![/success]'
    )


@app.command('polygon', help='Build a contest package for Polygon.')
@contest_package.within_contest
@syncer.sync
async def polygon(
    verification: environment.VerificationParam,
    language: Optional[str] = typer.Option(
        None,
        '--language',
        '-l',
        help='If set, will use the given language as the main language.',
    ),
):
    from rbx.box.packaging.polygon.packager import (
        PolygonContestPackager,
        PolygonPackager,
    )

    await run_contest_packager(
        PolygonContestPackager,
        PolygonPackager,
        verification=verification,
        main_language=language,
    )


@app.command('boca', help='Build a contest package for BOCA.')
@contest_package.within_contest
@syncer.sync
async def boca(
    verification: environment.VerificationParam,
):
    from rbx.box.packaging.boca.packager import BocaPackager

    class BocaContestPackager(ContestZipper):
        def __init__(self, **kwargs):
            super().__init__('boca-contest', zip_inner=True, **kwargs)

        def name(self) -> str:
            return 'boca'

    await run_contest_packager(
        BocaContestPackager, BocaPackager, verification=verification
    )


@app.command('pkg', help='Build a contest package for PKG.')
@contest_package.within_contest
@syncer.sync
async def pkg(
    verification: environment.VerificationParam,
):
    from rbx.box.packaging.pkg.packager import PkgContestPackager, PkgPackager

    await run_contest_packager(
        PkgContestPackager, PkgPackager, verification=verification
    )
