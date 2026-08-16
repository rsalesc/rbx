import os
import pathlib
import subprocess
from collections.abc import Iterator
from typing import Any, Dict, Optional

import pytest

from rbx import testing_utils
from rbx.box import package, setter_config
from rbx.box.statements.latex import LatexResult
from rbx.box.testing import testing_package
from rbx.config import CACHE_DIR_NAME, LEGACY_CACHE_DIR_NAME
from rbx.grading.caching import DependencyCache
from rbx.grading.judge import storage as storage_module
from rbx.grading.judge.cacher import FileCacher
from rbx.utils import copytree_honoring_gitignore


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
    request, testdata_path: pathlib.Path, pkg_cleandir: pathlib.Path, pkg_cder
) -> Iterator[pathlib.Path]:
    marker = request.node.get_closest_marker('test_pkg')
    if marker is None:
        raise ValueError('test_pkg marker not found')
    testdata = testdata_path / marker.args[0]
    copytree_honoring_gitignore(
        testdata,
        pkg_cleandir,
        extra_gitignore=f'{CACHE_DIR_NAME}\n{LEGACY_CACHE_DIR_NAME}\nbuild\n.limits/\n',
    )
    with pkg_cder(pkg_cleandir.absolute()):
        testing_utils.clear_all_functools_cache()
        yield pkg_cleandir


@pytest.fixture
def pkg_from_resources(
    request, resources_path: pathlib.Path, pkg_cleandir: pathlib.Path, pkg_cder
):
    marker = request.node.get_closest_marker('resource_pkg')
    if marker is None:
        raise ValueError('resource_pkg marker not found')
    testdata = resources_path / marker.args[0]
    copytree_honoring_gitignore(
        testdata,
        pkg_cleandir,
        extra_gitignore=f'{CACHE_DIR_NAME}/\n{LEGACY_CACHE_DIR_NAME}/\nbuild/\n',
    )
    with pkg_cder(pkg_cleandir.absolute()):
        testing_utils.clear_all_functools_cache()
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
    with testing_package.TestingPackage(pkg_cleandir) as pkg:
        yield pkg


@pytest.fixture
def testing_pkg_from_testdata(
    pkg_from_testdata: pathlib.Path,
) -> Iterator[testing_package.TestingPackage]:
    with testing_package.TestingPackage(pkg_from_testdata) as pkg:
        yield pkg


@pytest.fixture(autouse=True, scope='session')
def precompilation_should_use_tmp_cache(monkeysession, tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp('cache')
    monkeysession.setattr(
        'rbx.box.global_package.get_global_cache_dir_path',
        lambda: cache_dir / CACHE_DIR_NAME,
    )


@pytest.fixture(scope='session')
def shared_problem_cache(tmp_path_factory) -> Dict[str, Any]:
    """Build the session-wide problem cache accessors, one set per worker.

    Every test gets a fresh problem directory, and the problem cache lives
    inside it (`<problem>/.rbx`), so each test starts with an empty cache DB
    and recompiles the same handful of sources from scratch. Cache keys are
    content-addressed, so a cache shared across problems is still correct -- it
    just turns those recompilations into hits.

    Sharing is opt-in, so this fixture is not autouse: it is only instantiated
    the first time a test carrying the `shared_cache` marker runs.
    """
    cache_dir = tmp_path_factory.mktemp('problem_cache')
    storage = storage_module.FilesystemStorage(cache_dir / '.storage', compress=False)
    cacher = FileCacher(storage)
    dependency_cache = DependencyCache(cache_dir, cacher)

    return {
        'get_cache_storage': lambda *a, **k: storage,
        'get_file_cacher': lambda *a, **k: cacher,
        'get_dependency_cache': lambda *a, **k: dependency_cache,
    }


@pytest.fixture(autouse=True)
def maybe_shared_problem_cache(request):
    """Install the session-wide problem cache for tests marked `shared_cache`.

    Unmarked tests are left completely untouched: `package.get_cache_storage`,
    `get_file_cacher` and `get_dependency_cache` keep pointing at the problem
    directory, so each test gets its own isolated cache. A single test inside a
    module that opts in can opt back out with `@pytest.mark.shared_cache(False)`.

    The accessors are `functools.cache`d, so their caches have to be cleared
    both when installing and when restoring -- otherwise a cache object built
    for one side leaks across the boundary.

    Patching is done by hand rather than through the `monkeypatch` fixture:
    requesting `monkeypatch` from an autouse conftest fixture would make it be
    set up before the test's own autouse fixtures, flipping the teardown order
    of any `monkeypatch.setattr` a test stacks on top of a `mock.patch`.
    """
    marker = request.node.get_closest_marker('shared_cache')
    if marker is None or marker.args == (False,):
        yield
        return
    shared = request.getfixturevalue('shared_problem_cache')
    originals = {name: getattr(package, name) for name in shared}
    for name, patched in shared.items():
        originals[name].cache_clear()
        setattr(package, name, patched)
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(package, name, original)
            original.cache_clear()


@pytest.fixture(autouse=True, scope='session')
def mock_setter_config(mock_app_path):
    cfg = setter_config.get_setter_config()
    cfg.judging = setter_config.JudgingConfig(check_stack=False)
    setter_config.save_setter_config(cfg)


@pytest.fixture(autouse=True, scope='session')
def mock_pdflatex(monkeysession):
    monkeysession.setattr(
        'rbx.box.statements.latex.Latex.build_pdf',
        lambda *args, **kwargs: LatexResult(
            result=subprocess.CompletedProcess(
                args='', returncode=0, stdout=b'', stderr=b''
            ),
            pdf=b'',
        ),
    )
