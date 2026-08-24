import pathlib
from typing import List, Optional, Tuple

from rbx.box import environment, package
from rbx.box.completion import peek
from rbx.box.contest import contest_package, problem_selector
from rbx.box.contest.schema import ContestProblem

SHELL_NAMES = frozenset({'bash', 'zsh', 'fish', 'sh', 'dash', 'ksh', 'csh', 'tcsh'})

# Token that separates chained commands in `rbx each` / `rbx on`.
COMMAND_SEPARATOR = '::'


class EmptyCommandError(ValueError):
    """Raised when a command chain has an empty group around a `::`."""

    def __init__(self):
        super().__init__(f'empty command in chain around `{COMMAND_SEPARATOR}`')


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


def split_commands(args: List[str]) -> List[List[str]]:
    """Split extra args into command groups on bare `::` tokens.

    A group with no args is a typo (a doubled, leading or trailing separator),
    so it raises instead of being silently dropped.
    """
    groups: List[List[str]] = []
    current: List[str] = []
    for arg in args:
        if arg == COMMAND_SEPARATOR:
            if not current:
                raise EmptyCommandError()
            groups.append(current)
            current = []
            continue
        current.append(arg)
    if not current and groups:
        raise EmptyCommandError()
    if current:
        groups.append(current)
    return groups


def build_command_argvs(
    args: List[str],
) -> Tuple[List[List[str]], Optional[str]]:
    """Build the argvs and placeholder_prefix for a chain of commands.

    Each group is prefixed independently, so a shell group in the chain keeps
    running as-is. The placeholder_prefix only feeds the interactive input
    hint, so it follows the first group.
    """
    groups = split_commands(args)
    if not groups:
        return [], 'rbx'
    built = [build_command_argv(group) for group in groups]
    return [argv for argv, _ in built], built[0][1]


def _problem_name(root: pathlib.Path, contest_problem: ContestProblem) -> Optional[str]:
    """The `name` a problem declares in its own package, if it declares one.

    Read with the tolerant peek helper rather than a full package load: the
    selector only needs one string, and a problem that does not parse should
    fail when it is built, not when a sibling is selected.
    """
    name = peek.peek(root / contest_problem.get_path() / 'problem.rbx.yml').get('name')
    return name if isinstance(name, str) else None


def get_problems_of_interest(problems: str) -> List[ContestProblem]:
    contest = contest_package.find_contest_package_or_die()
    root = contest_package.find_contest()
    return problem_selector.resolve_selector(
        problems, contest.problems, lambda p: _problem_name(root, p)
    )


def clear_all_caches():
    pkgs = [package, environment, contest_package]

    for pkg in pkgs:
        for fn in pkg.__dict__.values():
            if hasattr(fn, 'cache_clear'):
                fn.cache_clear()
