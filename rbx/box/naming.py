from typing import Optional

from rbx.box import package
from rbx.box.contest import contest_package


def get_problem_shortname() -> Optional[str]:
    contest = contest_package.find_contest_package()
    if contest is None:
        return None
    problem_path = package.find_problem()
    contest_path = contest_package.find_contest()

    for problem in contest.problems:
        if problem.path is None:
            continue
        if (problem_path / 'problem.rbx.yml').samefile(
            contest_path / problem.path / 'problem.rbx.yml'
        ):
            return problem.short_name

    return None


def get_problem_name_with_contest_info() -> str:
    problem = package.find_problem_package_or_die()
    contest = contest_package.find_contest_package()
    short_name = get_problem_shortname()
    if contest is None or short_name is None:
        return problem.name
    return f'{contest.name}-{short_name}-{problem.name}'
