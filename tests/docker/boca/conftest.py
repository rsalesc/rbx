"""Pytest configuration for the docker-backed BOCA E2E tests.

This suite used to live under ``tests/rbx/box/packaging/e2e/`` and inherited
fixtures from ``tests/rbx/conftest.py`` and ``tests/rbx/box/conftest.py``.
Now that it lives outside that tree, those fixtures are re-exported here
explicitly so the tests keep behaving the same way.

Collection is gated by ``tests/docker/conftest.py`` -- see that file.
"""

import asyncio
import pathlib
from typing import Iterator

import pytest

from rbx.box.testing import testing_package
from tests.rbx.box.conftest import (  # noqa: F401
    mock_pdflatex,
    mock_setter_config,
    pkg_cder,
    pkg_cleandir,
    pkg_from_resources,
    pkg_from_testdata,
    precompilation_should_use_tmp_cache,
    testing_pkg,
    testing_pkg_factory,
    testing_pkg_from_testdata,
)
from tests.rbx.conftest import (  # noqa: F401
    _isolate_global_state,
    cder,
    cleandir,
    cleandir_with_testdata,
    mock_app_path,
    monkeysession,
    resources_path,
    rich_no_markup,
    testdata_path,
)


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """Provision a fresh asyncio loop per test so syncer-wrapped Typer
    commands work under Python 3.14, where get_event_loop() no longer
    creates one implicitly."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        except Exception:
            pass
        asyncio.set_event_loop(None)
        loop.close()


def pytest_configure(config):
    """Configure custom markers."""
    config.addinivalue_line(
        'markers', 'e2e: mark test as end-to-end test (deselect with \'-m "not e2e"\')'
    )
    config.addinivalue_line(
        'markers', 'slow: mark test as slow (deselect with \'-m "not slow"\')'
    )
    config.addinivalue_line('markers', 'docker: mark test as requiring docker')


@pytest.fixture(autouse=True)
def skip_if_no_docker(request):
    """Skip tests marked with 'docker' if docker is not available."""
    if request.node.get_closest_marker('docker'):
        import subprocess

        try:
            subprocess.run(
                ['docker', '--version'],
                check=True,
                capture_output=True,
                timeout=5,
            )
        except (
            subprocess.CalledProcessError,
            FileNotFoundError,
            subprocess.TimeoutExpired,
        ):
            pytest.skip('Docker not available')


@pytest.fixture
def docker_cleanup():
    """Ensure docker containers are cleaned up even on test failure."""
    import atexit
    import subprocess

    containers_to_cleanup = []

    def add_container(container_id):
        containers_to_cleanup.append(container_id)

    def cleanup():
        for container_id in containers_to_cleanup:
            try:
                subprocess.run(
                    ['docker', 'rm', '-f', container_id],
                    capture_output=True,
                )
            except Exception:
                pass

    atexit.register(cleanup)

    yield add_container

    cleanup()


@pytest.fixture
def preset_testing_pkg_from_resources(
    request,
    pkg_from_resources: pathlib.Path,  # noqa: F811 - fixture request, not a redefinition
) -> Iterator[testing_package.TestingPackage]:
    marker = request.node.get_closest_marker('preset_path')
    if marker is None:
        raise ValueError('preset_path marker not found')
    preset_path = pkg_from_resources / marker.args[0]
    with testing_package.TestingPackage(preset_path) as pkg:
        yield pkg
