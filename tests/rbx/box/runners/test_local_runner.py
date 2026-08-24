import dataclasses
import pathlib
from typing import List, Tuple

import pytest

from rbx.box import solutions
from rbx.box.deferred import Deferred
from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.runners.base import RunContext, RunnerCapabilities
from rbx.box.runners.local import LocalRunner
from rbx.box.solutions import SolutionSkeleton, run_solutions
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.grading import steps
from rbx.grading.steps import CheckerResult, Evaluation, Outcome

# Compiling `box1`'s solutions is the cost these tests share with
# `solutions_test.py` -- share its problem cache too.
pytestmark = pytest.mark.shared_cache


async def _build_testset() -> None:
    """Generate inputs and outputs for whatever package the test is in."""
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)


@dataclasses.dataclass
class RecordingRunner:
    """A backend that runs nothing and remembers how it was called.

    The point is to pin the *seam* rather than the sandbox: which calls
    `run_solutions` makes, with what, and in what order. Nothing here compiles or
    executes, so these tests cost milliseconds and can use a four-group package
    that a real run would make far too slow.
    """

    name: str = 'recording'
    caps: RunnerCapabilities = dataclasses.field(default_factory=RunnerCapabilities)
    prepared: int = 0
    # One entry per `run_solution` call: the solution's path and its testcases.
    calls: List[Tuple[str, List[GenerationTestcaseEntry]]] = dataclasses.field(
        default_factory=list
    )
    # Every deferred handed back, flattened -- so a test can check what
    # `run_solutions` did with them by identity.
    returned: List[Deferred[Evaluation]] = dataclasses.field(default_factory=list)

    async def prepare(self, ctx: RunContext) -> None:
        assert not self.calls, 'prepare must come before any run_solution'
        self.prepared += 1

    def run_solution(
        self,
        solution: SolutionSkeleton,
        entries: List[GenerationTestcaseEntry],
        ctx: RunContext,
    ) -> List[Deferred[Evaluation]]:
        self.calls.append((str(solution.path), list(entries)))

        def make(entry: GenerationTestcaseEntry) -> Deferred[Evaluation]:
            async def run_fn() -> Evaluation:
                return Evaluation(
                    result=CheckerResult(outcome=Outcome.ACCEPTED),
                    testcase=steps.TestcaseIO(index=entry.group_entry.index),
                    # A real log, even though these deferreds are never awaited in
                    # most tests: `log` is not Optional, and a `None` here only
                    # survives by that accident.
                    log=steps.TestcaseLog(exitcode=0, exitstatus='ok'),
                )

            return Deferred(run_fn)

        res = [make(entry) for entry in entries]
        self.returned.extend(res)
        return res

    async def close(self) -> None:
        """Nothing to drop; present so the runtime `SolutionRunner` check passes.

        A result now carries the backend that produced it, and the protocol is
        `runtime_checkable`, so a fake missing `close` stops being a valid runner.
        """
        return None


@pytest.mark.test_pkg('problems/abort-groups')
async def test_the_backend_is_called_once_per_solution(
    pkg_from_testdata: pathlib.Path,
):
    """The seam's whole promise: one call carries a solution's entire testset.

    `abort-groups` has four testgroups, so a per-group seam shows up here as four
    calls where there must be one -- which is exactly the regression a
    single-group package like `box1` cannot see.
    """
    await _build_testset()
    runner = RecordingRunner()

    result = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        runner=runner,
    )

    assert runner.prepared == 1
    assert len(runner.calls) == 1

    (path, entries), *_ = runner.calls
    assert path == 'sol.cpp'

    # The whole testset arrives flattened in group order, and every item
    # `run_solutions` reports comes back in that same order.
    expected = [
        entry.group_entry
        for group in result.skeleton.groups
        for entry in result.skeleton.get_entries_for_group(group.name)
    ]
    assert [entry.group_entry for entry in entries] == expected
    assert [item.testcase_entry for item in result.items] == expected
    assert [entry.group for entry in expected] == (
        ['small'] * 3 + ['mid'] * 2 + ['late'] * 2 + ['independent'] * 2
    )


@pytest.mark.test_pkg('problems/abort-groups')
async def test_every_solution_gets_its_own_call(pkg_from_testdata: pathlib.Path):
    await _build_testset()
    runner = RecordingRunner()

    await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp', 'sol2.cpp'],
        runner=runner,
    )

    assert runner.prepared == 1
    assert [path for path, _ in runner.calls] == ['sol.cpp', 'sol2.cpp']


@pytest.mark.test_pkg('problems/abort-groups')
async def test_a_run_without_abort_passes_the_deferreds_straight_through(
    pkg_from_testdata: pathlib.Path,
):
    """No `abort_on` means no gate wrapper -- checked by identity, not by result.

    This is the guarantee that keeps an ordinary run byte-identical to one with no
    seam at all. Comparing evaluations would pass either way; only `is` can tell a
    pass-through from a wrapper that happens to return the same verdict.
    """
    await _build_testset()
    runner = RecordingRunner()

    result = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        runner=runner,
    )

    # `strict` covers length; `is` is the whole point -- `Deferred` has no
    # `__eq__`, so a list comparison here would only look like a value check.
    assert all(
        item.eval is deferred
        for item, deferred in zip(result.items, runner.returned, strict=True)
    )


@pytest.mark.test_pkg('problems/abort-groups')
async def test_run_solutions_defaults_to_the_local_runner(
    pkg_from_testdata: pathlib.Path,
):
    """The default backend is the local sandbox, by name and by type.

    Asserting the type is the only way to catch a `run_solutions` that ignored
    `runner=` altogether -- comparing two runs against each other cannot.
    """
    await _build_testset()
    seen: List[object] = []

    real_run_solution = LocalRunner.run_solution

    def spy(self, *args, **kwargs):
        seen.append(self)
        return real_run_solution(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(LocalRunner, 'run_solution', spy)
        await run_solutions(
            verification=VerificationLevel.FULL, tracked_solutions=['sol.cpp']
        )

    assert seen and all(isinstance(runner, LocalRunner) for runner in seen)
    assert seen[0].name == 'local'


@pytest.mark.test_pkg('problems/box1')
async def test_local_runner_yields_one_lazy_deferred_per_testcase(
    pkg_from_testdata: pathlib.Path,
):
    """The one test here that really compiles and runs in the sandbox."""
    await _build_testset()

    result = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        runner=LocalRunner(),
    )

    # One item per (solution, testcase), covering the whole testset in order.
    assert [item.testcase_entry for item in result.items] == [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    # Every one of them still lazy: nothing may have run just because the items
    # were produced.
    assert all(item.eval.peek() is None for item in result.items)

    # Awaiting is what runs them, and the result is memoized.
    first = result.items[0]
    evaluation = await first.eval()
    assert first.eval.peek() is evaluation
    assert await first.eval() is evaluation
    assert evaluation.result.outcome == Outcome.ACCEPTED


@pytest.mark.test_pkg('problems/box1')
async def test_local_runner_forwards_keep_checker_stderr(
    pkg_from_testdata: pathlib.Path,
):
    """`--keep-checker-stderr` has to reach the one call that can honour it."""
    await _build_testset()

    seen: List[bool] = []
    real_run = solutions.run_solution_on_testcase

    async def spy(*args, **kwargs):
        seen.append(kwargs.get('keep_checker_stderr', False))
        return await real_run(*args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(solutions, 'run_solution_on_testcase', spy)
        result = await run_solutions(
            verification=VerificationLevel.FULL,
            tracked_solutions=['sol.cpp'],
            runner=LocalRunner(),
            keep_checker_stderr=True,
        )
        await result.items[0].eval()

    assert seen == [True]
