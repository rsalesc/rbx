import pathlib
import tempfile
from typing import Optional

import typer

from rbx import console
from rbx.box import builder, cd, package
from rbx.box.environment import VerificationLevel
from rbx.box.packaging.boca.packager import BocaPackager
from rbx.box.packaging.importer import BaseImporter
from rbx.box.packaging.moj.packager import MojPackager
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.packaging.polygon.importer import PolygonImporter
from rbx.box.packaging.polygon.packager import PolygonPackager
from rbx.box.statements.build_statements import build_statement

PACKAGER_REGISTRY = {
    'polygon': PolygonPackager,
    'boca': BocaPackager,
    'moj': MojPackager,
}

IMPORTER_REGISTRY = {
    'polygon': PolygonImporter,
}


def get_packager(source: str, **kwargs) -> BasePackager:
    if source not in PACKAGER_REGISTRY:
        console.console.print(f'Unknown packager: {source}')
        raise typer.Exit(1)
    return PACKAGER_REGISTRY[source](**kwargs)


def get_importer(source: str, **kwargs) -> BaseImporter:
    if source not in IMPORTER_REGISTRY:
        console.console.print(f'Unknown importer: {source}')
        raise typer.Exit(1)
    return IMPORTER_REGISTRY[source](**kwargs)


async def convert(
    pkg_dir: pathlib.Path,
    into_dir: pathlib.Path,
    source: str,
    destination: str,
    main_language: Optional[str] = None,
) -> pathlib.Path:
    importer = get_importer(source, main_language=main_language)
    packager = get_packager(destination)
    await importer.import_package(pkg_dir, into_dir)

    with cd.new_package_cd(into_dir):
        package.clear_package_cache()

        pkg = package.find_problem_package_or_die()

        if not await builder.build(VerificationLevel.NONE.value):
            console.console.print('[error]Failed to build the problem.[/error]')
            raise typer.Exit(1)

        built_statements = []
        for statement_type in packager.statement_types():
            for language in packager.languages():
                statement = packager.get_statement_for_language_or_die(language)
                statement_path = build_statement(statement, pkg, statement_type)
                built_statements.append(
                    BuiltStatement(statement, statement_path, statement_type)
                )

        with tempfile.TemporaryDirectory() as td:
            result_path = packager.package(
                package.get_build_path(), pathlib.Path(td), built_statements
            )
            return result_path
