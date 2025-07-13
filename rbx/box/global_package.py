import functools
import pathlib
import shutil

from rbx.config import get_app_path
from rbx.grading.caching import DependencyCache
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
from rbx.grading.judge.storage import FilesystemStorage, Storage

CACHE_STEP_VERSION = 4


def get_cache_fingerprint() -> str:
    return f'{CACHE_STEP_VERSION}'


@functools.cache
def is_cache_valid(cache_dir: pathlib.Path) -> bool:
    if not cache_dir.is_dir():
        return True
    fingerprint_file = cache_dir / 'fingerprint'
    if not fingerprint_file.is_file():
        return False
    fingerprint = fingerprint_file.read_text()
    if fingerprint.strip() != get_cache_fingerprint():
        return False
    return True


def get_global_cache_dir_path() -> pathlib.Path:
    return get_app_path() / '.box'


@functools.cache
def get_global_cache_dir() -> pathlib.Path:
    cache_dir = get_global_cache_dir_path()
    cache_dir.mkdir(parents=True, exist_ok=True)
    fingerprint_file = cache_dir / 'fingerprint'
    if not fingerprint_file.is_file():
        fingerprint_file.write_text(get_cache_fingerprint())
    return cache_dir


def is_global_cache_valid() -> bool:
    return is_cache_valid(get_global_cache_dir())


@functools.cache
def get_global_storage_dir() -> pathlib.Path:
    storage_dir = get_global_cache_dir() / '.storage'
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


@functools.cache
def get_global_cache_storage() -> Storage:
    return FilesystemStorage(get_global_storage_dir())


@functools.cache
def get_global_file_cacher() -> FileCacher:
    return FileCacher(get_global_cache_storage())


@functools.cache
def get_global_dependency_cache() -> DependencyCache:
    return DependencyCache(get_global_cache_dir(), get_global_file_cacher())


@functools.cache
def get_global_sandbox() -> SandboxBase:
    return StupidSandbox(get_global_file_cacher())


def clear_global_cache():
    shutil.rmtree(get_global_cache_dir(), ignore_errors=True)
