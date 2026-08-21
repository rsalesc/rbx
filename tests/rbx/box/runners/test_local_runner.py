import pathlib

import pytest

from rbx.box.environment import VerificationLevel
from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.runners.local import LocalRunner
from rbx.box.solutions import run_solutions
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups

# Running `box1`'s solutions is the whole point of these tests, so they pay the
# same compilation cost `solutions_test.py` does -- share its problem cache.
pytestmark = pytest.mark.shared_cache


async def _build_box1_testset() -> None:
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)


@pytest.mark.test_pkg('problems/box1')
async def test_local_runner_yields_one_deferred_per_testcase(
    pkg_from_testdata: pathlib.Path,
):
    await _build_box1_testset()

    result = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        runner=LocalRunner(),
    )

    # One item per (solution, testcase), and every one of them still lazy: nothing
    # may have run just because the items were produced.
    assert result.items
    assert all(item.eval.peek() is None for item in result.items)

    # Awaiting is what runs them, and the result is memoized.
    first = result.items[0]
    evaluation = await first.eval()
    assert first.eval.peek() is evaluation
    assert await first.eval() is evaluation


@pytest.mark.test_pkg('problems/box1')
async def test_run_solutions_defaults_to_the_local_runner(
    pkg_from_testdata: pathlib.Path,
):
    await _build_box1_testset()

    explicit = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        runner=LocalRunner(),
    )
    implicit = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
    )

    assert len(implicit.items) == len(explicit.items)
    assert [item.testcase_entry for item in implicit.items] == [
        item.testcase_entry for item in explicit.items
    ]
