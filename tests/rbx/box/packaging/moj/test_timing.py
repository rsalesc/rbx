import pytest
import typer

from rbx.box.packaging.moj import timing
from rbx.box.packaging.moj.packager import JudgeCalibrated
from tests.rbx.box.packaging.moj.conftest import (
    CHECKER,
    build_entries,
    minimal_package,
    run_packager,
    with_limits_profile,
)


def _conf_value(conf: str, key: str) -> str:
    for line in conf.splitlines():
        if line.startswith(f'{key}='):
            return line.split('=', 1)[1]
    raise AssertionError(f'{key} not found in conf:\n{conf}')


def _keys(conf: str) -> list:
    return [line.split('=', 1)[0] for line in conf.splitlines() if '=' in line]


# -- the emitted numbers -----------------------------------------------------


def test_fmt_seconds_is_exact():
    assert timing.fmt_seconds(1234) == '1.234'
    assert timing.fmt_seconds(2000) == '2.000'
    assert timing.fmt_seconds(50) == '0.050'
    assert timing.fmt_seconds(0) == '0.000'


def test_fixed_limits_split_into_a_default_and_the_languages_off_it():
    limits = timing.build_fixed_limits({'cpp': 1000, 'java': 3000}, base_ms=1000)
    assert limits.base_ms == 1000
    # cpp is at the default, so it needs no override of its own.
    assert limits.per_language_ms == {'java': 3000}


def test_fixed_limits_take_the_default_from_the_tightest_bucket():
    # The profile's own base counts too: a language MOJ knows but the package emits
    # no scripts for falls back to `TLOVERRIDE[default]`, so the tightest limit
    # involved is what that fallback has to be.
    limits = timing.build_fixed_limits({'cpp': 1000, 'py': 3000}, base_ms=700)
    assert limits.base_ms == 700
    assert limits.per_language_ms == {'cpp': 1000, 'py': 3000}


# -- what lands in conf ------------------------------------------------------


def test_conf_pins_the_limits_of_the_moj_profile(testing_pkg, tmp_path):
    minimal_package(testing_pkg)
    with_limits_profile(
        testing_pkg, time_limit=1000, per_language={'java': 3000, 'py': 2500}
    )
    testing_pkg.save()

    conf = (
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
        / 'conf'
    ).read_text()

    # Literal seconds: MOJ greps TLOVERRIDE out of conf, it never evaluates it.
    assert _conf_value(conf, 'TLOVERRIDE[default]') == '1.000'
    assert _conf_value(conf, 'TLOVERRIDE[java]') == '3.000'
    assert _conf_value(conf, 'TLOVERRIDE[py]') == '2.500'
    # A language sitting at the default needs no override of its own.
    assert 'TLOVERRIDE[cpp]' not in _keys(conf)
    assert 'TLOVERRIDE[c]' not in _keys(conf)
    # Nothing goes through the calibration arithmetic any more.
    assert 'TLMOD[calibrafactor]' not in _keys(conf)
    assert not [key for key in _keys(conf) if key.endswith('.sum]')]


def test_conf_pins_a_single_limit_when_every_language_agrees(moj_package):
    conf = (moj_package / 'conf').read_text()
    assert [key for key in _keys(conf) if key.startswith('TLOVERRIDE[')] == [
        'TLOVERRIDE[default]'
    ]
    assert _conf_value(conf, 'TLOVERRIDE[default]') == '1.000'
    assert 'TLMOD[calibrafactor]' not in _keys(conf)


def test_calibration_tl_covers_the_largest_pinned_limit():
    limits = timing.FixedTimeLimits(base_ms=2000, per_language_ms={'py': 8000})
    assert timing.calibration_tl_seconds(limits) == 8


def test_calibration_tl_never_drops_below_the_mojtools_default():
    limits = timing.FixedTimeLimits(base_ms=1000, per_language_ms={})
    assert timing.calibration_tl_seconds(limits) == 5


def test_calibration_tl_covers_the_inference_timeout():
    # rbx was willing to wait `inferenceTimeout` for a solution while estimating, and
    # calibration re-runs those same solutions, so it must wait at least as long.
    limits = timing.FixedTimeLimits(base_ms=1000, per_language_ms={})
    assert timing.calibration_tl_seconds(limits, inference_timeout_ms=10000) == 10
    # The largest pinned limit still wins when it is the bigger of the two.
    slow = timing.FixedTimeLimits(base_ms=2000, per_language_ms={'py': 15000})
    assert timing.calibration_tl_seconds(slow, inference_timeout_ms=10000) == 15


def test_conf_raises_the_calibration_limit_for_a_slow_problem(testing_pkg, tmp_path):
    # calibreitor.sh enforces a 5s dummy limit while it runs the solutions; an
    # accepted solution allowed 12s by the problem would time out during calibration.
    minimal_package(testing_pkg)
    with_limits_profile(testing_pkg, time_limit=2000, per_language={'py': 12000})
    testing_pkg.save()

    conf = (
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
        / 'conf'
    ).read_text()

    assert _conf_value(conf, 'CALIBRATIONTL') == '12'


def test_conf_raises_the_calibration_limit_to_the_inference_timeout(moj_package):
    # Every limit here is 1s, but the environment's inferenceTimeout is 10s -- the
    # cap the slow solutions were measured under.
    assert _conf_value((moj_package / 'conf').read_text(), 'CALIBRATIONTL') == '10'


def test_packaging_without_a_limits_profile_fails(testing_pkg, tmp_path):
    # MOJ owns the time limit unless rbx pins it, so a package with neither an
    # estimated profile nor --calibrate has nothing to say about its limits.
    minimal_package(testing_pkg)
    (testing_pkg.root / '.limits' / 'moj.yml').unlink()
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            pin_limits=False,
        )


def test_calibrate_hands_the_ac_ratio_to_moj(testing_pkg, tmp_path):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=JudgeCalibrated(),
            pin_limits=False,
        )
        / 'conf'
    ).read_text()

    # The environment's acToTimeLimit, so the judge's own measurements land where
    # `rbx time` would have put the limit.
    assert _conf_value(conf, 'TLMOD[calibrafactor]') == '2'
    # Nothing is pinned, so the judge's measurement is not overridden either.
    assert not [key for key in _keys(conf) if key.startswith('TLOVERRIDE[')]
    assert 'CALIBRATIONTL' not in _keys(conf)
