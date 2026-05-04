"""Generic assertion helpers for e2e scenarios.

Each ``check_*`` function takes an :class:`AssertionContext` plus the value
of the corresponding ``expect.*`` field and raises :class:`AssertionError`
on failure. The runner is responsible for wrapping that error with package
and scenario context; assertion messages here should be specific enough that
the wrapped message pinpoints the failure but should NOT duplicate the
package/scenario prefix.
"""

import fnmatch
import pathlib
import re
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Union

from rbx import utils
from rbx.box.solutions import (
    SolutionReportSkeleton,
    SolutionSkeleton,
    get_worst_outcome,
)
from rbx.grading.steps import Evaluation
from tests.e2e.spec import SolutionMatcher, ZipMatcher


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


def _glob_in_zip(zip_path: pathlib.Path, pattern: str) -> bool:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    return any(fnmatch.fnmatch(n, pattern) for n in names)


def check_zip_contains(ctx: AssertionContext, matcher: ZipMatcher) -> None:
    zip_paths = _glob(ctx.package_root, matcher.path)
    if not zip_paths:
        raise AssertionError(f'no zip matched {matcher.path!r}')
    zip_path = zip_paths[0]
    for entry in matcher.entries:
        if not _glob_in_zip(zip_path, entry):
            raise AssertionError(f'{zip_path.name}: missing entry {entry!r}')


def _load_skeleton(package_root: pathlib.Path) -> SolutionReportSkeleton:
    """Load ``<package_root>/.box/runs/skeleton.yml``.

    Note: ``.box/runs/.irun/`` is the interactive-debug scratch space and is
    never read here; we only ever read the top-level ``skeleton.yml``.
    """
    skeleton_path = package_root / '.box' / 'runs' / 'skeleton.yml'
    if not skeleton_path.is_file():
        raise AssertionError(
            f'no run results found at {skeleton_path}; did the scenario run '
            f'`rbx run` before asserting `solutions:`?'
        )
    return utils.model_from_yaml(SolutionReportSkeleton, skeleton_path.read_text())


def _find_solution_skeleton(
    skeleton: SolutionReportSkeleton, sol_path: str
) -> SolutionSkeleton:
    target = pathlib.PurePath(sol_path)
    for sol in skeleton.solutions:
        if pathlib.PurePath(sol.path) == target:
            return sol
    known = sorted(str(s.path) for s in skeleton.solutions)
    raise AssertionError(
        f'solution {sol_path!r} not present in skeleton.yml; known solutions: {known}'
    )


def _resolve_eval_path(
    skeleton: SolutionReportSkeleton,
    sol: SolutionSkeleton,
    group: str,
    idx: int,
) -> pathlib.Path:
    """Compute the on-disk ``.eval`` path for a (solution, group, index) cell.

    The eval filename stem is taken from ``Testcase.inputPath.stem``, which
    for generated tests reflects the subgroup naming
    (e.g. ``1-gen-000``), not a flat ``{idx:03d}``. We recover it by looking
    up the matching ``GenerationTestcaseEntry`` in ``skeleton.entries``.
    """
    for entry in skeleton.entries:
        ge = entry.group_entry
        if ge.group == group and ge.index == idx:
            stem = entry.metadata.copied_to.inputPath.stem
            return sol.runs_dir / group / f'{stem}.eval'
    # Fallback to the historical ``{idx:03d}`` convention so cleanly-laid-out
    # packages still resolve even if entries metadata is sparse.
    return sol.runs_dir / group / f'{idx:03d}.eval'


def _read_eval(
    skeleton: SolutionReportSkeleton,
    sol: SolutionSkeleton,
    group: str,
    idx: int,
) -> Evaluation:
    eval_path = _resolve_eval_path(skeleton, sol, group, idx)
    if not eval_path.is_file():
        raise AssertionError(
            f'missing eval file for {sol.path}::{group}/{idx} at {eval_path}; '
            f'did the run finish without errors?'
        )
    return utils.model_from_yaml(Evaluation, eval_path.read_text())


def check_solutions(
    ctx: AssertionContext, matchers: Dict[str, SolutionMatcher]
) -> None:
    """Assert verdicts for one or more solutions.

    See ``docs/plans/2026-05-03-e2e-testing-strategy-design.md`` (Verdict
    source section) for the on-disk format. The matcher reads only what is
    asserted: groups/tests not mentioned (and not covered by ``*``) are
    silently allowed to have any verdict.

    Caveat: verdicts are the on-disk ``Outcome`` enum (post soft-TLE
    promotion). The cosmetic "⧖" rendering in the run report is a
    presentation-layer concern and is not what we compare against here.
    """
    skeleton = _load_skeleton(ctx.package_root)

    for sol_path, matcher in matchers.items():
        sol = _find_solution_skeleton(skeleton, sol_path)

        per_test = {k: v for k, v in matcher.entries.items() if '/' in k}
        per_group = {k: v for k, v in matcher.entries.items() if '/' not in k}

        # Validate unknown group references early.
        known_groups = {g.name for g in skeleton.groups}
        for gname in per_group:
            if gname not in known_groups:
                raise AssertionError(
                    f'{sol_path}: unknown group {gname!r}; '
                    f'known groups: {sorted(known_groups)}'
                )
        for test_path in per_test:
            gname, _, _ = test_path.partition('/')
            if gname not in known_groups:
                raise AssertionError(
                    f'{sol_path}: unknown group {gname!r} in test path '
                    f'{test_path!r}; known groups: {sorted(known_groups)}'
                )

        # 1. Per-test assertions.
        for test_path, expected in per_test.items():
            gname, _, idx_str = test_path.partition('/')
            try:
                idx = int(idx_str)
            except ValueError as e:
                raise AssertionError(
                    f'{sol_path}: invalid test index in {test_path!r}; '
                    f'expected `<group>/<int>`'
                ) from e
            actual = _read_eval(skeleton, sol, gname, idx).result.outcome
            if not expected.match(actual):
                raise AssertionError(
                    f'{sol_path}::{gname}/{idx}: expected {expected.name}, '
                    f'got {actual.short_name()} ({actual.value})'
                )

        # 2. Per-group + '*' fallback. Groups already covered by per-test
        # entries do NOT also receive an implicit group-level assertion.
        groups_with_per_test = {p.partition('/')[0] for p in per_test}

        for group in skeleton.groups:
            gname = group.name
            if gname in per_group:
                expected = per_group[gname]
            elif matcher.star is not None and gname not in groups_with_per_test:
                expected = matcher.star
            else:
                continue
            n = len(group.testcases)
            if n == 0:
                continue
            evals = [_read_eval(skeleton, sol, gname, i) for i in range(n)]
            actual = get_worst_outcome(evals)
            if not expected.match(actual):
                raise AssertionError(
                    f'{sol_path}::{gname}: expected {expected.name}, '
                    f'got {actual.short_name()} ({actual.value})'
                )


def check_zip_not_contains(ctx: AssertionContext, matcher: ZipMatcher) -> None:
    # Decision: a missing zip is treated as an error rather than a benign
    # no-op. A user writing ``zip_not_contains`` is asserting against a
    # specific zip they expect to exist; if the path resolves to nothing,
    # the most likely explanation is a typo in ``path``, not a deliberate
    # "nothing to assert against" intent. Pair with ``files_exist`` if you
    # need to be explicit that the zip itself must exist.
    zip_paths = _glob(ctx.package_root, matcher.path)
    if not zip_paths:
        raise AssertionError(f'no zip matched {matcher.path!r}')
    zip_path = zip_paths[0]
    for entry in matcher.entries:
        if _glob_in_zip(zip_path, entry):
            raise AssertionError(f'{zip_path.name}: unexpected entry {entry!r}')
