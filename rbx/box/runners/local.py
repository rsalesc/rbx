"""The sandbox on this machine. What rbx has always done."""

from typing import List

from rbx.box import solutions
from rbx.box.deferred import Deferred
from rbx.box.formatting import href
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.runners.base import RunContext, RunnerCapabilities, SolutionRunner
from rbx.box.solutions import SolutionSkeleton
from rbx.grading.steps import Evaluation


class LocalRunner:
    name = 'local'
    caps = RunnerCapabilities()

    async def prepare(self, ctx: RunContext) -> None:
        return None

    def run_solution(
        self,
        solution: SolutionSkeleton,
        entries: List[GenerationTestcaseEntry],
        ctx: RunContext,
    ) -> List[Deferred[Evaluation]]:
        compiled_digest = ctx.skeleton.get_solution_compiled_digest(solution)
        runs_dir = solution.runs_dir
        # Resolved once per solution: its language cannot change between
        # testcases. A per-language override that does not mention this
        # solution's language resolves to None -- the profile's own limit --
        # rather than to some other language's.
        solution_timelimit = solutions.resolve_timelimit_override(
            ctx.timelimit_override, solutions.find_language_name(solution)
        )

        res: List[Deferred[Evaluation]] = []
        for entry in entries:
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
                testcase=testcase,
                output_path=output_path,
                # The index a testcase is known by is its position *within its
                # group*, not within the flattened testset -- it is what names
                # the on-disk artifact and what `TestcaseIO.index` reports.
                index=entry.group_entry.index,
            ):
                # Reached through the module rather than imported by name: the
                # single dispatch of one testcase is what callers (and tests)
                # observe a run by, and `solutions.run_solution_on_testcase` is
                # where they have always watched it. Binding the function here
                # would move that observation point without saying so.
                return await solutions.run_solution_on_testcase(
                    solution,
                    compiled_digest,
                    ctx.checker_digest,
                    testcase,
                    output_dir=output_path,
                    interactor_digest=ctx.interactor_digest,
                    testcase_index=index,
                    verification=ctx.verification,
                    timelimit_override=solution_timelimit,
                    nruns=ctx.nruns,
                    capture_pipes=ctx.skeleton.capture_pipes,
                )

            res.append(Deferred(run_fn))

        return res

    async def close(self) -> None:
        """Nothing to drop: this backend never has work outstanding.

        Every testcase runs *inside* the deferred the consumer awaits, on the
        consumer's own thread of control -- so when the consumer stops, the
        sandbox work stops with it, and a testcase whose deferred was never
        awaited was never dispatched at all. There is no background task, no
        remote job and no session, which is precisely what a backend that
        dispatches ahead of the consumer (`MojRunner`) does have.
        """
        return None


# There is no type checker in this build, so the Protocol is only load-bearing if
# something checks it at run time. An annotated assignment would not have: Python
# binds the value and ignores the annotation.
#
# `runtime_checkable` checks that the members are *present*, nothing more. It
# catches a missing or misspelled `run_solution`, `prepare` or `caps` -- the
# realistic way a new backend goes wrong -- but it does not compare signatures,
# so a runner whose `run_solution` takes the wrong arguments still passes here
# and fails at the call site instead.
assert isinstance(LocalRunner(), SolutionRunner)
