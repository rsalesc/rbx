import pathlib
from unittest import mock

from rbx.box import package, setter_config, solutions
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import ExpectedOutcome
from rbx.box.testing import testing_package
from rbx.grading.steps import GradingFileInput, GradingLogsHolder, PreprocessLog


async def test_compile_solutions_records_warnings_in_stack(
    testing_pkg: testing_package.TestingPackage, monkeypatch
):
    """compile_solutions drives compile_item, which forwards warning logs to the
    warning stack -- proving the streamer flow wires warnings end to end."""
    sol_path = testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    testing_pkg.add_from_testdata('sol.cpp', 'compile_test/simple.cpp')

    warning_log = PreprocessLog(
        cmd=['g++', 'sol.cpp'],
        log='sol.cpp:1:1: warning: unused variable',
        warnings=True,
    )

    async def compile_side_effect(
        commands, params, artifacts, sandbox, dependency_cache
    ):
        for output in artifacts.outputs:
            if output.digest is not None:
                cacher = package.get_file_cacher()
                output.digest.value = await cacher.put_file_content(b'mock content')
        artifacts.logs = GradingLogsHolder(preprocess=[warning_log])
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
    cfg = setter_config.get_setter_config()
    monkeypatch.setattr(cfg.warnings, 'enabled', True)

    warning_stack.get_warning_stack().clear()
    compiled = await solutions.compile_solutions(['sol.cpp'])

    assert pathlib.Path(sol_path).name == 'sol.cpp'
    assert pathlib.Path('sol.cpp') in compiled
    assert pathlib.Path('sol.cpp') in warning_stack.get_warning_stack().warnings
    warning_stack.get_warning_stack().clear()
