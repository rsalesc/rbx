"""Statements v2 contest-aware resolver + matching (design §2/§3, issue #563).

Two resolution problems live here, both pure over their inputs so they are
unit-testable without a package on disk:

- **Standalone** (`rbx st b`): a problem statement borrows the *template* from a
  contest statement. The candidates are the contest statements that share the
  problem statement's ``(language, variant)`` AND carry a
  ``standaloneProblemTemplate``. Exactly one must exist — 0 or >1 is a hard
  config error the user fixes (design §2, decision 3).
- **Join** (`rbx contest st b`): a joinable (rbx*) contest statement pulls one
  statement from each problem, matched by ``(language, variant)`` and required
  to share the contest statement's rbx* type (design §3.2).

Building a problem statement outside a contest (or with no contest statement
matching its ``(language, variant)``) is no longer a hard error: ``resolve_standalone``
falls back to the bundled default chrome/template (design S15 / issue #571). An
*unselected dispatcher* is still rejected — that is a 'forgot to select a contest'
mistake, not a genuinely contest-less problem.
"""

import dataclasses
import pathlib
from typing import List, Optional

from rbx import config
from rbx.box.contest import contest_package, contest_state
from rbx.box.contest.schema import Contest, ContestStatement
from rbx.box.exception import RbxException
from rbx.box.statements.schema import Statement, StatementKind
from rbx.box.yaml_validation import load_yaml_model


class StatementResolverError(RbxException):
    pass


# The bundled default chrome reused for contest-less builds lives in the default
# preset's contest dir (design S15, decision 3).
_PRESET_CONTEST_RESOURCE = pathlib.Path('presets') / 'default' / 'contest'


def _describe_key(language: str, variant: str) -> str:
    return f'{language}/{variant}'


def _standalone_candidates(
    statement: Statement, contest_statements: List[ContestStatement]
) -> List[ContestStatement]:
    return [
        cs
        for cs in contest_statements
        if cs.standaloneProblemTemplate is not None
        and (cs.language, cs.variant) == (statement.language, statement.variant)
    ]


def select_standalone_contest_statement(
    statement: Statement,
    contest_statements: List[ContestStatement],
) -> ContestStatement:
    """Pick the contest statement that provides the standalone template for this
    problem statement's ``(language, variant)``.

    Candidates carry a ``standaloneProblemTemplate`` and match the problem
    statement on ``(language, variant)``. Exactly one is required.
    """
    candidates = _standalone_candidates(statement, contest_statements)
    key = _describe_key(statement.language, statement.variant)
    if not candidates:
        with StatementResolverError() as err:
            err.print(
                f'[error]No contest statement provides a standalone template for '
                f'problem statement [item]{key}[/item].[/error]'
            )
            err.print(
                '[warning]Add a contest statement with a matching '
                '[item](language, variant)[/item] and a '
                '[item]standaloneProblemTemplate[/item] to build this statement '
                'standalone.[/warning]'
            )
    if len(candidates) > 1:
        names = [cs.name for cs in candidates]
        with StatementResolverError() as err:
            err.print(
                f'[error]Multiple contest statements provide a standalone template '
                f'for problem statement [item]{key}[/item]: [item]{names}[/item]. '
                f'Exactly one must carry a [item]standaloneProblemTemplate[/item] '
                f'for this [item](language, variant)[/item].[/error]'
            )
    return candidates[0]


@dataclasses.dataclass
class StandaloneResolution:
    """Resolved inputs for a standalone problem-statement build (design S15).

    ``contest_statement`` is a real contest statement (single match) or a
    synthetic one derived from the bundled default preset (fallback).
    ``contest`` is the real owning contest when present (its metadata feeds the
    ``contest.*`` namespace), ``None`` when there is no contest at all.
    ``contest_root`` is the dir the template + chrome resolve against (the real
    contest root, or the bundled preset contest dir).
    """

    contest: Optional[Contest]
    contest_statement: ContestStatement
    contest_root: pathlib.Path
    is_fallback: bool


def _raise_dispatcher_hint_if_unselected() -> None:
    """Raise a ``StatementResolverError`` (with the ``-C`` hint) when a contest
    root exists but is a dispatcher with no explicit selection. No-op otherwise.

    That is a 'forgot to select a contest' situation, not a genuinely
    contest-less problem, so callers must NOT fall back to the bundled default
    when this raises (design S15, decision 2)."""
    contest_root = contest_package.find_contest_root()
    if contest_root is not None and contest_state.resolve_explicit_selection() is None:
        variants = contest_package.discover_contest_variants(contest_root)
        available = sorted(v for v in variants if v is not None)
        if available:
            with StatementResolverError() as err:
                err.print(
                    '[error]Building a problem statement requires a contest, but '
                    'the contest here is a dispatcher with no explicit selection. '
                    f'Pass [item]-C <id>[/item] or set [item]RBX_CONTEST=<id>[/item]. '
                    f'Available contests: [item]{available}[/item].[/error]'
                )


def _bundled_default_statement(
    statement: Statement, kind: StatementKind
) -> tuple[ContestStatement, pathlib.Path]:
    """Synthesize a contest statement from the bundled default preset, rebound to
    the problem statement's ``(language, variant)`` so it matches any language."""
    preset_root = config.get_resources_dir(_PRESET_CONTEST_RESOURCE)
    preset_contest = load_yaml_model(preset_root / 'contest.rbx.yml', Contest)
    src_list = (
        preset_contest.expanded_tutorials
        if kind == StatementKind.TUTORIALS
        else preset_contest.expanded_statements
    )
    # The bundled preset always ships a first statement and tutorial (repo-guaranteed).
    src = src_list[0]
    synthetic = src.model_copy(
        update={'language': statement.language, 'variant': statement.variant}
    )
    return synthetic, preset_root


def resolve_standalone(
    statement: Statement, kind: StatementKind
) -> StandaloneResolution:
    """Resolve the contest statement for a standalone problem-statement build.

    Returns a real contest statement when exactly one matches the problem's
    ``(language, variant)`` and carries a ``standaloneProblemTemplate``; on zero
    matches falls back to the bundled default preset template (design S15 /
    issue #571). ``>1`` matches and an unselected dispatcher both hard-error.
    """
    contest = find_contest_for_problem()
    contest_statements: List[ContestStatement] = []
    if contest is not None:
        contest_statements = (
            contest.expanded_tutorials
            if kind == StatementKind.TUTORIALS
            else contest.expanded_statements
        )
    candidates = _standalone_candidates(statement, contest_statements)

    if len(candidates) == 1:
        return StandaloneResolution(
            contest=contest,
            contest_statement=candidates[0],
            contest_root=contest_package.find_contest(),
            is_fallback=False,
        )
    if len(candidates) > 1:
        # Reuse the ambiguity error message (raises).
        select_standalone_contest_statement(statement, contest_statements)
        raise AssertionError('unreachable')  # pragma: no cover

    if contest is None:
        _raise_dispatcher_hint_if_unselected()
    synthetic, preset_root = _bundled_default_statement(statement, kind)
    return StandaloneResolution(
        contest=contest,
        contest_statement=synthetic,
        contest_root=preset_root,
        is_fallback=True,
    )


def select_problem_statement(
    contest_statement: ContestStatement,
    problem_statements: List[Statement],
    problem_label: str,
) -> Statement:
    """Pick the problem statement that joins into ``contest_statement``.

    Matched by ``(language, variant)``; the matched statement must share the
    contest statement's rbx* type. ``problem_label`` (usually the short name) is
    used only for error messages.
    """
    key = (contest_statement.language, contest_statement.variant)
    described = _describe_key(*key)
    matching = [st for st in problem_statements if st.key == key]
    if not matching:
        with StatementResolverError() as err:
            err.print(
                f'[error]Problem [item]{problem_label}[/item] has no statement '
                f'matching [item]{described}[/item], required by contest statement '
                f'[item]{contest_statement.name}[/item].[/error]'
            )
    statement = matching[0]
    if statement.type != contest_statement.type:
        with StatementResolverError() as err:
            err.print(
                f'[error]Problem [item]{problem_label}[/item] statement '
                f'[item]{described}[/item] has type [item]{statement.type}[/item], '
                f'but contest statement [item]{contest_statement.name}[/item] joins '
                f'[item]{contest_statement.type}[/item] statements. The types must '
                f'match for the join.[/error]'
            )
    return statement


def find_contest_for_problem() -> Optional[Contest]:
    """Best-effort contest lookup (no error). Used where a contest is optional."""
    return contest_package.find_contest_package()
