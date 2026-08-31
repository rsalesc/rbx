import pytest

from rbx.box import estimation_checksum
from rbx.box.estimation_checksum import (
    ChecksumBucket,
    EstimationChecksum,
)
from rbx.box.generators import generate_testcases
from rbx.box.schema import ExpectedOutcome, InferenceRole
from rbx.box.testing import testing_package

pytestmark = pytest.mark.shared_cache


def _add_manual_test(
    pkg: testing_package.TestingPackage, group: str, contents: str
) -> None:
    pkg.add_file('manual/000.in', src=None)
    (pkg.root / 'manual' / '000.in').write_text(contents)
    pkg.add_testgroup_with_manual_testcases(group, [{'inputPath': 'manual/000.in'}])


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage):
    """A package with one accepted and one slow solution, and one manual test."""
    testing_pkg.add_solution('sols/ac.cpp', outcome=ExpectedOutcome.ACCEPTED)
    (testing_pkg.root / 'sols' / 'ac.cpp').write_text('int main() { return 0; }\n')
    testing_pkg.add_solution(
        'sols/slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    (testing_pkg.root / 'sols' / 'slow.cpp').write_text('int main() { for(;;); }\n')
    _add_manual_test(testing_pkg, 'main', '1 2\n')
    return testing_pkg


# --- The light level ---------------------------------------------------------


def test_checksum_is_stable_across_calls(pkg: testing_package.TestingPackage):
    assert estimation_checksum.compute() == estimation_checksum.compute()


def test_checksum_is_light_without_a_build(pkg: testing_package.TestingPackage):
    checksum = estimation_checksum.compute()

    assert not checksum.is_heavy
    assert checksum.encode().startswith('v1.l.')
    assert checksum.encode().count('.') == 2


def test_checksum_moves_when_a_solution_body_changes(
    pkg: testing_package.TestingPackage,
):
    before = estimation_checksum.compute()

    (pkg.root / 'sols' / 'ac.cpp').write_text('int main() { return 1; }\n')

    assert estimation_checksum.compute().solutions != before.solutions


def test_checksum_moves_when_a_solution_joins_the_set(
    pkg: testing_package.TestingPackage,
):
    before = estimation_checksum.compute()

    pkg.add_solution('sols/other.cpp', outcome=ExpectedOutcome.ACCEPTED)
    (pkg.root / 'sols' / 'other.cpp').write_text('int main() { return 0; }\n')

    assert estimation_checksum.compute().solutions != before.solutions


def test_checksum_ignores_a_solution_that_bounds_nothing(
    pkg: testing_package.TestingPackage,
):
    """`accepted-or-tle` is neither good nor slow, so it never feeds the estimate.

    Adding one must not make a saved limit look stale: nothing about the number
    it produced has changed.
    """
    before = estimation_checksum.compute()

    pkg.add_solution('sols/borderline.cpp', outcome=ExpectedOutcome.ACCEPTED_OR_TLE)
    (pkg.root / 'sols' / 'borderline.cpp').write_text('int main() { return 0; }\n')

    assert estimation_checksum.compute().solutions == before.solutions


def test_checksum_moves_when_an_inference_role_changes(
    pkg: testing_package.TestingPackage,
):
    """Same bytes, different meaning: a solution promoted to an upper bound
    changes what the estimate was validated against."""
    before = estimation_checksum.compute()

    pkg.yml.solutions[1].inference = InferenceRole.LOWER
    pkg.yml.solutions[1].outcome = ExpectedOutcome.ACCEPTED
    pkg.save()

    assert estimation_checksum.compute().solutions != before.solutions


def test_checksum_moves_when_a_header_in_the_closure_changes(
    testing_pkg: testing_package.TestingPackage,
):
    """The bytes of the solution itself never move here -- only the header it
    includes, which is where a C++ solution's hot loop often lives."""
    testing_pkg.add_solution('sols/ac.cpp', outcome=ExpectedOutcome.ACCEPTED)
    (testing_pkg.root / 'sols' / 'ac.cpp').write_text(
        '#include "lib.h"\nint main() { return f(); }\n'
    )
    testing_pkg.add_file('sols/lib.h')
    header = testing_pkg.root / 'sols' / 'lib.h'
    header.write_text('int f() { return 0; }\n')
    _add_manual_test(testing_pkg, 'main', '1\n')

    before = estimation_checksum.compute()
    header.write_text('int f() { return 1; }\n')

    assert estimation_checksum.compute().solutions != before.solutions


# --- The heavy level ---------------------------------------------------------


async def test_checksum_is_heavy_after_a_validated_build(
    pkg: testing_package.TestingPackage,
):
    from rbx.box.environment import VerificationLevel
    from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
    from rbx.box.testset_manifest import write_manifest

    digests = await generate_testcases(verification=VerificationLevel.VALIDATE)
    entries = await extract_generation_testcases_from_groups(None)
    write_manifest(entries, None, digests, deterministic=True, partial=False)

    checksum = estimation_checksum.compute()

    assert checksum.is_heavy
    assert checksum.encode().startswith('v1.h.')
    assert checksum.encode().count('.') == 4
    # No interactor in this package: the segment is present but empty, so a
    # package that later gains one still reads as a change.
    assert checksum.interactor == '-'


async def test_heavy_checksum_moves_when_a_test_input_changes(
    pkg: testing_package.TestingPackage,
):
    from rbx.box.environment import VerificationLevel
    from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
    from rbx.box.testset_manifest import write_manifest

    async def rebuild():
        digests = await generate_testcases(verification=VerificationLevel.VALIDATE)
        entries = await extract_generation_testcases_from_groups(None)
        write_manifest(entries, None, digests, deterministic=True, partial=False)

    await rebuild()
    before = estimation_checksum.compute()

    (pkg.root / 'manual' / '000.in').write_text('3 4\n')
    await rebuild()
    after = estimation_checksum.compute()

    assert after.solutions == before.solutions
    assert after.tests != before.tests
    assert estimation_checksum.compare(before.encode()) == ChecksumBucket.TESTS


async def test_checksum_stays_light_when_determinism_was_not_checked(
    pkg: testing_package.TestingPackage,
):
    """A `-v0` build never proved its generators reproducible, so its digests
    describe one run rather than the testset. Hashing them would warn on every
    package with an unseeded generator, forever."""
    from rbx.box.environment import VerificationLevel
    from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
    from rbx.box.testset_manifest import write_manifest

    digests = await generate_testcases(verification=VerificationLevel.NONE)
    entries = await extract_generation_testcases_from_groups(None)
    write_manifest(entries, None, digests, deterministic=False, partial=False)

    assert not estimation_checksum.compute().is_heavy


async def test_checksum_stays_light_when_only_some_groups_were_built(
    pkg: testing_package.TestingPackage,
):
    """A `--samples-only` package build leaves a manifest describing one group.
    Comparing it against an estimate taken over the whole testset would flag
    every such build."""
    from rbx.box.environment import VerificationLevel
    from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
    from rbx.box.testset_manifest import write_manifest

    digests = await generate_testcases(
        groups={'main'}, verification=VerificationLevel.VALIDATE
    )
    entries = await extract_generation_testcases_from_groups({'main'})
    write_manifest(entries, None, digests, deterministic=True, partial=True)

    assert not estimation_checksum.compute().is_heavy


async def test_a_group_that_produces_no_tests_keeps_the_heavy_level(
    testing_pkg: testing_package.TestingPackage,
):
    """A declared group can legitimately be empty -- a `testcaseGlob` matching
    nothing. Inferring "partial build" by comparing declared groups against built
    ones would read that as a subset build forever, silently disabling the heavy
    level for the whole package.
    """
    from rbx.box.environment import VerificationLevel
    from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
    from rbx.box.testset_manifest import write_manifest

    testing_pkg.add_solution('sols/ac.cpp', outcome=ExpectedOutcome.ACCEPTED)
    (testing_pkg.root / 'sols' / 'ac.cpp').write_text('int main() { return 0; }\n')
    _add_manual_test(testing_pkg, 'main', '1\n')
    testing_pkg.add_testgroup_from_glob('empty', 'nothing/*.in')

    digests = await generate_testcases(verification=VerificationLevel.VALIDATE)
    entries = await extract_generation_testcases_from_groups(None)
    write_manifest(entries, None, digests, deterministic=True, partial=False)

    assert estimation_checksum.compute().is_heavy


async def test_light_only_ignores_a_manifest_an_earlier_build_left(
    pkg: testing_package.TestingPackage,
):
    """`rbx irun` never builds a testset, so whatever is in `build/` describes
    some earlier run and must not satisfy the tests segment."""
    from rbx.box.environment import VerificationLevel
    from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
    from rbx.box.testset_manifest import write_manifest

    digests = await generate_testcases(verification=VerificationLevel.VALIDATE)
    entries = await extract_generation_testcases_from_groups(None)
    write_manifest(entries, None, digests, deterministic=True, partial=False)

    assert estimation_checksum.compute().is_heavy
    assert not estimation_checksum.compute(light_only=True).is_heavy


# --- Encoding and comparison -------------------------------------------------


def test_encode_round_trips():
    for checksum in (
        EstimationChecksum(version='v1', level='l', solutions='aaaaaaaa'),
        EstimationChecksum(
            version='v1',
            level='h',
            solutions='aaaaaaaa',
            interactor='bbbbbbbb',
            tests='cccccccc',
        ),
    ):
        assert EstimationChecksum.decode(checksum.encode()) == checksum


@pytest.mark.parametrize(
    'value',
    ['', 'nonsense', 'v1.l', 'v1.h.aaaaaaaa', 'v1.x.aaaaaaaa', 'v1.l.a.b.c.d'],
)
def test_decode_rejects_anything_it_cannot_read(value: str):
    assert EstimationChecksum.decode(value) is None


def test_compare_is_silent_for_a_version_it_does_not_speak():
    """A newer rbx must not greet an old package with a warning about a format
    it cannot evaluate."""
    assert estimation_checksum.compare('v99.l.aaaaaaaa') is None


def test_compare_is_silent_for_an_unreadable_checksum():
    assert estimation_checksum.compare('hand-edited nonsense') is None


def test_compare_names_the_solutions_bucket():
    current = EstimationChecksum(version='v1', level='l', solutions='bbbbbbbb')
    recorded = EstimationChecksum(version='v1', level='l', solutions='aaaaaaaa')

    assert (
        estimation_checksum.compare(recorded.encode(), current)
        == ChecksumBucket.SOLUTIONS
    )


def test_compare_names_the_interactor_bucket():
    recorded = EstimationChecksum(
        version='v1', level='h', solutions='a', interactor='b', tests='c'
    )
    current = EstimationChecksum(
        version='v1', level='h', solutions='a', interactor='B', tests='c'
    )

    assert (
        estimation_checksum.compare(recorded.encode(), current)
        == ChecksumBucket.INTERACTOR
    )


def test_compare_matches():
    checksum = EstimationChecksum(
        version='v1', level='h', solutions='a', interactor='b', tests='c'
    )

    assert estimation_checksum.compare(checksum.encode(), checksum) is None


def test_compare_ignores_heavy_segments_when_the_current_side_is_light():
    """The common case on a clean checkout: the profile remembers the tests, the
    working tree has not built them. The solutions still get compared."""
    recorded = EstimationChecksum(
        version='v1', level='h', solutions='a', interactor='b', tests='c'
    )
    light = EstimationChecksum(version='v1', level='l', solutions='a')

    assert estimation_checksum.compare(recorded.encode(), light) is None

    moved = EstimationChecksum(version='v1', level='l', solutions='z')
    assert (
        estimation_checksum.compare(recorded.encode(), moved)
        == ChecksumBucket.SOLUTIONS
    )


# --- Wiring into a profile ---------------------------------------------------


def test_check_profile_is_silent_without_a_profile(
    pkg: testing_package.TestingPackage,
):
    assert estimation_checksum.check_profile('local') is None


def test_check_profile_is_silent_for_a_profile_that_was_never_estimated(
    pkg: testing_package.TestingPackage,
):
    """`--strategy inherit` and `--strategy custom` write no checksum, so their
    profiles are never warned about."""
    from rbx.box import timing

    timing.set_time_limit(1000, profile='local')

    assert estimation_checksum.check_profile('local') is None


def test_check_profile_flags_a_stale_estimate(pkg: testing_package.TestingPackage):
    from rbx import utils
    from rbx.box import package
    from rbx.box.schema import LimitsProfile

    limits = LimitsProfile(
        timeLimit=1000,
        estimationChecksum=estimation_checksum.compute().encode(),
    )
    limits_path = package.get_limits_file('local')
    limits_path.parent.mkdir(parents=True, exist_ok=True)
    limits_path.write_text(utils.model_to_yaml(limits))

    assert estimation_checksum.check_profile('local') is None

    (pkg.root / 'sols' / 'ac.cpp').write_text('int main() { return 7; }\n')

    assert estimation_checksum.check_profile('local') == ChecksumBucket.SOLUTIONS


def test_warn_if_stale_accepts_no_active_profile(
    pkg: testing_package.TestingPackage,
):
    """Callers hand over `limits_info.get_active_profile()` directly, which is
    None whenever no profile was named."""
    assert estimation_checksum.warn_if_stale(None) is None


def _recording_console(monkeypatch):
    import rich.console

    import rbx.console

    recorder = rich.console.Console(
        theme=rbx.console.theme, record=True, width=200, color_system=None
    )
    monkeypatch.setattr(rbx.console, 'console', recorder)
    return recorder


def _save_profile(profile: str, checksum: str) -> None:
    from rbx import utils
    from rbx.box import package
    from rbx.box.schema import LimitsProfile

    limits_path = package.get_limits_file(profile)
    limits_path.parent.mkdir(parents=True, exist_ok=True)
    limits_path.write_text(
        utils.model_to_yaml(LimitsProfile(timeLimit=1000, estimationChecksum=checksum))
    )


def test_warn_if_stale_says_which_bucket_and_how_to_fix_it(
    pkg: testing_package.TestingPackage, monkeypatch
):
    _save_profile('boca', estimation_checksum.compute().encode())
    (pkg.root / 'sols' / 'ac.cpp').write_text('int main() { return 7; }\n')

    recorder = _recording_console(monkeypatch)
    assert estimation_checksum.warn_if_stale('boca') == ChecksumBucket.SOLUTIONS

    text = recorder.export_text()
    assert 'boca' in text
    assert 'stale' in text
    assert 'solutions' in text
    assert 'rbx time -p boca' in text


def test_warn_if_stale_says_nothing_when_the_estimate_is_current(
    pkg: testing_package.TestingPackage, monkeypatch
):
    _save_profile('boca', estimation_checksum.compute().encode())

    recorder = _recording_console(monkeypatch)
    assert estimation_checksum.warn_if_stale('boca') is None
    assert recorder.export_text().strip() == ''


def test_timing_profile_carries_the_checksum_into_the_limits():
    from rbx.box.timing import TimingProfile

    profile = TimingProfile(timeLimit=1000, estimationChecksum='v1.l.aaaaaaaa')

    assert profile.to_limits().estimationChecksum == 'v1.l.aaaaaaaa'
