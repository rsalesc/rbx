"""Pytest configuration for E2E tests."""

import pathlib
from typing import Iterator

import pytest

from rbx.box.testing import testing_package


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
    pkg_from_resources: pathlib.Path,
) -> Iterator[testing_package.TestingPackage]:
    marker = request.node.get_closest_marker('preset_path')
    if marker is None:
        raise ValueError('preset_path marker not found')
    preset_path = pkg_from_resources / marker.args[0]
    with testing_package.TestingPackage(preset_path) as pkg:
        yield pkg
