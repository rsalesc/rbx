import atexit
import pathlib
import shutil
import tempfile
import zipfile
from typing import Annotated, Optional

import syncer
import typer

from rbx import annotations, console
from rbx.box.tooling.boca import main as boca_main

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)

app.add_typer(boca_main.app, name='boca')


@app.command('convert')
@syncer.sync
async def convert(
    pkg: Annotated[pathlib.Path, typer.Argument(help='The package to convert.')],
    source: Annotated[
        str, typer.Option('-s', '--source', help='The format to convert from.')
    ],
    dest: Annotated[
        str, typer.Option('-d', '--dest', help='The format to convert to.')
    ],
    output: Annotated[str, typer.Option('-o', '--output', help='The output path.')],
    language: Annotated[
        Optional[str],
        typer.Option('--language', '-l', help='The main language of the problem.'),
    ] = None,
):
    from rbx.box.tooling import converter

    if pkg.suffix == '.zip':
        temp_dir = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(pkg, 'r') as zip_ref:
            zip_ref.extractall(temp_dir.name)
        pkg = pathlib.Path(temp_dir.name)

        atexit.register(temp_dir.cleanup)

    if not pkg.is_dir():
        console.console.print(f'[error]Package {pkg} is not a directory.[/error]')
        raise typer.Exit(1)

    with tempfile.TemporaryDirectory() as td:
        result_path = await converter.convert(
            pkg, pathlib.Path(td), source, dest, main_language=language
        )
        output_path = pathlib.Path(output)
        if output_path.suffix == '.zip':
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(result_path, output_path)
        else:
            output_path.mkdir(parents=True, exist_ok=True)
            shutil.unpack_archive(result_path, output_path)
        console.console.print(
            f'[success]Converted package to [item]{output_path}[/item].[/success]'
        )
