import pathlib
from typing import List, Optional, Tuple

import typer

from rbx.box import package
from rbx.box.contest import contest_package, contest_state
from rbx.box.contest.contest_package import discover_contest_variants
from rbx.box.contest.schema import Contest, ContestProblem, ContestStatement
from rbx.box.schema import Package
from rbx.box.statements.schema import Statement
from rbx.console import console


def _entry_in_contest(
    contest: Contest,
    contest_root: pathlib.Path,
) -> Optional[Tuple[int, ContestProblem]]:
    problem_path = package.find_problem()
    for i, problem in enumerate(contest.problems):
        if problem.path is None:
            continue
        candidate = contest_root / problem.path / 'problem.rbx.yml'
        if not candidate.is_file():
            continue
        if (problem_path / 'problem.rbx.yml').samefile(candidate):
            return i, problem
    return None


def get_problem_entry_in_contest() -> Optional[Tuple[int, ContestProblem]]:
    # Fast path: explicit selection or single-mode contest.
    contest = contest_package.find_contest_package()
    if contest is not None:
        contest_path = contest_package.find_contest()
        return _entry_in_contest(contest, contest_path)

    # Past this point: find_contest_package returned None. Either there's
    # no contest at all, or we're in dispatcher mode without a selection.
    if contest_state.resolve_explicit_selection() is not None:
        # Selection set but contest_package returned None -> upstream
        # already errored or there is no matching variant.
        return None

    contest_root = contest_package.find_contest_root()
    if contest_root is None:
        return None

    variants = discover_contest_variants(contest_root)
    matches: List[Tuple[int, ContestProblem]] = []
    for vid, _yaml_path in variants.items():
        if vid is None:
            continue
        candidate_contest = contest_package.find_contest_package(
            contest_root, contest_id=vid
        )
        if candidate_contest is None:
            continue
        entry = _entry_in_contest(candidate_contest, contest_root)
        if entry is not None:
            matches.append(entry)

    if len(matches) == 1:
        return matches[0]
    return None


def require_problem_in_contest() -> Tuple[int, ContestProblem]:
    """Like `get_problem_entry_in_contest` but errors if not uniquely resolvable."""
    entry = get_problem_entry_in_contest()
    if entry is not None:
        return entry

    contest_root = contest_package.find_contest_root()
    if contest_root is None:
        console.print('[error]No contest found for the current problem.[/error]')
        raise typer.Exit(1)

    variants = discover_contest_variants(contest_root)
    selection = contest_state.resolve_explicit_selection()
    available = sorted(v for v in variants if v is not None)

    if len(available) > 1 and selection is None:
        console.print(
            f'[error]This problem is part of multiple contests. '
            f'Pass -C <id> or set RBX_CONTEST=<id>. '
            f'Available contests: {available}.[/error]'
        )
        raise typer.Exit(1)

    # Single mode, OR dispatcher with explicit selection: the problem isn't in
    # the active contest. Tell the user which variants DO contain it (if any).
    containing: List[str] = []
    for vid in variants:
        if vid is None:
            continue
        candidate = contest_package.find_contest_package(contest_root, contest_id=vid)
        if candidate is None:
            continue
        if _entry_in_contest(candidate, contest_root) is not None:
            containing.append(vid)

    if selection is not None:
        msg = (
            f'[error]This problem directory is not listed in the problems[] of '
            f'contest variant {selection!r}.[/error]'
        )
        if containing:
            msg += f' [info]It is listed in: {sorted(containing)}.[/info]'
        console.print(msg)
    else:
        console.print(
            "[error]This problem directory is not listed in the active contest's "
            'problems[] field.[/error]'
        )
    raise typer.Exit(1)


def get_problem_shortname() -> Optional[str]:
    entry = get_problem_entry_in_contest()
    if entry is None:
        return None
    _, problem = entry
    return problem.short_name


def get_problem_shortname_or_require() -> Optional[str]:
    """Return the problem's contest letter, or None if the problem is outside any contest.

    Unlike `get_problem_shortname`, this raises `typer.Exit(1)` with a picker
    message (delegating to `require_problem_in_contest`) whenever a contest
    root is present but the entry cannot be uniquely resolved. Concretely:

    - dispatcher mode without explicit selection, AND multiple variants
      contain (or could contain) this problem,
    - explicit selection set but the problem is not listed in the selected
      variant's problems[],
    - single-mode contest exists but does not list this problem.

    Returning `None` is reserved for the stand-alone case (no contest at all).
    Use this at call sites that compose filenames or archive keys: silently
    dropping the letter in any of the above cases would be wrong.
    """
    entry = get_problem_entry_in_contest()
    if entry is not None:
        _, problem = entry
        return problem.short_name

    # No entry — distinguish "no contest at all" (graceful) from
    # "contest present but ambiguous/mismatched" (error).
    if contest_package.find_contest_root() is None:
        return None

    # There is a contest root: defer to require_problem_in_contest so the
    # user gets the picker / mismatch error message.
    require_problem_in_contest()
    # Unreachable: require_problem_in_contest always raises in this branch.
    return None


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


def get_contest_problem_label(problem: ContestProblem) -> str:
    """Human-readable label for a contest problem: '<short_name>. <name>'.

    Falls back to just the short name when the problem package cannot be
    loaded (e.g. missing or broken problem.rbx.yml) or has no name, so
    callers keep working on a partially set-up contest.
    """
    pkg = package.find_problem_package(problem.get_path())
    if pkg is not None and pkg.name:
        return f'{problem.short_name}. {pkg.name}'
    return problem.short_name


def get_problem_title(
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
                    f'[error]Package [item]{pkg.name}[/item] has multiple titles and no statement. Could not infer which title to use.[/error]'
                )
                console.print(f'Available titles: {pkg.titles}')
                raise typer.Exit(1)
            title = list(pkg.titles.values())[0]
        else:
            title = pkg.name
    return title


def get_contest_title(
    lang: Optional[str] = None,
    statement: Optional[ContestStatement] = None,
    contest: Optional[Contest] = None,
    fallback_to_title: bool = False,
) -> str:
    if contest is None:
        contest = contest_package.find_contest_package_or_die()

    title: Optional[str] = None
    if lang is not None:
        title = contest.titles.get(lang)
    if statement is not None:
        title = statement.title or title
    if title is None:
        if fallback_to_title:
            if len(contest.titles) != 1:
                console.print(
                    '[error]Contest has multiple titles and no statement. Could not infer which title to use.[/error]'
                )
                console.print(f'Available titles: {contest.titles}')
                raise typer.Exit(1)
            title = list(contest.titles.values())[0]
        else:
            title = contest.name
    return title
