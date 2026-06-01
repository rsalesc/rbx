from rbx.box.packaging.boca.packager import _fmt_seconds


def test_fmt_seconds_is_exact():
    assert _fmt_seconds(1234) == '1.234'
    assert _fmt_seconds(2000) == '2.000'
    assert _fmt_seconds(500) == '0.500'
    assert _fmt_seconds(50) == '0.050'
    assert _fmt_seconds(1200) == '1.200'
    assert _fmt_seconds(0) == '0.000'
