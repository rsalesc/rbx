import functools
from typing import Dict, List

import iso639


@functools.cache
def _get_lowercase_name_mapping() -> Dict[str, iso639.Lang]:
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
    return iso639.Lang(lang).name.lower()


def code_to_langs(langs: List[str]) -> List[str]:
    return [code_to_lang(lang) for lang in langs]


@functools.cache
def is_valid_lang_code(lang: str) -> bool:
    return iso639.is_language(lang)


def lang_to_code(lang: str) -> str:
    return iso639.Lang(_get_lang_name(lang)).pt1


def langs_to_code(langs: List[str]) -> List[str]:
    return [lang_to_code(lang) for lang in langs]
