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

from rbx.box import setter_config
from rbx.box.deferred import Deferred
from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.generators import generate_outputs_for_testcases, generate_testcases
from rbx.box.runners.base import RunContext, RunnerCapabilities, RunnerCapabilityError
from rbx.box.solutions import (
    SolutionSkeleton,
    get_evals_formatted_memory,
    get_evals_formatted_time,
    get_worst_outcome,
    run_solutions,
)
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.grading import steps
from rbx.grading.steps import CheckerResult, Evaluation, Outcome

pytestmark = pytest.mark.shared_cache


async def _build_testset() -> None:
    """Generate inputs and outputs for whatever package the test is in."""
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)


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


def test_a_judge_reported_mle_survives_having_no_memory_reading():
    """An MLE verdict is believed even when nothing measured the memory.

    MLE is decided from the sandbox exit status (`checkers.py`), never by
    comparing a measured number against a limit -- which is what makes a backend
    that cannot measure memory safe. The verdict and the (absent) measurement are
    independent, so the missing one must not soften the verdict.

    The published-report side of this contract is pinned in `run_report_test.py`.
    """
    reported_mle = Evaluation(
        result=CheckerResult(outcome=Outcome.MEMORY_LIMIT_EXCEEDED),
        testcase=steps.TestcaseIO(index=0),
        log=steps.TestcaseLog(exitcode=0, exitstatus='ok'),
    )

    assert get_evals_formatted_memory([reported_mle]) == '-'
    assert get_worst_outcome([reported_mle]) == Outcome.MEMORY_LIMIT_EXCEEDED


# -- The asking side: a run a backend cannot honour is refused. ----------------


@dataclasses.dataclass
class LimitedRunner:
    """A backend that declares reduced capabilities and records what it was asked.

    Modelled on `RecordingRunner` in `test_local_runner.py`. It executes nothing:
    `run_solution` hands back deferreds over canned verdicts. `prepared` and
    `calls` are what the tests read -- the refusal tests assert the run never
    reached either, and the tests either side of a refusal assert it reached both.
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

    async def close(self) -> None:
        """Nothing to drop; present so the runtime `SolutionRunner` check passes.

        A result now carries the backend that produced it, and the protocol is
        `runtime_checkable`, so a fake missing `close` stops being a valid runner.
        """
        return None


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

    # The whole message, because every part of it is load-bearing: it names the
    # runner, the count, and -- crucially -- the flag the setter has to drop.
    # `str(exc)` is what a setter actually sees: `main.py` prints it with a bare
    # builtin `print`, not through the rich console, so any rich markup here would
    # reach them as literal `[item]` tags.
    assert str(exc.value) == (
        'Runner `limited` runs each testcase exactly once, but `--runs 3` asked '
        'for 3 runs per testcase. Drop `--runs`/`-r`, or run this on a backend '
        'that can repeat.'
    )
    # Refused before anything was set up, let alone dispatched.
    assert runner.prepared == 0
    assert runner.calls == 0


@pytest.mark.test_pkg('problems/abort-groups')
async def test_configured_repeats_are_refused_by_a_backend_that_runs_once(
    pkg_from_testdata: pathlib.Path,
    monkeypatch,
):
    """`nruns=0` resolves to the setter's configured repeats, and must be caught.

    This is the route most runs take: `nruns=0` is the default for every caller,
    so a setter who configured repeats once for stable timings would otherwise get
    a single measurement and read it as the average they asked for. Refusing on the
    raw parameter alone would let exactly that through.
    """
    cfg = setter_config.get_setter_config()
    monkeypatch.setattr(cfg.repeats, 'reps', 3)
    runner = LimitedRunner(caps=RunnerCapabilities(supports_nruns=False))

    with pytest.raises(RunnerCapabilityError) as exc:
        await run_solutions(
            verification=VerificationLevel.FULL,
            tracked_solutions=['sol.cpp'],
            runner=runner,
        )

    # Points at the config, which is the file the setter actually has to edit --
    # and says nothing about a flag they did not pass.
    assert str(exc.value) == (
        'Runner `limited` runs each testcase exactly once, but `repeats.reps` in '
        'your `setter_config.yml` is 3. Set it back to 1, or run this on a '
        'backend that can repeat.'
    )
    assert '--runs' not in str(exc.value)
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
    await _build_testset()
    runner = LimitedRunner(caps=RunnerCapabilities(supports_nruns=False))

    await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        nruns=1,
        runner=runner,
    )

    # `prepared` is asserted here and nowhere else on a passing path: without it,
    # the refusal tests' `prepared == 0` would also hold for a runner whose
    # `prepare` was never wired up at all.
    assert runner.prepared == 1
    assert runner.calls == 1


@pytest.mark.test_pkg('problems/abort-groups')
async def test_the_configured_default_of_one_run_is_fine(
    pkg_from_testdata: pathlib.Path,
):
    """`nruns=0` resolving to `reps=1` is an ordinary run, not a repeated one.

    The counterpart of the configured-repeats refusal: a guard written as
    `reps >= 1`, or one that treated the unresolved `nruns=0` as unknown and
    refused defensively, would break every ordinary run on such a backend.
    """
    await _build_testset()
    assert setter_config.get_setter_config().repeats.reps == 1
    runner = LimitedRunner(caps=RunnerCapabilities(supports_nruns=False))

    await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        runner=runner,
    )

    assert runner.prepared == 1
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
    # Printed with a bare `print`, so markup would show up as literal tags.
    assert '[item]' not in str(exc.value)
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
    # Printed with a bare `print`, so markup would show up as literal tags.
    assert '[item]' not in str(exc.value)
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
    await _build_testset()

    returned: List[Deferred[Evaluation]] = []

    @dataclasses.dataclass
    class BatchRunner(LimitedRunner):
        def run_solution(
            self,
            solution: SolutionSkeleton,
            entries: List[GenerationTestcaseEntry],
            ctx: RunContext,
        ) -> List[Deferred[Evaluation]]:
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
