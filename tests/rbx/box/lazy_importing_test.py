import subprocess
import sys
from pathlib import Path
from typing import List

LAZY_MODULES = {
    'gitpython',
    'questionary',
    'fastapi',
    'requests',
    'pydantic_xml',
    'textual',
    'rbx.box.packaging.polygon.packager',
    'rbx.box.stresses',
}

# Modules that must not be loaded by `rbx.box.cli`, which every command pulls in.
CLI_LAZY_MODULES = {
    'textual',
    'iso639',
    # The BOCA scraping stack, reachable only through a `@boca/...` expansion.
    'bs4',
    'lxml',
    'mechanize',
    'dateparser',
}


def _imported_modules(*args: str) -> List[str]:
    result = subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        encoding='utf-8',
    )
    assert result.returncode == 0, result.stderr
    modules = result.stdout.splitlines()
    assert modules, (
        f'expected the helper to print the imported modules: {result.stderr}'
    )
    return modules


def test_rich_not_imported_unnecessary():
    file_path = Path(__file__).parent / 'lazy_importing_main.py'
    modules = _imported_modules('-m', 'coverage', 'run', str(file_path))
    assert not [module for module in modules if module in LAZY_MODULES]


def test_cli_does_not_import_lazy_modules():
    modules = _imported_modules(
        '-c',
        'import sys; import rbx.box.cli; print("\\n".join(sys.modules))',
    )
    assert not [module for module in modules if module in CLI_LAZY_MODULES]
