import pathlib

from rbx import utils
from rbx.grading.steps import CheckerResult, Outcome, RunLog, RunTiming


def test_of_returns_none_for_a_missing_run_log():
    assert RunTiming.of(None) is None


def test_of_carries_both_clocks_off_the_run_log():
    timing = RunTiming.of(RunLog(time=0.048, wall_time=0.051))
    assert timing == RunTiming(time=0.048, wall_time=0.051)


def test_a_result_without_timing_adds_no_keys_to_the_dumped_yaml():
    # The `.eval` artifact is written with `model_to_yaml`, which drops None.
    # A run whose checker never executed must write exactly the bytes it always
    # did, so this file format stays backward compatible.
    dumped = utils.model_to_yaml(CheckerResult(outcome=Outcome.ACCEPTED))
    assert 'checker_timing' not in dumped
    assert 'interactor_timing' not in dumped


def test_timing_round_trips_through_yaml(tmp_path: pathlib.Path):
    result = CheckerResult(
        outcome=Outcome.ACCEPTED,
        checker_timing=RunTiming(time=0.048, wall_time=0.051),
    )
    path = tmp_path / 'result.yml'
    path.write_text(utils.model_to_yaml(result))

    reloaded = utils.model_from_yaml(CheckerResult, path.read_text())
    assert reloaded.checker_timing == RunTiming(time=0.048, wall_time=0.051)
    assert reloaded.interactor_timing is None
