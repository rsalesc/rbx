import pathlib
import shutil
from typing import Optional

import typer

from rbx import annotations, console
from rbx.box import header, package, remote
from rbx.box.schema import CodeItem
from rbx.config import (
    download_jngen,
    download_testlib,
    download_tgen,
    get_builtin_checker,
)
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


def maybe_add_testlib(code: CodeItem, artifacts: steps.GradingArtifacts):
    # Prefer a testlib.h shipped at the package root, else fall back to the tool's.
    artifact = get_local_artifact('testlib.h') or steps.testlib_grading_input()
    artifact.dest = steps.INTERNAL_DIR / artifact.dest
    artifacts.inputs.append(artifact)


def maybe_add_jngen(code: CodeItem, artifacts: steps.GradingArtifacts):
    # Prefer a jngen.h shipped at the package root, else fall back to the tool's.
    artifact = get_local_artifact('jngen.h') or steps.jngen_grading_input()
    artifact.dest = steps.INTERNAL_DIR / artifact.dest
    artifacts.inputs.append(artifact)


def maybe_add_tgen(code: CodeItem, artifacts: steps.GradingArtifacts):
    # Prefer a tgen.h shipped at the package root, else fall back to the tool's.
    artifact = get_local_artifact('tgen.h') or steps.tgen_grading_input()
    artifact.dest = steps.INTERNAL_DIR / artifact.dest
    artifacts.inputs.append(artifact)


_INTO_HELP = (
    'Path (relative to the package root) where the file should be placed. '
    'Parent directories are created automatically. If omitted, the file is '
    'written to the current directory.'
)


@app.command('testlib', help='Download the latest testlib.h')
@package.within_problem
def testlib(
    into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP),
):
    target = _resolve_download_target('testlib.h', into)
    shutil.copyfile(download_testlib(), target)
    console.console.print(
        f'Downloaded [item]testlib.h[/item] into [item]{target}[/item].'
    )


@app.command('jngen', help='Download the latest jngen.h')
@package.within_problem
def jngen(
    into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP),
):
    target = _resolve_download_target('jngen.h', into)
    shutil.copyfile(download_jngen(), target)
    console.console.print(
        f'Downloaded [item]jngen.h[/item] into [item]{target}[/item].'
    )


@app.command('tgen', help='Download the latest tgen.h')
@package.within_problem
def tgen(
    into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP),
):
    target = _resolve_download_target('tgen.h', into)
    shutil.copyfile(download_tgen(), target)
    console.console.print(f'Downloaded [item]tgen.h[/item] into [item]{target}[/item].')


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
