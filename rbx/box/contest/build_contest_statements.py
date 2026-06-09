"""Contest statement building.

statements v2: this module is rebuilt in #566 (S10) — the recursive overlay
join via `\\subimport` (design §6.2). The old v1 pipeline depended on the
removed schema fields (`joiner`/`match`/`steps`/`configure`/`assets`/`override`)
and on the deleted `statement_overriding` module, so its body is intentionally
stubbed here. Only the symbols imported elsewhere are kept:

- ``StatementBuildIssue`` — used by ``contest/statements.py`` to flag failures.
- ``build_statement`` — the contest-statement entry point.
- ``get_statement_build_dir`` — the per-statement build directory (still valid).
"""

import pathlib
from typing import Any, Dict, List, Optional, Tuple

from rbx.box.contest.contest_package import get_contest_statements_build_path
from rbx.box.contest.schema import Contest, ContestProblem, ContestStatement
from rbx.box.sanitizers.issue_stack import Issue
from rbx.box.statements.schema import StatementType

_V2_PENDING = (
    'statements v2: the contest-statement join is not wired yet; it lands in '
    '#566 (S10). See docs/plans/2026-06-09-statements-v2-design.md §6.2.'
)


class StatementBuildIssue(Issue):
    def __init__(self, problem: ContestProblem):
        self.problem = problem

    def get_overview_section(self) -> Optional[Tuple[str, ...]]:
        return ('statement',)

    def get_overview_message(self) -> str:
        return f'Error building statement for problem [item]{self.problem.short_name}[/item].'


def get_statement_build_dir(statement: ContestStatement) -> pathlib.Path:
    return get_contest_statements_build_path() / statement.name


async def build_statement(
    statement: ContestStatement,
    contest: Contest,
    problems_of_interest: Optional[List[ContestProblem]] = None,
    output_type: Optional[StatementType] = None,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
    install_tex: bool = False,
) -> pathlib.Path:
    raise NotImplementedError(_V2_PENDING)
