"""Tests for ANSI-stripping in stdout/stderr assertions.

When the runner captures CLI output with Rich color enabled (FORCE_COLOR=1
or a TTY-detected stream), each styled segment is wrapped in ANSI escape
codes — so a literal substring like ``'div1 *'`` is no longer contiguous
in the raw bytes. The runner strips ANSI from stdout/stderr before
``stdout_contains`` / ``stderr_contains`` / ``stdout_matches`` see them.
"""

from tests.e2e.runner import _strip_ansi


def test_strip_ansi_removes_sgr_sequences():
    styled = '\x1b[1;34mdiv1\x1b[0m \x1b[90m*\x1b[0m'
    assert _strip_ansi(styled) == 'div1 *'


def test_strip_ansi_removes_csi_cursor_moves():
    text = 'before\x1b[2Khidden\x1b[1Aafter'
    assert _strip_ansi(text) == 'beforehiddenafter'


def test_strip_ansi_removes_osc_hyperlinks():
    # OSC 8 hyperlink terminators (BEL or ESC \).
    bel = 'see \x1b]8;;https://example.com\x07link\x1b]8;;\x07 here'
    assert _strip_ansi(bel) == 'see link here'

    esc = 'see \x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\ here'
    assert _strip_ansi(esc) == 'see link here'


def test_strip_ansi_passes_plain_text_through():
    plain = 'no ansi here\nsecond line\n'
    assert _strip_ansi(plain) == plain


def test_strip_ansi_handles_empty():
    assert _strip_ansi('') == ''
