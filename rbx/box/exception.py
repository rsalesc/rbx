from typing import List, Optional

from rich.console import Capture, Console

from rbx import console


class PossiblyCapture:
    def __init__(
        self, console: Console, msg: List[str], capture: Optional[Capture] = None
    ):
        self.console = console
        self.msg = msg
        self.capture = capture
        self.actual_capture = None

    def __enter__(self):
        if self.capture is not None:
            return
        self.actual_capture = self.console.capture()
        self.actual_capture.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.actual_capture is not None:
            self.actual_capture.__exit__(exc_type, exc_value, traceback)
            self.msg.append(self.actual_capture.get())
            self.actual_capture = None


class RbxException(RuntimeError):
    def __init__(self):
        super().__init__()
        self.msg = []
        self.capture = None
        self.console = console.new_console()

    def possibly_capture(self):
        return PossiblyCapture(self.console, self.msg, self.capture)

    def rule(self, *args, **kwargs):
        with self.possibly_capture():
            self.console.rule(*args, **kwargs)

    def print(self, *args, **kwargs):
        with self.possibly_capture():
            self.console.print(*args, **kwargs)

    def log(self, *args, **kwargs):
        with self.possibly_capture():
            self.console.log(*args, **kwargs)

    def __enter__(self):
        capture = self.console.capture()
        capture.__enter__()
        self.capture = capture
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.capture is not None:
            self.capture.__exit__(exc_type, exc_value, traceback)
            self.msg.append(self.capture.get())
            self.capture = None
        if exc_type is not None:
            return
        raise self

    def __str__(self) -> str:
        if not self.msg:
            return ''
        return ''.join(self.msg)
