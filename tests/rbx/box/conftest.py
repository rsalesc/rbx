import os
import pathlib
import shutil
from collections.abc import Iterator

import pytest

from rbx import testing_utils
from rbx.box import package


@pytest.fixture
def pkg_cleandir(cleandir: pathlib.Path) -> Iterator[pathlib.Path]:
    old_temp_dir = package.TEMP_DIR
    package.TEMP_DIR = cleandir

    pkgdir = cleandir / 'pkg'
    pkgdir.mkdir(exist_ok=True, parents=True)
    lwd = pathlib.Path.cwd()
    os.chdir(str(pkgdir))
    try:
        yield pkgdir.absolute()
    finally:
        os.chdir(str(lwd))
        package.TEMP_DIR = old_temp_dir


@pytest.fixture
def pkg_from_testdata(
    request, testdata_path: pathlib.Path, pkg_cleandir: pathlib.Path
) -> Iterator[pathlib.Path]:
    marker = request.node.get_closest_marker('test_pkg')
    if marker is None:
        raise ValueError('test_pkg marker not found')
    testdata = testdata_path / marker.args[0]
    shutil.copytree(str(testdata), str(pkg_cleandir), dirs_exist_ok=True)
    yield pkg_cleandir


@pytest.fixture(autouse=True)
def clear_cache():
    testing_utils.clear_all_functools_cache()
