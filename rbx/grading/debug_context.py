import contextvars
import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class DebugContext:
    enable: bool = False


debug_var = contextvars.ContextVar('debug', default=DebugContext())


def get_debug_context() -> DebugContext:
    return debug_var.get()


class Debug:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.token = None

    def __enter__(self):
        self.token = debug_var.set(
            dataclasses.replace(debug_var.get(), *self.args, **self.kwargs)
        )

    def __exit__(self, exc_type, exc_value, traceback):
        if self.token is not None:
            debug_var.reset(self.token)
