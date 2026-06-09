import pytest

from rbx.box.completion import _spec, registry


@pytest.fixture(autouse=True)
def _seed_completers():
    registry.register_all(_spec.COMPLETERS)
    yield
