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
