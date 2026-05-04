"""Runtime for executing e2e scenarios.

Each :class:`E2EScenarioItem` represents a single scenario from an
``e2e.rbx.yml`` file. To guarantee hermetic isolation, the source package
directory (the directory containing ``e2e.rbx.yml``) is copied to a fresh
temporary directory before the scenario runs, and all CLI invocations execute
with that temporary directory as the cwd. This ensures the on-disk source
tree is never mutated by ``rbx`` commands (which create ``.box/``, ``build/``
and other artefacts).

We intentionally do not use :class:`TestingPackage` here because its
``initialize_preset`` step writes a ``.local.rbx/preset.rbx.yml`` without a
``min_version`` field, which the ``rbx`` CLI then rejects on load. The e2e
runner instead just chdirs into the copied package and lets ``rbx`` discover
``problem.rbx.yml`` via its normal lookup path.
"""

import asyncio
import os
import pathlib
import shlex
import shutil
import tempfile
import traceback

import pytest
from typer.testing import CliRunner

from rbx import testing_utils
from rbx.box.cli import app as rbx_app
from tests.e2e.spec import Scenario, Step

# Patterns excluded when copying a fixture directory into the run tmpdir.
# These are paths that ``rbx`` (or prior test runs) generates and that should
# regenerate freshly inside the tmpdir rather than leak in from source.
COPY_IGNORE_PATTERNS = (
    '.box',
    'build',
    '.limits',
    '__pycache__',
    '*.pyc',
    'rbx.h',
    '.local.rbx',
    '.cache',
    '.testdata',
)


def run_step(
    scenario_path: pathlib.Path,
    scenario_name: str,
    step: Step,
    cwd: pathlib.Path,
) -> None:
    """Invoke a single step's CLI command and assert its exit code.

    Raises ``AssertionError`` with package name, scenario name, command,
    expected vs actual exit codes, and stdout/stderr if the exit code does
    not match.
    """
    old_cwd = pathlib.Path.cwd()
    os.chdir(cwd)
    try:
        result = CliRunner().invoke(rbx_app, shlex.split(step.cmd))
    finally:
        os.chdir(old_cwd)
    if result.exit_code != step.expect_exit:
        exc = ''
        if result.exception is not None:
            exc = '\nexception:\n' + ''.join(
                traceback.format_exception(
                    type(result.exception),
                    result.exception,
                    result.exception.__traceback__,
                )
            )
        raise AssertionError(
            f'[{scenario_path.parent.name}::{scenario_name}] '
            f'step {step.cmd!r} exited {result.exit_code}, '
            f'expected {step.expect_exit}\n'
            f'stdout:\n{result.stdout}\n'
            f'stderr:\n{result.stderr}'
            f'{exc}'
        )


class E2EScenarioItem(pytest.Item):
    def __init__(self, *, scenario: Scenario, **kwargs):
        super().__init__(**kwargs)
        self.scenario = scenario

    def runtest(self):
        source_dir = self.path.parent
        with tempfile.TemporaryDirectory(prefix='rbx-e2e-') as tmp_root:
            pkg_dir = pathlib.Path(
                shutil.copytree(
                    source_dir,
                    tmp_root,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS),
                )
            )
            # ``rbx`` CLI commands use ``syncer`` which calls
            # ``asyncio.get_event_loop()``; on Python 3.12+ that requires a
            # current loop to be set. Provision one for the duration of the
            # scenario.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                testing_utils.clear_all_functools_cache()
                for step in self.scenario.steps:
                    run_step(self.path, self.scenario.name, step, pkg_dir)
            finally:
                testing_utils.clear_all_functools_cache()
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.run_until_complete(loop.shutdown_default_executor())
                except Exception:
                    pass
                finally:
                    asyncio.set_event_loop(None)
                    loop.close()

    def reportinfo(self):
        return self.path, 0, f'scenario: {self.name}'
