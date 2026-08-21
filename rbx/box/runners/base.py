"""The backend that actually runs a solution's testcases.

`run_solutions` decides *what* to run -- which solutions, which testcases, under
which limits -- and a `SolutionRunner` decides *where*. The local sandbox is one;
a judge reached over its own CLI is another.

The seam is per **solution**, not per testcase, because that is the grain a remote
judge works at: one submission is judged against every test at once. A per-testcase
seam would force every batch backend to secretly coalesce calls back into a batch.
"""

import dataclasses
from typing import TYPE_CHECKING, List, Optional, Protocol

from rbx.box.deferred import Deferred
from rbx.box.environment import VerificationLevel
from rbx.grading.steps import Evaluation
from rbx.utils import StatusProgress

if TYPE_CHECKING:
    from rbx.box.generation_schema import GenerationTestcaseEntry
    from rbx.box.schema import Solution
    from rbx.box.solutions import (
        AbortPredicate,
        GroupSkeleton,
        SolutionReportSkeleton,
        _AbortGate,
    )


@dataclasses.dataclass(frozen=True)
class RunnerCapabilities:
    """What a backend can and cannot report.

    Declared rather than discovered: a consumer that silently reads a `None` as
    zero would report an instantaneous run for something that was never measured.
    """

    # Fills TestcaseLog.memory.
    measures_memory: bool = True
    # Writes .out / .err / .log beside the .eval.
    captures_artifacts: bool = True
    # Fills CheckerResult.message with the checker's own words.
    checker_messages: bool = True
    # Can run a testcase several times and keep the best measurement.
    supports_nruns: bool = True
    # Can stop a solution part-way through, so `abort_on` means something.
    supports_abort: bool = True
    supports_interactive: bool = True
    supports_sanitizers: bool = True


@dataclasses.dataclass
class RunContext:
    """Everything a runner needs that is fixed for a whole `run_solutions` call."""

    skeleton: 'SolutionReportSkeleton'
    checker_digest: Optional[str]
    interactor_digest: Optional[str]
    verification: VerificationLevel
    timelimit_override: Optional[int]
    nruns: int
    capture_pipes: bool
    progress: Optional[StatusProgress]
    abort_on: Optional['AbortPredicate']


class SolutionRunner(Protocol):
    name: str
    caps: RunnerCapabilities

    async def prepare(self, ctx: RunContext) -> None:
        """Do the once-per-run setup, before any solution is run."""
        ...

    def run_solution(
        self,
        solution: 'Solution',
        entries: List['GenerationTestcaseEntry'],
        groups: List['GroupSkeleton'],
        ctx: RunContext,
        gate: Optional['_AbortGate'],
    ) -> List[Deferred[Evaluation]]:
        """One deferred per entry, in entry order. Must not block."""
        ...

    async def finalize(self) -> None:
        """Release whatever `prepare` acquired. Always called."""
        ...
