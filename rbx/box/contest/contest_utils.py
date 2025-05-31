from typing import List

from rbx.box import environment, package
from rbx.box.contest import contest_package
from rbx.box.contest.schema import ContestProblem


def match_problem(problems: str, contest_problem: ContestProblem) -> bool:
    short_name = contest_problem.short_name.lower()
    problems = problems.lower()
    if problems == '*':
        return True
    if '-' in problems:
        start, end = problems.split('-')
        return start <= short_name <= end
    problem_set = set(p.strip().lower() for p in problems.split(','))
    return short_name in problem_set


def get_problems_of_interest(problems: str) -> List[ContestProblem]:
    contest = contest_package.find_contest_package_or_die()
    problems_of_interest = []

    for p in contest.problems:
        if match_problem(problems, p):
            problems_of_interest.append(p)
    return problems_of_interest


def clear_all_caches():
    pkgs = [package, environment, contest_package]

    for pkg in pkgs:
        for fn in pkg.__dict__.values():
            if hasattr(fn, 'cache_clear'):
                fn.cache_clear()
