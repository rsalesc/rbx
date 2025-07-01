import contextvars
from typing import Callable, Optional, Union

from rbx.autoenum import AutoEnum, alias

Condition = Union[bool, Callable[[], bool]]


class ConditionedContext:
    def __init__(self, when: Condition = True):
        self.when = when

    def should_enter(self) -> bool:
        if isinstance(self.when, bool):
            return self.when
        return self.when()


class CacheLevel(AutoEnum):
    NO_CACHE = alias('none')
    CACHE_TRANSIENTLY = alias('transient')
    CACHE_COMPILATION = alias('compilation')
    CACHE_ALL = alias('all')


cache_level_var = contextvars.ContextVar('cache_level', default=CacheLevel.CACHE_ALL)


def is_compilation_only() -> bool:
    return cache_level_var.get() == CacheLevel.CACHE_COMPILATION


def is_transient() -> bool:
    return cache_level_var.get() == CacheLevel.CACHE_TRANSIENTLY or is_no_cache()


def is_no_cache() -> bool:
    return cache_level_var.get() == CacheLevel.NO_CACHE


class cache_level(ConditionedContext):
    def __init__(self, level: CacheLevel, when: Condition = True):
        super().__init__(when)
        self.level = level
        self.token = None

    def __enter__(self):
        if self.should_enter():
            self.token = cache_level_var.set(self.level)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token is not None:
            cache_level_var.reset(self.token)
        return None


compression_level_var = contextvars.ContextVar('compression_level', default=5)
use_compression_var = contextvars.ContextVar('use_compression', default=False)


def get_compression_level() -> int:
    return compression_level_var.get()


def should_compress() -> bool:
    return use_compression_var.get()


class compression(ConditionedContext):
    def __init__(
        self,
        level: Optional[int] = None,
        use_compression: Optional[bool] = None,
        when: Condition = True,
    ):
        super().__init__(when)
        self.level = level
        self.use_compression = use_compression
        self.level_token = None
        self.use_compression_token = None

    def __enter__(self):
        if not self.should_enter():
            return self
        if self.level is not None:
            self.level_token = compression_level_var.set(self.level)
        if self.use_compression is not None:
            self.use_compression_token = use_compression_var.set(self.use_compression)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.level_token is not None:
            compression_level_var.reset(self.level_token)
        if self.use_compression_token is not None:
            use_compression_var.reset(self.use_compression_token)
        return None


check_integrity_var = contextvars.ContextVar('check_integrity', default=True)


def should_check_integrity() -> bool:
    return check_integrity_var.get()


class check_integrity(ConditionedContext):
    def __init__(self, enabled: bool, when: Condition = True):
        super().__init__(when)
        self.enabled = enabled
        self.token = None

    def __enter__(self):
        if not self.should_enter():
            return self
        self.token = check_integrity_var.set(self.enabled)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token is not None:
            check_integrity_var.reset(self.token)
        return None
