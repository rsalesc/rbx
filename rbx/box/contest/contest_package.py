import functools
import pathlib
from typing import Dict, List, NoReturn, Optional, Tuple

import ruyaml
import typer

from rbx import console, utils
from rbx.box import cd
from rbx.box.contest.contest_state import is_valid_variant_id
from rbx.box.contest.schema import Contest
from rbx.box.package import find_problem_package_or_die
from rbx.box.sanitizers import issue_stack
from rbx.box.schema import Package
from rbx.box.yaml_validation import load_yaml_model

YAML_NAME = 'contest.rbx.yml'
PROBLEM_YAML_NAME = 'problem.rbx.yml'
VARIANT_GLOB = 'contest.*.rbx.yml'


def discover_contest_variants(
    contest_root: pathlib.Path,
) -> Dict[Optional[str], pathlib.Path]:
    """Returns variant_id -> yaml path. Single-contest mode uses key None.

    Errors via typer.Exit if contest.rbx.yml is a real contest AND there are
    sibling contest.<id>.rbx.yml files (ambiguous).
    """
    canonical = contest_root / YAML_NAME
    if not canonical.is_file():
        return {}

    canonical_contest = load_yaml_model(canonical, Contest)
    sibling_paths = sorted(contest_root.glob(VARIANT_GLOB))
    siblings: Dict[str, pathlib.Path] = {}
    for path in sibling_paths:
        # path.name is e.g. 'contest.div1.rbx.yml' -> id 'div1'
        # Strip leading 'contest.' and trailing '.rbx.yml'.
        name = path.name[len('contest.') : -len('.rbx.yml')]
        if not is_valid_variant_id(name):
            console.console.print(
                f'[warning]Skipping {path.name}: not a valid contest '
                f'variant id.[/warning]'
            )
            continue
        siblings[name] = path

    if canonical_contest.is_dispatcher:
        return dict(siblings)

    if siblings:
        names = [p.name for p in siblings.values()]
        console.console.print(
            f'[error]contest.rbx.yml at {contest_root} is configured as a '
            f'real contest but sibling variant files exist: {names}. Either '
            f'set `use_variants: true` on contest.rbx.yml to enable '
            f'dispatcher mode, or rename/remove the sibling files.[/error]'
        )
        raise typer.Exit(1)

    return {None: canonical}


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


# NOTE: `find_contest_yaml` is `@functools.cache`d. The contextvar fallback
# (via `resolve_explicit_selection`) is consulted only when `contest_id` is
# None, which means a cache hit may return a stale result if the contextvar
# changes between calls with the same `(root, None)` key. Production callers
# resolve selection once at the CLI callback boundary; tests must
# `cache_clear()` when manipulating the contextvar.
@functools.cache
def find_contest_yaml(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> Optional[pathlib.Path]:
    from rbx.box.contest.contest_state import resolve_explicit_selection

    root = utils.abspath(root)
    contest_yaml_path = root / YAML_NAME
    while root != pathlib.PosixPath('/') and not contest_yaml_path.is_file():
        root = root.parent
        contest_yaml_path = root / YAML_NAME
    if not contest_yaml_path.is_file():
        return None

    contest_root = contest_yaml_path.parent
    canonical_contest = load_yaml_model(contest_yaml_path, Contest)

    effective_id = (
        contest_id if contest_id is not None else resolve_explicit_selection()
    )

    if not canonical_contest.is_dispatcher:
        if effective_id is not None:
            console.console.print(
                f'[error]Contest at {contest_root} is not a dispatcher (no '
                f'use_variants). Cannot select variant {effective_id!r}.[/error]'
            )
            raise typer.Exit(1)
        # Single-mode: return canonical without calling
        # `discover_contest_variants`, which would error if stray sibling
        # variant files exist. The strict check is deferred to explicit
        # callers (e.g. `rbx contest list`).
        return contest_yaml_path

    # Dispatcher mode.
    variants = discover_contest_variants(contest_root)
    if effective_id is None:
        return None
    if effective_id not in variants:
        # Dispatcher mode never produces a None key.
        console.console.print(
            f'[error]Contest variant {effective_id!r} not found. '
            f'Pass -C <id> or set RBX_CONTEST=<id>. '
            f'Available: {sorted(variants)}.[/error]'
        )
        raise typer.Exit(1)
    return variants[effective_id]


@functools.cache
def find_contest_package(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> Optional[Contest]:
    contest_yaml_path = find_contest_yaml(root, contest_id=contest_id)
    if not contest_yaml_path:
        return None
    contest = load_yaml_model(contest_yaml_path, Contest)

    contest_root = contest_yaml_path.parent
    validate_problem_folders_exist(contest, contest_root)
    validate_problem_folders_are_packages(contest, contest_root)
    return contest


def _die_no_contest(root: pathlib.Path) -> NoReturn:
    """Errors with a contextual message when no contest is resolved.

    Re-walks the tree to detect dispatcher mode. This duplicates the walk
    in `find_contest_yaml`, but keeps the public signature minimal.
    """
    abs_root = utils.abspath(root)
    walker = abs_root
    contest_yaml_path = walker / YAML_NAME
    while walker != pathlib.PosixPath('/') and not contest_yaml_path.is_file():
        walker = walker.parent
        contest_yaml_path = walker / YAML_NAME
    if contest_yaml_path.is_file():
        canonical = load_yaml_model(contest_yaml_path, Contest)
        if canonical.is_dispatcher:
            variants = discover_contest_variants(contest_yaml_path.parent)
            # Dispatcher mode never produces a None key.
            available = sorted(variants)
            console.console.print(
                f'[error]Multiple contests are defined in this directory. '
                f'Pass -C <id> or set RBX_CONTEST=<id>. '
                f'Available contests: {available}.[/error]'
            )
            raise typer.Exit(1)
    console.console.print(f'Contest not found in {abs_root}', style='error')
    raise typer.Exit(1)


def find_contest_package_or_die(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> Contest:
    package = find_contest_package(root, contest_id=contest_id)
    if package is None:
        _die_no_contest(root)
    return package


def find_contest(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> pathlib.Path:
    found = find_contest_yaml(root, contest_id=contest_id)
    if found is None:
        _die_no_contest(root)
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
    package: Optional[Contest] = None,
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> None:
    package = package or find_contest_package_or_die(root, contest_id=contest_id)
    contest_yaml_path = find_contest_yaml(root, contest_id=contest_id)
    if not contest_yaml_path:
        console.console.print(f'Contest not found in {root.absolute()}', style='error')
        raise typer.Exit(1)
    contest_yaml_path.write_text(utils.model_to_yaml(package))


def get_problems(contest: Contest) -> List[Package]:
    problems = []
    for problem in contest.problems:
        problems.append(find_problem_package_or_die(problem.get_path()))
    return problems


def get_ruyaml(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> Tuple[ruyaml.YAML, ruyaml.Any]:
    contest_yaml_path = find_contest_yaml(root, contest_id=contest_id)
    if contest_yaml_path is None:
        console.console.print(f'[error]Contest not found in {root.absolute()}[/error]')
        raise typer.Exit(1)
    res = ruyaml.YAML()
    return res, res.load(contest_yaml_path.read_text())
