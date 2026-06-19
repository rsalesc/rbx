import pathlib

from rbx.box.statements.schema import Statement


def test_assets_defaults_to_empty_list():
    st = Statement(language='en', file=pathlib.Path('statement/statement.rbx.tex'))
    assert st.assets == []


def test_assets_accepts_globs():
    st = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['statement/**/*.png', 'extra/logo.svg'],
    )
    assert st.assets == ['statement/**/*.png', 'extra/logo.svg']
