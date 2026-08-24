"""Fail the build when a release artifact is bigger than we allow it to be.

Run by `mise run build` right after `uv build`, so every path that produces
artifacts -- `build`, `publish`, `release` -- is guarded before anything
reaches PyPI.

The check exists because size regressions here are silent and one-directional:
1.2.0 shipped a 23.8 MB sdist, 90% of which was `vscode/node_modules` swept in
by accident. Nothing failed, nothing warned, and the only symptom was a slow
`pip download`. A hard ceiling turns that class of mistake into a build error.

When an artifact is over its limit the report names the directories responsible
rather than just the number, so the failure points at the cause. Limits live in
`[tool.rbx.dist]` in pyproject.toml and are meant to be edited -- but
deliberately, when growth is understood, never to silence a red build.
"""

import argparse
import dataclasses
import pathlib
import sys
import tarfile
import zipfile
from typing import Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - exercised by whichever interpreter runs the build
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

MB = 1024 * 1024

# Kind -> the pyproject key holding its ceiling, and the fallback used when
# pyproject says nothing. The fallbacks are a backstop for a malformed config,
# not the source of truth -- pyproject is.
LIMIT_KEYS: Dict[str, str] = {'wheel': 'max-wheel-mb', 'sdist': 'max-sdist-mb'}
DEFAULT_LIMITS: Dict[str, float] = {'wheel': 5.0, 'sdist': 5.0}

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclasses.dataclass
class Violation:
    path: pathlib.Path
    kind: str
    size: int
    limit_mb: float
    offenders: List[Tuple[str, int]]
    total_uncompressed: int


def load_limits(pyproject: pathlib.Path) -> Dict[str, float]:
    """Read the per-kind ceilings (in MB) out of `[tool.rbx.dist]`."""
    limits = dict(DEFAULT_LIMITS)
    if not pyproject.is_file():
        return limits
    with pyproject.open('rb') as f:
        data = tomllib.load(f)
    table = data.get('tool', {}).get('rbx', {}).get('dist', {})
    for kind, key in LIMIT_KEYS.items():
        value = table.get(key)
        if isinstance(value, (int, float)) and value > 0:
            limits[kind] = float(value)
    return limits


def kind_of(path: pathlib.Path) -> Optional[str]:
    if path.name.endswith('.whl'):
        return 'wheel'
    if path.name.endswith('.tar.gz'):
        return 'sdist'
    return None


def entries(path: pathlib.Path) -> List[Tuple[str, int]]:
    """List `(name, uncompressed_size)` for every file inside an artifact."""
    kind = kind_of(path)
    if kind == 'wheel':
        with zipfile.ZipFile(path) as zf:
            return [(i.filename, i.file_size) for i in zf.infolist() if not i.is_dir()]
    with tarfile.open(path) as tf:
        # Strip the `name-version/` prefix every sdist wraps its content in, so
        # offenders read as repository paths.
        return [
            (m.name.split('/', 1)[1] if '/' in m.name else m.name, m.size)
            for m in tf.getmembers()
            if m.isfile()
        ]


def top_offenders(
    files: Sequence[Tuple[str, int]], depth: int = 2, limit: int = 6
) -> List[Tuple[str, int]]:
    """Aggregate files into their top `depth` path components, largest first."""
    totals: Dict[str, int] = {}
    for name, size in files:
        parts = name.split('/')
        key = '/'.join(parts[:depth]) if len(parts) > depth else name
        totals[key] = totals.get(key, 0) + size
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:limit]


def check_artifact(path: pathlib.Path, limits: Dict[str, float]) -> Optional[Violation]:
    kind = kind_of(path)
    if kind is None:
        return None
    size = path.stat().st_size
    limit_mb = limits[kind]
    if size <= limit_mb * MB:
        return None
    files = entries(path)
    return Violation(
        path=path,
        kind=kind,
        size=size,
        limit_mb=limit_mb,
        offenders=top_offenders(files),
        total_uncompressed=sum(s for _, s in files),
    )


def _mib(n: int) -> str:
    return f'{n / MB:.2f} MiB'


def format_violation(v: Violation) -> str:
    rule = '=' * 72
    lines = [
        '',
        rule,
        f'  RELEASE BLOCKED: {v.path.name} is {_mib(v.size)}, '
        f'over the {v.limit_mb:.2f} MB limit',
        rule,
        '',
        f'  Unpacked it holds {_mib(v.total_uncompressed)}. Biggest contents:',
        '',
    ]
    for name, size in v.offenders:
        share = size / v.total_uncompressed * 100 if v.total_uncompressed else 0.0
        lines.append(f'    {_mib(size):>12}  {share:5.1f}%  {name}')
    lines += [
        '',
        '  If something in that list should not ship, exclude it in',
        f'  [tool.hatch.build.targets.{v.kind}] in pyproject.toml.',
        '',
        f'  If this growth is intended, raise {LIMIT_KEYS[v.kind]} in',
        '  [tool.rbx.dist] -- and say why in the commit message.',
        rule,
        '',
    ]
    return '\n'.join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='Fail the build when a release artifact exceeds its size limit.'
    )
    parser.add_argument(
        'dist',
        nargs='?',
        default=str(REPO_ROOT / 'dist'),
        help='directory holding the built artifacts (default: ./dist)',
    )
    args = parser.parse_args(argv)

    dist = pathlib.Path(args.dist)
    limits = load_limits(REPO_ROOT / 'pyproject.toml')
    artifacts = sorted(p for p in dist.glob('*') if kind_of(p) is not None)

    if not artifacts:
        # Passing on an empty dist/ would make the guard quietly useless the
        # first time someone reorders the build steps.
        print(
            f'No wheel or sdist found in {dist}/ -- nothing to check.', file=sys.stderr
        )
        return 1

    violations = [v for v in (check_artifact(p, limits) for p in artifacts) if v]
    for v in violations:
        print(format_violation(v), file=sys.stderr)

    if violations:
        return 1

    for p in artifacts:
        kind = kind_of(p)
        assert kind is not None
        print(f'{p.name}: {_mib(p.stat().st_size)} (limit {limits[kind]:.2f} MB) OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
