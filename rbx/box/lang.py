import functools
from typing import List

import iso639

from rbx import console


def code_to_langs(langs: List[str]) -> List[str]:
    return [iso639.Language.from_part1(lang).name.lower() for lang in langs]


@functools.cache
def is_valid_lang_code(lang: str) -> bool:
    try:
        code_to_langs([lang])
    except iso639.LanguageNotFoundError:
        console.console.print(
            f'[warning]Language [item]{lang}[/item] is being skipped because it is not a iso639 language.[/warning]'
        )
        return False

    return True


def langs_to_code(langs: List[str]) -> List[str]:
    return [iso639.Language.from_name(lang).part1 for lang in langs]
