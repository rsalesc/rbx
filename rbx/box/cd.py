import contextlib
import functools
import pathlib
from typing import Optional

import typer

from rbx import console
from rbx.box.sanitizers import warning_stack
from rbx.utils import new_cd


def find_package(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    root = root.resolve()

    def has_file():
        problem_yaml_path = root / 'problem.rbx.yml'
        contest_yaml_path = root / 'contest.rbx.yml'
        return problem_yaml_path.is_file() or contest_yaml_path.is_file()

    while root != pathlib.PosixPath('/') and not has_file():
        root = root.parent
    if not has_file():
        return None
    return root


def within_closest_package(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        package = find_package()
        if package is None:
            console.console.print('[error]No rbx package found.[/error]')
            raise typer.Exit(1)
        # Get deepest package.
        with new_package_cd(package):
            return func(*args, **kwargs)

    return wrapper


@contextlib.contextmanager
def new_package_cd(x: pathlib.Path):
    with new_cd(x):
        yield
        warning_stack.print_warning_stack_report()
