"""Runtime for executing e2e scenarios.

Each :class:`E2EScenarioItem` represents a single scenario from an
``e2e.rbx.yml`` file. To guarantee hermetic isolation, the source package
directory (the directory containing ``e2e.rbx.yml``) is copied to a fresh
temporary directory before the scenario runs, and all CLI invocations execute
with that temporary directory as the cwd. This ensures the on-disk source
tree is never mutated by ``rbx`` commands (which create ``.rbx/``, ``build/``
and other artefacts).

We intentionally do not use :class:`TestingPackage` here because its
``initialize_preset`` step writes a ``.local.rbx/preset.rbx.yml`` without a
``min_version`` field, which the ``rbx`` CLI then rejects on load. The e2e
runner instead just chdirs into the copied package and lets ``rbx`` discover
``problem.rbx.yml`` via its normal lookup path.
"""

import asyncio
import contextlib
import os
import pathlib
import re
import shlex
import shutil
import tempfile
import traceback

import pytest
from typer.testing import CliRunner

from rbx import testing_utils
from rbx.box.cli import app as rbx_app
from rbx.box.contest import contest_state
from rbx.config import get_default_app_path
from tests.e2e.assertions import (
    AssertionContext,
    check_file_contains,
    check_files_absent,
    check_files_exist,
    check_solutions,
    check_stderr_contains,
    check_stdout_contains,
    check_stdout_matches,
    check_stdout_not_contains,
    check_tests,
    check_zip_contains,
    check_zip_file_contains,
    check_zip_not_contains,
)
from tests.e2e.spec import Expect, Scenario, Step

# ANSI CSI/SGR/OSC sequences emitted by Rich when colors are enabled in the
# capture stream (e.g. FORCE_COLOR=1, or TTY-detected runs). Stdout/stderr
# assertions test user-visible content, so strip these before comparing —
# otherwise styled segments break literal substring matches like 'div1 *'.
_ANSI_RE = re.compile(r'\x1b(?:\[[0-9;?]*[A-Za-z]|\][^\x07\x1b]*(?:\x07|\x1b\\))')


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


# Patterns excluded when copying a fixture directory into the run tmpdir.
# These are paths that ``rbx`` (or prior test runs) generates and that should
# regenerate freshly inside the tmpdir rather than leak in from source.
# Note: ``.local.rbx`` is intentionally NOT excluded -- a fixture may commit a
# minimal local preset there (e.g. so ``contest add_variant`` resolves offline).
COPY_IGNORE_PATTERNS = (
    '.rbx',
    '.box',
    'build',
    '.limits',
    '__pycache__',
    '*.pyc',
    'rbx.h',
    '.cache',
    '.testdata',
)


def seed_package_from_preset(preset_name: str, dest: pathlib.Path) -> None:
    """Overlay a named preset's ``problem/`` package into ``dest``.

    Resolves ``presets/<preset_name>/problem`` under the rbx resources path (the
    same location ``rbx`` itself resolves presets from) and copies it into
    ``dest``, dereferencing symlinks (so statement assets like
    ``documents/icpc.sty`` land as regular files) and skipping build cruft
    (``.rbx``, ``build``, ...). ``dest`` is an existing package directory (the
    overlay target); any files already present (e.g. the fixture's own
    ``e2e.rbx.yml``) are preserved unless the preset overwrites them.
    """
    if not dest.is_dir():
        raise FileNotFoundError(f'seed destination does not exist: {dest}')
    preset_problem_dir = get_default_app_path() / 'presets' / preset_name / 'problem'
    if not preset_problem_dir.is_dir():
        raise FileNotFoundError(
            f'preset {preset_name!r} problem package not found at {preset_problem_dir}'
        )
    shutil.copytree(
        preset_problem_dir,
        dest,
        symlinks=False,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS),
    )


# Field names on ``Expect`` paired with the assertion check they dispatch to.
_GENERIC_CHECKS = (
    ('stdout_contains', check_stdout_contains),
    ('stdout_not_contains', check_stdout_not_contains),
    ('stderr_contains', check_stderr_contains),
    ('stdout_matches', check_stdout_matches),
    ('files_exist', check_files_exist),
    ('files_absent', check_files_absent),
    ('file_contains', check_file_contains),
    ('zip_contains', check_zip_contains),
    ('zip_not_contains', check_zip_not_contains),
    ('zip_file_contains', check_zip_file_contains),
    ('solutions', check_solutions),
    ('tests', check_tests),
)


@contextlib.contextmanager
def _snapshot_e2e_contextvars():
    """Snapshots and restores ContextVars that scenarios may mutate.

    Keep the list of vars in sync with ``_isolate_global_state`` in
    ``tests/rbx/conftest.py`` so unit and e2e suites have matching isolation.
    """
    context_vars = [contest_state.selected_variant_id_var]
    snapshots = [(v, v.get()) for v in context_vars]
    try:
        yield
    finally:
        for var, value in snapshots:
            var.set(value)


def _run_generic_assertions(ctx: AssertionContext, expect: Expect) -> None:
    for name, fn in _GENERIC_CHECKS:
        value = getattr(expect, name)
        if value is None:
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        fn(ctx, value)


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
    target_cwd = cwd / step.cwd if step.cwd else cwd
    if not target_cwd.is_dir():
        raise AssertionError(
            f'[{scenario_path.parent.name}::{scenario_name}] '
            f'step cwd {step.cwd!r} does not exist under {cwd}'
        )
    old_cwd = pathlib.Path.cwd()
    os.chdir(target_cwd)
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

    ctx = AssertionContext(
        package_root=cwd,
        stdout=_strip_ansi(result.stdout),
        stderr=_strip_ansi(result.stderr),
    )
    try:
        _run_generic_assertions(ctx, step.expect)
    except AssertionError as e:
        raise AssertionError(
            f'[{scenario_path.parent.name}::{scenario_name}] '
            f'step {step.cmd!r}: {e}\n'
            f'stdout:\n{result.stdout}\n'
            f'stderr:\n{result.stderr}'
        ) from e


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
            if self.scenario.seed_from_preset:
                seed_package_from_preset(self.scenario.seed_from_preset, pkg_dir)
            # ``rbx`` CLI commands use ``syncer`` which calls
            # ``asyncio.get_event_loop()``; on Python 3.12+ that requires a
            # current loop to be set. Provision one for the duration of the
            # scenario.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # Snapshot contextvars that the CLI mutates, so a scenario that
            # sets `-C <id>` does not leak its variant id into the next
            # scenario run in the same process. Mirrors the autouse
            # `_isolate_global_state` fixture in tests/rbx/conftest.py.
            try:
                testing_utils.clear_all_functools_cache()
                with _snapshot_e2e_contextvars():
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
