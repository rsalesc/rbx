import pathlib

import typer

from rbx import annotations, console
from rbx.box import code, package
from rbx.box.code import SanitizationLevel
from rbx.box.schema import CodeItem

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


def _compile_out():
    return package.get_build_path() / 'exe'


def _compile(item: CodeItem, sanitized: SanitizationLevel):
    console.console.print(f'Compiling [item]{item.path}[/item]...')
    digest = code.compile_item(item, sanitized)
    cacher = package.get_file_cacher()
    out_path = _compile_out()
    cacher.get_file_to_path(digest, out_path)
    out_path.chmod(0o755)

    console.console.print(
        f'[success]Compiled file written at [item]{out_path}[/item][/success]'
    )


def any(path: str, sanitized: bool = False):
    pkg = package.find_problem_package_or_die()

    solution = package.get_solution_or_nil(path)
    if solution is not None:
        _compile(
            solution,
            sanitized=SanitizationLevel.FORCE if sanitized else SanitizationLevel.NONE,
        )
        return

    for generator in pkg.generators:
        if generator.path == pathlib.Path(path) or generator.name == path:
            _compile(
                generator,
                sanitized=SanitizationLevel.FORCE
                if sanitized
                else SanitizationLevel.PREFER,
            )
            return

    if pkg.checker is not None and pkg.checker.path == pathlib.Path(path):
        _compile(
            pkg.checker,
            sanitized=SanitizationLevel.FORCE
            if sanitized
            else SanitizationLevel.PREFER,
        )
        return

    if pkg.validator is not None and pkg.validator.path == pathlib.Path(path):
        _compile(
            pkg.validator,
            sanitized=SanitizationLevel.FORCE
            if sanitized
            else SanitizationLevel.PREFER,
        )
        return

    _compile(
        CodeItem(path=pathlib.Path(path)),
        sanitized=SanitizationLevel.FORCE if sanitized else SanitizationLevel.NONE,
    )
