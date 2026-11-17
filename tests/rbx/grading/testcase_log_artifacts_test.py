import pathlib

from rbx.grading import steps


def _touch(path: pathlib.Path) -> pathlib.Path:
    path.write_text(path.name)
    return path


def test_lists_every_file_of_a_communication_run(tmp_path: pathlib.Path):
    out = _touch(tmp_path / '000.out')
    siblings = [
        _touch(out.with_suffix(suffix))
        for suffix in (*steps.CAPTURE_SUFFIXES, '.int.err', '.int.log', '.sol.log')
    ]
    err = _touch(tmp_path / '000.err')
    log = _touch(tmp_path / '000.log')
    eval = _touch(tmp_path / '000.eval')
    checker_err = _touch(tmp_path / '000.checker.err')

    testcase_log = steps.TestcaseLog(
        stdout_absolute_path=out,
        stderr_absolute_path=err,
        log_absolute_path=log,
        eval_absolute_path=eval,
        checker_stderr_absolute_path=checker_err,
    )

    assert sorted(testcase_log.artifact_paths()) == sorted(
        [out, err, log, eval, checker_err, *siblings]
    )


def test_lists_only_files_that_exist(tmp_path: pathlib.Path):
    out = _touch(tmp_path / '000.out')
    pio = _touch(tmp_path / '000.pio')

    testcase_log = steps.TestcaseLog(
        stdout_absolute_path=out,
        stderr_absolute_path=tmp_path / '000.err',
        log_absolute_path=tmp_path / '000.log',
    )

    assert testcase_log.artifact_paths() == [out, pio]


def test_lists_a_file_named_twice_once(tmp_path: pathlib.Path):
    out = _touch(tmp_path / '000.out')
    sol_log = _touch(tmp_path / '000.sol.log')

    # The run's log is also a sibling of its output.
    testcase_log = steps.TestcaseLog(
        stdout_absolute_path=out, log_absolute_path=sol_log
    )

    assert testcase_log.artifact_paths() == [out, sol_log]


def test_no_output_lists_only_the_named_files(tmp_path: pathlib.Path):
    eval = _touch(tmp_path / '000.eval')
    _touch(tmp_path / '000.pio')

    testcase_log = steps.TestcaseLog(eval_absolute_path=eval)

    assert testcase_log.artifact_paths() == [eval]
