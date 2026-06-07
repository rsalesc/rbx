from unittest import mock

from rbx.box.packaging.boca import boca_language_utils
from rbx.box.packaging.boca.extension import BocaLanguageExtension


def _mk_language(name: str, ext: BocaLanguageExtension | None = None):
    lang = mock.MagicMock()
    lang.name = name
    lang.get_extension_or_default.return_value = ext or BocaLanguageExtension()
    return lang


def test_forward_map_uses_primary_from_languages(monkeypatch):
    cpp_lang = _mk_language(
        'cpp', BocaLanguageExtension(languages=['cc', 'cpp'], template='cc')
    )
    monkeypatch.setattr(boca_language_utils, 'get_language', lambda n: cpp_lang)

    assert boca_language_utils.get_boca_language_from_rbx_language('cpp') == 'cc'


def test_forward_map_name_fallback_for_literal(monkeypatch):
    # rbx language named 'c' with NO boca extension falls back to its own name.
    c_lang = _mk_language('c', BocaLanguageExtension())
    monkeypatch.setattr(boca_language_utils, 'get_language', lambda n: c_lang)

    assert boca_language_utils.get_boca_language_from_rbx_language('c') == 'c'


def test_reverse_map_resolves_alias_via_membership(monkeypatch):
    cpp_lang = _mk_language(
        'cpp', BocaLanguageExtension(languages=['cc', 'cpp'], template='cc')
    )
    env = mock.MagicMock()
    env.languages = [cpp_lang]
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)
    monkeypatch.setattr(
        boca_language_utils, 'get_language_by_extension_or_nil', lambda _: None
    )

    assert boca_language_utils.get_rbx_language_from_boca_language('cc') == 'cpp'
    assert boca_language_utils.get_rbx_language_from_boca_language('cpp') == 'cpp'


def _mk_env(languages):
    env = mock.MagicMock()
    env.languages = languages
    return env


def test_emitted_set_union_from_languages(monkeypatch):
    env = _mk_env(
        [
            _mk_language(
                'cpp', BocaLanguageExtension(languages=['cc', 'cpp'], template='cc')
            ),
            _mk_language(
                'py', BocaLanguageExtension(languages=['py3'], template='py3')
            ),
        ]
    )
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_emitted_boca_languages() == ['cc', 'cpp', 'py3']


def test_emitted_set_name_fallback_for_zero_config(monkeypatch):
    # rbx language named 'c' with NO boca extension -> contributes 'c'.
    c_lang = _mk_language('c', BocaLanguageExtension())  # empty boca ext
    env = _mk_env([c_lang])
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_emitted_boca_languages() == ['c']


def test_emitted_set_deduplicates_and_preserves_order(monkeypatch):
    env = _mk_env(
        [
            _mk_language(
                'cpp', BocaLanguageExtension(languages=['cc', 'cpp'], template='cc')
            ),
            _mk_language('cc', BocaLanguageExtension(languages=['cc'], template='cc')),
        ]
    )
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_emitted_boca_languages() == ['cc', 'cpp']


def test_emitted_set_name_fallback_skipped_when_resolved_non_empty(monkeypatch):
    # When an rbx language declares languages, name-fallback must NOT also
    # contribute the language's name. cpp -> ['cc'] should emit only ['cc'],
    # never ['cc', 'cpp'].
    env = _mk_env(
        [_mk_language('cpp', BocaLanguageExtension(languages=['cc'], template='cc'))]
    )
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_emitted_boca_languages() == ['cc']


def test_emitted_set_non_literal_name_with_no_boca_config_contributes_nothing(
    monkeypatch,
):
    # rbx language named 'python' (NOT a BocaLanguage literal) with no boca ext
    # must not be contributed by the name-fallback branch.
    env = _mk_env([_mk_language('python', BocaLanguageExtension())])
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_emitted_boca_languages() == []


def test_get_boca_template_name_uses_resolved_template(monkeypatch):
    # cpp declares languages=['cc','cpp'] with explicit template='cc'.
    # Both emitted BOCA names must source from the 'cc' template (true aliasing).
    cpp_lang = _mk_language(
        'cpp',
        BocaLanguageExtension(languages=['cc', 'cpp'], template='cc'),
    )
    env = mock.MagicMock()
    env.languages = [cpp_lang]
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)
    monkeypatch.setattr(
        boca_language_utils, 'get_language_by_extension_or_nil', lambda _: None
    )

    assert boca_language_utils.get_boca_template_name('cc') == 'cc'
    assert boca_language_utils.get_boca_template_name('cpp') == 'cc'


def test_get_boca_template_name_falls_back_to_boca_language(monkeypatch):
    # No rbx language declared -> reverse map returns the BOCA name itself,
    # and the helper must fall back to using the BOCA name as the template dir
    # rather than raising. Preserves zero-config emission.
    env = mock.MagicMock()
    env.languages = []
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)
    monkeypatch.setattr(
        boca_language_utils, 'get_language_by_extension_or_nil', lambda _: None
    )

    assert boca_language_utils.get_boca_template_name('cc') == 'cc'
