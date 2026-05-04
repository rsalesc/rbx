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
                    ignore=shutil.ignore_patterns(
                        '.box', 'build', '.limits', '__pycache__', '*.pyc'
                    ),
                )
            )
            old_cwd = pathlib.Path.cwd()
            # ``rbx`` CLI commands use ``syncer`` which calls
            # ``asyncio.get_event_loop()``; on Python 3.12+ that requires a
            # current loop to be set. Provision one for the duration of the
            # scenario.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                os.chdir(pkg_dir)
                testing_utils.clear_all_functools_cache()
                for step in self.scenario.steps:
                    self._run_step(pkg_dir, step)
            finally:
                os.chdir(old_cwd)
                testing_utils.clear_all_functools_cache()
                asyncio.set_event_loop(None)
                loop.close()

    def _run_step(self, pkg_dir: pathlib.Path, step: Step):
        result = CliRunner().invoke(rbx_app, shlex.split(step.cmd))
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
                f'[{self.path.parent.name}::{self.scenario.name}] '
                f'step {step.cmd!r} exited {result.exit_code}, '
                f'expected {step.expect_exit}\n'
                f'stdout:\n{result.stdout}\n'
                f'stderr:\n{result.stderr}'
                f'{exc}'
            )

    def reportinfo(self):
        return self.path, 0, f'scenario: {self.name}'
