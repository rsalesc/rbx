"""Copy the files every bundled preset shares into each of them.

Some files -- the contest's `statements/icpc.sty` first of all -- must be the
same in every preset rbx ships, or a fix (or a new statement language) lands in
one preset and silently not in the others (#969). Their single source is
`rbx/resources/presets/_shared/`, laid out like a preset: a file at
`_shared/<path>` is copied to `<preset>/<path>` for every bundled preset (each
folder under `presets/` holding a `preset.rbx.yml`).

Why copies rather than symlinks: a preset is also installed straight from the
repository (`rsalesc/rbx/rbx/resources/presets/<name>`, at a tool tag), which
clones the repo and copies only the preset's own directory, symlinks kept as
symlinks. A link reaching out to `_shared/` would arrive dangling. So every
preset stays self-contained, and `--check` -- which a test calls -- is what
keeps the copies from drifting.

Edit the file under `_shared/`, then run `mise run sync-presets`. It also runs
as a commitizen `pre_bump_hook`, so a release's bump commit -- and the tag that
remote installs fetch presets from -- always carries synced copies; and
`mise run build` runs `--check`, so a wheel is never built from drifted ones.
Standard library only: hooks run under whatever `python3` is on PATH.
"""

import argparse
import pathlib
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PRESETS_DIR = REPO_ROOT / 'rbx' / 'resources' / 'presets'
SHARED_DIR = PRESETS_DIR / '_shared'


def bundled_presets() -> List[pathlib.Path]:
    return sorted(
        d
        for d in PRESETS_DIR.iterdir()
        if d.is_dir() and d != SHARED_DIR and (d / 'preset.rbx.yml').is_file()
    )


def shared_files() -> List[pathlib.Path]:
    return sorted(
        p.relative_to(SHARED_DIR) for p in SHARED_DIR.rglob('*') if p.is_file()
    )


def copies() -> List[Tuple[pathlib.Path, pathlib.Path]]:
    """Every (source, destination) pair the shared folder implies."""
    return [
        (SHARED_DIR / rel, preset / rel)
        for preset in bundled_presets()
        for rel in shared_files()
    ]


def out_of_sync() -> List[pathlib.Path]:
    return [
        dst
        for src, dst in copies()
        if not dst.is_file() or dst.read_bytes() != src.read_bytes()
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        '--check',
        action='store_true',
        help='Only report out-of-sync copies; exit 1 if there are any.',
    )
    parser.add_argument(
        '--stage',
        action='store_true',
        help='`git add` every copy written. The bump commit is made with '
        '`git commit -a`, which would miss a copy new to its preset.',
    )
    args = parser.parse_args(argv)

    stale = out_of_sync()
    if args.check:
        for dst in stale:
            print(f'out of sync: {dst.relative_to(REPO_ROOT)}')
        return 1 if stale else 0

    for src, dst in copies():
        if dst in stale:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            print(f'updated {dst.relative_to(REPO_ROOT)}')
    if args.stage and stale:
        subprocess.run(
            ['git', 'add', '--', *map(str, stale)], cwd=REPO_ROOT, check=True
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
