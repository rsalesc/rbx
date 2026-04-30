import functools
import pathlib
from typing import List, Optional, Tuple

import ruyaml
import typer
from pydantic import ValidationError

from rbx import console, utils
from rbx.box import cd
from rbx.box.contest.schema import Contest
from rbx.box.package import find_problem_package_or_die
from rbx.box.sanitizers import issue_stack
from rbx.box.schema import Package

YAML_NAME = 'contest.rbx.yml'
PROBLEM_YAML_NAME = 'problem.rbx.yml'


def validate_problem_folders_exist(
    contest: Contest, contest_root: pathlib.Path
) -> None:
    missing: List[Tuple[str, pathlib.Path]] = []
    for problem in contest.problems:
        problem_path = problem.get_path()
        resolved = (
            problem_path if problem_path.is_absolute() else contest_root / problem_path
        )
        if not resolved.is_dir():
            missing.append((problem.short_name, resolved))

    if not missing:
        return

    console.console.print(
        '[error]Some contest problems point to folders that do not exist:[/error]'
    )
    for short_name, resolved in missing:
        console.console.print(f'[error]  - {short_name}: {resolved}[/error]')
    raise typer.Exit(1)


def validate_problem_folders_are_packages(
    contest: Contest, contest_root: pathlib.Path
) -> None:
    missing: List[Tuple[str, pathlib.Path]] = []
    for problem in contest.problems:
        problem_path = problem.get_path()
        resolved = (
            problem_path if problem_path.is_absolute() else contest_root / problem_path
        )
        if not (resolved / PROBLEM_YAML_NAME).is_file():
            missing.append((problem.short_name, resolved))

    if not missing:
        return

    console.console.print(
        '[error]Some contest problem folders are missing problem.rbx.yml:[/error]'
    )
    for short_name, resolved in missing:
        console.console.print(f'[error]  - {short_name}: {resolved}[/error]')
    raise typer.Exit(1)


@functools.cache
def find_contest_yaml(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    root = utils.abspath(root)
    contest_yaml_path = root / YAML_NAME
    while root != pathlib.PosixPath('/') and not contest_yaml_path.is_file():
        root = root.parent
        contest_yaml_path = root / YAML_NAME
    if not contest_yaml_path.is_file():
        return None
    return contest_yaml_path


@functools.cache
def find_contest_package(root: pathlib.Path = pathlib.Path()) -> Optional[Contest]:
    contest_yaml_path = find_contest_yaml(root)
    if not contest_yaml_path:
        return None
    try:
        contest = utils.model_from_yaml(Contest, contest_yaml_path.read_text())
    except ValidationError as e:
        console.console.print(e)
        console.console.print('[error]Error parsing contest.rbx.yml.[/error]')
        console.console.print(
            '[error]If you are sure the file is correct, ensure you are '
            'in the latest version of [item]rbx[/item].[/error]'
        )
        raise typer.Exit(1) from e

    contest_root = contest_yaml_path.parent
    validate_problem_folders_exist(contest, contest_root)
    validate_problem_folders_are_packages(contest, contest_root)
    return contest


def find_contest_package_or_die(root: pathlib.Path = pathlib.Path()) -> Contest:
    package = find_contest_package(root)
    if package is None:
        console.console.print(f'Contest not found in {root.absolute()}', style='error')
        raise typer.Exit(1)
    return package


def find_contest(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    found = find_contest_yaml(root)
    if found is None:
        console.console.print(f'Contest not found in {root.absolute()}', style='error')
        raise typer.Exit(1)
    return found.parent


def within_contest(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with cd.new_package_cd(find_contest()):
            issue_level_token = issue_stack.issue_level_var.set(
                issue_stack.IssueLevel.OVERVIEW
            )
            ret = func(*args, **kwargs)
            issue_stack.print_current_report()
            issue_stack.issue_level_var.reset(issue_level_token)
            return ret

    return wrapper


def save_contest(
    package: Optional[Contest] = None, root: pathlib.Path = pathlib.Path()
) -> None:
    package = package or find_contest_package_or_die(root)
    contest_yaml_path = find_contest_yaml(root)
    if not contest_yaml_path:
        console.console.print(f'Contest not found in {root.absolute()}', style='error')
        raise typer.Exit(1)
    contest_yaml_path.write_text(utils.model_to_yaml(package))


def get_problems(contest: Contest) -> List[Package]:
    problems = []
    for problem in contest.problems:
        problems.append(find_problem_package_or_die(problem.get_path()))
    return problems


def get_ruyaml(root: pathlib.Path = pathlib.Path()) -> Tuple[ruyaml.YAML, ruyaml.Any]:
    contest_yaml_path = find_contest_yaml(root)
    if contest_yaml_path is None:
        console.console.print(f'[error]Contest not found in {root.absolute()}[/error]')
        raise typer.Exit(1)
    res = ruyaml.YAML()
    return res, res.load(contest_yaml_path.read_text())
