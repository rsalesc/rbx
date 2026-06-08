"""Tests for formatting Polygon FAILED-response comments before display (#389).

Two concerns:
- Compiler output frequently contains ``[...]`` (e.g. ``[with _Tp = int]``) which
  Rich would otherwise consume as markup and silently drop.
- Polygon truncates the ``comment`` field server-side, so long compilation errors
  are cut off; users should be told to look at the full log on the Polygon UI.
"""

from rich.text import Text

from rbx.box.packaging.polygon import polygon_api as api
from rbx.box.packaging.polygon import upload


def _render_plain(markup: str) -> str:
    return Text.from_markup(markup).plain


def test_bracketed_compiler_text_survives_rendering():
    comment = (
        'file: sol.cpp:5:9: error: no matching function [with _Tp = int; _Up = long]'
    )

    rendered = _render_plain(upload._format_request_failed_comment(comment))  # noqa: SLF001

    # The bracketed segment must NOT be eaten by Rich markup parsing.
    assert '[with _Tp = int; _Up = long]' in rendered


def test_long_comment_gets_truncation_hint():
    # A comment at/over Polygon's cap is almost certainly truncated.
    comment = 'file: ' + 'x' * api.COMMENT_LENGTH_LIMIT

    rendered = _render_plain(upload._format_request_failed_comment(comment))  # noqa: SLF001

    assert str(api.COMMENT_LENGTH_LIMIT) in rendered
    assert 'Polygon' in rendered
    assert 'truncat' in rendered.lower()


def test_short_comment_has_no_truncation_hint():
    comment = 'file: sol.cpp: ok'

    rendered = _render_plain(upload._format_request_failed_comment(comment))  # noqa: SLF001

    assert 'truncat' not in rendered.lower()
    # The original message is preserved verbatim.
    assert comment in rendered


def test_polygon_comment_length_limit_is_255():
    # Documents the observed Polygon API cap on the message portion (#389).
    assert api.COMMENT_LENGTH_LIMIT == 255
