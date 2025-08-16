from typing import Optional, Tuple

import typer

from rbx.box import package
from rbx.box.contest import contest_package
from rbx.box.contest.schema import ContestProblem
from rbx.box.schema import Package
from rbx.box.statements.schema import Statement
from rbx.console import console


def get_problem_entry_in_contest() -> Optional[Tuple[int, ContestProblem]]:
    contest = contest_package.find_contest_package()
    if contest is None:
        return None
    problem_path = package.find_problem()
    contest_path = contest_package.find_contest()

    for i, problem in enumerate(contest.problems):
        if problem.path is None:
            continue
        if (problem_path / 'problem.rbx.yml').samefile(
            contest_path / problem.path / 'problem.rbx.yml'
        ):
            return i, problem
    return None


def get_problem_shortname() -> Optional[str]:
    entry = get_problem_entry_in_contest()
    if entry is None:
        return None
    _, problem = entry
    return problem.short_name


def get_problem_index() -> Optional[int]:
    entry = get_problem_entry_in_contest()
    if entry is None:
        return None
    return entry[0]


def get_problem_name_with_contest_info() -> str:
    problem = package.find_problem_package_or_die()
    contest = contest_package.find_contest_package()
    short_name = get_problem_shortname()
    if contest is None or short_name is None:
        return problem.name
    return f'{contest.name}-{short_name}-{problem.name}'


def get_title(
    lang: Optional[str] = None,
    statement: Optional[Statement] = None,
    pkg: Optional[Package] = None,
    fallback_to_title: bool = False,
) -> str:
    if pkg is None:
        pkg = package.find_problem_package_or_die()
    title: Optional[str] = None
    if lang is not None:
        title = pkg.titles.get(lang)
    if statement is not None:
        title = statement.title or title
    if title is None:
        if fallback_to_title and pkg.titles:
            if len(pkg.titles) != 1:
                console.print(
                    '[error]Package has multiple titles and no statement. Could not infer which title to use.[/error]'
                )
                console.print(f'Available titles: {pkg.titles}')
                raise typer.Exit(1)
            title = list(pkg.titles.values())[0]
        else:
            title = pkg.name
    return title
