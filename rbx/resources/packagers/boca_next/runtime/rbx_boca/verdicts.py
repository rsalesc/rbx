from dataclasses import dataclass
from typing import Optional


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


def compare_verdict(testlib_code: Optional[int], checker_exit: Optional[int]) -> int:
    """BOCA compare exit code. See rbx/resources/packagers/boca/compare.sh.

    AC=4, WA=6, JUDGE_ERROR=43, OTHER_ERROR=47.
    """
    if testlib_code is not None:
        if testlib_code in (1, 2):
            return 6
        if testlib_code == 3:
            return 43
        return 47
    if checker_exit == 0:
        return 4
    if checker_exit in (1, 2):
        return 6
    if checker_exit == 3:
        return 43
    return 47
