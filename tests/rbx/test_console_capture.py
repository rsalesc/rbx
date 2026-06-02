import rich.table

from rbx import console


def test_capture_ansi_contains_text_and_escape_codes():
    table = rich.table.Table('Col')
    table.add_row('hello')
    out = console.capture_ansi(table, width=40)
    assert 'hello' in out
    assert '\x1b[' in out  # SGR / box-drawing escapes emitted


def test_capture_ansi_resolves_theme_markup():
    # 'warning' is a project theme style; markup must resolve, not error.
    out = console.capture_ansi('[warning]careful[/warning]', width=40)
    assert 'careful' in out
    assert '\x1b[' in out
