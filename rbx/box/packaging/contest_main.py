import pathlib
import tempfile
from typing import Optional, Type

import syncer
import typer

from rbx import annotations, console
from rbx.box import cd, environment, limits_info, package, package_utils
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
    packager = contest_packager_cls(**kwargs)
    packager.check_contest()

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
            package_utils.clear_package_cache()
            package_path = await run_packager(
                packager_cls, verification=verification, **kwargs
            )
            if package_path is None:
                continue
            built_packages.append(
                BuiltProblemPackage(
                    path=problem.get_path() / package_path,
                    package=package.find_problem_package_or_die(),
                    problem=problem,
                )
            )

    # Build statements.
    statement_types = packager.statement_types()
    built_statements = []

    with limits_info.use_profile(contest_packager_cls.name()):
        for statement_type in statement_types:
            languages = packager.languages()
            for language in languages:
                statement = packager.get_statement_for_language(language)
                statement_path = await build_contest_statements.build_statement(
                    statement, contest, output_type=statement_type
                )
                built_statements.append(
                    BuiltContestStatement(statement, statement_path, statement_type)
                )

    console.console.print(f'Packaging contest for [item]{packager.name()}[/item]...')

    # Build contest-level package.
    with (
        tempfile.TemporaryDirectory() as td,
        limits_info.use_profile(contest_packager_cls.name()),
    ):
        result_path = packager.package(
            built_packages,
            contest_package.get_contest_build_path(),
            pathlib.Path(td),
            built_statements,
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
        autocompletion=annotations._adapt('language'),  # noqa: SLF001
    ),
    cms: bool = typer.Option(
        False,
        '--cms',
        help=(
            'If set, the package also carries what CMS (cms-dev) reads when '
            'importing it with its Polygon loader: group scoring, problem '
            'statements, a manager for interactive problems and, for contests, '
            'problem directories.'
        ),
    ),
):
    from rbx.box.packaging.cms import settings as cms_settings
    from rbx.box.packaging.cms import support as cms_support
    from rbx.box.packaging.polygon.packager import (
        PolygonContestPackager,
        PolygonPackager,
    )

    if cms:
        cms_settings.warn_for_polygon(cms_settings.resolve())
        # Before any problem is built: one interactive problem fails the lot.
        for problem in contest_package.find_contest_package_or_die().problems:
            with cd.new_package_cd(problem.get_path()):
                package_utils.clear_package_cache()
                cms_support.ensure_supported(package.find_problem_package_or_die())

    await run_contest_packager(
        PolygonContestPackager,
        PolygonPackager,
        verification=verification,
        main_language=language,
        cms=cms,
    )


@app.command(
    'cms-contest',
    help=(
        'Build a CMS contest without its problems, for CMS to attach the tasks of '
        '"rbx contest package polygon --cms" to.'
    ),
)
@contest_package.within_contest
def cms_contest():
    """Build `build/cms-contest.zip`: the contest in CMS's Italian YAML format.

    It carries the CMS contest settings and the CMS languages of `env.rbx.yml`,
    which the Polygon contest importer cannot. No problem is built.
    """
    import shutil

    from rbx.box.packaging.cms import italy_loader
    from rbx.box.packaging.cms import settings as cms_settings

    contest = contest_package.find_contest_package_or_die()
    languages, unmapped = italy_loader.contest_languages()
    if not languages:
        console.console.print(
            '[warning]No language in [item]env.rbx.yml[/item] declares the CMS '
            'languages it maps to, under [item]extensions.cms.languages[/item], so '
            'the contest gets the default languages of CMS.[/warning]'
        )
    elif unmapped:
        console.console.print(
            '[warning]These languages declare no CMS language, so the contest does '
            f'not allow them: [item]{", ".join(unmapped)}[/item].[/warning]'
        )

    build_path = contest_package.get_contest_build_path()
    root = build_path / 'cms-contest'
    shutil.rmtree(root, ignore_errors=True)
    italy_loader.write_contest(
        root / contest.name, contest, cms_settings.resolve(), languages
    )
    result_path = pathlib.Path(
        shutil.make_archive(str(build_path / 'cms-contest'), 'zip', root)
    )

    console.console.print(
        f'[success]Created CMS contest package at [item]{result_path}[/item]![/success]'
    )
    console.console.print(
        'Import every task first, from [item]rbx contest package polygon --cms[/item], '
        'with [item]cmsImportTask -L polygon_task[/item]. Then import the contest, '
        f'which attaches them: [item]cmsImportContest -L italy_yaml {contest.name}[/item]. '
        'Never pass [item]--import-tasks[/item] or [item]--update-tasks[/item] to it.'
    )


class BocaContestPackager(ContestZipper):
    def __init__(self, **kwargs):
        super().__init__('boca-contest', zip_inner=True, **kwargs)

    # `name()` is read off the class, never off an instance, so this override
    # has to be a classmethod like every other packager's.
    @classmethod
    def name(cls) -> str:
        return 'boca'


@app.command('boca', help='Build a contest package for BOCA.')
@contest_package.within_contest
@syncer.sync
async def boca(
    verification: environment.VerificationParam,
):
    from rbx.box.packaging.boca.packager import BocaPackager

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
