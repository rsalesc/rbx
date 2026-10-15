"""Naming files of glob-backed test groups, and checking new group names.

What a promotion does lives in :mod:`rbx.box.promotion_plan`; where a test can
go, in :mod:`rbx.box.promotion_sinks`. These are the small pieces both share
with the interactive prompts.
"""

import itertools
import pathlib
import re
from typing import Dict, List, Optional, Set

import pydantic

from rbx.box import package
from rbx.box.schema import TestcaseGroup


def fill_glob(glob: str, stem: str) -> pathlib.Path:
    """Return the path obtained by filling ``glob``'s last ``*`` with ``stem``.

    Examples:
        ``manual_tests/manual-*.in`` + ``000`` -> ``manual_tests/manual-000.in``
        ``tests/manual/*.in`` + ``000`` -> ``tests/manual/000.in``

    If ``glob`` contains multiple ``*``, only the LAST one is filled; the rest
    are kept as literal text. If ``glob`` has no ``*``, a ``ValueError`` is
    raised: a manual group glob must contain a ``*`` to receive promoted tests.
    """
    if '*' not in glob:
        raise ValueError(f'manual group glob must contain a `*` (got {glob!r})')
    head, _, tail = glob.rpartition('*')
    return pathlib.Path(f'{head}{stem}{tail}')


def stems_matching_glob(glob: str, base_dir: pathlib.Path = pathlib.Path()) -> Set[str]:
    """Return the substring each on-disk file's last ``*`` captured for ``glob``.

    Enumerates files under ``base_dir`` matching ``glob`` and, for each, returns
    the text that the glob's LAST ``*`` matched. Earlier ``*`` are treated as
    non-capturing wildcards. Files that do not match the anchored pattern are
    ignored. Returns an empty set when nothing matches.
    """
    if '*' not in glob:
        raise ValueError(f'manual group glob must contain a `*` (got {glob!r})')

    # Build an anchored regex from the glob: literal segments are escaped, each
    # '*' becomes a wildcard, and the LAST '*' is the only capturing group so we
    # can recover the stem it matched.
    segments = glob.split('*')
    last = len(segments) - 1
    pattern = ''
    for i, segment in enumerate(segments):
        pattern += re.escape(segment)
        if i != last:
            pattern += '(.*)' if i == last - 1 else '.*'
    regex = re.compile(f'^{pattern}$')

    stems: Set[str] = set()
    # Candidates are pre-filtered by ``base_dir.glob(glob)`` (pathlib ``*`` does
    # not cross ``/``), so each candidate lies within a single path segment and
    # the regex's ``.*`` greediness is safely bounded to that segment.
    for path in base_dir.glob(glob):
        rel = path.relative_to(base_dir).as_posix()
        match = regex.match(rel)
        if match is None:
            continue
        stems.add(match.group(match.lastindex))
    return stems


def next_testcase_name(
    glob: str,
    used: Optional[Set[str]] = None,
    base_dir: pathlib.Path = pathlib.Path(),
) -> str:
    """Return the next free zero-padded counter name (no extension).

    Scans for files matching ``glob`` under ``base_dir`` (deducing each one's
    ``*`` stem) and returns the lowest non-colliding ``f'{i:03d}'`` stem.
    Returns ``'000'`` when nothing matches the glob yet.

    ``used`` adds extra reserved stems on top of the on-disk files, letting
    callers simulate a counter across not-yet-written names.
    """
    existing = stems_matching_glob(glob, base_dir=base_dir)
    if used is not None:
        existing |= used

    for i in itertools.count():
        name = f'{i:03d}'
        if name not in existing:
            return name
    raise AssertionError('unreachable')  # pragma: no cover


def default_stems(
    glob: str, count: int, base_dir: pathlib.Path = pathlib.Path()
) -> List[str]:
    """Assign ``count`` sequential glob-aware default stems.

    Simulates the on-disk counter so the defaults are sequential and
    collision-free against both files already matching ``glob`` and the stems
    assigned earlier in the same batch (000, 001, ... skipping taken ones).
    """
    # ``next_testcase_name`` re-scans disk on every call and unions ``used`` on
    # top, so we only need to accumulate the stems chosen so far this batch --
    # the on-disk collisions are handled for us.
    used: Set[str] = set()
    stems: List[str] = []
    for _ in range(count):
        stem = next_testcase_name(glob, used=used, base_dir=base_dir)
        used.add(stem)
        stems.append(stem)
    return stems


def validate_stems(stems: List[str]) -> Optional[str]:
    """Return an error message if ``stems`` is not a valid batch, else ``None``.

    A batch is invalid if any stem is empty/whitespace-only (no filename),
    contains whitespace (would yield an awkward filename), or if two stems are
    equal (they would map to the same file and overwrite one another).
    """
    for stem in stems:
        if not stem.strip():
            return 'Filenames cannot be empty.'
        if any(ch.isspace() for ch in stem):
            return f'Filename {stem!r} must not contain whitespace.'
    seen: Set[str] = set()
    for stem in stems:
        if stem in seen:
            return f'Duplicate filename {stem!r}: each test needs a distinct name.'
        seen.add(stem)
    return None


def get_manual_groups_by_name() -> Dict[str, TestcaseGroup]:
    """Return test groups backed by a glob-based manual folder.

    Filters ``package.get_test_groups_by_name()`` down to groups whose
    ``testcaseGlob`` is set and ends with ``.in``.
    """
    res: Dict[str, TestcaseGroup] = {}
    for name, group in package.get_test_groups_by_name().items():
        if group.testcaseGlob is not None and group.testcaseGlob.endswith('.in'):
            res[name] = group
    return res


def group_name_error(name: str) -> Optional[str]:
    """Why ``name`` cannot name a new test group, or ``None`` if it can."""
    try:
        TestcaseGroup(name=name)
    except pydantic.ValidationError:
        return (
            f'{name!r} is not a valid test group name: it must be 3 to 32 letters, '
            'digits, `-` or `_`, starting with a letter or digit.'
        )
    return None
