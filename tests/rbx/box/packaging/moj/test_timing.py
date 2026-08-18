import pytest
import typer

from rbx.box.packaging.moj import timing
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


# -- the bc expressions ------------------------------------------------------


def test_fmt_seconds_is_exact():
    assert timing.fmt_seconds(1234) == '1.234'
    assert timing.fmt_seconds(2000) == '2.000'
    assert timing.fmt_seconds(50) == '0.050'
    assert timing.fmt_seconds(0) == '0.000'


@pytest.mark.parametrize('base_ms', [500, 1000, 1350, 12000])
@pytest.mark.parametrize('measured_seconds', ['0.01', '0.35', '4.2'])
def test_calibrafactor_pins_the_limit_whatever_was_measured(base_ms, measured_seconds):
    # calibreitor.sh splices the factor into `<factor> * <worst> + 0.02` and hands
    # that to bc, whose precedence Python shares. That the measured time cannot move
    # the result is the whole mechanism, so it is asserted over the real expression
    # rather than over the string.
    factor = timing.calibrafactor_for_fixed_limit(base_ms)
    limit = eval(f'{factor} * {measured_seconds} + 0.02')  # noqa: S307
    assert limit == pytest.approx(base_ms / 1000)


def test_fixed_limits_split_into_a_base_and_increments():
    limits = timing.build_fixed_limits({'cpp': 1000, 'java': 3000}, base_ms=1000)
    assert limits.base_ms == 1000
    # cpp is at the base, so it needs no increment at all.
    assert limits.per_language_ms == {'java': 3000}


def test_fixed_limits_take_the_base_from_the_tightest_bucket():
    # The profile's own base counts too: a language MOJ knows but the package emits
    # no scripts for falls back to `TL[default]`, which the pinned factor sets to
    # exactly this base. Taking the smallest number involved also keeps every
    # increment non-negative.
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

    # 1000ms base, minus the 0.02 calibreitor.sh adds back.
    assert _conf_value(conf, 'TLMOD[calibrafactor]') == '0.980+0'
    assert _conf_value(conf, 'TLMOD[java.sum]') == '2.000'
    assert _conf_value(conf, 'TLMOD[py.sum]') == '1.500'
    # A language sitting at the base needs no increment.
    assert 'TLMOD[cpp.sum]' not in _keys(conf)
    assert 'TLMOD[c.sum]' not in _keys(conf)


def test_conf_pins_a_single_limit_when_every_language_agrees(moj_package):
    conf = (moj_package / 'conf').read_text()
    assert _conf_value(conf, 'TLMOD[calibrafactor]') == '0.980+0'
    assert not [key for key in _keys(conf) if key.endswith('.sum]')]


def test_conf_raises_the_calibration_limit_for_a_slow_problem(testing_pkg, tmp_path):
    # calibreitor.sh enforces a 5s dummy limit while it measures; an accepted
    # solution allowed 8s by the problem would time out during calibration.
    minimal_package(testing_pkg)
    with_limits_profile(testing_pkg, time_limit=2000, per_language={'py': 8000})
    testing_pkg.save()

    conf = (
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
        / 'conf'
    ).read_text()

    assert _conf_value(conf, 'CALIBRATIONTL') == '8'


def test_conf_leaves_the_calibration_limit_alone_by_default(moj_package):
    # The default 5s already covers a 1s problem; a redundant knob is noise.
    assert 'CALIBRATIONTL' not in _keys((moj_package / 'conf').read_text())


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
            calibrate=True,
            pin_limits=False,
        )
        / 'conf'
    ).read_text()

    # The environment's acToTimeLimit, so the judge's own measurements land where
    # `rbx time` would have put the limit.
    assert _conf_value(conf, 'TLMOD[calibrafactor]') == '2'
    assert not [key for key in _keys(conf) if key.endswith('.sum]')]
    assert 'CALIBRATIONTL' not in _keys(conf)
