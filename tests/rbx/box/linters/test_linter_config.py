from rbx.box.environment import EnvironmentLanguage, ExecutionConfig, LinterConfig
from rbx.box.linters.asset_kind import AssetKind


def _lang(**kw):
    return EnvironmentLanguage(
        name='cpp', extension='cpp', execution=ExecutionConfig(), **kw
    )


def test_linters_default_empty():
    assert _lang().linters == []


def test_shorthand_string_coerced_to_config():
    lang = _lang(linters=['testlib'])
    assert lang.linters == [LinterConfig(name='testlib', applies_to=None)]


def test_full_form_with_applies_to():
    lang = _lang(linters=[{'name': 'testlib', 'applies_to': ['generators']}])
    assert lang.linters[0].name == 'testlib'
    assert lang.linters[0].applies_to == [AssetKind.GENERATOR]


def test_singular_applies_to_token_accepted():
    lang = _lang(linters=[{'name': 'testlib', 'applies_to': ['generator']}])
    assert lang.linters[0].applies_to == [AssetKind.GENERATOR]
