from typing import List, Optional, Tuple

from rbx.box import environment, package
from rbx.box.contest import contest_package
from rbx.box.contest.schema import ContestProblem

SHELL_NAMES = frozenset({'bash', 'zsh', 'fish', 'sh', 'dash', 'ksh', 'csh', 'tcsh'})


def is_shell_command(command: str) -> bool:
    """Check if a command name refers to a known shell."""
    return command in SHELL_NAMES


def find_command_executable(args: List[str]) -> Optional[str]:
    """Find the executable name from a list of command args.

    Returns the basename of the first arg, or None if args is empty.
    """
    if not args:
        return None
    return args[0]


def build_command_argv(args: List[str]) -> Tuple[List[str], Optional[str]]:
    """Build the argv and placeholder_prefix for running a command in contest context.

    If the command is a shell (bash, zsh, fish, etc.), returns the args as-is
    with no placeholder_prefix. Otherwise, prepends 'rbx' and sets
    placeholder_prefix to 'rbx'.
    """
    executable = find_command_executable(args)
    if executable is not None and is_shell_command(executable):
        return list(args), None
    return ['rbx'] + list(args), 'rbx'


def match_problem(problems: str, contest_problem: ContestProblem) -> bool:
    short_name = contest_problem.short_name.lower()
    problems_lower = problems.lower()
    if problems_lower == '*':
        return True
    if '-' in problems_lower:
        start, end = problems_lower.split('-')
        return start <= short_name <= end
    problem_set = set(p.strip().lower() for p in problems_lower.split(','))
    return bool(problem_set & contest_problem.all_identifiers())


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
