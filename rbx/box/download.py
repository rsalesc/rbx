import pathlib
import shutil
from typing import Optional

import typer

from rbx import annotations, console
from rbx.box import header, package, remote
from rbx.box.schema import CodeItem
from rbx.config import get_builtin_checker, get_jngen, get_testlib
from rbx.grading import steps

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


def get_local_artifact(name: str) -> Optional[steps.GradingFileInput]:
    path = pathlib.Path(name)
    if path.is_file():
        return steps.GradingFileInput(src=path, dest=path)
    return None


def maybe_add_rbx_header(code: CodeItem, artifacts: steps.GradingArtifacts):
    header.get_header()
    artifact = get_local_artifact('rbx.h')
    assert artifact is not None
    compilation_files = package.get_compilation_files(code)
    if any(dest == artifact.dest for _, dest in compilation_files):
        return
    artifacts.inputs.append(artifact)


def maybe_add_testlib(code: CodeItem, artifacts: steps.GradingArtifacts):
    # Try to get from compilation files, then from package folder, then from tool.
    artifact = get_local_artifact('testlib.h') or steps.testlib_grading_input()
    compilation_files = package.get_compilation_files(code)
    if any(dest == artifact.dest for _, dest in compilation_files):
        return
    artifacts.inputs.append(artifact)


def maybe_add_jngen(code: CodeItem, artifacts: steps.GradingArtifacts):
    # Try to get from compilation files, then from package folder, then from tool.
    artifact = get_local_artifact('jngen.h') or steps.jngen_grading_input()
    compilation_files = package.get_compilation_files(code)
    if any(dest == artifact.dest for _, dest in compilation_files):
        return
    artifacts.inputs.append(artifact)


@app.command('testlib', help='Download testlib.h')
@package.within_problem
def testlib():
    shutil.copyfile(get_testlib(), pathlib.Path('testlib.h'))
    console.console.print('Downloaded [item]testlib.h[/item] into current package.')


@app.command('jngen', help='Download jngen.h')
@package.within_problem
def jngen():
    shutil.copyfile(get_jngen(), pathlib.Path('jngen.h'))
    console.console.print('Downloaded [item]jngen.h[/item] into current package.')


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
