from dataclasses import dataclass


@dataclass(frozen=True)
class PipeLog:
    """Parsed pipe.log: see rbx/resources/packagers/boca/pipe.c lines 359-362."""

    first_tag: int  # 1 = solution exited first, 2 = interactor exited first
    solution_status: int  # bash-like: 0-255, or 128+signal
    interactor_status: int

    @staticmethod
    def parse(text: str) -> 'PipeLog':
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() != '']
        if len(lines) < 3:
            raise ValueError(f'pipe.log must have 3 numeric lines, got: {text!r}')
        return PipeLog(int(lines[0]), int(lines[1]), int(lines[2]))
