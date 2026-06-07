import pathlib
import shutil
from typing import Optional

import typer

from rbx import annotations, console
from rbx.box import header, package, remote
from rbx.box.schema import CodeItem
from rbx.config import get_builtin_checker
from rbx.grading import steps

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


def get_local_artifact(name: str) -> Optional[steps.GradingFileInput]:
    path = pathlib.Path(name)
    if path.is_file():
        return steps.GradingFileInput(src=path, dest=path)
    return None


def _resolve_download_target(name: str, into: Optional[str]) -> pathlib.Path:
    # Callers are guarded by @package.within_problem, so cwd is the package root.
    if into is None:
        return pathlib.Path(name)
    target = pathlib.Path.cwd() / into
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


# Builtin headers are injected into the reserved __internal__/ directory (exposed
# via -I__internal__) so quoted #includes like "testlib.h" resolve from any source
# location, flat or nested. A user's own header of the same name still wins when it
# sits next to the source, since quoted includes are resolved source-relative first;
# otherwise the builtin in __internal__/ is used as the fallback.
def maybe_add_rbx_header(code: CodeItem, artifacts: steps.GradingArtifacts):
    header.get_header()
    artifact = get_local_artifact('rbx.h')
    assert artifact is not None
    artifact.dest = steps.INTERNAL_DIR / artifact.dest
    artifacts.inputs.append(artifact)


_INTO_HELP = (
    'Path (relative to the package root) where the file should be placed. '
    'Parent directories are created automatically. If omitted, the file is '
    'written to the current directory.'
)


def _download_libraries(name: Optional[str], into: Optional[str]) -> None:
    from rbx.box import libraries as box_libraries
    from rbx.box.presets import library_fetch

    declared = box_libraries.get_declared_libraries()
    if name is None:
        if into is not None:
            console.console.print('[error]--into requires a library name.[/error]')
            raise typer.Exit(1)
        targets = declared
        if not targets:
            console.console.print(
                '[warning]The active preset declares no libraries.[/warning]'
            )
            return
    else:
        targets = [lib for lib in declared if lib.name == name]
        if not targets:
            console.console.print(
                f'[error]No library named [item]{name}[/item] is declared by the '
                'active preset.[/error]'
            )
            raise typer.Exit(1)

    for library in targets:
        cached = library_fetch.fetch_library(library)
        if into is not None:
            target = _resolve_download_target(library.dest.name, into)
            shutil.copyfile(cached, target)
            console.console.print(
                f'Downloaded [item]{library.name}[/item] into [item]{target}[/item].'
            )
        else:
            library_fetch.materialize_library(library, cached, pathlib.Path.cwd())
            console.console.print(
                f'Downloaded [item]{library.name}[/item] to [item]{library.dest}[/item].'
            )


@app.command(
    'lib, library', help='Download preset-declared libraries (omit NAME for all).'
)
@package.within_problem
def lib(
    name: Optional[str] = typer.Argument(
        None, help='Library name; omit to (re)fetch all declared libraries.'
    ),
    into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP),
):
    _download_libraries(name, into)


@app.command('testlib', help='Download the preset-declared testlib library.')
@package.within_problem
def testlib(into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP)):
    _download_libraries('testlib', into)


@app.command('jngen', help='Download the preset-declared jngen library.')
@package.within_problem
def jngen(into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP)):
    _download_libraries('jngen', into)


@app.command('tgen', help='Download the preset-declared tgen library.')
@package.within_problem
def tgen(into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP)):
    _download_libraries('tgen', into)


@app.command('checker', help='Download a built-in checker from testlib GH repo.')
@package.within_problem
def checker(name: str):
    if not name.endswith('.cpp'):
        name = f'{name}.cpp'
    path = get_builtin_checker(name)
    shutil.copyfile(path, pathlib.Path(name))
    console.console.print(
        f'[success]Downloaded [item]{name}[/item] into current package.[/success]'
    )


@app.command('remote, r', help='Download a remote code.')
@package.within_problem
def remote_cmd(
    name: str,
    output: Optional[str] = typer.Option(
        None,
        '-o',
        '--output',
        help='Whether to not build outputs for tests and run checker.',
    ),
):
    path = remote.expand_file(name)

    if output is not None:
        pathlib.Path(output).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(path), output)
