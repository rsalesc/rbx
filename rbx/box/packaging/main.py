import pathlib
import tempfile
from typing import Type

import syncer
import typer

from rbx import annotations, console
from rbx.box import environment, header, package
from rbx.box.formatting import href
from rbx.box.naming import get_problem_name_with_contest_info
from rbx.box.package import get_build_path
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.statements.build_statements import build_statement

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


async def run_packager(
    packager_cls: Type[BasePackager],
    verification: environment.VerificationParam,
    **kwargs,
) -> pathlib.Path:
    from rbx.box import builder

    header.generate_header()

    if not await builder.verify(verification=verification):
        console.console.print(
            '[error]Build or verification failed, check the report.[/error]'
        )
        raise typer.Exit(1)

    pkg = package.find_problem_package_or_die()

    if pkg.type not in packager_cls.task_types():
        console.console.print(
            f'[error]Packager [item]{packager_cls.name()}[/item] does not support task type [item]{pkg.type}[/item].[/error]'
        )
        raise typer.Exit(1)

    packager = packager_cls(**kwargs)

    statement_types = packager.statement_types()
    built_statements = []

    for statement_type in statement_types:
        languages = packager.languages()
        for language in languages:
            statement = packager.get_statement_for_language(language)
            statement_path = build_statement(statement, pkg, statement_type)
            built_statements.append(
                BuiltStatement(statement, statement_path, statement_type)
            )

    console.console.print(f'Packaging problem for [item]{packager.name()}[/item]...')

    with tempfile.TemporaryDirectory() as td:
        result_path = packager.package(
            get_build_path(), pathlib.Path(td), built_statements
        )

    console.console.print(
        f'[success]Problem packaged for [item]{packager.name()}[/item]![/success]'
    )
    console.console.print(f'Package was saved at {href(result_path)}')
    return result_path


@app.command('polygon', help='Build a package for Polygon.')
@package.within_problem
@syncer.sync
async def polygon(
    verification: environment.VerificationParam,
    upload: bool = typer.Option(
        False,
        '--upload',
        '-u',
        help='If set, will upload the package to Polygon.',
    ),
    preserve_language: bool = typer.Option(
        False,
        '--preserve-language',
        help='If set, will preserve the original language of the statement.',
    ),
):
    from rbx.box.packaging.polygon.packager import PolygonPackager

    await run_packager(PolygonPackager, verification=verification)

    if upload:
        from rbx.box.packaging.polygon.upload import upload_problem

        await upload_problem(
            name=get_problem_name_with_contest_info(),
            preserve_language=preserve_language,
        )


@app.command('boca', help='Build a package for BOCA.')
@package.within_problem
@syncer.sync
async def boca(
    verification: environment.VerificationParam,
    upload: bool = typer.Option(
        False,
        '--upload',
        '-u',
        help='If set, will upload the package to BOCA.',
    ),
):
    from rbx.box.packaging.boca.packager import BocaPackager

    result_path = await run_packager(BocaPackager, verification=verification)

    if upload:
        from rbx.box.packaging.boca.upload import get_boca_uploader

        uploader = get_boca_uploader()
        uploader.login_and_upload(result_path)


@app.command('moj', help='Build a package for MOJ.')
@package.within_problem
@syncer.sync
async def moj(
    verification: environment.VerificationParam,
    for_boca: bool = typer.Option(
        False, help='Build a package for BOCA instead of MOJ.'
    ),
):
    from rbx.box.packaging.moj.packager import MojPackager

    await run_packager(MojPackager, verification=verification, for_boca=for_boca)
