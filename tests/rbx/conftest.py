import os
import pathlib
from collections.abc import Iterator

import pytest
from rich.console import Console

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
    copytree_honoring_gitignore(testdata, cleandir, extra_gitignore='.box/\nbuild/\n')
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
def mock_app_path(monkeysession, tmp_path_factory):
    app_path = tmp_path_factory.mktemp('app')
    monkeysession.setattr('rbx.utils.get_app_path', lambda: app_path)
    yield app_path
