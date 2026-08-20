import pathlib
from unittest import mock

from rbx.box import package, solutions
from rbx.box.schema import ExpectedOutcome
from rbx.box.testing import testing_package
from rbx.grading import steps
from rbx.grading.steps import GradingFileInput, GradingLogsHolder, PreprocessLog


async def test_compile_solutions_reports_failures_to_the_caller(
    testing_pkg: testing_package.TestingPackage, monkeypatch
):
    """A solution that does not compile is skipped, and named in `failures`.

    The skeleton is built from that dict: a failed solution is filtered out of
    `solutions` and out of `compiled_solutions`, so without this out-parameter
    nothing downstream could tell it had ever been declared.
    """
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    testing_pkg.add_from_testdata('sol.cpp', 'compile_test/simple.cpp')
    testing_pkg.add_solution('broken.cpp', outcome=ExpectedOutcome.WRONG_ANSWER)
    testing_pkg.add_from_testdata('broken.cpp', 'compile_test/simple.cpp')

    async def compile_side_effect(
        commands, params, artifacts, sandbox, dependency_cache
    ):
        if any('broken' in str(input.src) for input in artifacts.inputs):
            error = steps.CompilationError()
            error.logs = [
                PreprocessLog(
                    cmd=['g++', 'broken.cpp'],
                    log='broken.cpp:1:1: error: boom',
                    exitcode=1,
                )
            ]
            raise error
        for output in artifacts.outputs:
            if output.digest is not None:
                cacher = package.get_file_cacher()
                output.digest.value = await cacher.put_file_content(b'mock content')
        artifacts.logs = GradingLogsHolder(preprocess=[])
        return True

    monkeypatch.setattr(
        'rbx.box.code.steps_with_caching.compile',
        mock.AsyncMock(side_effect=compile_side_effect),
    )
    monkeypatch.setattr(
        'rbx.box.code._precompile_header',
        mock.AsyncMock(
            return_value=GradingFileInput(
                src=pathlib.Path('test.h.gch'),
                dest=pathlib.Path('test.h.gch'),
                hash=False,
            )
        ),
    )

    failures: dict[pathlib.Path, BaseException] = {}
    compiled = await solutions.compile_solutions(
        ['sol.cpp', 'broken.cpp'], skip_if_fail=True, failures=failures
    )

    assert pathlib.Path('sol.cpp') in compiled
    assert pathlib.Path('broken.cpp') not in compiled
    assert list(failures) == [pathlib.Path('broken.cpp')]
    assert isinstance(failures[pathlib.Path('broken.cpp')], steps.CompilationError)
