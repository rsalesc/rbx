import os
import pathlib
import shutil
from collections.abc import Iterator
from typing import Optional

import pytest

from rbx import testing_utils
from rbx.box import package
from rbx.box.testing import testing_package


@pytest.fixture(scope='session')
def pkg_cder(tmp_path_factory):
    class PkgCder:
        def __init__(self, pkg_dir: pathlib.Path):
            self.pkg_dir = pkg_dir

        def __enter__(self):
            self.old_cwd = pathlib.Path.cwd()
            self.old_temp_dir = package.TEMP_DIR
            package.TEMP_DIR = tmp_path_factory.mktemp('tmp')
            os.chdir(self.pkg_dir)

        def __exit__(self, exc_type, exc_value, traceback):
            os.chdir(self.old_cwd)
            package.TEMP_DIR = self.old_temp_dir

    yield PkgCder


@pytest.fixture
def pkg_cleandir(cleandir: pathlib.Path, pkg_cder) -> Iterator[pathlib.Path]:
    pkgdir = cleandir / 'pkg'
    pkgdir.mkdir(exist_ok=True, parents=True)
    with pkg_cder(pkgdir.absolute()):
        yield pkgdir.absolute()


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


@pytest.fixture(scope='session')
def testing_pkg_factory(tmp_path_factory):
    def new_testing_pkg(
        pkg_dir: Optional[pathlib.Path] = None,
    ) -> testing_package.TestingPackage:
        if pkg_dir is None:
            pkg_dir = tmp_path_factory.mktemp('pkg')
        return testing_package.TestingPackage(pkg_dir)

    return new_testing_pkg


@pytest.fixture
def testing_pkg(pkg_cleandir: pathlib.Path) -> Iterator[testing_package.TestingPackage]:
    pkg = testing_package.TestingPackage(pkg_cleandir)
    yield pkg
    pkg.cleanup()


@pytest.fixture(autouse=True)
def clear_cache():
    testing_utils.clear_all_functools_cache()


@pytest.fixture(autouse=True, scope='session')
def precompilation_should_use_local_cache(monkeysession):
    monkeysession.setattr(
        'rbx.box.global_package.get_global_dependency_cache',
        package.get_dependency_cache,
    )
    monkeysession.setattr(
        'rbx.box.global_package.get_global_sandbox',
        package.get_singleton_sandbox,
    )
