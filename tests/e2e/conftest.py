"""Pytest configuration for the rbx end-to-end test suite.

Collects ``e2e.rbx.yml`` files as pytest test files and yields one
:class:`tests.e2e.runner.E2EScenarioItem` per scenario.
"""

import pytest

from tests.e2e.runner import E2EScenarioItem
from tests.e2e.spec import load_spec

pytest_plugins = ['pytester']


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
