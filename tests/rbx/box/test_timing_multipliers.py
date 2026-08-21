from typing import Optional

import pytest

from rbx.box.schema import TimingMultipliers
from rbx.box.timing import (
    compute_bounds,
    make_multipliers_derive,
    make_multipliers_eval,
)
from rbx.box.timing_groups import (
    GroupMeasurements,
    GroupTimings,
    GroupValidationError,
    TimingRangeError,
    UpperTimings,
)


def _eval_limit(multipliers: TimingMultipliers):
    """Just the limit the estimator lands on. It also reports the bounds that
    produced it, so the group reports can record them without recomputing them;
    that provenance is asserted in the estimation tests, while every case here
    is about the limit itself."""
    eval_fn = make_multipliers_eval(multipliers)
    return lambda measured: eval_fn(measured).time_limit


def _derive_limit(multipliers: TimingMultipliers):
    """Same, for the post-processor of a limit derived from another group."""
    derive_fn = make_multipliers_derive(multipliers)
    return lambda tl, measured: derive_fn(tl, measured).time_limit


def _measurements(
    slowest: Optional[int] = None,
    slowest_solution: Optional[str] = None,
    fastest_slow: Optional[int] = None,
    fastest_slow_solution: Optional[str] = None,
) -> GroupMeasurements:
    lower = None
    if slowest is not None:
        lower = GroupTimings(
            fastest=slowest,
            slowest=slowest,
            solution_count=1,
            slowest_solution=slowest_solution,
        )
    upper = None
    if fastest_slow is not None:
        upper = UpperTimings(
            fastest_slow=fastest_slow, fastest_slow_solution=fastest_slow_solution
        )
    return GroupMeasurements(lower=lower, upper=upper)


def test_lower_bound_rounds_up_to_the_resolution():
    eval_fn = _eval_limit(TimingMultipliers(acToTimeLimit=2.0, timeResolution=100))
    # 410 * 2 = 820 -> 900.
    assert eval_fn(_measurements(slowest=410)) == 900


def test_lower_bound_already_on_the_grid_is_unchanged():
    eval_fn = _eval_limit(TimingMultipliers(acToTimeLimit=2.0, timeResolution=100))
    # 400 * 2 = 800, already a multiple of 100.
    assert eval_fn(_measurements(slowest=400)) == 800


def test_lower_bound_is_exact_despite_float_representation():
    # 50 * 1.1 is 55.00000000000001 in binary floating point; the bound is
    # computed in exact rational arithmetic, so it is exactly 55.
    eval_fn = _eval_limit(TimingMultipliers(acToTimeLimit=1.1, timeResolution=1))
    assert eval_fn(_measurements(slowest=50)) == 55


def test_no_upper_bound_when_time_limit_to_tle_is_unset():
    eval_fn = _eval_limit(TimingMultipliers(acToTimeLimit=2.0, timeResolution=100))
    # 500 would be way past any upper bound derived from a 500ms slow solution.
    assert eval_fn(_measurements(slowest=400, fastest_slow=500)) == 800


def test_no_upper_bound_when_there_are_no_upper_measurements():
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    assert eval_fn(_measurements(slowest=400)) == 800


def test_limit_comfortably_inside_the_range():
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    # lower 800, upper 6000 / 1.5 = 4000.
    assert eval_fn(_measurements(slowest=400, fastest_slow=6000)) == 800


def test_limit_exactly_equal_to_the_upper_bound_is_valid():
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    # lower 800, upper 1200 / 1.5 = 800: the boundary is inclusive.
    assert eval_fn(_measurements(slowest=400, fastest_slow=1200)) == 800


def test_boundary_is_exact_despite_float_representation():
    # 1100 / 1.1 is 999.9999999999999 in binary floating point but exactly 1000
    # as a rational, so the limit sits exactly on the cap and is accepted.
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.1, timeResolution=100)
    )
    assert eval_fn(_measurements(slowest=500, fastest_slow=1100)) == 1000
    # One millisecond over the same cap is not.
    strict = _eval_limit(
        TimingMultipliers(acToTimeLimit=1.0, timeLimitToTle=1.1, timeResolution=1)
    )
    assert strict(_measurements(slowest=1000, fastest_slow=1100)) == 1000
    with pytest.raises(TimingRangeError):
        strict(_measurements(slowest=1001, fastest_slow=1100))


def test_one_millisecond_over_the_bound_raises_at_large_magnitudes():
    # 222000 / 3.7 is exactly 60000: 60000 ms is allowed, 60001 ms is not.
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=1.0, timeLimitToTle=3.7, timeResolution=1)
    )
    assert eval_fn(_measurements(slowest=60000, fastest_slow=222000)) == 60000
    with pytest.raises(TimingRangeError):
        eval_fn(_measurements(slowest=60001, fastest_slow=222000))


def test_limit_one_step_past_the_upper_bound_raises():
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    # lower 800, upper 1199 / 1.5 = 799.33.
    with pytest.raises(TimingRangeError):
        eval_fn(_measurements(slowest=400, fastest_slow=1199))


def test_empty_range_raises_naming_both_binding_solutions():
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    with pytest.raises(TimingRangeError) as exc:
        eval_fn(
            _measurements(
                slowest=400,
                slowest_solution='sols/slow_ac.cpp',
                fastest_slow=900,
                fastest_slow_solution='sols/tle.cpp',
            )
        )
    message = str(exc.value)
    assert 'sols/slow_ac.cpp' in message
    assert 'sols/tle.cpp' in message
    # The remedy is spelled out on both sides.
    assert 'speed up' in message.lower()
    assert 'slow down' in message.lower()
    # The ratios really are unsatisfiable here, so the rounding is not blamed.
    assert 'timeResolution' not in message


def test_grid_miss_raises_even_though_the_range_is_not_empty():
    # lower 510 -> rounds up to 600, upper 550: the range [510, 550] is not
    # empty, but holds no multiple of 100.
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=1.0, timeLimitToTle=1.0, timeResolution=100)
    )
    with pytest.raises(TimingRangeError) as exc:
        eval_fn(_measurements(slowest=510, fastest_slow=550))
    message = str(exc.value)
    # The ratios are satisfiable at 510 ms; the rounding is what is not, and the
    # message must point at that knob rather than at a speedup nobody needs.
    assert 'timeResolution' in message
    assert '510 ms' in message
    assert 'Lower timeResolution' in message


def test_timing_range_error_is_a_group_validation_error():
    # Load-bearing: the interactive picker renders GroupValidationError inline.
    assert issubclass(TimingRangeError, GroupValidationError)


def test_derive_quantizes_a_relative_limit():
    derive_fn = _derive_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    assert derive_fn(2401, GroupMeasurements()) == 2500


def test_derive_upper_checks_a_relative_limit():
    derive_fn = _derive_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    # 2401 quantizes to 2500, but 3000 / 1.5 = 2000 caps it.
    with pytest.raises(TimingRangeError) as exc:
        derive_fn(2401, _measurements(fastest_slow=3000, fastest_slow_solution='s.cpp'))
    assert 's.cpp' in str(exc.value)


def test_derive_accepts_a_relative_limit_inside_the_range():
    derive_fn = _derive_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    assert derive_fn(2401, _measurements(fastest_slow=9000)) == 2500


def test_message_falls_back_when_neither_solution_path_is_known():
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    with pytest.raises(TimingRangeError) as exc:
        eval_fn(_measurements(slowest=400, fastest_slow=900))
    message = str(exc.value)
    assert 'the accepted solution runs in 400 ms' in message
    assert 'the slow solution runs in 900 ms' in message
    assert 'Speed up the accepted solution' in message
    assert 'slow down the slow solution' in message


def test_message_falls_back_on_one_side_at_a_time():
    eval_fn = _eval_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    with pytest.raises(TimingRangeError) as exc:
        eval_fn(
            _measurements(slowest=400, slowest_solution='sols/ac.cpp', fastest_slow=900)
        )
    assert 'sols/ac.cpp runs in 400 ms' in str(exc.value)
    assert 'the slow solution runs in 900 ms' in str(exc.value)

    with pytest.raises(TimingRangeError) as exc:
        eval_fn(
            _measurements(
                slowest=400, fastest_slow=900, fastest_slow_solution='sols/tle.cpp'
            )
        )
    assert 'the accepted solution runs in 400 ms' in str(exc.value)
    assert 'sols/tle.cpp runs in 900 ms' in str(exc.value)


def test_derived_message_has_no_lower_side_solution():
    derive_fn = _derive_limit(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    with pytest.raises(TimingRangeError) as exc:
        derive_fn(2401, _measurements(fastest_slow=3000))
    message = str(exc.value)
    # There is no accepted solution in this group to point at, so the message
    # names the group the limit derives from instead of inventing one.
    assert 'the limit derived for this group is 2401 ms' in message
    assert 'acToTimeLimit' not in message
    assert 'the accepted solutions of the group this limit derives from' in message


def test_compute_bounds_exposes_both_sides_for_the_limits_profile():
    bounds = compute_bounds(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100),
        _measurements(
            slowest=630,
            slowest_solution='sols/slow_ac.cpp',
            fastest_slow=6100,
            fastest_slow_solution='sols/tle.cpp',
        ),
    )
    assert bounds.lower == 1260
    assert bounds.lower_solution == 'sols/slow_ac.cpp'
    assert bounds.time_limit == 1300
    assert bounds.upper == 4066  # floor(6100 / 1.5)
    assert bounds.upper_solution == 'sols/tle.cpp'
    assert not bounds.derived
    assert bounds.fits
    assert not bounds.quantization_is_binding


def test_compute_bounds_leaves_the_upper_side_empty_when_unbounded():
    bounds = compute_bounds(
        TimingMultipliers(acToTimeLimit=2.0, timeResolution=100),
        _measurements(slowest=400, fastest_slow=500),
    )
    assert bounds.upper is None
    assert bounds.upper_solution is None
    assert bounds.fits


def test_compute_bounds_marks_a_derived_lower_bound():
    bounds = compute_bounds(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100),
        _measurements(fastest_slow=3000),
        derived_from=2401,
    )
    assert bounds.derived
    assert bounds.lower == 2401
    assert bounds.lower_solution is None
    assert bounds.time_limit == 2500
    assert bounds.upper == 2000
    assert not bounds.fits


def test_compute_bounds_distinguishes_a_grid_miss_from_an_empty_range():
    multipliers = TimingMultipliers(
        acToTimeLimit=1.0, timeLimitToTle=1.0, timeResolution=100
    )
    grid_miss = compute_bounds(
        multipliers, _measurements(slowest=510, fastest_slow=550)
    )
    assert not grid_miss.fits
    assert grid_miss.quantization_is_binding

    empty = compute_bounds(multipliers, _measurements(slowest=610, fastest_slow=550))
    assert not empty.fits
    assert not empty.quantization_is_binding


def test_a_forced_estimate_keeps_the_limit_that_violates_the_upper_bound():
    # Accepting a violated upper bound is a decision the setter makes, so the
    # limit survives -- but the bound it violates is still reported, not
    # swallowed, so the profile records what was overridden.
    multipliers = TimingMultipliers(
        acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100
    )
    measured = _measurements(
        slowest=500,
        slowest_solution='sols/ac.cpp',
        fastest_slow=1100,
        fastest_slow_solution='sols/slow.cpp',
    )
    # acToTimeLimit puts the limit at 1000 ms; timeLimitToTle caps it at 733 ms.
    with pytest.raises(TimingRangeError):
        make_multipliers_eval(multipliers)(measured)

    forced = make_multipliers_eval(multipliers, force=True)(measured)
    assert forced.time_limit == 1000
    assert forced.upper_bound is not None
    assert forced.upper_bound.value == 733
    assert forced.upper_bound.solution == 'sols/slow.cpp'


def test_a_forced_derive_keeps_a_relative_limit_that_violates_the_bound():
    multipliers = TimingMultipliers(
        acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100
    )
    measured = _measurements(fastest_slow=1100, fastest_slow_solution='sols/slow.cpp')
    with pytest.raises(TimingRangeError):
        make_multipliers_derive(multipliers)(1000, measured)

    forced = make_multipliers_derive(multipliers, force=True)(1000, measured)
    assert forced.time_limit == 1000
    assert forced.upper_bound is not None
    assert forced.upper_bound.value == 733


def test_forcing_changes_nothing_when_the_bound_is_respected():
    multipliers = TimingMultipliers(
        acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100
    )
    measured = _measurements(slowest=500, fastest_slow=3000)
    assert (
        make_multipliers_eval(multipliers, force=True)(measured).time_limit
        == make_multipliers_eval(multipliers)(measured).time_limit
    )
