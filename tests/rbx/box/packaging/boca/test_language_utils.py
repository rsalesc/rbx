from unittest import mock

from rbx.box.packaging.boca import boca_language_utils
from rbx.box.packaging.boca.extension import BocaLanguageExtension


def _mk_language(name: str, ext: BocaLanguageExtension | None = None):
    lang = mock.MagicMock()
    lang.name = name
    lang.get_extension_or_default.return_value = ext or BocaLanguageExtension()
    return lang


def test_forward_map_uses_primary_from_bocaLanguages(monkeypatch):
    cpp_lang = _mk_language('cpp', BocaLanguageExtension(bocaLanguages=['cc', 'cpp']))
    monkeypatch.setattr(boca_language_utils, 'get_language', lambda n: cpp_lang)
    env = mock.MagicMock()
    env.extensions = None
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_boca_language_from_rbx_language('cpp') == 'cc'


def test_reverse_map_resolves_alias_via_membership(monkeypatch):
    cpp_lang = _mk_language('cpp', BocaLanguageExtension(bocaLanguages=['cc', 'cpp']))
    env = mock.MagicMock()
    env.languages = [cpp_lang]
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)
    monkeypatch.setattr(
        boca_language_utils, 'get_language_by_extension_or_nil', lambda _: None
    )

    assert boca_language_utils.get_rbx_language_from_boca_language('cc') == 'cpp'
    assert boca_language_utils.get_rbx_language_from_boca_language('cpp') == 'cpp'


def test_reverse_map_back_compat_with_singular(monkeypatch):
    py_lang = _mk_language('py', BocaLanguageExtension(bocaLanguage='py3'))
    env = mock.MagicMock()
    env.languages = [py_lang]
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)
    monkeypatch.setattr(
        boca_language_utils, 'get_language_by_extension_or_nil', lambda _: None
    )

    assert boca_language_utils.get_rbx_language_from_boca_language('py3') == 'py'
