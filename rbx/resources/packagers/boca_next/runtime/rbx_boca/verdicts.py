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


def batch_run_exit(safeexec_exit: int) -> int:
    """Map safeexec's exit code to the run-script exit code BOCA expects.

    Mirrors rbx/resources/packagers/boca/run/* : codes > 10 (child exited with
    nonzero N, reported as N+10) collapse to 9 (runtime error).
    """
    return 9 if safeexec_exit > 10 else safeexec_exit
