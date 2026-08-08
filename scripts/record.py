"""Record the documentation's asciinema casts.

Usage:
    python scripts/record.py                # record everything
    python scripts/record.py run-basic ...  # record only the named specs
    python scripts/record.py --check        # lint references, record nothing
"""

import argparse
import pathlib
import sys
from typing import List

from scripts.casts.links import check_links
from scripts.casts.recorder import record
from scripts.casts.spec import load_spec

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SPECS_ROOT = REPO_ROOT / 'casts'
FIXTURES_ROOT = SPECS_ROOT / 'fixtures'
DOCS_ROOT = REPO_ROOT / 'docs'
CASTS_OUT = DOCS_ROOT / 'assets' / 'casts'


def _spec_paths(names: List[str]) -> List[pathlib.Path]:
    if not names:
        return sorted(SPECS_ROOT.glob('*.yml'))
    paths = []
    for name in names:
        path = SPECS_ROOT / f'{name}.yml'
        if not path.exists():
            raise SystemExit(f'no such recording spec: {path}')
        paths.append(path)
    return paths


def _run_check() -> int:
    report = check_links(DOCS_ROOT, CASTS_OUT)
    for reference in report.missing:
        print(f'{reference.page}:{reference.line}: no cast named {reference.target!r}')
    for orphan in report.orphans:
        print(f'{CASTS_OUT / (orphan + ".cast")}: not referenced by any page')
    for pending in report.pending:
        print(f'{pending.page}:{pending.line}: {pending.detail}')
    if report.legacy:
        print(
            f'{len(report.legacy)} cast(s) still hosted on asciinema.org, '
            'not yet migrated'
        )
    print('OK' if report.ok else 'FAILED')
    return 0 if report.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('names', nargs='*', help='recording names (default: all)')
    parser.add_argument(
        '--check', action='store_true', help='lint references only, record nothing'
    )
    args = parser.parse_args()

    if args.check:
        return _run_check()

    for path in _spec_paths(args.names):
        spec = load_spec(path)
        print(f'recording {spec.name}...', flush=True)
        out = record(
            spec, fixtures_root=FIXTURES_ROOT, out_path=CASTS_OUT / f'{spec.name}.cast'
        )
        print(f'  wrote {out.relative_to(REPO_ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
