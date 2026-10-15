import functools
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    import iso639


@functools.cache
def _get_lowercase_name_mapping() -> Dict[str, 'iso639.Lang']:
    import iso639

    res = {}
    for lang in iso639.iter_langs():
        res[lang.name.lower()] = lang
    return res


def _get_lang_name(lang: str) -> str:
    mapping = _get_lowercase_name_mapping()
    if lang.lower() in mapping:
        return mapping[lang.lower()].name
    return lang


def code_to_lang(lang: str) -> str:
    import iso639

    return iso639.Lang(lang).name.lower()


def code_to_langs(langs: List[str]) -> List[str]:
    return [code_to_lang(lang) for lang in langs]


# Every ISO 639-1 code, as `iso639` knows them (pinned by `lang_test.py`).
# Statement languages are checked on every package load, and these are what
# they almost always are; answering from here spares importing `iso639` and
# loading its data, 40-80ms on every `rbx st b`.
ISO_639_1_CODES = frozenset(
    """
    aa ab ae af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co
    cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd
    gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv
    ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg
    mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os
    pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss
    st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo
    wa wo xh yi yo za zh zu
    """.split()
)


@functools.cache
def is_valid_lang_code(lang: str) -> bool:
    if lang in ISO_639_1_CODES:
        return True
    import iso639

    return iso639.is_language(lang)


def lang_to_code(lang: str) -> str:
    import iso639

    return iso639.Lang(_get_lang_name(lang)).pt1


def langs_to_code(langs: List[str]) -> List[str]:
    return [lang_to_code(lang) for lang in langs]
