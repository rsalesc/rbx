"""`rbx compile`, `rbx validate`, `rbx unit` and `rbx header`.

The one-off commands that act on a single asset.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

import pathlib
import tempfile
from typing import Annotated, List, Optional

import syncer
import typer

from rbx import annotations, console, utils
from rbx.annotations import PackagePath
from rbx.box import (
    compile,
    package,
    validators,
)
from rbx.box.header import generate_header

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'compile',
    rich_help_panel='Testing',
    help='Compile an asset given its path.',
    context_settings={'ignore_unknown_options': True},
)
@package.within_problem
@syncer.sync
async def compile_command(
    path: Annotated[
        Optional[str],
        PackagePath,
        typer.Argument(help='Path to the asset to compile.'),
    ] = None,
    sanitized: bool = typer.Option(
        False,
        '--sanitized',
        '-s',
        help='Whether to compile the asset with sanitizers enabled.',
    ),
    warnings: bool = typer.Option(
        False,
        '--warnings',
        '-w',
        help='Whether to compile the asset with warnings enabled.',
    ),
    all: bool = typer.Option(
        False,
        '--all',
        '-a',
        help='Whether to compile all assets.',
    ),
    extra_flags: Annotated[
        Optional[List[str]],
        typer.Argument(
            metavar='[-- EXTRA_FLAGS...]',
            help='Extra flags to pass to the compiler, after a `--` separator.',
        ),
    ] = None,
):
    extra_flags = list(extra_flags or [])

    # Click fills positional arguments in order and does not report where `--` was,
    # so `rbx compile -- -O0` binds `-O0` to `path`. A leading dash is never a path.
    if path is not None and path.startswith('-'):
        extra_flags.insert(0, path)
        path = None

    if path is None and not all:
        import questionary

        path = await questionary.path("What's the path to your asset?").ask_async()
        if path is None:
            console.console.print('[error]No path specified.[/error]')
            raise typer.Exit(1)

    if all:
        for solution in package.get_solutions():
            await compile.any(
                str(solution.path), sanitized, warnings, extra_flags=extra_flags
            )
        if package.get_checker() is not None:
            await compile.any(
                str(package.get_checker().path),
                sanitized,
                warnings,
                extra_flags=extra_flags,
            )
        if package.get_validator() is not None:
            await compile.any(
                str(package.get_validator().path),
                sanitized,
                warnings,
                extra_flags=extra_flags,
            )
        if package.get_interactor() is not None:
            await compile.any(
                str(package.get_interactor().path),
                sanitized,
                warnings,
                extra_flags=extra_flags,
            )

    if path is not None:
        await compile.any(path, sanitized, warnings, extra_flags=extra_flags)


@app.command(
    'validate',
    rich_help_panel='Testing',
    help='Run the validator in a one-off fashion, interactively.',
)
@package.within_problem
@syncer.sync
async def validate(
    path: Annotated[
        Optional[str],
        PackagePath,
        typer.Option('--path', '-p', help='Path to the testcase to validate.'),
    ] = None,
):
    all_validators = package.get_all_validators()
    if not all_validators:
        console.console.print('[error]No validator found for this problem.[/error]')
        raise typer.Exit(1)

    with utils.StatusProgress('Compiling validators...') as s:
        validators_digests = await validators.compile_validators(
            all_validators, progress=s
        )

    input = console.multiline_prompt('Testcase input')

    if path is None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = pathlib.Path(tmpdir) / '000.in'
            tmppath.write_text(input)

            infos = await validators.validate_one_off(
                pathlib.Path(tmppath), all_validators, validators_digests
            )
    else:
        infos = await validators.validate_one_off(
            pathlib.Path(path), all_validators, validators_digests
        )

    validators.print_validation_report(infos)


@app.command(
    'unit',
    rich_help_panel='Testing',
    help='Run unit tests for the validator and checker.',
)
@package.within_problem
@syncer.sync
async def unit_tests():
    from rbx.box import unit

    with utils.StatusProgress('Running unit tests...') as s:
        await unit.run_unit_tests(s)


@app.command(
    'header',
    rich_help_panel='Configuration',
    help='Generate the rbx.h header file.',
)
@package.within_problem
def header():
    generate_header()
