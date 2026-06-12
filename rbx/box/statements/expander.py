"""Statements v2 `extends` expander (design §5).

A slimmed-down replacement for the old full pydantic deep-merge. `extends`
shares only the *build recipe* across statements:

- **Inherited** (child overrides parent; `params` deep-merges key-by-key):
  `type`, `file`, `params`, and — for contest statements — the two templates
  `standaloneProblemTemplate` / `contestProblemTemplate`.
- **Never inherited** (always the child's own): `name`, `language`, `variant`.

Problem statements are keyed by `(language, variant)` and reference a parent by
language (`extends: en`) or `{language, variant}`. Contest statements/documents
are keyed by `name` and reference a parent by name. Cycles and dangling
references are errors.
"""

import collections
import copy
from typing import Callable, Hashable, List, Optional, Tuple, TypeVar

from deepmerge import always_merger

from rbx.box.exception import RbxException
from rbx.box.statements.schema import (
    DEFAULT_VARIANT,
    BaseStatement,
    Statement,
    StatementVariantRef,
)

TypeVarT = TypeVar('TypeVarT', bound=BaseStatement)

# Recipe fields shared by `extends` (besides `params`, handled specially).
_PROBLEM_ALLOWLIST = ('type', 'file', 'assets')
_CONTEST_ALLOWLIST = (
    'type',
    'file',
    'assets',
    'standaloneProblemTemplate',
    'contestProblemTemplate',
)


class StatementExpanderError(RbxException):
    pass


def _merge(parent: TypeVarT, child: TypeVarT, allowlist: Tuple[str, ...]) -> TypeVarT:
    """Build an expanded `child` that inherits the allowlisted recipe fields from
    the already-expanded `parent`, deep-merging `params` key-by-key."""
    update = {}
    for field in allowlist:
        # Skip fields this model doesn't carry (e.g. documents have no templates).
        if field not in type(child).model_fields:
            continue
        # Inherit only fields the child did not set explicitly.
        if field not in child.model_fields_set:
            update[field] = getattr(parent, field)
    update['params'] = always_merger.merge(
        copy.deepcopy(dict(parent.params)),
        copy.deepcopy(dict(child.params)),
    )
    merged = child.model_copy(update=update)
    # Re-validate so type-dependent rules (e.g. templates only on rbx* types)
    # still hold after inheritance.
    return type(child).model_validate(merged.model_dump())


def _expand(
    statements: List[TypeVarT],
    get_key: Callable[[TypeVarT], Hashable],
    get_parent_key: Callable[[TypeVarT], Optional[Hashable]],
    describe_key: Callable[[Hashable], str],
    allowlist: Tuple[str, ...],
) -> List[TypeVarT]:
    by_key = {get_key(st): st for st in statements}

    deg: collections.defaultdict = collections.defaultdict(int)
    dependents: collections.defaultdict = collections.defaultdict(list)
    for st in statements:
        parent_key = get_parent_key(st)
        if parent_key is None:
            continue
        if parent_key not in by_key:
            with StatementExpanderError() as err:
                err.print(
                    f'[error]Failed to expand statements: statement '
                    f'[item]{describe_key(get_key(st))}[/item] extends '
                    f'[item]{describe_key(parent_key)}[/item], but '
                    f'[item]{describe_key(parent_key)}[/item] is not defined.[/error]'
                )
        deg[get_key(st)] += 1
        dependents[parent_key].append(get_key(st))

    expanded: dict = {}
    queue = [st for st in statements if deg[get_key(st)] == 0]
    while queue:
        st = queue.pop()
        key = get_key(st)
        parent_key = get_parent_key(st)
        if parent_key is None:
            expanded[key] = st
        else:
            expanded[key] = _merge(expanded[parent_key], st, allowlist)
        for dep_key in dependents[key]:
            deg[dep_key] -= 1
            if deg[dep_key] == 0:
                queue.append(by_key[dep_key])

    if len(expanded) != len(statements):
        with StatementExpanderError() as err:
            err.print(
                f'[error]Failed to expand statements: only [item]{len(expanded)}[/item] '
                f'out of [item]{len(statements)}[/item] were expanded. This means '
                f'there is a cycle introduced by the `extends` field.[/error]'
            )

    return [expanded[get_key(st)] for st in statements]


def _problem_parent_key(st: Statement) -> Optional[Tuple[str, str]]:
    if st.extends is None:
        return None
    if isinstance(st.extends, StatementVariantRef):
        return (st.extends.language, st.extends.variant)
    return (st.extends, DEFAULT_VARIANT)


def expand_problem_statements(statements: List[Statement]) -> List[Statement]:
    return _expand(
        statements,
        get_key=lambda st: (st.language, st.variant),
        get_parent_key=_problem_parent_key,
        describe_key=lambda key: f'{key[0]}/{key[1]}',
        allowlist=_PROBLEM_ALLOWLIST,
    )


def expand_contest_statements(statements: List[TypeVarT]) -> List[TypeVarT]:
    return _expand(
        statements,
        get_key=lambda st: st.name,  # type: ignore[attr-defined]
        get_parent_key=lambda st: st.extends,  # type: ignore[attr-defined]
        describe_key=lambda key: str(key),
        allowlist=_CONTEST_ALLOWLIST,
    )
