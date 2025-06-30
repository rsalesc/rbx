import pathlib
from collections.abc import Iterator

import pytest

from rbx.grading.caching import DependencyCache
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
from rbx.grading.judge.storage import FilesystemStorage, Storage


@pytest.fixture
def storage(request, cleandir: pathlib.Path) -> Iterator[Storage]:
    storage_path = cleandir / '.box' / '.storage'
    yield FilesystemStorage(storage_path)


@pytest.fixture
def file_cacher(request, storage: Storage) -> Iterator[FileCacher]:
    yield FileCacher(storage)


@pytest.fixture
def sandbox(request, file_cacher: FileCacher) -> Iterator[SandboxBase]:
    yield StupidSandbox(file_cacher=file_cacher)


@pytest.fixture
def dependency_cache(
    request, cleandir: pathlib.Path, file_cacher: FileCacher
) -> Iterator[DependencyCache]:
    yield DependencyCache(cleandir / '.box', file_cacher)
