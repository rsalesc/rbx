import contextlib
import functools
import pathlib
from typing import List, Optional

import typer

from rbx import console, utils
from rbx.box.sanitizers import warning_stack
from rbx.utils import new_cd


def find_package(
    root: pathlib.Path = pathlib.Path(), consider_presets: bool = False
) -> Optional[pathlib.Path]:
    root = utils.abspath(root)

    def has_file():
        problem_yaml_path = root / 'problem.rbx.yml'
        contest_yaml_path = root / 'contest.rbx.yml'
        preset_yaml_path = root / 'preset.rbx.yml'
        return (
            problem_yaml_path.is_file()
            or contest_yaml_path.is_file()
            or (consider_presets and preset_yaml_path.is_file())
        )

    while root != pathlib.PosixPath('/') and not has_file():
        root = root.parent
    if not has_file():
        return None
    return root


def find_all_ancestor_packages(
    root: pathlib.Path = pathlib.Path(),
) -> List[pathlib.Path]:
    packages = []
    while (pkg := find_package(root)) is not None:
        packages.append(pkg)
        root = pkg.parent
    return packages


def is_problem_package(root: pathlib.Path = pathlib.Path()) -> bool:
    dir = find_package(root)
    if dir is None:
        return False
    return (dir / 'problem.rbx.yml').is_file()


def is_contest_package(root: pathlib.Path = pathlib.Path()) -> bool:
    dir = find_package(root)
    if dir is None:
        return False
    return (dir / 'contest.rbx.yml').is_file()


def is_preset_package(root: pathlib.Path = pathlib.Path()) -> bool:
    dir = find_package(root, consider_presets=True)
    if dir is None:
        return False
    return (dir / 'preset.rbx.yml').is_file()


def within_closest_package(func, consider_presets: bool = False):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        package = find_package(consider_presets=consider_presets)
        if package is None:
            console.console.print('[error]No rbx package found.[/error]')
            raise typer.Exit(1)
        # Get deepest package.
        with new_package_cd(package):
            return func(*args, **kwargs)

    return wrapper


def within_closest_wrapper(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        package = find_package(consider_presets=True)
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
