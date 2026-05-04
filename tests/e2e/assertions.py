"""Generic assertion helpers for e2e scenarios.

Each ``check_*`` function takes an :class:`AssertionContext` plus the value
of the corresponding ``expect.*`` field and raises :class:`AssertionError`
on failure. The runner is responsible for wrapping that error with package
and scenario context; assertion messages here should be specific enough that
the wrapped message pinpoints the failure but should NOT duplicate the
package/scenario prefix.
"""

import pathlib
import re
from dataclasses import dataclass
from typing import Dict, List, Union


@dataclass
class AssertionContext:
    package_root: pathlib.Path
    stdout: str
    stderr: str


def _as_list(value: Union[str, List[str], None]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


# Bracket characters are interpreted as glob char-classes; literal brackets
# must be escaped with ``[[]``.
_GLOB_MAGIC = re.compile(r'[*?]|\[[^]]+\]')


def _glob(root: pathlib.Path, pattern: str) -> List[pathlib.Path]:
    # ``Path.glob`` does not accept absolute patterns; route plain literal
    # paths through ``exists()`` so callers can write ``foo.txt`` without
    # any wildcards. Only treat ``[`` as magic when it forms a matched
    # ``[...]`` pair, so stray brackets in literal paths do not confuse glob.
    if _GLOB_MAGIC.search(pattern):
        return list(root.glob(pattern))
    target = root / pattern
    return [target] if target.exists() else []


def check_stdout_contains(
    ctx: AssertionContext, expected: Union[str, List[str]]
) -> None:
    for needle in _as_list(expected):
        if needle not in ctx.stdout:
            raise AssertionError(f'stdout missing {needle!r}')


def check_stderr_contains(
    ctx: AssertionContext, expected: Union[str, List[str]]
) -> None:
    for needle in _as_list(expected):
        if needle not in ctx.stderr:
            raise AssertionError(f'stderr missing {needle!r}')


def check_stdout_matches(ctx: AssertionContext, pattern: str) -> None:
    if not re.search(pattern, ctx.stdout):
        raise AssertionError(f'stdout did not match /{pattern}/')


def check_files_exist(ctx: AssertionContext, patterns: List[str]) -> None:
    for pat in patterns:
        if not _glob(ctx.package_root, pat):
            raise AssertionError(f'no file matched {pat!r}')


def check_files_absent(ctx: AssertionContext, patterns: List[str]) -> None:
    for pat in patterns:
        if _glob(ctx.package_root, pat):
            raise AssertionError(f'unexpected file matched {pat!r}')


def check_file_contains(ctx: AssertionContext, mapping: Dict[str, str]) -> None:
    """Assert that each file under ``package_root`` contains the given value.

    Values whose length is greater than 2 and which both start and end with
    a forward slash (``/``) are interpreted as Python regular expressions
    (the surrounding slashes are stripped). All other values are treated as
    literal substrings.

    Note the ambiguity: a value like ``/usr/bin/`` is interpreted as the
    regex ``usr/bin``, not as the literal substring ``/usr/bin/``. Callers
    that need a literal value with leading and trailing slashes should pad
    the value or rely on a different assertion.
    """
    for path, needle in mapping.items():
        target = ctx.package_root / path
        if not target.exists():
            raise AssertionError(f'{path}: file does not exist')
        text = target.read_text()
        if len(needle) > 2 and needle.startswith('/') and needle.endswith('/'):
            regex = needle[1:-1]
            if not re.search(regex, text):
                raise AssertionError(f'{path}: regex {needle} no match')
        elif needle not in text:
            raise AssertionError(f'{path}: missing {needle!r}')
