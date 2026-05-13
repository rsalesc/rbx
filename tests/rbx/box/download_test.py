import pathlib
from unittest import mock

import pytest

from rbx.box import download
from rbx.box.testing import testing_package


class _FakeResponse:
    def __init__(self, content: bytes = b'// fake header\n', ok: bool = True):
        self.content = content
        self.ok = ok


@pytest.fixture
def fake_requests_get():
    with mock.patch('requests.get') as m:
        m.return_value = _FakeResponse()
        yield m


class TestDownloadTgen:
    def test_writes_tgen_to_cwd_by_default(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.tgen(into=None)
        target = pathlib.Path.cwd() / 'tgen.h'
        assert target.read_bytes() == b'// fake header\n'

    def test_into_resolves_relative_to_package_root(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.tgen(into='libs/headers/tgen.h')
        target = pathlib.Path.cwd() / 'libs' / 'headers' / 'tgen.h'
        assert target.read_bytes() == b'// fake header\n'

    def test_refetches_on_every_invocation(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.tgen(into=None)
        download.tgen(into=None)
        assert fake_requests_get.call_count == 2


class TestDownloadJngenRefresh:
    def test_jngen_refetches_even_when_cached(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.jngen(into=None)
        download.jngen(into=None)
        assert fake_requests_get.call_count == 2


class TestDownloadTestlibRefresh:
    def test_testlib_refetches_even_when_cached(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.testlib(into=None)
        download.testlib(into=None)
        assert fake_requests_get.call_count == 2
