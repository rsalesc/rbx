"""Builds the publishable tree for the versioned schema site.

Run from CI against a checkout at a release tag:

    uv run python -m rbx.box.schema_publish <out-dir> <version>

`out-dir` is a checkout of the schemas repo, so existing version directories
are preserved and the index is recomputed from what is on disk.
"""

import json
import pathlib
import shutil
import sys

from rbx.box.schema_export import MODELS, export_schemas
from rbx.utils import get_semver


def _version_dirs(out: pathlib.Path):
    """Published `<major>.<minor>` directories, oldest first."""

    def key(name: str):
        return tuple(int(part) for part in name.split('.'))

    names = []
    for path in out.iterdir():
        if not path.is_dir() or path.name == 'latest':
            continue
        parts = path.name.split('.')
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            names.append(path.name)
    return sorted(names, key=key)


def build_site(out: pathlib.Path, version: str) -> None:
    semver = get_semver(version)
    minor = f'{semver.major}.{semver.minor}'

    out.mkdir(parents=True, exist_ok=True)
    target = out / minor
    if target.exists():
        shutil.rmtree(target)
    export_schemas(target)

    versions = _version_dirs(out)
    # `latest` tracks the greatest published minor on disk, so re-publishing an
    # older patch never demotes it.
    latest = versions[-1]

    latest_dir = out / 'latest'
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    shutil.copytree(out / latest, latest_dir)

    (out / 'index.json').write_text(
        json.dumps(
            {
                'latest': latest,
                'versions': versions,
                'models': [model.__name__ for model in MODELS],
            },
            indent=4,
        )
    )


if __name__ == '__main__':
    build_site(pathlib.Path(sys.argv[1]), sys.argv[2])
