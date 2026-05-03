"""Runtime for executing e2e scenarios.

The actual step execution is implemented in a later task. For now this module
only exposes the pytest item type used by the collection hook in
``tests/e2e/conftest.py``.
"""

import pytest

from tests.e2e.spec import Scenario


class E2EScenarioItem(pytest.Item):
    def __init__(self, *, scenario: Scenario, **kwargs):
        super().__init__(**kwargs)
        self.scenario = scenario

    def runtest(self):
        # Implemented in a subsequent task of the e2e testing plan.
        pass

    def reportinfo(self):
        return self.path, 0, f'scenario: {self.name}'
