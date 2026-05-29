from dataclasses import dataclass
from typing import Optional

# Run-phase judge-error exit code. Mirrors JUDGE_ERROR=4 in
# rbx/resources/packagers/boca_next/runtime/interactor_run.sh:101. Named to
# disambiguate from the compare-phase AC=4 in compare_verdict, which is unrelated.
_INTERACTOR_JUDGE_ERROR = 4


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


@dataclass(frozen=True)
class RunDecision:
    run_exit: int
    testlib_code: Optional[int]


def _check_interactor(ecint: int) -> Optional['RunDecision']:
    """interactor_run.sh check_interactor: 0->pass(None); 1..4->emit code, exit 0;
    else->judge error (exit 4)."""
    if ecint == 0:
        return None
    if 1 <= ecint <= 4:
        return RunDecision(run_exit=0, testlib_code=ecint)
    return RunDecision(run_exit=_INTERACTOR_JUDGE_ERROR, testlib_code=None)


def interactive_run_decision(first_tag: int, ecsf: int, ecint: int) -> RunDecision:
    """Ordered priority logic from interactor_run.sh:133-157.

    Ordering IS the spec: resource limits (TLE/MLE) beat the interactor verdict,
    which beats a solution RTE.
    """
    interactor_first = first_tag == 2
    is_testlib = 0 <= ecint <= 4

    # 1. interactor crashed before solution
    if interactor_first and not is_testlib:
        return _check_interactor(ecint)  # -> run_exit _INTERACTOR_JUDGE_ERROR

    # 2. solution TLE (3) / MLE (7)
    if ecsf in (3, 7):
        return RunDecision(run_exit=ecsf, testlib_code=None)

    # 3. interactor finished first -> its verdict
    if interactor_first:
        decided = _check_interactor(ecint)
        if decided is not None:
            return decided  # ecint==0 falls through

    # 4. solution error
    if ecsf != 0:
        return RunDecision(run_exit=ecsf, testlib_code=None)

    # 5. interactor error regardless of order
    decided = _check_interactor(ecint)
    if decided is not None:
        return decided

    # 6. success -> compare decides
    return RunDecision(run_exit=0, testlib_code=None)
