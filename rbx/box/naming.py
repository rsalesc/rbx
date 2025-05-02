from typing import Optional, Tuple

from rbx.box import package
from rbx.box.contest import contest_package
from rbx.box.contest.schema import ContestProblem


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
