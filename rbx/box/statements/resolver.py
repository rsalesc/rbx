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

Building a problem statement outside a contest is a hard error (design §2,
decision 1); ``require_contest_for_problem`` enforces that.
"""

from typing import List, Optional

from rbx.box.contest import contest_package, contest_state
from rbx.box.contest.schema import Contest, ContestStatement
from rbx.box.exception import RbxException
from rbx.box.statements.schema import Statement


class StatementResolverError(RbxException):
    pass


def _describe_key(language: str, variant: str) -> str:
    return f'{language}/{variant}'


def select_standalone_contest_statement(
    statement: Statement,
    contest_statements: List[ContestStatement],
) -> ContestStatement:
    """Pick the contest statement that provides the standalone template for this
    problem statement's ``(language, variant)``.

    Candidates carry a ``standaloneProblemTemplate`` and match the problem
    statement on ``(language, variant)``. Exactly one is required.
    """
    candidates = [
        cs
        for cs in contest_statements
        if cs.standaloneProblemTemplate is not None
        and (cs.language, cs.variant) == (statement.language, statement.variant)
    ]
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


def require_contest_for_problem() -> Contest:
    """Return the contest the current problem belongs to, or hard-error.

    Statements v2 requires a contest to build any problem statement (design §2,
    decision 1). Gives a dispatcher-aware hint when the contest exists but no
    variant is selected.
    """
    contest = contest_package.find_contest_package()
    if contest is not None:
        return contest

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

    with StatementResolverError() as err:
        err.print(
            '[error]Building a problem statement requires a contest, but no '
            'contest was found for this problem. Statements v2 cannot build a '
            'problem statement standalone outside a contest.[/error]'
        )
    raise AssertionError('unreachable')  # pragma: no cover


def find_contest_for_problem() -> Optional[Contest]:
    """Best-effort contest lookup (no error). Used where a contest is optional."""
    return contest_package.find_contest_package()
