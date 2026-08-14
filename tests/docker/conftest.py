"""Collection gate for the docker-backed test suites.

Everything under ``tests/docker/`` needs a real docker daemon (and, for BOCA,
a full docker-compose environment cloned from GitHub). These suites are
therefore **disabled by default**: pytest does not even collect them unless
``RBX_DOCKER_TESTS=1`` is exported. That keeps them out of ``pytest``,
``mise run test``, CI and any agent-driven test run that doesn't explicitly
opt in.

To run them by hand:

    RBX_DOCKER_TESTS=1 uv run pytest tests/docker -m docker -v -s

or simply ``mise run test-docker``, which sets the variable for you.

The individual test modules also carry a module-level ``skipif`` on the same
variable, so they stay disabled even if something bypasses this hook.
"""

import os

DOCKER_TESTS_ENV_VAR = 'RBX_DOCKER_TESTS'

DOCKER_TESTS_ENABLED = os.environ.get(DOCKER_TESTS_ENV_VAR) == '1'

DISABLED_REASON = (
    'Docker-backed tests are disabled by default; '
    f'set {DOCKER_TESTS_ENV_VAR}=1 (or run `mise run test-docker`) to enable them.'
)

# Skip collection of this whole subtree unless explicitly opted in.
collect_ignore_glob = [] if DOCKER_TESTS_ENABLED else ['*']
