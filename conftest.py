"""Root pytest configuration.

Registers the ``pytester`` plugin globally so that ``tests/e2e`` self-tests
(which use the ``pytester`` fixture to spin up isolated pytest invocations)
can run. ``pytest_plugins`` may only be defined in the rootdir conftest.
"""

pytest_plugins = ['pytester']
