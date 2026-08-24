"""Resolution of the problem selector accepted by `rbx on`.

The selector is a comma-separated list of tokens, each of which may be negated
with a leading `!`:

    selector := token (',' token)*
    token    := ['!'] atom
    atom     := '*' | range | pattern
    range    := <short-name> '..' <short-name>

A pattern is resolved through four tiers -- short name, problem name, alias,
folder basename -- stopping at the first tier that matches anything, so a token
that is one problem's short name never also drags in another problem that
happens to carry it as an alias.

The functions here are pure: the caller supplies the problems and a lookup for
the problem names, which live in each problem's own package file.
"""

import fnmatch
from typing import Callable, Iterator, List, Optional, Sequence

from rbx.box.contest.schema import ContestProblem

RANGE_SEPARATOR = '..'
NEGATION_PREFIX = '!'

# Reads a problem's declared `name` from its package, or None when it has none.
NameLookup = Callable[[ContestProblem], Optional[str]]


class ProblemSelectorError(ValueError):
    """Raised when a selector does not resolve to problems in this contest."""


def _is_glob(token: str) -> bool:
    return '*' in token or '?' in token


def _matches(candidate: str, token: str) -> bool:
    # Case-insensitive everywhere: tokens keep the user's casing so error
    # messages can quote them back verbatim.
    candidate, token = candidate.lower(), token.lower()
    if _is_glob(token):
        return fnmatch.fnmatchcase(candidate, token)
    return candidate == token


def _basename(problem: ContestProblem) -> str:
    return problem.get_path().name


def _tiers(
    token: str, problems: Sequence[ContestProblem], name_lookup: NameLookup
) -> Iterator[List[ContestProblem]]:
    """The candidate lists for `token`, in decreasing order of priority.

    Yielded one tier at a time: reading problem names touches the filesystem, so
    it only happens once short names have missed.
    """
    yield [p for p in problems if _matches(p.short_name, token)]
    yield [
        p
        for p in problems
        if (name := name_lookup(p)) is not None and _matches(name, token)
    ]
    yield [p for p in problems if any(_matches(a, token) for a in p.aliases)]
    yield [p for p in problems if _matches(_basename(p), token)]


def _resolve_pattern(
    token: str, problems: Sequence[ContestProblem], name_lookup: NameLookup
) -> List[ContestProblem]:
    for tier in _tiers(token, problems, name_lookup):
        if tier:
            return tier
    return []


def _range_hint(
    token: str, problems: Sequence[ContestProblem], name_lookup: NameLookup
) -> Optional[str]:
    """The `X..Y` a user probably meant when they typed `X-Y`.

    Only offered when both halves name a problem on their own -- otherwise the
    hyphen is just part of a name that does not exist in this contest.
    """
    for i, char in enumerate(token):
        if char != '-':
            continue
        start, end = token[:i], token[i + 1 :]
        if not start or not end:
            continue
        if _resolve_pattern(start, problems, name_lookup) and _resolve_pattern(
            end, problems, name_lookup
        ):
            return f'{start}{RANGE_SEPARATOR}{end}'
    return None


def _unmatched_error(
    token: str, problems: Sequence[ContestProblem], name_lookup: NameLookup
) -> ProblemSelectorError:
    message = f'No problem in contest matches [item]{token}[/item].'
    hint = _range_hint(token, problems, name_lookup)
    if hint is not None:
        message += (
            f' Did you mean the range [item]{hint}[/item]? '
            'Ranges are written with two dots.'
        )
    available = ', '.join(p.short_name for p in problems)
    message += (
        f' Available problems: {available} '
        '(match by short name, name, alias or folder).'
    )
    return ProblemSelectorError(message)


def _short_name_index(
    endpoint: str, problems: Sequence[ContestProblem], token: str
) -> int:
    for i, problem in enumerate(problems):
        if problem.short_name.lower() == endpoint.lower():
            return i
    raise ProblemSelectorError(
        f'Range [item]{token}[/item] has no problem with short name '
        f'[item]{endpoint}[/item]. Range endpoints are short names.'
    )


def _resolve_range(
    token: str, problems: Sequence[ContestProblem]
) -> List[ContestProblem]:
    parts = token.split(RANGE_SEPARATOR)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ProblemSelectorError(
            f'Malformed range [item]{token}[/item]. A range looks like '
            '[item]A..C[/item].'
        )
    start = _short_name_index(parts[0], problems, token)
    end = _short_name_index(parts[1], problems, token)
    if start > end:
        raise ProblemSelectorError(
            f'Range [item]{token}[/item] is inverted: [item]{parts[0]}[/item] comes '
            f'after [item]{parts[1]}[/item] in the contest.'
        )
    return list(problems[start : end + 1])


def _resolve_atom(
    atom: str, problems: Sequence[ContestProblem], name_lookup: NameLookup
) -> List[ContestProblem]:
    if atom == '*':
        return list(problems)
    if RANGE_SEPARATOR in atom:
        return _resolve_range(atom, problems)
    matched = _resolve_pattern(atom, problems, name_lookup)
    if not matched:
        raise _unmatched_error(atom, problems, name_lookup)
    return matched


def resolve_selector(
    selector: str,
    problems: Sequence[ContestProblem],
    name_lookup: NameLookup,
) -> List[ContestProblem]:
    """Resolve a selector into problems, in contest order.

    Raises `ProblemSelectorError` for a malformed selector, and for any token
    that matches no problem -- including a negated one, so that a typo is caught
    instead of silently excluding nothing.
    """
    included: List[ContestProblem] = []
    excluded: List[ContestProblem] = []
    has_include = False

    tokens = selector.split(',')
    for raw_token in tokens:
        token = raw_token.strip()
        if not token:
            raise ProblemSelectorError(
                f'Empty problem in selector [item]{selector}[/item].'
            )
        negated = token.startswith(NEGATION_PREFIX)
        atom = token[len(NEGATION_PREFIX) :] if negated else token
        if not atom:
            raise ProblemSelectorError(
                f'Selector [item]{selector}[/item] has a [item]{NEGATION_PREFIX}[/item] '
                'with nothing to exclude.'
            )
        matched = _resolve_atom(atom, problems, name_lookup)
        if negated:
            excluded.extend(matched)
        else:
            has_include = True
            included.extend(matched)

    # A selector made only of exclusions carves them out of the whole contest.
    base = included if has_include else list(problems)
    base_ids = {id(p) for p in base}
    excluded_ids = {id(p) for p in excluded}
    return [p for p in problems if id(p) in base_ids and id(p) not in excluded_ids]
