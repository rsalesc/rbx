import contextvars
import dataclasses
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DebugContext:
    enable: bool = False


debug_var: contextvars.ContextVar[Optional[DebugContext]] = contextvars.ContextVar(
    'debug', default=None
)


def get_debug_context() -> DebugContext:
    return debug_var.get() or DebugContext()


class Debug:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.token = None

    def __enter__(self):
        self.token = debug_var.set(
            dataclasses.replace(get_debug_context(), *self.args, **self.kwargs)
        )

    def __exit__(self, exc_type, exc_value, traceback):
        if self.token is not None:
            debug_var.reset(self.token)
