from rbx.grading.limits import Limits


def test_display_time_falls_back_to_enforced_time_when_configured_is_unset():
    limits = Limits(time=1500)
    assert limits.display_time() == 1500


def test_display_time_prefers_configured_time_when_enforcement_is_off():
    # The enforced ``time`` is stripped (no TL applied for this run), but the
    # declared time limit is still known and should be what we display.
    limits = Limits(time=None, configuredTime=2000)
    assert limits.display_time() == 2000


def test_display_time_is_none_when_no_limit_is_known():
    limits = Limits(time=None, configuredTime=None)
    assert limits.display_time() is None
