"""Wildcard statement expansion (design 2026-09-20 §1).

A statement with ``language: "*"`` stands for one statement per language of the
package's effective ``languages:`` list. Expansion substitutes ``{lang}`` in
``name``, ``file``, the two contest templates, ``assets`` and ``params``
values, and yields the concrete entries in list order, one per language. A
concrete entry with the same key (``(language, variant)`` for problems,
``name`` for contests) wins over the expansion, so one language can still be
special-cased. It runs *before* ``extends`` expansion, so an expanded entry
can be extended by language like any other.
"""

import pathlib
from typing import Any, Callable, Hashable, List, Optional, TypeVar

from rbx.box.exception import RbxException
from rbx.box.statements.schema import LANG_PLACEHOLDER, BaseStatement

T = TypeVar('T', bound=BaseStatement)

# Fields whose values get `{lang}` substituted. Skipped on models that lack them
# (problem statements have no name/templates).
_SUBSTITUTED_FIELDS = (
    'name',
    'file',
    'standaloneProblemTemplate',
    'contestProblemTemplate',
    'assets',
    'params',
)


class WildcardExpansionError(RbxException):
    pass


def substitute_lang(value: Any, lang: str) -> Any:
    """Replace `{lang}` with `lang` in a string or path, recursing into lists
    and dicts. Anything else is returned untouched."""
    if isinstance(value, str):
        return value.replace(LANG_PLACEHOLDER, lang)
    if isinstance(value, pathlib.Path):
        return pathlib.Path(str(value).replace(LANG_PLACEHOLDER, lang))
    if isinstance(value, list):
        return [substitute_lang(v, lang) for v in value]
    if isinstance(value, dict):
        return {k: substitute_lang(v, lang) for k, v in value.items()}
    return value


def concrete_languages(statements: List[BaseStatement]) -> List[str]:
    """Distinct languages of the non-wildcard entries, in order of appearance."""
    seen: List[str] = []
    for st in statements:
        if not st.is_wildcard and st.language not in seen:
            seen.append(st.language)
    return seen


def _instantiate(st: T, lang: str) -> T:
    update: dict = {'language': lang}
    for field in _SUBSTITUTED_FIELDS:
        if field in type(st).model_fields and getattr(st, field) is not None:
            update[field] = substitute_lang(getattr(st, field), lang)
    # Re-validate so name patterns and type-dependent rules hold after
    # substitution, exactly as the `extends` expander does.
    return type(st).model_validate(st.model_copy(update=update).model_dump())


def _expand(
    statements: List[T],
    languages: Optional[List[str]],
    get_key: Callable[[T], Hashable],
) -> List[T]:
    if not any(st.is_wildcard for st in statements):
        return statements
    if not languages:
        with WildcardExpansionError() as err:
            err.print(
                '[error]A statement uses [item]language: "*"[/item] but no '
                '[item]languages[/item] list is in effect. Add '
                '[item]languages: [en, ...][/item] to the package (or to its '
                'contest).[/error]'
            )
    concrete_keys = {get_key(st) for st in statements if not st.is_wildcard}
    out: List[T] = []
    for st in statements:
        if not st.is_wildcard:
            out.append(st)
            continue
        for lang in languages or []:
            inst = _instantiate(st, lang)
            if get_key(inst) in concrete_keys:
                continue
            out.append(inst)
    return out


def expand_problem_wildcards(
    statements: List[T], languages: Optional[List[str]]
) -> List[T]:
    return _expand(
        statements,
        languages,
        get_key=lambda st: (st.language, st.variant),
    )


def expand_contest_wildcards(
    statements: List[T], languages: Optional[List[str]]
) -> List[T]:
    return _expand(
        statements,
        languages,
        get_key=lambda st: st.name,  # type: ignore[attr-defined]
    )
