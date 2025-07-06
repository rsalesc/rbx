import os
import pathlib
import shutil
import tempfile
from collections.abc import Iterator

import pytest

from rbx.testing_utils import get_testdata_path


@pytest.fixture
def testdata_path() -> pathlib.Path:
    return get_testdata_path()


@pytest.fixture
def cleandir() -> Iterator[pathlib.Path]:
    with tempfile.TemporaryDirectory() as newpath:
        abspath = pathlib.Path(newpath).absolute()
        old_cwd = pathlib.Path.cwd()
        os.chdir(newpath)
        try:
            yield abspath
        finally:
            os.chdir(str(old_cwd))


@pytest.fixture
def cleandir_with_testdata(
    request, testdata_path: pathlib.Path, cleandir: pathlib.Path
) -> Iterator[pathlib.Path]:
    marker = request.node.get_closest_marker('test_pkg')
    if marker is None:
        raise ValueError('test_pkg marker not found')
    testdata = testdata_path / marker.args[0]
    shutil.copytree(str(testdata), str(cleandir), dirs_exist_ok=True)
    yield cleandir
