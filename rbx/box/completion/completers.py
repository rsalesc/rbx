"""Dynamic completers. MUST stay light — do not import the heavy app here."""

import importlib.resources
from pathlib import Path
from typing import List

from click.shell_completion import CompletionItem

from rbx.box.completion import peek
from rbx.box.completion.registry import CompletionContext, register_completer


def _items(values) -> List[CompletionItem]:
    return [CompletionItem(v) for v in sorted(values)]


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
    data = peek.peek(Path(root) / 'contest.rbx.yml')
    shorts = {
        p.get('short_name') for p in data.get('problems', []) if isinstance(p, dict)
    }
    return _items(s for s in shorts if s)


# Built-in solution-path expanders (kept in sync with rbx/box/remote.py via
# enum_consistency_test.py). @boca needs a run id we cannot enumerate, so we
# offer only the prefix.
_SOLUTION_PREFIXES = (
    ('@main', 'first accepted solution'),
    ('@boca/', 'download a BOCA submission, e.g. @boca/123'),
)


@register_completer('solutions')
def complete_solutions(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    items: List[CompletionItem] = []
    root = ctx.package_root
    if root is not None:
        data = peek.peek(Path(root) / 'problem.rbx.yml')
        for sol in data.get('solutions', []):
            if isinstance(sol, dict) and sol.get('path'):
                outcome = sol.get('outcome')
                help_text = str(outcome) if outcome is not None else None
                items.append(CompletionItem(str(sol['path']), help=help_text))
    items += [CompletionItem(v, help=h) for v, h in _SOLUTION_PREFIXES]
    return items


# (token, human description). Kept complete vs ExpectedOutcome by
# enum_consistency_test.py -- exactly one token per enum member.
_OUTCOME_TABLE = (
    ('any', 'matches any verdict'),
    ('ac', 'accepted'),
    ('ac/tle', 'accepted or time limit exceeded'),
    ('wa', 'wrong answer'),
    ('incorrect', 'any incorrect verdict (WA/RTE/MLE/OLE/TLE)'),
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
    data = peek.peek(Path(root) / 'problem.rbx.yml')
    names = {g.get('name') for g in data.get('testcases', []) if isinstance(g, dict)}
    return _items(n for n in names if n)
