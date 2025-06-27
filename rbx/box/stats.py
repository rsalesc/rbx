import pathlib
from typing import Iterable, List, Tuple

from rbx import console
from rbx.box.cd import (
    find_all_ancestor_packages,
    is_contest_package,
    is_problem_package,
)
from rbx.box.contest.contest_package import find_contest, find_contest_package_or_die
from rbx.box.formatting import get_formatted_memory


def find_problem_packages_from_contest(
    root: pathlib.Path = pathlib.Path(),
) -> Iterable[pathlib.Path]:
    contest_path = find_contest(root)
    contest = find_contest_package_or_die(contest_path)
    for problem in contest.problems:
        yield contest_path / problem.get_path()


def find_all_reachable_packages(
    root: pathlib.Path = pathlib.Path(),
) -> List[pathlib.Path]:
    packages = find_all_ancestor_packages(root)

    for package in list(packages):
        if is_contest_package(package):
            packages.extend(find_problem_packages_from_contest(package))
    return packages


def find_and_group_all_reachable_packages(
    root: pathlib.Path = pathlib.Path(),
) -> Tuple[List[pathlib.Path], List[pathlib.Path]]:
    packages = find_all_reachable_packages(root)
    contest_packages = set(pkg for pkg in packages if is_contest_package(pkg))
    problem_packages = set(pkg for pkg in packages if is_problem_package(pkg))
    return sorted(contest_packages), sorted(problem_packages)


def get_dir_size(path: pathlib.Path) -> int:
    if not path.is_dir():
        return 0
    return sum(
        f.stat().st_size
        for f in path.glob('**/*')
        if f.is_file() and not f.is_symlink()
    )


def get_cache_size(root: pathlib.Path = pathlib.Path()) -> int:
    cache_dir = root / '.box'
    return get_dir_size(cache_dir)


def get_build_size(root: pathlib.Path = pathlib.Path()) -> int:
    build_dir = root / 'build'
    return get_dir_size(build_dir)


def print_package_stats(root: pathlib.Path = pathlib.Path()) -> int:
    if is_contest_package(root):
        console.console.print(f'[status]Contest package[/status]: [item]{root}[/item]')
    else:
        console.console.print(f'[status]Problem package[/status]: [item]{root}[/item]')

    cache_size = get_cache_size(root)
    build_size = get_build_size(root)
    console.console.print(
        f'[status]Cache size[/status]: [item]{get_formatted_memory(cache_size)}[/item]'
    )
    console.console.print(
        f'[status]Build size[/status]: [item]{get_formatted_memory(build_size)}[/item]'
    )

    return cache_size + build_size


def print_global_stats() -> int:
    cache_size = get_cache_size()
    console.console.print(
        f'[status]Global cache size[/status]: [item]{get_formatted_memory(cache_size)}[/item]'
    )
    return cache_size


def print_reachable_package_stats(root: pathlib.Path = pathlib.Path()) -> None:
    contest_packages, problem_packages = find_and_group_all_reachable_packages(root)
    total_size = 0
    for pkg in contest_packages:
        total_size += print_package_stats(pkg)
        console.console.print()
    for pkg in problem_packages:
        total_size += print_package_stats(pkg)
        console.console.print()

    total_size += print_global_stats()
    console.console.print(
        f'[status]Total size[/status]: [item]{get_formatted_memory(total_size)}[/item]'
    )
