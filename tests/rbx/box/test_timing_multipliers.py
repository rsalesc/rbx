from typing import Optional

import pytest

from rbx.box.schema import TimingMultipliers
from rbx.box.timing import make_multipliers_derive, make_multipliers_eval
from rbx.box.timing_groups import (
    GroupMeasurements,
    GroupTimings,
    GroupValidationError,
    TimingRangeError,
    UpperTimings,
)


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
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeResolution=100)
    )
    # 410 * 2 = 820 -> 900.
    assert eval_fn(_measurements(slowest=410)) == 900


def test_lower_bound_already_on_the_grid_is_unchanged():
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeResolution=100)
    )
    # 400 * 2 = 800, already a multiple of 100.
    assert eval_fn(_measurements(slowest=400)) == 800


def test_lower_bound_absorbs_float_representation_error():
    # 50 * 1.1 is 55.00000000000001 in binary floating point; a naive ceil would
    # push the limit to 56 and, with a coarser resolution, a whole bucket up.
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=1.1, timeResolution=1)
    )
    assert eval_fn(_measurements(slowest=50)) == 55


def test_no_upper_bound_when_time_limit_to_tle_is_unset():
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeResolution=100)
    )
    # 500 would be way past any upper bound derived from a 500ms slow solution.
    assert eval_fn(_measurements(slowest=400, fastest_slow=500)) == 800


def test_no_upper_bound_when_there_are_no_upper_measurements():
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    assert eval_fn(_measurements(slowest=400)) == 800


def test_limit_comfortably_inside_the_range():
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    # lower 800, upper 6000 / 1.5 = 4000.
    assert eval_fn(_measurements(slowest=400, fastest_slow=6000)) == 800


def test_limit_exactly_equal_to_the_upper_bound_is_valid():
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    # lower 800, upper 1200 / 1.5 = 800: the boundary is inclusive.
    assert eval_fn(_measurements(slowest=400, fastest_slow=1200)) == 800


def test_boundary_absorbs_float_representation_error():
    # 1000 * 1.1 == 1100 mathematically, and 1100 / 1.1 is 999.9999999999999 in
    # binary floating point; the boundary must still be accepted.
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.1, timeResolution=100)
    )
    assert eval_fn(_measurements(slowest=500, fastest_slow=1100)) == 1000


def test_limit_one_step_past_the_upper_bound_raises():
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    # lower 800, upper 1199 / 1.5 = 799.33.
    with pytest.raises(TimingRangeError):
        eval_fn(_measurements(slowest=400, fastest_slow=1199))


def test_empty_range_raises_naming_both_binding_solutions():
    eval_fn = make_multipliers_eval(
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


def test_grid_miss_raises_even_though_the_range_is_not_empty():
    # lower 510 -> rounds up to 600, upper 550: the range [510, 550] is not
    # empty, but holds no multiple of 100.
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=1.0, timeLimitToTle=1.0, timeResolution=100)
    )
    with pytest.raises(TimingRangeError):
        eval_fn(_measurements(slowest=510, fastest_slow=550))


def test_timing_range_error_is_a_group_validation_error():
    # Load-bearing: the interactive picker renders GroupValidationError inline.
    assert issubclass(TimingRangeError, GroupValidationError)


def test_derive_quantizes_a_relative_limit():
    derive_fn = make_multipliers_derive(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    assert derive_fn(2401, GroupMeasurements()) == 2500


def test_derive_upper_checks_a_relative_limit():
    derive_fn = make_multipliers_derive(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    # 2401 quantizes to 2500, but 3000 / 1.5 = 2000 caps it.
    with pytest.raises(TimingRangeError) as exc:
        derive_fn(2401, _measurements(fastest_slow=3000, fastest_slow_solution='s.cpp'))
    assert 's.cpp' in str(exc.value)


def test_derive_accepts_a_relative_limit_inside_the_range():
    derive_fn = make_multipliers_derive(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    assert derive_fn(2401, _measurements(fastest_slow=9000)) == 2500
