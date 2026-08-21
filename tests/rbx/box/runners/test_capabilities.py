"""What a backend cannot report, and what a run does about it.

A remote judge reports strictly less than a local sandbox: no memory, no
artifacts, no checker message -- a verdict and a time per test. These tests pin
the two halves of that gap. The reporting side must read a missing measurement as
*unmeasured*, never as zero, because a zero is a plausible-looking lie. The
asking side must refuse a run the backend cannot honour, rather than quietly
running a downgraded one under the same name.
"""

import dataclasses
import pathlib
from typing import List, Optional

import pytest

from rbx.box.deferred import Deferred
from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.generators import generate_outputs_for_testcases, generate_testcases
from rbx.box.run_report import _max_of
from rbx.box.runners.base import RunContext, RunnerCapabilities, RunnerCapabilityError
from rbx.box.solutions import (
    SolutionSkeleton,
    get_evals_formatted_memory,
    get_evals_formatted_time,
    run_solutions,
)
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.grading import steps
from rbx.grading.steps import CheckerResult, Evaluation, Outcome

pytestmark = pytest.mark.shared_cache


def _unmeasured_evaluation(
    time: Optional[float] = None, memory: Optional[int] = None
) -> Evaluation:
    """What a backend that reports a verdict but no resource usage produces."""
    return Evaluation(
        result=CheckerResult(outcome=Outcome.ACCEPTED, message=''),
        testcase=steps.TestcaseIO(index=0),
        log=steps.TestcaseLog(
            exitcode=0, exitstatus='ok', time=time, wall_time=time, memory=memory
        ),
    )


# -- The reporting side: a missing measurement reads as unmeasured. ------------


def test_unmeasured_memory_reads_as_unmeasured_not_zero():
    assert get_evals_formatted_memory([_unmeasured_evaluation()]) == '-'


def test_unmeasured_time_reads_as_unmeasured_not_zero():
    assert get_evals_formatted_time([_unmeasured_evaluation()]) == '-'


def test_a_backend_that_times_but_measures_no_memory_still_reports_the_time():
    """A remote judge reports a time per test and nothing about memory.

    The two measurements must be independent: the missing one must not suppress
    the one that is really there, and the present one must not invent the other.
    """
    evals = [_unmeasured_evaluation(time=0.25)]

    assert get_evals_formatted_time(evals) == '250 ms'
    assert get_evals_formatted_memory(evals) == '-'


def test_one_measured_testcase_among_unmeasured_ones_sets_the_maximum():
    """An unmeasured testcase contributes nothing, rather than dragging to zero.

    Averaging or `max`-ing a coalesced zero in would both be wrong; the maximum
    must be taken over what was actually measured.
    """
    evals = [
        _unmeasured_evaluation(),
        _unmeasured_evaluation(time=0.5, memory=4 * 1024 * 1024),
        _unmeasured_evaluation(),
    ]

    assert get_evals_formatted_time(evals) == '500 ms'
    assert get_evals_formatted_memory(evals) == '4 MiB'


def test_the_published_report_leaves_an_unmeasured_maximum_empty():
    """`run_report`'s maxTime/maxMemory are `None`, not 0, when nothing measured.

    The report is a published contract read by clients that format it themselves,
    so a `0` there would be rendered as a real '0 ms' with nothing marking it as
    absent.
    """
    evals = [_unmeasured_evaluation(), _unmeasured_evaluation()]

    assert _max_of(eval.log.time for eval in evals) is None
    assert _max_of(eval.log.memory for eval in evals) is None

    evals.append(_unmeasured_evaluation(time=0.5, memory=1024))
    assert _max_of(eval.log.time for eval in evals) == 0.5
    assert _max_of(eval.log.memory for eval in evals) == 1024


def test_a_backend_that_cannot_measure_memory_never_reports_a_false_mle():
    """MLE is read off the verdict, never inferred from a memory number.

    That is what makes an unmeasurable backend safe: with no memory reading there
    is nothing to compare against a limit, so nothing can manufacture an MLE --
    and a judge that really says MLE is still believed.
    """
    unmeasured = _unmeasured_evaluation()
    assert unmeasured.result.outcome == Outcome.ACCEPTED

    reported_mle = Evaluation(
        result=CheckerResult(outcome=Outcome.MEMORY_LIMIT_EXCEEDED),
        testcase=steps.TestcaseIO(index=0),
        log=steps.TestcaseLog(exitcode=0, exitstatus='ok'),
    )
    assert reported_mle.result.outcome == Outcome.MEMORY_LIMIT_EXCEEDED
    assert get_evals_formatted_memory([reported_mle]) == '-'


# -- The asking side: a run a backend cannot honour is refused. ----------------


@dataclasses.dataclass
class LimitedRunner:
    """A backend that declares reduced capabilities and runs nothing.

    Modelled on `RecordingRunner` in `test_local_runner.py`, but it exists to be
    *refused*: every test here asserts `run_solution` was never reached.
    """

    caps: RunnerCapabilities
    name: str = 'limited'
    prepared: int = 0
    calls: int = 0

    async def prepare(self, ctx: RunContext) -> None:
        self.prepared += 1

    def run_solution(
        self,
        solution: SolutionSkeleton,
        entries: List[GenerationTestcaseEntry],
        ctx: RunContext,
    ) -> List[Deferred[Evaluation]]:
        self.calls += 1

        def make(entry: GenerationTestcaseEntry) -> Deferred[Evaluation]:
            async def run_fn() -> Evaluation:
                return Evaluation(
                    result=CheckerResult(outcome=Outcome.ACCEPTED),
                    testcase=steps.TestcaseIO(index=entry.group_entry.index),
                    log=steps.TestcaseLog(exitcode=0, exitstatus='ok'),
                )

            return Deferred(run_fn)

        return [make(entry) for entry in entries]


@pytest.mark.test_pkg('problems/abort-groups')
async def test_repeated_runs_are_refused_by_a_backend_that_runs_once(
    pkg_from_testdata: pathlib.Path,
):
    """Silently running once would read as a stable measurement, not a noisy one."""
    runner = LimitedRunner(caps=RunnerCapabilities(supports_nruns=False))

    with pytest.raises(RunnerCapabilityError) as exc:
        await run_solutions(
            verification=VerificationLevel.FULL,
            tracked_solutions=['sol.cpp'],
            nruns=3,
            runner=runner,
        )

    assert 'limited' in exc.value.message
    assert '3' in exc.value.message
    # Refused before anything was set up, let alone dispatched.
    assert runner.prepared == 0
    assert runner.calls == 0


@pytest.mark.test_pkg('problems/abort-groups')
async def test_a_single_run_is_fine_for_a_backend_that_runs_once(
    pkg_from_testdata: pathlib.Path,
):
    """The guard refuses *repetition*, not the backend.

    Without this, a guard written as `nruns > 0` would reject every ordinary run
    on such a backend and the refusal tests above would still pass.
    """
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)
    runner = LimitedRunner(caps=RunnerCapabilities(supports_nruns=False))

    await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        nruns=1,
        runner=runner,
    )

    assert runner.calls == 1


@pytest.mark.test_pkg('problems/abort-groups')
async def test_a_sanitized_run_is_refused_by_a_backend_without_sanitizers(
    pkg_from_testdata: pathlib.Path,
):
    runner = LimitedRunner(caps=RunnerCapabilities(supports_sanitizers=False))

    with pytest.raises(RunnerCapabilityError) as exc:
        await run_solutions(
            verification=VerificationLevel.FULL,
            tracked_solutions=['sol.cpp'],
            sanitized=True,
            runner=runner,
        )

    assert 'limited' in exc.value.message
    assert runner.prepared == 0
    assert runner.calls == 0


@pytest.mark.test_pkg('problems/interactive')
async def test_a_communication_problem_is_refused_by_a_non_interactive_backend(
    pkg_from_testdata: pathlib.Path,
):
    runner = LimitedRunner(caps=RunnerCapabilities(supports_interactive=False))

    with pytest.raises(RunnerCapabilityError) as exc:
        await run_solutions(
            verification=VerificationLevel.FULL,
            tracked_solutions=['sols/main.cpp'],
            runner=runner,
        )

    assert 'limited' in exc.value.message
    assert runner.prepared == 0
    assert runner.calls == 0


@pytest.mark.test_pkg('problems/abort-groups')
async def test_a_batch_backend_keeps_its_verdicts_even_when_the_run_aborts(
    pkg_from_testdata: pathlib.Path,
):
    """`supports_abort=False` means ungated, not "aborts anyway".

    A backend that already ran the whole submission holds a real verdict for every
    testcase. Wrapping those in the abort gate would overwrite them with SKIPPED,
    which is worse than useless: it throws away results the judge produced and
    makes the report claim work did not happen. Identity is the check -- comparing
    verdicts would pass against a gate that simply never tripped.
    """
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)

    returned: List[Deferred[Evaluation]] = []

    @dataclasses.dataclass
    class BatchRunner(LimitedRunner):
        def run_solution(self, solution, entries, ctx):
            res = LimitedRunner.run_solution(self, solution, entries, ctx)
            returned.extend(res)
            return res

    runner = BatchRunner(caps=RunnerCapabilities(supports_abort=False))

    result = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        # Aborts on the very first testcase, so a gate would show up immediately.
        abort_on=lambda ctx: True,
        runner=runner,
    )

    assert returned
    assert all(
        item.eval is deferred
        for item, deferred in zip(result.items, returned, strict=True)
    )
