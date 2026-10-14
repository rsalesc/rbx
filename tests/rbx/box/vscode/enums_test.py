"""The extension's verdict tables are checked against a JSON dump of rbx's enums.

This is the Python half: it fails when the dump no longer matches the enums, so
adding an `ExpectedOutcome` or `Outcome` member forces a regenerate -- and the
regenerated file then fails the extension's own tests until it has a row.
"""

from scripts import gen_vscode_enums


def test_vscode_enum_fixture_is_current():
    assert gen_vscode_enums.ENUMS_JSON.read_text(encoding='utf-8') == (
        gen_vscode_enums.render()
    ), 'Stale fixture: run `uv run python scripts/gen_vscode_enums.py`.'
