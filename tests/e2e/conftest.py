"""Pytest configuration for the rbx end-to-end test suite.

Collects ``e2e.rbx.yml`` files as pytest test files and yields one
:class:`tests.e2e.runner.E2EScenarioItem` per scenario.

This conftest intentionally does NOT inherit from ``tests/rbx/conftest.py``
or ``tests/rbx/box/conftest.py`` (it lives in a sibling tree). To keep e2e
runs hermetic with respect to the user's real filesystem, we re-declare the
session-scoped autouse fixtures that those conftests provide:

- ``mock_app_path`` redirects ``rbx.utils.get_app_path`` to a tmpdir, so the
  real ``~/.local/share/rbx/`` is never touched.
- ``precompilation_should_use_tmp_cache`` redirects the global precompilation
  cache to a tmpdir, so compiled artefacts do not accumulate in the user's
  global ``.box`` cache.
- ``mock_setter_config`` writes a permissive setter config inside the
  redirected app path so checks (e.g. stack-size) do not query the host.
- ``mock_pdflatex`` short-circuits the LaTeX build so statement scenarios
  do not require a real ``pdflatex`` install.
"""

import subprocess

import pytest

from rbx.box import setter_config
from rbx.box.statements.latex import LatexResult
from tests.e2e.runner import E2EScenarioItem
from tests.e2e.spec import load_spec

# NOTE: ``pytest_plugins = ['pytester']`` is declared at the repo-root
# ``conftest.py`` because pytest only honours that hook in the rootdir
# conftest. The fixture is consumed by ``tests/e2e/test_collection.py`` and
# friends.


@pytest.fixture(scope='session')
def monkeysession():
    from _pytest.monkeypatch import MonkeyPatch

    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(autouse=True, scope='session')
def mock_app_path(monkeysession, tmp_path_factory):
    app_path = tmp_path_factory.mktemp('app')
    monkeysession.setattr('rbx.utils.get_app_path', lambda: app_path)
    yield app_path


@pytest.fixture(autouse=True, scope='session')
def precompilation_should_use_tmp_cache(monkeysession, tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp('cache')
    monkeysession.setattr(
        'rbx.box.global_package.get_global_cache_dir_path',
        lambda: cache_dir / '.box',
    )


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


class E2EYamlFile(pytest.File):
    def collect(self):
        spec = load_spec(self.path)
        for scenario in spec.scenarios:
            yield E2EScenarioItem.from_parent(
                self, name=scenario.name, scenario=scenario
            )


def pytest_collect_file(parent, file_path):
    if file_path.name == 'e2e.rbx.yml':
        return E2EYamlFile.from_parent(parent, path=file_path)


def pytest_collection_modifyitems(config, items):
    for item in items:
        if isinstance(item, E2EScenarioItem):
            item.add_marker(pytest.mark.e2e)
            for marker in item.scenario.markers:
                item.add_marker(getattr(pytest.mark, marker))
