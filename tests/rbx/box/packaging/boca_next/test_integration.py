"""Phase 9 integration harness for the rbx_boca Layer-2 runtime.

These tests validate the runtime end-to-end. They are deliberately HERMETIC:
no gcc, no root, no real SUID safeexec, no real pipe.exe (this machine cannot
build/run SUID safeexec or compile C).

Manifest reading from the .pyz uses ``pkgutil.get_data`` (zip-safe, not
deprecated); verified by ``test_pyz_limits_end_to_end`` reading task.json /
language.json from inside a real archive with NO env override.
"""

import subprocess

from tests.rbx.box.packaging.boca_next import _bundle

# --- Task 9.1: zipapp bundle + limits e2e -------------------------------------


def test_pyz_limits_end_to_end(tmp_path):
    """A real .pyz reads its bundled manifests (no env override) and prints the
    limits. Proves zipimport + manifest reading works from a real archive."""
    pyz = _bundle.build_pyz(
        tmp_path,
        task_json={'task_type': 'batch', 'output_kb': 65536},
        language_json={
            'language': {
                'id': 'cpp',
                'kind': 'compiled_static',
                'compiler_argv': ['g++', '-o', '{exe}', '{src}'],
                'run_argv': ['{exe}'],
            },
            'limits': {'time_sec': 3, 'runs': 2, 'memory_mb': 256},
        },
    )
    result = subprocess.run(
        [str(pyz), 'limits'],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['3', '2', '256', '65536']
