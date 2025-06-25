import contextvars
from enum import Enum
from typing import Optional


class CacheLevel(Enum):
    NO_CACHE = 0
    CACHE_TRANSIENTLY = 1
    CACHE_COMPILATION = 2
    CACHE_ALL = 3


cache_level_var = contextvars.ContextVar('cache_level', default=CacheLevel.CACHE_ALL)


def is_compilation_only() -> bool:
    return cache_level_var.get() == CacheLevel.CACHE_COMPILATION


def is_transient() -> bool:
    return cache_level_var.get().value <= CacheLevel.CACHE_TRANSIENTLY.value


def is_no_cache() -> bool:
    return cache_level_var.get().value <= CacheLevel.NO_CACHE.value


class cache_level:
    def __init__(self, level: CacheLevel, when: Optional[CacheLevel] = None):
        self.level = level
        self.token = None
        self.when = when

    def __enter__(self):
        if self.when is None or self.when == cache_level_var.get():
            self.token = cache_level_var.set(self.level)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token is not None:
            cache_level_var.reset(self.token)
        return None
