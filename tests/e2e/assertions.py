"""Generic assertion helpers for e2e scenarios.

Each ``check_*`` function takes an :class:`AssertionContext` plus the value
of the corresponding ``expect.*`` field and raises :class:`AssertionError`
on failure. The runner is responsible for wrapping that error with package
and scenario context; assertion messages here should be specific enough that
the wrapped message pinpoints the failure but should NOT duplicate the
package/scenario prefix.
"""

import collections
import fnmatch
import json
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
from rbx.box.testcase_schema import TestcaseEntry
from rbx.config import CACHE_DIR_NAME
from rbx.grading.steps import Evaluation
from tests.e2e.spec import (
    PolygonUploadMatcher,
    SolutionMatcher,
    TestsMatcher,
    ZipFileMatcher,
    ZipMatcher,
)

# Matches a single ``\includegraphics{...}`` (optionally with ``[opts]``) and
# captures the resource path argument.
_INCLUDEGRAPHICS_RE = re.compile(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}')

# Statement fields the recording fake serializes (see tests/e2e/polygon_capture.py).
_STATEMENT_FIELDS = ('name', 'legend', 'input', 'output', 'interaction', 'notes')


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


def check_stdout_not_contains(
    ctx: AssertionContext, expected: Union[str, List[str]]
) -> None:
    for needle in _as_list(expected):
        if needle in ctx.stdout:
            raise AssertionError(f'stdout unexpectedly contains {needle!r}')


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
        _match_text(path, target.read_text(), needle)


def _match_text(label: str, text: str, needle: str) -> None:
    """Assert ``text`` matches ``needle`` using ``file_contains`` semantics.

    A value longer than two chars wrapped in forward slashes is a regex (the
    slashes are stripped); everything else is a literal substring. Raises
    ``AssertionError`` prefixed with ``label`` on mismatch.
    """
    if len(needle) > 2 and needle.startswith('/') and needle.endswith('/'):
        regex = needle[1:-1]
        if not re.search(regex, text):
            raise AssertionError(f'{label}: regex {needle} no match')
    elif needle not in text:
        raise AssertionError(f'{label}: missing {needle!r}')


def check_polygon_upload(ctx: AssertionContext, matcher: PolygonUploadMatcher) -> None:
    """Assert over the recording-fake capture written by ``rbx package polygon -u``.

    Reads the capture directory (``matcher.dir`` relative to the package root)
    produced by :mod:`tests.e2e.polygon_capture`: ``resources.json`` (uploaded
    statement-resource names) and ``statements/<lang>.json`` (the captured
    ``save_statement`` payloads). See :class:`PolygonUploadMatcher`.
    """
    cap = ctx.package_root / matcher.dir
    if not cap.is_dir():
        raise AssertionError(f'polygon capture dir not found: {matcher.dir}')

    resources_json = cap / 'resources.json'
    uploaded = (
        set(json.loads(resources_json.read_text()))
        if resources_json.is_file()
        else set()
    )

    for name in matcher.resources_present:
        if name not in uploaded:
            raise AssertionError(
                f'expected uploaded resource {name!r}; uploaded: {sorted(uploaded)}'
            )
    for name in matcher.resources_absent:
        if name in uploaded:
            raise AssertionError(f'resource {name!r} should NOT have been uploaded')

    statements_dir = cap / 'statements'
    for lang, expect in matcher.statements.items():
        path = statements_dir / f'{lang}.json'
        if not path.is_file():
            present = sorted(p.stem for p in statements_dir.glob('*.json'))
            raise AssertionError(
                f'no statement uploaded for language {lang!r}; present: {present}'
            )
        data = json.loads(path.read_text())
        for field in _STATEMENT_FIELDS:
            for needle in _as_list(getattr(expect, f'{field}_contains')):
                if needle not in (data.get(field) or ''):
                    raise AssertionError(
                        f'statement[{lang}].{field} missing {needle!r}; '
                        f'got: {data.get(field)!r}'
                    )

    if matcher.resources_referenced_consistent:
        # Stems of uploaded resources, so an extension-less reference
        # (``\includegraphics{img__d}``) still matches ``img__d.png``.
        stems = {n.rsplit('.', 1)[0] for n in uploaded}
        for path in sorted(statements_dir.glob('*.json')):
            data = json.loads(path.read_text())
            for field in _STATEMENT_FIELDS:
                text = data.get(field) or ''
                for ref in _INCLUDEGRAPHICS_RE.findall(text):
                    if ref not in uploaded and ref not in stems:
                        raise AssertionError(
                            f'statement[{path.stem}].{field} references '
                            f'\\includegraphics{{{ref}}} but no matching resource '
                            f'was uploaded; uploaded: {sorted(uploaded)}'
                        )


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


def check_zip_file_contains(ctx: AssertionContext, matcher: ZipFileMatcher) -> None:
    zip_paths = _glob(ctx.package_root, matcher.path)
    if not zip_paths:
        raise AssertionError(f'no zip matched {matcher.path!r}')
    zip_path = zip_paths[0]
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        for entry, needle in matcher.entries.items():
            if entry not in names:
                raise AssertionError(f'{zip_path.name}: no entry {entry!r}')
            text = zf.read(entry).decode()
            _match_text(f'{zip_path.name}:{entry}', text, needle)


def _load_skeleton(package_root: pathlib.Path) -> SolutionReportSkeleton:
    """Load ``<package_root>/.rbx/runs/skeleton.yml``.

    Note: ``.rbx/runs/.irun/`` is the interactive-debug scratch space and is
    never read here; we only ever read the top-level ``skeleton.yml``.
    """
    skeleton_path = package_root / CACHE_DIR_NAME / 'runs' / 'skeleton.yml'
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
    return skeleton.get_solution_entry_prefix(
        sol, TestcaseEntry(group=group, index=idx)
    ).with_suffix('.eval')


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


def check_tests(ctx: AssertionContext, matcher: TestsMatcher) -> None:
    """Assert against the contents of ``build/tests/`` after ``rbx build``.

    Counts are computed from ``*.in`` files only -- ``*.out``, ``*.eval``
    and ``*.log`` siblings are ignored. Group names are the immediate
    subdirectories of ``build/tests/`` (e.g. ``main``, ``samples``).

    ``all_valid`` is currently unsupported because ``rbx build`` does not
    persist a per-testcase validation report. Setting it to ``True``
    raises rather than silently passing -- see :class:`TestsMatcher` for
    background.
    """
    tests_root = ctx.package_root / 'build' / 'tests'
    if not tests_root.is_dir():
        raise AssertionError(
            "build/tests/ not found; did 'rbx build' run successfully?"
        )

    inputs = sorted(p for p in tests_root.rglob('*.in') if p.is_file())
    actual_count = len(inputs)
    actual_groups: Dict[str, int] = collections.Counter(p.parent.name for p in inputs)

    if matcher.count is not None and actual_count != matcher.count:
        raise AssertionError(
            f'tests.count: expected {matcher.count}, got {actual_count}'
        )

    for grp, n in matcher.groups.items():
        if grp not in actual_groups:
            raise AssertionError(
                f'tests.groups.{grp}: group not found; '
                f'known groups: {sorted(actual_groups)}'
            )
        if actual_groups[grp] != n:
            raise AssertionError(
                f'tests.groups.{grp}: expected {n}, got {actual_groups[grp]}'
            )

    for path in matcher.exist:
        if not (tests_root / path).exists():
            raise AssertionError(f'tests.exist: missing {path!r}')

    if matcher.all_valid is True:
        raise AssertionError(
            'tests.all_valid: not yet supported; rbx build does not persist '
            'a structured per-testcase validation report. Drop the flag '
            'until the build report lands.'
        )
