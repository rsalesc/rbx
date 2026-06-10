"""Dynamic completers. MUST stay light — do not import the heavy app here."""

import importlib.resources
from pathlib import Path
from typing import List, Optional

from click.shell_completion import CompletionItem

from rbx.box.completion import peek
from rbx.box.completion.registry import CompletionContext, register_completer


def _items(values) -> List[CompletionItem]:
    return [CompletionItem(v) for v in sorted(values)]


def _peek_list(root: Path, filename: str, key: str) -> list:
    """A top-level list field from a package YAML, tolerant of malformed input.

    `peek` already swallows IO/parse errors; this additionally coerces a
    missing/None/scalar field to `[]` so callers never iterate a non-list.
    """
    value = peek.peek(root / filename).get(key)
    return value if isinstance(value, list) else []


@register_completer('language')
def complete_language(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    from rbx.config import get_config  # local import keeps module light

    return _items(get_config().languages.keys())


@register_completer('checker')
def complete_checker(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    from rbx import config

    names = set()
    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / 'checkers'
    ) as d:
        names.update(p.name for p in d.iterdir() if p.is_file())
    app_checkers = config.get_app_path() / 'checkers'
    if app_checkers.is_dir():
        names.update(p.name for p in app_checkers.iterdir() if p.is_file())
    names.discard('boilerplate.cpp')
    return _items(names)


@register_completer('problem')
def complete_problem(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    root = ctx.package_root
    if root is None:
        return []
    names = set()
    for p in _peek_list(Path(root), 'contest.rbx.yml', 'problems'):
        if not isinstance(p, dict):
            continue
        if p.get('short_name'):
            names.add(p['short_name'])
        aliases = p.get('aliases')
        if isinstance(aliases, list):
            for alias in aliases:
                if alias:
                    names.add(alias)
    return _items(names)


# Built-in solution-path expanders, mirroring rbx/box/remote.py's
# REGISTERED_EXPANDERS (guarded by enum_consistency_test.py). @boca needs a run
# id we cannot enumerate, so we offer only the prefix. `@main` leads the list and
# `@boca/` trails it (the order the engine emits, preserved by the shell scripts).
_MAIN_PREFIX = ('@main', 'first accepted solution')
_BOCA_PREFIX = ('@boca/', 'download a BOCA submission, e.g. @boca/123')
_SOLUTION_PREFIXES = (_MAIN_PREFIX, _BOCA_PREFIX)


def _expand_solution_paths(root: Path, sol: dict):
    """Yield the concrete solution files a `solutions[]` entry refers to.

    Mirrors rbx/box/package.py:get_globbed_code_items lightly: a `*` path is
    globbed against the package root (like the real CLI), anything else is taken
    verbatim. No language-extension filtering (that needs the heavy app)."""
    path = str(sol['path'])
    if '*' in path:
        for f in sorted(root.glob(path)):
            if f.is_file():
                yield str(f.relative_to(root))
    else:
        yield path


@register_completer('solutions')
def complete_solutions(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    items: List[CompletionItem] = [
        CompletionItem(_MAIN_PREFIX[0], help=_MAIN_PREFIX[1])
    ]
    root = ctx.package_root
    if root is not None:
        root = Path(root)
        seen = set()
        for sol in _peek_list(root, 'problem.rbx.yml', 'solutions'):
            if not (isinstance(sol, dict) and sol.get('path')):
                continue
            outcome = sol.get('outcome')
            help_text = str(outcome) if outcome is not None else None
            for value in _expand_solution_paths(root, sol):
                if value not in seen:
                    seen.add(value)
                    items.append(CompletionItem(value, help=help_text))
    items.append(CompletionItem(_BOCA_PREFIX[0], help=_BOCA_PREFIX[1]))
    return items


# (token, human description). Kept complete vs ExpectedOutcome by
# enum_consistency_test.py -- exactly one token per enum member.
_OUTCOME_TABLE = (
    ('any', 'matches any verdict'),
    ('ac', 'accepted'),
    ('ac/tle', 'accepted or time limit exceeded'),
    ('wa', 'wrong answer'),
    ('incorrect', 'any incorrect (non-AC) verdict'),
    ('rte', 'runtime error'),
    ('tle', 'time limit exceeded'),
    ('mle', 'memory limit exceeded'),
    ('ole', 'output limit exceeded'),
    ('tle/rte', 'time limit exceeded or runtime error'),
    ('jf', 'judge failed'),
    ('ce', 'compilation error'),
)


@register_completer('outcome')
def complete_outcome(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    return [CompletionItem(v, help=h) for v, h in _OUTCOME_TABLE]


# (value, level name). Kept in sync with environment.VerificationLevel by
# enum_consistency_test.py.
_VERIFICATION_TABLE = (
    ('0', 'NONE'),
    ('1', 'VALIDATE'),
    ('2', 'FAST_SOLUTIONS'),
    ('3', 'ALL_SOLUTIONS'),
    ('4', 'FULL'),
)


@register_completer('verification_level')
def complete_verification_level(
    ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    return [CompletionItem(v, help=h) for v, h in _VERIFICATION_TABLE]


@register_completer('profile')
def complete_profile(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    root = ctx.package_root
    if root is None:
        return []
    limits_dir = Path(root) / '.limits'
    if not limits_dir.is_dir():
        return []
    return _items(p.stem for p in limits_dir.glob('*.yml'))


@register_completer('testgroup')
def complete_testgroup(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    root = ctx.package_root
    if root is None:
        return []
    groups = _peek_list(Path(root), 'problem.rbx.yml', 'testcases')
    names = {g.get('name') for g in groups if isinstance(g, dict)}
    return _items(n for n in names if n)


_CONTEST_PREFIX = 'contest.'
_CONTEST_SUFFIX = '.rbx.yml'


def _find_contest_root(start: Optional[Path]) -> Optional[Path]:
    """Nearest ancestor (incl. start) holding a contest.rbx.yml. Light, no load."""
    if start is None:
        return None
    cur = Path(start)
    for d in [cur, *cur.parents]:
        if (d / 'contest.rbx.yml').exists():
            return d
    return None


@register_completer('contest_variant')
def complete_contest_variant(
    ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    root = _find_contest_root(ctx.package_root)
    if root is None:
        return []
    ids = []
    for p in root.glob(f'{_CONTEST_PREFIX}*{_CONTEST_SUFFIX}'):
        name = p.name[len(_CONTEST_PREFIX) : -len(_CONTEST_SUFFIX)]
        if name:
            ids.append(name)
    return _items(ids)
