from rbx.box.packaging.boca.packager import _compute_reps, _fmt_seconds


def test_fmt_seconds_is_exact():
    assert _fmt_seconds(1234) == '1.234'
    assert _fmt_seconds(2000) == '2.000'
    assert _fmt_seconds(500) == '0.500'
    assert _fmt_seconds(50) == '0.050'
    assert _fmt_seconds(1200) == '1.200'
    assert _fmt_seconds(0) == '0.000'


def test_compute_reps_single_run_when_no_minimum():
    assert _compute_reps(1200, None) == (1, False)
    assert _compute_reps(50, None) == (1, False)


def test_compute_reps_ceil_to_reach_minimum_budget():
    # 0.3s TL, 1s minimum -> ceil(1000/300) = 4 reps, budget 1.2s, not capped.
    assert _compute_reps(300, 1000) == (4, False)
    # exact multiple: 0.5s TL, 1s minimum -> 2 reps.
    assert _compute_reps(500, 1000) == (2, False)
    # TL already >= minimum -> 1 rep.
    assert _compute_reps(1500, 1000) == (1, False)


def test_compute_reps_caps_at_max_reps_and_flags():
    # 0.05s TL, 2s minimum would need 40 reps; cap at 10 and flag capped=True.
    assert _compute_reps(50, 2000) == (10, True)
