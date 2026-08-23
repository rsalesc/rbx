"""The backend that actually runs a solution's testcases.

`run_solutions` decides *what* to run -- which solutions, which testcases, under
which limits -- and a `SolutionRunner` decides *where*. The local sandbox is one;
a judge reached over its own CLI is another.

The seam is per **solution**, not per testcase, because that is the grain a remote
judge works at: one submission is judged against every test at once. A per-testcase
seam would force every batch backend to secretly coalesce calls back into a batch.

Skipping and aborting are deliberately *not* a backend's business. When a run asks
for them, `run_solutions` wraps the deferreds a backend hands back with the gate
logic, so a backend never reimplements it and every backend gets it identically.
When it does not -- the common case -- the backend's own deferreds are passed
through untouched, which is what keeps a plain run byte-identical to one that had
no seam at all. A backend declaring `supports_abort=False` is passed through too:
see `supports_abort` below for why that is a correctness rule, not an optimization.
"""

import dataclasses
import typing
from typing import TYPE_CHECKING, Dict, List, Optional, Protocol, Tuple

from rbx.box.deferred import Deferred
from rbx.box.environment import VerificationLevel
from rbx.box.exception import RbxException
from rbx.grading.steps import Evaluation
from rbx.utils import StatusProgress

if TYPE_CHECKING:
    from rbx.box.generation_schema import GenerationTestcaseEntry
    from rbx.box.solutions import (
        AbortPredicate,
        SolutionReportSkeleton,
        SolutionSkeleton,
        TimelimitOverride,
    )


class RunnerCapabilityError(RbxException):
    """The run asked a backend for something it declared it cannot do.

    Raised up front, before anything is prepared or dispatched, so the answer is
    an error naming the backend rather than a crash halfway through a run or --
    worse -- a quietly downgraded run that reads as a normal one.
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


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
    reports_checker_messages: bool = True
    # Can run a testcase several times and keep the best measurement.
    supports_nruns: bool = True
    # Can still save the work of a skipped testcase, which requires that the
    # testcase has not run yet. A batch backend has already handed the whole
    # submission to a judge and holds every verdict by the time rbx looks, so
    # `False` here is not merely "cannot save the work": gating such a backend
    # would overwrite verdicts the judge really produced with SKIPPED, throwing
    # away real information to mark work that was already done as not done.
    # `run_solutions` therefore leaves a `False` backend ungated even when the
    # run passed `abort_on`.
    supports_abort: bool = True
    # Can drive an interactor against the solution, for COMMUNICATION problems.
    supports_interactive: bool = True
    # Can build and run the solution under a sanitizer.
    supports_sanitizers: bool = True


@dataclasses.dataclass(frozen=True)
class RunnerChip:
    """One thing a backend wants said about a solution, right now.

    Text and a style, not a typed state. A typed `RunnerStatus` would put MOJ's
    vocabulary -- `queued`, `running`, `done` -- into the reporter, and the next
    judge's vocabulary after that. The backend owns its own words; the reporter
    owns the layout and knows nothing about judges.
    """

    text: str
    style: str = 'bright_black'


class RunProgress:
    """What each backend wants said about each solution while the report waits.

    A **board**, written by the backend and read by the reporter, rather than a
    channel between them. The two cannot be wired together directly: the reporter
    is built from a `RunSolutionResult`, so it does not exist yet when
    `run_solutions` hands the backend its `RunContext`. The board is created
    before either and handed to both.

    **Pull, not push.** The reporter reads whichever solution it is currently
    blocked on, every time it paints. A backend that dispatched ten solutions is
    therefore free to keep all ten slots current -- the nine nobody is looking at
    cost a dict write each -- which is what lets a poll say something without
    fighting the reporter for the console. That was the standing objection to a
    backend writing status lines at all (see `MojRunner._wait_for_testrun`), and
    it is dissolved rather than worked around: a poll writes into its own slot,
    and only the slot being waited on is ever drawn.

    **No locking.** Backend and reporter run on the same event loop, so a write
    is a plain dict assignment. Chips are stored as a tuple so a reader cannot be
    handed a list that the next write mutates underneath it.

    A backend that never writes -- `LocalRunner` -- costs nothing and reads back
    empty.
    """

    def __init__(self) -> None:
        self._chips: Dict[str, Tuple[RunnerChip, ...]] = {}

    def set(self, solution_path: str, *chips: RunnerChip) -> None:
        """Replace this solution's chips. Whole line at once, never appended.

        A backend says what is true *now*; it does not accumulate. Half a
        solution's state from one moment beside half from another is exactly the
        kind of line that reads as a bug in whatever it describes.
        """
        self._chips[solution_path] = chips

    def clear(self, solution_path: str) -> None:
        self._chips.pop(solution_path, None)

    def get(self, solution_path: str) -> Tuple[RunnerChip, ...]:
        return self._chips.get(solution_path, ())


@dataclasses.dataclass
class RunContext:
    """Everything a runner needs that is fixed for a whole `run_solutions` call."""

    skeleton: 'SolutionReportSkeleton'
    checker_digest: Optional[str]
    interactor_digest: Optional[str]
    verification: VerificationLevel
    # One limit for every language, or one per language. The per-language form is
    # what `rbx time`'s validation phase passes: each language group gets its own
    # estimated limit, so the bound each slow solution has to clear differs by
    # language. `solutions.resolve_timelimit_override` turns it into the limit for
    # one solution; a backend that can only enforce a single number for the whole
    # run has to reconcile the two itself, and say so when it cannot.
    timelimit_override: Optional['TimelimitOverride']
    nruns: int
    progress: Optional[StatusProgress]
    abort_on: Optional['AbortPredicate']
    # Where a backend says what it is doing, per solution, while the report is
    # waiting on it. Defaulted so a caller that does not care -- every test that
    # builds a context by hand -- gets a working board rather than a `None` to
    # guard against at every write site.
    progress_board: RunProgress = dataclasses.field(default_factory=RunProgress)


@typing.runtime_checkable
class SolutionRunner(Protocol):
    name: str
    caps: RunnerCapabilities

    async def prepare(self, ctx: RunContext) -> None:
        """Do the once-per-run setup, before any solution is run."""
        ...

    def run_solution(
        self,
        solution: 'SolutionSkeleton',
        entries: List['GenerationTestcaseEntry'],
        ctx: RunContext,
    ) -> List[Deferred[Evaluation]]:
        """One deferred per entry, in entry order. Must not block.

        `entries` is the solution's whole testset, flattened in group order.
        """
        ...

    async def close(self) -> None:
        """Drop the work this batch left outstanding. Idempotent.

        **This ends a batch, not the object.** A closed runner may be prepared
        and run again -- which is exactly what `rbx time`'s validation phase
        does, re-preparing at `ceil(TL_lang x timeLimitToTle)` and checking the
        solutions expected to be too slow against it, once per round the picker
        re-opens -- so `close` drops what is *in flight* and deliberately leaves
        everything `prepare` settled alone. On `MojRunner` that state is what
        lets a second batch reuse the remote problem it already bound.

        **This is not the `finalize` hook the seam started with, and the
        difference is the whole point.** `finalize` fired inside `run_solutions`,
        which only *builds* the deferreds -- so it ran before a single one had
        resolved and would have torn a remote session down before the first
        result was fetched. `close` is called by the code that **consumed** the
        deferreds, from a `finally` around that consumption, so by the time it
        runs every result the caller wanted has already been taken.

        What is left when it runs is therefore work nobody is going to ask for:
        a backend that dispatched every solution up front (which is exactly why
        the seam is per solution) still has jobs in flight when the consumer
        stops early -- because a solution failed, because the setter pressed
        Ctrl-C, because the report raised. Those jobs keep polling a remote judge
        for results that will never be read, and asyncio complains about them at
        interpreter exit. `close` is where they are cancelled.

        **Async, because cancelling is not the same as having cancelled.**
        `Task.cancel` only *schedules* the `CancelledError`; a task suspended in
        a subprocess call (`cli.testrun_status` awaits
        `process.communicate()`) needs more than one turn of the loop to unwind,
        and `syncer` runs the command with `run_until_complete` on a loop that
        stops as soon as the consumer returns or raises -- which is precisely
        the path `close` exists for. Reproduced on this project's Python: the
        sync version leaves `Task was destroyed but it is pending!` on stderr
        and the subprocess transport unclosed. So `close` awaits its own
        cancellations rather than hoping something else pumps the loop.

        Awaiting an **unresolved** deferred after `close` is not supported: on a
        backend that cancelled its jobs, that deferred raises `CancelledError`.
        A deferred already resolved keeps answering from its memo, which is what
        lets a consumer close and go on rendering what it has.
        """
        ...
