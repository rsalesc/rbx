"""Test helper: build a real executable ``.pyz`` bundling the ``rbx_boca``
runtime plus its manifests, mirroring the Layer-1 packaged layout.

The produced archive is self-contained: ``importlib.resources`` /
``pkgutil.get_data`` find ``task.json`` and ``language.json`` inside the zip,
so the runtime reads them with NO ``RBX_BOCA_BUNDLE_DIR`` override -- exactly as
it will in production.
"""

import json
import os
import shutil
import tempfile
import zipapp
from pathlib import Path
from typing import Any, Dict, Optional

# rbx_boca runtime package dir: tests/rbx/box/packaging/boca_next -> repo root.
_RUNTIME_PKG = (
    Path(__file__).resolve().parents[5]
    / 'rbx'
    / 'resources'
    / 'packagers'
    / 'boca_next'
    / 'runtime'
    / 'rbx_boca'
)

_MAIN = (
    'import sys\n'
    'from rbx_boca import entrypoints\n'
    'sys.exit(entrypoints.main(sys.argv[1:]))\n'
)


def build_pyz(
    dest_dir: Path,
    task_json: Dict[str, Any],
    language_json: Dict[str, Any],
    *,
    assets: Optional[Dict[str, bytes]] = None,
) -> Path:
    """Build an executable ``app.pyz`` under ``dest_dir`` and return its path.

    - ``task_json`` / ``language_json`` are written into ``rbx_boca/`` inside the
      archive so the runtime reads them via ``pkgutil.get_data``.
    - ``assets`` (name -> bytes) are written into ``rbx_boca/assets/``.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / 'app.pyz'

    staging = Path(tempfile.mkdtemp(prefix='rbx_boca_pyz_'))
    try:
        pkg = staging / 'rbx_boca'
        # Copy the whole package, skipping bytecode caches.
        shutil.copytree(
            _RUNTIME_PKG, pkg, ignore=shutil.ignore_patterns('__pycache__', '*.pyc')
        )

        (pkg / 'task.json').write_text(json.dumps(task_json))
        (pkg / 'language.json').write_text(json.dumps(language_json))

        if assets:
            assets_dir = pkg / 'assets'
            assets_dir.mkdir(exist_ok=True)
            for name, content in assets.items():
                (assets_dir / name).write_bytes(content)

        (staging / '__main__.py').write_text(_MAIN)

        zipapp.create_archive(
            str(staging), str(target), interpreter='/usr/bin/env python3'
        )
        os.chmod(str(target), 0o755)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return target
