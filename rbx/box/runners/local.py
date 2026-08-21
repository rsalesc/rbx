"""The sandbox on this machine. What rbx has always done."""

from typing import List, Optional

from rbx.box import solutions
from rbx.box.deferred import Deferred
from rbx.box.formatting import href
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.runners.base import RunContext, RunnerCapabilities
from rbx.box.solutions import (
    AbortContext,
    GroupSkeleton,
    SolutionSkeleton,
    _AbortGate,  # noqa: SLF001
    _record_skipped_evaluation,  # noqa: SLF001
)
from rbx.grading.steps import Evaluation


class LocalRunner:
    name = 'local'
    caps = RunnerCapabilities()

    async def prepare(self, ctx: RunContext) -> None:
        return None

    def run_solution(
        self,
        # Narrower than the protocol's `Solution` on purpose: only the skeleton
        # knows where this solution's run artifacts go, and every caller already
        # iterates over `skeleton.solutions`.
        solution: SolutionSkeleton,
        entries: List[GenerationTestcaseEntry],
        groups: List[GroupSkeleton],
        ctx: RunContext,
        gate: Optional[_AbortGate],
    ) -> List[Deferred[Evaluation]]:
        compiled_digest = ctx.skeleton.get_solution_compiled_digest(solution)
        runs_dir = solution.runs_dir
        groups_by_name = {group.name: group for group in groups}

        res: List[Deferred[Evaluation]] = []
        for i, entry in enumerate(entries):
            testcase = entry.metadata.copied_to
            group_name = entry.group_entry.group
            assert testcase.outputPath is not None
            output_path = runs_dir / group_name
            output_path.mkdir(parents=True, exist_ok=True)

            if ctx.progress:
                ctx.progress.update(
                    f'Running solution {href(solution.path)} on test [item]{entry}[/item]...'
                )

            async def run_fn(
                i=i, testcase=testcase, output_path=output_path, entry=entry
            ):
                group_name = entry.group_entry.group
                if gate is not None and gate.is_skipped(group_name):
                    return _record_skipped_evaluation(testcase, i, output_path)
                # Reached through the module rather than imported by name: the
                # single dispatch of one testcase is what callers (and tests)
                # observe a run by, and `solutions.run_solution_on_testcase` is
                # where they have always watched it. Binding the function here
                # would move that observation point without saying so.
                evaluation = await solutions.run_solution_on_testcase(
                    solution,
                    compiled_digest,
                    ctx.checker_digest,
                    testcase,
                    output_dir=output_path,
                    interactor_digest=ctx.interactor_digest,
                    testcase_index=i,
                    verification=ctx.verification,
                    timelimit_override=ctx.timelimit_override,
                    nruns=ctx.nruns,
                    capture_pipes=ctx.capture_pipes,
                )
                if gate is not None and ctx.abort_on is not None:
                    # Every entry belongs to a group of the skeleton. Assert rather
                    # than skip: a refactor that broke this would silently turn the
                    # abort off instead of failing.
                    group = groups_by_name.get(group_name)
                    assert group is not None
                    context = AbortContext(
                        solution=solution,
                        group=group,
                        entry=entry.group_entry,
                        expected_outcome=solution.outcome,
                        group_expected_outcome=solution.expected_outcome_for_group(
                            group_name
                        ),
                        evaluation=evaluation,
                    )
                    if ctx.abort_on(context):
                        gate.trip(group_name)
                return evaluation

            res.append(Deferred(run_fn))

        return res

    async def finalize(self) -> None:
        return None
