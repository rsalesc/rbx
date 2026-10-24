import pathlib

import pytest

from rbx.box.packaging.polygon import xml_schema as polygon_schema
from rbx.box.packaging.polygon.packager import PolygonPackager, _get_solution_tag
from rbx.box.schema import ExpectedOutcome, Solution


def _solution(outcome: ExpectedOutcome) -> Solution:
    return Solution(path=pathlib.Path('sols/sol.cpp'), outcome=outcome)


@pytest.mark.parametrize(
    ('outcome', 'is_main', 'tag'),
    [
        (ExpectedOutcome.ACCEPTED, True, 'main'),
        (ExpectedOutcome.ACCEPTED, False, 'accepted'),
        (ExpectedOutcome.ACCEPTED_OR_TLE, False, 'time-limit-exceeded-or-accepted'),
        (ExpectedOutcome.WRONG_ANSWER, False, 'wrong-answer'),
        (ExpectedOutcome.TIME_LIMIT_EXCEEDED, False, 'time-limit-exceeded'),
        (
            ExpectedOutcome.TLE_OR_MLE,
            False,
            'time-limit-exceeded-or-memory-limit-exceeded',
        ),
        (ExpectedOutcome.MEMORY_LIMIT_EXCEEDED, False, 'memory-limit-exceeded'),
        # No Polygon tag for these, so they are only known to fail.
        (ExpectedOutcome.RUNTIME_ERROR, False, 'rejected'),
        (ExpectedOutcome.INCORRECT, False, 'rejected'),
        (ExpectedOutcome.ANY, False, None),
    ],
)
def test_solution_tag(outcome, is_main, tag):
    assert _get_solution_tag(_solution(outcome), is_main=is_main) == tag


def test_polygon_offline_declares_solutions(testing_pkg):
    # A local checker, so the builtin one is not downloaded.
    testing_pkg.add_file('check.cpp').write_text('#include "testlib.h"\nint main(){}\n')
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sols/main.cpp', ExpectedOutcome.ACCEPTED)
    testing_pkg.add_solution('sols/ac.py', ExpectedOutcome.ACCEPTED)
    testing_pkg.add_solution('sols/wa.cpp', ExpectedOutcome.WRONG_ANSWER)
    testing_pkg.add_solution('sols/any.cpp', ExpectedOutcome.ANY)

    packager = PolygonPackager(testcase_entries=[])
    ns = packager._flatten_sources()  # noqa: SLF001

    assert packager._get_solutions(ns) == [  # noqa: SLF001
        polygon_schema.Solution(
            tag='main',
            source=polygon_schema.File(
                path='solutions/main.cpp', type='cpp.gcc13-64-winlibs-g++20'
            ),
        ),
        polygon_schema.Solution(
            tag='accepted',
            source=polygon_schema.File(path='solutions/ac.py', type='python.3'),
        ),
        polygon_schema.Solution(
            tag='wrong-answer',
            source=polygon_schema.File(
                path='solutions/wa.cpp', type='cpp.gcc13-64-winlibs-g++20'
            ),
        ),
    ]


def test_sample_flag_is_only_written_for_samples():
    packager = PolygonPackager(testcase_entries=[])

    sample = packager._get_manual_test(is_sample=True)  # noqa: SLF001
    test = packager._get_manual_test(is_sample=False)  # noqa: SLF001

    assert b'sample="true"' in sample.to_xml(skip_empty=True)
    assert b'sample' not in test.to_xml(skip_empty=True)
