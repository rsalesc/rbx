from rbx import console


class RbxException(RuntimeError):
    def __init__(self):
        super().__init__()
        self.msg = []
        self.capture = None
        self.console = console.new_console()

    def rule(self, *args, **kwargs):
        self.console.rule(*args, **kwargs)

    def print(self, *args, **kwargs):
        self.console.print(*args, **kwargs)

    def log(self, *args, **kwargs):
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
