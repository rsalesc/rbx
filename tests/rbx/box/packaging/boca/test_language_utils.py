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
