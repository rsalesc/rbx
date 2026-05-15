import pathlib
from unittest import mock

from rbx.box import package, setter_config, solutions
from rbx.box.parallel import live_tasks
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import ExpectedOutcome
from rbx.box.testing import testing_package
from rbx.grading.steps import GradingFileInput, GradingLogsHolder, PreprocessLog


async def test_compile_solutions_records_warnings_in_stack(
    testing_pkg: testing_package.TestingPackage, monkeypatch
):
    """compile_solutions drives compile_item, which forwards warning logs to the
    warning stack, and the streamer flips the LiveTask to WARNINGS -- proving the
    flow wires warnings end to end."""
    sol_path = testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    testing_pkg.add_from_testdata('sol.cpp', 'compile_test/simple.cpp')

    created_tasks: list[solutions.SolutionCompilationTask] = []
    real_task_cls = solutions.SolutionCompilationTask

    class RecordingTask(real_task_cls):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created_tasks.append(self)

    monkeypatch.setattr(solutions, 'SolutionCompilationTask', RecordingTask)

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
    assert len(created_tasks) == 1
    assert created_tasks[0].status is live_tasks.CompilationStatus.WARNINGS
    assert (
        created_tasks[0].warning_summary == '1 warning'
    )  # C/C++ summarizer counts the unused-variable warning
    warning_stack.get_warning_stack().clear()
