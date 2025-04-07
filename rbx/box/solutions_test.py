import pathlib

import pytest

from rbx.box.environment import VerificationLevel
from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.solutions import (
    convert_list_of_solution_evaluations_to_dict,
    run_solutions,
)
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.grading.steps import Outcome


@pytest.mark.test_pkg('box1')
async def test_solutions(pkg_from_testdata: pathlib.Path):
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)

    result = run_solutions(verification=VerificationLevel.FULL)
    res = await convert_list_of_solution_evaluations_to_dict(result.items)

    # First solution should pass all tests.
    assert all(chk.result.outcome == Outcome.ACCEPTED for chk in res[0]['gen1'])
    # 25 test should be WA for the second solution.
    assert res[1]['gen1'][3].result.outcome == Outcome.WRONG_ANSWER
    # Runtime error for third solution.
    assert all(chk.result.outcome == Outcome.RUNTIME_ERROR for chk in res[2]['gen1'])
    # 1e9 test should be TLE for the fourth solution (soft TLE)
    assert res[3]['gen1'][4].result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    # no TLE outcome should be WA (soft TLE)
    assert res[4]['gen1'][4].result.no_tle_outcome == Outcome.WRONG_ANSWER
    # hard TLE
    assert res[5]['gen1'][4].result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    assert res[5]['gen1'][4].result.no_tle_outcome is None
    # OLE
    assert all(
        chk.result.outcome == Outcome.OUTPUT_LIMIT_EXCEEDED for chk in res[6]['gen1']
    )
