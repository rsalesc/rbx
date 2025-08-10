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
        return utils.model_from_yaml(Contest, contest_yaml_path.read_text())
    except ValidationError as e:
        console.console.print(e)
        console.console.print('[error]Error parsing contest.rbx.yml.[/error]')
        raise typer.Exit(1) from e


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
