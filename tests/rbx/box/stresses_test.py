"""`rbx stress` publishes its session to `.rbx/runs/.stress/`.

The VS Code extension never parses terminal output: it reads `stress.yml` and
the per-finding directories. These tests pin that layout.
"""

import pytest
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


async def test_findings_are_published(pkg: testing_package.TestingPackage):
    report = await _run_stress(
        timeout_in_seconds=30,
        generator_call='gens/gen.cpp [1..1000]',
        finder='sols/wa.cpp',
        findings_limit=2,
    )

    assert len(report.findings) == 2
    manifest = stress_manifest.read_manifest()
    assert manifest is not None
    assert manifest.state == StressState.DONE
    assert manifest.spec.generator == 'gens/gen.cpp [1..1000]'
    assert manifest.spec.finder == 'sols/wa.cpp'
    assert manifest.spec.findingsLimit == 2
    assert manifest.spec.fuzz is None
    assert manifest.solutions == ['sols/ac.cpp', 'sols/wa.cpp']
    assert manifest.executed == report.executed
    assert [f.index for f in manifest.findings] == [1, 2]
    assert [f.generator for f in manifest.findings] == [
        f.generator for f in report.findings
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


async def test_manifest_is_running_while_the_loop_runs(
    pkg: testing_package.TestingPackage,
):
    from unittest import mock

    seen = []
    real = stresses.generate_standalone

    async def spy(*args, **kwargs):
        manifest = stress_manifest.read_manifest()
        assert manifest is not None
        seen.append(manifest.state)
        return await real(*args, **kwargs)

    with mock.patch('rbx.box.stresses.generate_standalone', spy):
        await _run_stress(
            timeout_in_seconds=30,
            generator_call='gens/gen.cpp [1..1000]',
            finder='sols/wa.cpp',
            findings_limit=1,
        )

    assert seen and set(seen) == {StressState.RUNNING}
    manifest = stress_manifest.read_manifest()
    assert manifest is not None
    assert manifest.state == StressState.DONE


async def test_keyboard_interrupt_marks_interrupted(
    pkg: testing_package.TestingPackage,
):
    from unittest import mock

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

    manifest = stress_manifest.read_manifest()
    assert manifest is not None
    assert manifest.state == StressState.INTERRUPTED
    assert len(manifest.findings) == len(report.findings) == 1
    assert manifest.executed == 2


async def test_other_exceptions_mark_failed(pkg: testing_package.TestingPackage):
    from unittest import mock

    async def boom(*args, **kwargs):
        raise RuntimeError('boom')

    with mock.patch('rbx.box.stresses.generate_standalone', boom):
        with pytest.raises(RuntimeError):
            await _run_stress(
                timeout_in_seconds=30,
                generator_call='gens/gen.cpp [1..1000]',
                finder='sols/wa.cpp',
            )

    manifest = stress_manifest.read_manifest()
    assert manifest is not None
    assert manifest.state == StressState.FAILED


async def test_slowest_renumbers_contiguously(pkg: testing_package.TestingPackage):
    report = await _run_stress(
        timeout_in_seconds=2,
        generator_call='gens/gen.cpp [1..1000]',
        finder='sols/ac.cpp',
        findings_limit=2,
        find_slowest=True,
    )

    # Every execution is a candidate, so the heap evicted some.
    assert report.executed > 2
    manifest = stress_manifest.read_manifest()
    assert manifest is not None
    assert manifest.state == StressState.DONE
    assert manifest.spec.slowest
    assert [f.index for f in manifest.findings] == [1, 2]
    durations = [f.duration for f in manifest.findings]
    assert durations == sorted(durations, reverse=True)
    assert [f.generator for f in manifest.findings] == [
        f.generator for f in report.findings
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
