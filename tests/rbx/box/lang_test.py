import iso639
import pytest

from rbx.box import lang


def test_iso_639_1_codes_match_iso639():
    assert lang.ISO_639_1_CODES == {lg.pt1 for lg in iso639.iter_langs() if lg.pt1}


@pytest.mark.parametrize('code', ['en', 'pt', 'zh', 'por', 'eng', 'xx', 'EN', ''])
def test_is_valid_lang_code_agrees_with_iso639(code):
    lang.is_valid_lang_code.cache_clear()
    assert lang.is_valid_lang_code(code) == iso639.is_language(code)
