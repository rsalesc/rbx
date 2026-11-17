import pickle

import pytest

from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.steps import (
    GradingLogsHolder,
    RunLog,
    RunLogMetadata,
    combine_process_logs,
)

OK = SandboxBase.EXIT_OK


def _log(
    exitstatus: str = OK,
    exitindex: int = 0,
    time: float = 0.1,
    wall_time: float = 0.2,
    memory: int = 1024,
    exitcode: int = 0,
    time_limit: int = 1000,
) -> RunLog:
    return RunLog(
        exitcode=exitcode,
        exitstatus=exitstatus,
        time=time,
        wall_time=wall_time,
        memory=memory,
        exitindex=exitindex,
        metadata=RunLogMetadata(timeLimit=time_limit),
    )


def test_one_log_comes_back_as_is():
    log = _log(SandboxBase.EXIT_TIMEOUT_WALL, time=0.01)
    combined, decider = combine_process_logs([log])
    assert combined is log
    assert decider is None


def test_ok_processes_sum_time_and_take_wall_and_memory_maxima():
    logs = [
        _log(exitindex=2, time=0.1, wall_time=0.5, memory=10),
        _log(exitindex=3, time=0.2, wall_time=0.3, memory=30, exitcode=0),
        _log(exitindex=1, time=0.3, wall_time=0.4, memory=20),
    ]
    logs[1].sandbox = 'last to exit'

    combined, decider = combine_process_logs(list(logs))

    assert decider is None
    assert combined is not None
    assert combined.time == pytest.approx(0.6)
    assert combined.wall_time == 0.5
    assert combined.memory == 30
    # The exit fields are those of the last process to exit.
    assert combined.exitstatus == OK
    assert combined.exitindex == 3
    assert combined.sandbox == 'last to exit'
    # The inputs are left alone.
    assert logs[1].time == 0.2


def test_a_failing_process_decides_with_its_exit_fields():
    logs = [
        _log(exitindex=3),
        _log(SandboxBase.EXIT_NONZERO_RETURN, exitindex=1, exitcode=3),
        _log(exitindex=2),
    ]
    combined, decider = combine_process_logs(list(logs))
    assert decider == 1
    assert combined is not None
    assert combined.exitstatus == SandboxBase.EXIT_NONZERO_RETURN
    assert combined.exitcode == 3


def test_the_first_failure_to_exit_decides():
    logs = [
        _log(SandboxBase.EXIT_SIGNAL, exitindex=4, exitcode=-9),
        _log(SandboxBase.EXIT_NONZERO_RETURN, exitindex=2, exitcode=1),
        _log(SandboxBase.EXIT_SIGNAL, exitindex=3, exitcode=-6),
    ]
    combined, decider = combine_process_logs(list(logs))
    assert decider == 1
    assert combined is not None
    assert combined.exitcode == 1


def test_a_sandbox_error_wins_over_an_earlier_failure():
    logs = [
        _log(SandboxBase.EXIT_NONZERO_RETURN, exitindex=0, exitcode=1),
        _log(SandboxBase.EXIT_SANDBOX_ERROR, exitindex=5),
    ]
    combined, decider = combine_process_logs(list(logs))
    assert decider == 1
    assert combined is not None
    assert combined.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR


def test_a_missing_log_combines_to_nothing():
    assert combine_process_logs([_log(), None, _log()]) == (None, None)


def test_summed_time_over_the_limit_is_reported_as_measured():
    # Each under the limit, the sum over it: the ladder sees the real sum.
    logs = [_log(time=0.4, exitindex=i) for i in range(3)]
    combined, _ = combine_process_logs(list(logs))
    assert combined is not None
    assert combined.time == pytest.approx(1.2)


def test_a_timeout_raises_the_sum_to_the_limit_once():
    # Every process stuck at the wall limit with next to no CPU: the run reports
    # the time limit once, not once per process.
    logs = [
        _log(SandboxBase.EXIT_TIMEOUT_WALL, exitindex=i, time=0.01) for i in range(4)
    ]
    combined, decider = combine_process_logs(list(logs))
    assert decider == 0
    assert combined is not None
    assert combined.time == pytest.approx(1.0)


def test_a_timeout_keeps_a_sum_already_over_the_limit():
    logs = [
        _log(SandboxBase.EXIT_TIMEOUT, exitindex=0, time=0.9),
        _log(exitindex=1, time=0.8),
    ]
    combined, _ = combine_process_logs(list(logs))
    assert combined is not None
    assert combined.time == pytest.approx(1.7)


def test_a_deciding_wall_timeout_becomes_a_timeout():
    logs = [
        _log(exitindex=1),
        _log(SandboxBase.EXIT_TIMEOUT_WALL, exitindex=0, time=0.01),
    ]
    combined, decider = combine_process_logs(list(logs))
    assert decider == 1
    assert combined is not None
    assert combined.exitstatus == SandboxBase.EXIT_TIMEOUT
    # The input log still says what the sandbox saw.
    assert logs[1].exitstatus == SandboxBase.EXIT_TIMEOUT_WALL


def test_warnings_of_any_process_carry_over():
    logs = [_log(exitindex=0), _log(exitindex=1)]
    logs[0].warnings = True
    combined, _ = combine_process_logs(list(logs))
    assert combined is not None
    assert combined.warnings


def test_a_logs_holder_pickled_before_runs_existed_loads():
    holder = GradingLogsHolder(run=_log(), cached=True)
    old = holder.model_copy(deep=True)
    # What a cache entry written before `runs` existed pickles.
    del old.__dict__['runs']
    restored = pickle.loads(pickle.dumps(old))

    assert restored.runs is None
    assert restored.run == holder.run
    assert restored.cached
    assert restored == holder
