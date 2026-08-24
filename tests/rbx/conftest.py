import dataclasses
import os
import pathlib
from collections.abc import Iterator

import pytest
from rich.console import Console

from rbx.config import CACHE_DIR_NAME, LEGACY_CACHE_DIR_NAME
from rbx.testing_utils import get_resources_path, get_testdata_path
from rbx.utils import copytree_honoring_gitignore


@pytest.fixture(scope='session')
def cder():
    class Cder:
        def __init__(self, path: pathlib.Path):
            self.path = path

        def __enter__(self) -> None:
            self.old_cwd = pathlib.Path.cwd()
            os.chdir(self.path)

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            os.chdir(self.old_cwd)

    yield Cder


@pytest.fixture
def testdata_path() -> pathlib.Path:
    return get_testdata_path()


@pytest.fixture
def resources_path() -> pathlib.Path:
    return get_resources_path()


@pytest.fixture
def cleandir(tmp_path_factory, cder) -> Iterator[pathlib.Path]:
    new_dir = tmp_path_factory.mktemp('cleandir')
    abspath = new_dir.absolute()
    with cder(abspath):
        yield abspath


@pytest.fixture
def cleandir_with_testdata(
    request, testdata_path: pathlib.Path, cleandir: pathlib.Path
) -> Iterator[pathlib.Path]:
    marker = request.node.get_closest_marker('test_pkg')
    if marker is None:
        raise ValueError('test_pkg marker not found')
    testdata = testdata_path / marker.args[0]
    copytree_honoring_gitignore(
        testdata,
        cleandir,
        extra_gitignore=f'{CACHE_DIR_NAME}/\n{LEGACY_CACHE_DIR_NAME}/\nbuild/\n',
    )
    yield cleandir


@pytest.fixture(scope='session')
def monkeysession():
    from _pytest.monkeypatch import MonkeyPatch

    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(autouse=True, scope='session')
def rich_no_markup(monkeysession):
    monkeysession.setattr('rbx.console.console', Console(soft_wrap=True, no_color=True))


@pytest.fixture(autouse=True, scope='session')
def skip_when_an_external_tool_is_missing(monkeysession):
    """Turn a missing external binary into a skip, everywhere except CI.

    `ExternalTool.ensure()` exits 1 with an install hint, which is right for a
    setter but useless in a test run: the suite reports 34 identical
    `click.exceptions.Exit: 1` failures that look like broken conversions rather
    than an absent `pandoc`. Skipping says what is actually wrong, and only for
    the tests that really reach the tool -- the check happens at the call site,
    so a module whose other tests never touch it still runs them.

    CI is exempt on purpose. There the tool *is* installed (see
    `.github/workflows/tests.yml`), so a missing one is a regression in the
    workflow, and a silent skip is exactly how that would go unnoticed.
    """
    if os.environ.get('CI'):
        return

    from rbx.tooling import ExternalTool

    ensure = ExternalTool.ensure

    def ensure_or_skip(self: ExternalTool) -> None:
        if not self.is_available():
            pytest.skip(
                f'{self.executable} is not installed, and this test needs it '
                f'for {self.purpose}.'
            )
        ensure(self)

    monkeysession.setattr(ExternalTool, 'ensure', ensure_or_skip)


@pytest.fixture(autouse=True, scope='session')
def mock_app_path(monkeysession, tmp_path_factory):
    app_path = tmp_path_factory.mktemp('app')
    monkeysession.setattr('rbx.utils.get_app_path', lambda: app_path)
    yield app_path


@pytest.fixture(autouse=True)
def _isolate_global_state() -> Iterator[None]:
    from rbx import testing_utils
    from rbx.box import global_package as _global_package
    from rbx.box import package as _package
    from rbx.box import state as _state
    from rbx.box.contest import contest_state as _contest_state
    from rbx.grading import grading_context as _gc

    original_cwd = os.getcwd()
    original_temp_dir = _package.TEMP_DIR
    # The root Typer callback writes to this global and never clears it, so a
    # test that invokes the CLI leaves every later test in the same worker
    # process looking like a CLI run -- which turns on checks (the macOS stack
    # limit one, say) that then fail unrelated tests. Every field leaks the same
    # way, so snapshot the whole dataclass rather than the fields that have bit
    # us so far.
    original_state = dataclasses.replace(_state.STATE)
    context_vars = [
        _gc.cache_level_var,
        _gc.compression_level_var,
        _gc.use_compression_var,
        _gc.check_integrity_var,
        _gc.is_stress_var,
        _contest_state.selected_variant_id_var,
    ]
    snapshots = [(v, v.get()) for v in context_vars]
    try:
        yield
    finally:
        try:
            os.chdir(original_cwd)
        except (FileNotFoundError, OSError):
            pass
        _package.TEMP_DIR = original_temp_dir
        # In place: the singleton is imported by reference all over rbx.
        for field in dataclasses.fields(original_state):
            setattr(_state.STATE, field.name, getattr(original_state, field.name))
        for var, value in snapshots:
            var.set(value)
        testing_utils.clear_all_functools_cache()
        _global_package.clear_cache_session_locks()
