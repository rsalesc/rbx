"""`rbx stress` publishes its session to `.rbx/runs/.stress/`.

The VS Code extension never parses terminal output: it reads `stress.yml` and
the per-finding directories. These tests pin that layout.
"""

import asyncio
import os
import signal
import threading
from unittest import mock

import pytest
import typer
import yaml

from rbx.box import stress_manifest, stresses, tasks
from rbx.box.environment import VerificationLevel
from rbx.box.schema import ExpectedOutcome
from rbx.box.stress_manifest import StressState
from rbx.box.testing import testing_package
from rbx.grading import grading_context
from rbx.grading.steps import Outcome

pytestmark = pytest.mark.shared_cache

_ECHO = (
    '#include <iostream>\n'
    'int main() { long long n; std::cin >> n; std::cout << n << std::endl; }\n'
)
_PLUS_ONE = (
    '#include <iostream>\n'
    'int main() { long long n; std::cin >> n; std::cout << n + 1 << std::endl; }\n'
)


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_solution('sols/ac.cpp', outcome=ExpectedOutcome.ACCEPTED)
    (testing_pkg.root / 'sols' / 'ac.cpp').write_text(_ECHO)
    testing_pkg.add_solution('sols/wa.cpp', outcome=ExpectedOutcome.WRONG_ANSWER)
    (testing_pkg.root / 'sols' / 'wa.cpp').write_text(_PLUS_ONE)
    return testing_pkg


async def _run_stress(**kwargs) -> stresses.StressReport:
    limits = tasks.get_limits_for_language(
        lang=None, timelimit_override=None, verification=VerificationLevel.NONE
    )
    with (
        grading_context.stress(True),
        grading_context.cache_level(grading_context.CacheLevel.CACHE_COMPILATION),
    ):
        return await stresses.run_stress(limits=limits, **kwargs)


def _read() -> stress_manifest.StressManifest:
    manifest = stress_manifest.read_manifest()
    assert manifest is not None
    return manifest


async def test_findings_are_published(pkg: testing_package.TestingPackage):
    report = await _run_stress(
        timeout_in_seconds=30,
        generator_call='gens/gen.cpp [1..1000]',
        finder='sols/wa.cpp',
        findings_limit=2,
    )

    assert len(report.findings) == 2
    manifest = _read()
    assert manifest.state == StressState.DONE
    assert manifest.spec.generator == 'gens/gen.cpp [1..1000]'
    assert manifest.spec.finder == 'sols/wa.cpp'
    assert manifest.spec.findingsLimit == 2
    assert manifest.spec.fuzz is None
    assert manifest.solutions == ['sols/ac.cpp', 'sols/wa.cpp']
    assert manifest.executed == report.executed
    assert [f.index for f in manifest.findings] == [1, 2]
    assert [(f.generator, f.duration) for f in manifest.findings] == [
        (f.generator, f.duration) for f in report.findings
    ]

    findings_dir = stress_manifest.findings_dir()
    assert sorted(p.name for p in findings_dir.iterdir()) == ['1', '2']
    for finding in manifest.findings:
        [result] = finding.results
        assert result.solution == 1
        assert result.outcome == Outcome.WRONG_ANSWER
        assert result.time is not None

        input_text = stress_manifest.finding_input_path(finding.index).read_text()
        n = int(input_text)
        assert finding.generator.args is not None
        assert int(finding.generator.args) == n

        directory = stress_manifest.finding_dir(finding.index)
        answer = stress_manifest.finding_answer_path(finding.index)
        assert answer.read_text().strip() == str(n)
        # The reference solution, which produced the expected answer...
        assert (directory / '0.out').read_text().strip() == str(n)
        # ...and the breaking one.
        assert (directory / '1.out').read_text().strip() == str(n + 1)
        assert (directory / '1.err').is_file()
        eval_data = yaml.safe_load((directory / '1.eval').read_text())
        assert eval_data['result']['outcome'] == 'wrong-answer'
        assert eval_data['log']['stdout_absolute_path'] == str(
            (directory / '1.out').absolute()
        )
        assert eval_data['testcase']['output'] == str(answer.absolute())


async def test_manifest_is_running_while_the_loop_runs(
    pkg: testing_package.TestingPackage,
):
    seen = []
    real = stresses.generate_standalone

    async def spy(*args, **kwargs):
        seen.append(_read().state)
        return await real(*args, **kwargs)

    with mock.patch('rbx.box.stresses.generate_standalone', spy):
        await _run_stress(
            timeout_in_seconds=30,
            generator_call='gens/gen.cpp [1..1000]',
            finder='sols/wa.cpp',
            findings_limit=1,
        )

    assert seen and set(seen) == {StressState.RUNNING}
    assert _read().state == StressState.DONE


async def test_keyboard_interrupt_marks_interrupted(
    pkg: testing_package.TestingPackage,
):
    calls = 0
    real = stresses.generate_standalone

    async def interrupt_on_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt()
        return await real(*args, **kwargs)

    with mock.patch('rbx.box.stresses.generate_standalone', interrupt_on_second):
        report = await _run_stress(
            timeout_in_seconds=30,
            generator_call='gens/gen.cpp [1..1000]',
            finder='sols/wa.cpp',
            findings_limit=5,
        )

    manifest = _read()
    assert manifest.state == StressState.INTERRUPTED
    assert len(manifest.findings) == len(report.findings) == 1
    assert manifest.executed == 2


async def test_sigint_stops_the_loop_and_marks_interrupted(
    pkg: testing_package.TestingPackage,
):
    previous_handler = signal.getsignal(signal.SIGINT)
    real = stresses.generate_standalone
    timer = None

    async def send_sigint_once_running(*args, **kwargs):
        nonlocal timer
        if timer is None:
            # A real signal, delivered while the loop awaits the sandbox.
            timer = threading.Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGINT))
            timer.start()
        return await real(*args, **kwargs)

    with mock.patch('rbx.box.stresses.generate_standalone', send_sigint_once_running):
        # The finder never matches, so only the signal can end this early.
        report = await _run_stress(
            timeout_in_seconds=30,
            generator_call='gens/gen.cpp [1..1000]',
            finder='sols/ac.cpp',
            findings_limit=1,
        )

    assert timer is not None
    timer.join()
    manifest = _read()
    assert manifest.state == StressState.INTERRUPTED
    assert manifest.elapsed < 30
    assert report.findings == []
    assert manifest.executed == report.executed
    # The handler is gone once the stress is over.
    assert signal.getsignal(signal.SIGINT) == previous_handler


async def test_sigint_during_the_finder_lets_the_iteration_finish(
    pkg: testing_package.TestingPackage,
):
    real_run = tasks.run_solution_on_testcase
    sent = False

    async def run(solution, *args, **kwargs):
        nonlocal sent
        evaluation = await real_run(solution, *args, **kwargs)
        if str(solution.path) == 'sols/wa.cpp' and not sent:
            sent = True
            # Delivered synchronously, while the finder calls are in flight.
            os.kill(os.getpid(), signal.SIGINT)
        return evaluation

    with (
        mock.patch('rbx.box.stresses.tasks.run_solution_on_testcase', run),
        mock.patch('rbx.box.stresses.console.console.print') as console_print,
    ):
        report = await _run_stress(
            timeout_in_seconds=30,
            generator_call='gens/gen.cpp [1..1000]',
            finder='sols/wa.cpp',
            findings_limit=5,
        )

    assert sent
    manifest = _read()
    assert manifest.state == StressState.INTERRUPTED
    # The iteration the stop landed in completed, and its finding was kept.
    assert manifest.executed == report.executed == 1
    assert [f.index for f in manifest.findings] == [1]
    assert len(report.findings) == 1
    assert stress_manifest.finding_input_path(1).is_file()
    notices = [
        call
        for call in console_print.call_args_list
        if 'Stopping after the current test' in str(call)
    ]
    assert len(notices) == 1


@pytest.mark.parametrize(
    'signame',
    [name for name in ('SIGTERM', 'SIGHUP') if hasattr(signal, name)],
)
def test_termination_signals_mark_interrupted_and_exit(
    pkg: testing_package.TestingPackage, signame: str
):
    signum = getattr(signal, signame)
    previous_handler = signal.getsignal(signum)
    real = stresses.generate_standalone
    timer = None

    async def send_signal_once_running(*args, **kwargs):
        nonlocal timer
        if timer is None:
            # A real signal, delivered while the loop awaits the sandbox.
            timer = threading.Timer(0.2, lambda: os.kill(os.getpid(), signum))
            timer.start()
        return await real(*args, **kwargs)

    # A loop of our own, rather than an async test: the handler raises
    # `SystemExit` wherever the main thread is, which is usually the event
    # loop's own wait rather than the test's coroutine.
    loop = asyncio.new_event_loop()
    try:
        with (
            mock.patch(
                'rbx.box.stresses.generate_standalone', send_signal_once_running
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            # The finder never matches, so only the signal can end this early.
            loop.run_until_complete(
                _run_stress(
                    timeout_in_seconds=30,
                    generator_call='gens/gen.cpp [1..1000]',
                    finder='sols/ac.cpp',
                    findings_limit=1,
                )
            )
        manifest = _read()
        assert manifest.state == StressState.INTERRUPTED
        assert manifest.elapsed < 30
        assert exc_info.value.code == 128 + signum

        # Unwinding what is left of the stress -- its `finally` included --
        # must not overwrite the stamp.
        # (Nothing is left when the signal landed inside the coroutine itself.)
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        assert _read().state == StressState.INTERRUPTED
    finally:
        loop.close()
        if timer is not None:
            timer.join()

    assert signal.getsignal(signum) == previous_handler


async def test_other_exceptions_mark_failed(pkg: testing_package.TestingPackage):
    async def boom(*args, **kwargs):
        raise RuntimeError('boom')

    with mock.patch('rbx.box.stresses.generate_standalone', boom):
        with pytest.raises(RuntimeError):
            await _run_stress(
                timeout_in_seconds=30,
                generator_call='gens/gen.cpp [1..1000]',
                finder='sols/wa.cpp',
            )

    assert _read().state == StressState.FAILED


async def test_exit_with_error_marks_failed(pkg: testing_package.TestingPackage):
    async def exit_1(*args, **kwargs):
        raise typer.Exit(1)

    with mock.patch('rbx.box.stresses.generate_standalone', exit_1):
        with pytest.raises(typer.Exit):
            await _run_stress(
                timeout_in_seconds=30,
                generator_call='gens/gen.cpp [1..1000]',
                finder='sols/wa.cpp',
            )

    assert _read().state == StressState.FAILED


async def test_manifest_write_failure_does_not_mask_the_error(
    pkg: testing_package.TestingPackage,
):
    async def boom(*args, **kwargs):
        raise RuntimeError('boom')

    real_write = stress_manifest.write_manifest

    def fail_on_final_write(manifest, path=None):
        if manifest.state != StressState.RUNNING:
            raise OSError('disk full')
        real_write(manifest, path)

    with (
        mock.patch('rbx.box.stresses.generate_standalone', boom),
        mock.patch(
            'rbx.box.stress_manifest.write_manifest', side_effect=fail_on_final_write
        ),
        pytest.raises(RuntimeError, match='boom'),
    ):
        await _run_stress(
            timeout_in_seconds=30,
            generator_call='gens/gen.cpp [1..1000]',
            finder='sols/wa.cpp',
        )


# Scripted per-iteration durations (ms) for the slowest test, with a findings
# limit of 2. Candidates are numbered by iteration while running:
#   1 (10ms) kept; 2 (30ms) kept; 3 (20ms) evicts 1; 4 (50ms) evicts 3;
#   5 (5ms) and every later 0ms iteration are too fast to be candidates.
_SLOWEST_DURATIONS = [10, 30, 20, 50, 5]


async def test_slowest_evicts_and_renumbers(pkg: testing_package.TestingPackage):
    iteration = 0
    calls_by_iteration = {}
    findings_before = {}
    real_generate = stresses.generate_standalone
    real_run = tasks.run_solution_on_testcase

    async def generate(metadata, *args, **kwargs):
        nonlocal iteration
        iteration += 1
        calls_by_iteration[iteration] = metadata.generator_call
        findings_before[iteration] = (
            [f.index for f in _read().findings],
            sorted(p.name for p in stress_manifest.findings_dir().glob('*')),
        )
        return await real_generate(metadata, *args, **kwargs)

    async def run(*args, **kwargs):
        evaluation = await real_run(*args, **kwargs)
        durations = _SLOWEST_DURATIONS
        ms = durations[iteration - 1] if iteration <= len(durations) else 0
        evaluation.log.time = ms / 1000
        return evaluation

    with (
        mock.patch('rbx.box.stresses.generate_standalone', generate),
        mock.patch('rbx.box.stresses.tasks.run_solution_on_testcase', run),
    ):
        report = await _run_stress(
            timeout_in_seconds=3,
            generator_call='gens/gen.cpp [1..1000]',
            finder='sols/ac.cpp',
            findings_limit=2,
            find_slowest=True,
        )

    assert iteration > len(_SLOWEST_DURATIONS)
    # Mid-run, candidates keep their running number and evictions are gone
    # from both the manifest and the disk.
    assert findings_before[4] == ([2, 3], ['2', '3'])
    assert findings_before[5] == ([2, 4], ['2', '4'])

    manifest = _read()
    assert manifest.state == StressState.DONE
    assert manifest.spec.slowest
    assert [(f.index, f.duration) for f in manifest.findings] == [(1, 50), (2, 30)]
    assert [f.generator for f in manifest.findings] == [
        calls_by_iteration[4],
        calls_by_iteration[2],
    ]
    assert [(f.generator, f.duration) for f in report.findings] == [
        (f.generator, f.duration) for f in manifest.findings
    ]

    findings_dir = stress_manifest.findings_dir()
    assert sorted(p.name for p in findings_dir.iterdir()) == ['1', '2']
    for finding in manifest.findings:
        n = int(stress_manifest.finding_input_path(finding.index).read_text())
        assert finding.generator.args is not None
        assert int(finding.generator.args) == n
        directory = stress_manifest.finding_dir(finding.index)
        assert (directory / '0.out').read_text().strip() == str(n)
        # Moved directories have their `.eval`s repointed at the new place.
        eval_data = yaml.safe_load((directory / '0.eval').read_text())
        assert eval_data['log']['stdout_absolute_path'] == str(
            (directory / '0.out').absolute()
        )
        assert eval_data['testcase']['input'] == str(
            stress_manifest.finding_input_path(finding.index).absolute()
        )
