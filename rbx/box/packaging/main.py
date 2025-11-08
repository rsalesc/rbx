from typing import List, Optional

import syncer
import typer

from rbx import annotations
from rbx.box import environment, package
from rbx.box.naming import get_problem_name_with_contest_info
from rbx.box.packaging.packager import run_packager

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


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
    language: Optional[str] = typer.Option(
        None,
        '--language',
        '-l',
        help='If set, will use the given language as the main language. '
        'Leave unset if your problem has no statements.',
    ),
    upload_as_english: bool = typer.Option(
        False,
        '--upload-as-english',
        help='If set, will force the main statement to be uploaded in English.',
    ),
    upload_only: Optional[List[str]] = typer.Option(  # noqa: B008  # type: ignore
        None,
        '--upload-only',
        help='Only upload the following types of assets to Polygon.',
    ),
    dont_upload: Optional[List[str]] = typer.Option(  # noqa: B008  # type: ignore
        None,
        '--upload-skip',
        help='Skip uploading the following types of assets to Polygon.',
    ),
):
    from rbx.box.packaging.polygon.packager import PolygonPackager

    await run_packager(
        PolygonPackager, verification=verification, main_language=language
    )

    if upload:
        from rbx.box.packaging.polygon.upload import upload_problem

        await upload_problem(
            name=get_problem_name_with_contest_info(),
            main_language=language,
            upload_as_english=upload_as_english,
            upload_only=set(upload_only or []),
            dont_upload=set(dont_upload or []),
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
    language: Optional[str] = typer.Option(
        None,
        '--language',
        '-l',
        help='If set, will use the given language as the main language. '
        'Leave unset if you want to use the language of the topmost statement.',
    ),
):
    from rbx.box.packaging.boca.packager import BocaPackager

    result_path = await run_packager(
        BocaPackager, verification=verification, language=language
    )

    if upload:
        from rbx.box.tooling.boca.scraper import get_boca_scraper

        uploader = get_boca_scraper()
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


@app.command('pkg', help='Build a package for PKG.')
@package.within_problem
@syncer.sync
async def pkg(
    verification: environment.VerificationParam,
):
    from rbx.box.packaging.pkg.packager import PkgPackager

    await run_packager(PkgPackager, verification=verification)
