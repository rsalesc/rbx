import subprocess
import sys
from pathlib import Path

LAZY_MODULES = {
    'gitpython',
    'questionary',
    'fastapi',
    'requests',
    'pydantic_xml',
    'rbx.box.packaging.polygon.packager',
    'rbx.box.stresses',
}


def test_rich_not_imported_unnecessary():
    file_path = Path(__file__).parent / 'lazy_importing_main.py'
    result = subprocess.run(
        [sys.executable, '-m', 'coverage', 'run', str(file_path)],
        capture_output=True,
        encoding='utf-8',
    )
    modules = result.stdout.splitlines()
    modules = [module for module in modules if module in LAZY_MODULES]
    assert not modules
