import pytest
from rbx_boca import verdicts


def test_pipelog_parses_three_lines():
    log = verdicts.PipeLog.parse('2\n0\n1\n')
    assert log == verdicts.PipeLog(first_tag=2, solution_status=0, interactor_status=1)


def test_pipelog_tolerates_whitespace():
    log = verdicts.PipeLog.parse(' 1 \n 139 \n 0 \n')
    assert log == verdicts.PipeLog(
        first_tag=1, solution_status=139, interactor_status=0
    )


def test_pipelog_rejects_short_log():
    with pytest.raises(ValueError):
        verdicts.PipeLog.parse('1\n0\n')


@pytest.mark.parametrize(
    'safeexec_exit,expected',
    [
        (0, 0),
        (3, 3),
        (7, 7),
        (2, 2),
        (9, 9),
        (10, 10),  # boundary: not remapped
        (11, 9),  # child nonzero (1+10) -> RTE
        (52, 9),  # child nonzero (42+10) -> RTE
    ],
)
def test_batch_run_exit(safeexec_exit, expected):
    assert verdicts.batch_run_exit(safeexec_exit) == expected


@pytest.mark.parametrize(
    'testlib,expected', [(1, 6), (2, 6), (3, 43), (4, 47), (5, 47)]
)
def test_compare_verdict_testlib(testlib, expected):
    assert verdicts.compare_verdict(testlib_code=testlib, checker_exit=None) == expected


@pytest.mark.parametrize(
    'checker,expected', [(0, 4), (1, 6), (2, 6), (3, 43), (4, 47), (9, 47)]
)
def test_compare_verdict_checker(checker, expected):
    assert verdicts.compare_verdict(testlib_code=None, checker_exit=checker) == expected
