from typing import Awaitable, Callable, Generic, Optional, TypeVar

T = TypeVar('T')
U = TypeVar('U')


class Deferred(Generic[T]):
    def __init__(self, func: Callable[[], Awaitable[T]]):
        self.func = func
        self.cache: Optional[T] = None

    def __call__(self) -> Awaitable[T]:
        async def async_wrapper():
            if self.cache is None:
                self.cache = await self.func()
            return self.cache

        return async_wrapper()

    def peek(self) -> Optional[T]:
        return self.cache

    def wrap_with(
        self, wrapper: Callable[[Awaitable[T]], Awaitable[U]]
    ) -> 'Deferred[U]':
        return Deferred(lambda: wrapper(self()))
