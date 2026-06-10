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
  global ``.rbx`` cache.
- ``mock_setter_config`` writes a permissive setter config inside the
  redirected app path so checks (e.g. stack-size) do not query the host.

Per-scenario patches (the conditional ``pdflatex`` mock and the recording
Polygon client) cannot live here: pytest does not run function-scoped fixtures
for the custom :class:`E2EScenarioItem`, only session-scoped ones. They are
applied per scenario in ``E2EScenarioItem.runtest`` instead.
"""

import pytest

from rbx.box import setter_config
from rbx.config import CACHE_DIR_NAME
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
        lambda: cache_dir / CACHE_DIR_NAME,
    )


@pytest.fixture(autouse=True, scope='session')
def mock_setter_config(mock_app_path):
    cfg = setter_config.get_setter_config()
    cfg.judging = setter_config.JudgingConfig(check_stack=False)
    setter_config.save_setter_config(cfg)


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


# Scenarios that encode DESIRED-but-not-yet-true behavior: registered xfail
# (non-strict) so the suite stays green while documenting a known bug, and flips
# to xpass the moment the bug is fixed. Keyed by scenario name. See
# docs/plans/2026-06-10-polygon-statement-upload-audit.md.
_XFAIL_SCENARIOS = {
    'polygon-upload-assets-referential-integrity': (
        'sample-explanation TikZ is not externalized/uploaded; the notes '
        'reference a non-existent artifacts/tikz_figures/0_0 PDF (#586 audit).'
    ),
    'problem-polygon-upload': (
        'default preset polygon upload fails on the editorial.rbx.tex overlay '
        'collision between the contest chrome and the problem statement dir '
        '(#586 audit).'
    ),
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        if isinstance(item, E2EScenarioItem):
            item.add_marker(pytest.mark.e2e)
            for marker in item.scenario.markers:
                item.add_marker(getattr(pytest.mark, marker))
            xfail_reason = _XFAIL_SCENARIOS.get(item.name)
            if xfail_reason is not None:
                item.add_marker(pytest.mark.xfail(reason=xfail_reason, strict=False))
