import typing

from rbx.box.environment import get_environment, get_language
from rbx.box.packaging.boca.extension import BocaLanguage, BocaLanguageExtension


def get_rbx_language_from_boca_language(boca_language: BocaLanguage) -> str:
    for language in get_environment().languages:
        language_extension = language.get_extension_or_default(
            language.name, BocaLanguageExtension
        )
        if language_extension.bocaLanguage == boca_language:
            return language.name
    return boca_language


def get_boca_language_from_rbx_language(rbx_language: str) -> BocaLanguage:
    language = get_language(rbx_language)
    language_extension = language.get_extension_or_default(
        'boca', BocaLanguageExtension
    )
    if language_extension.bocaLanguage:
        return typing.cast(BocaLanguage, language_extension.bocaLanguage)
    if rbx_language.lower() in typing.get_args(BocaLanguage):
        return typing.cast(BocaLanguage, rbx_language.lower())
    raise ValueError(f'No Boca language found for Rbx language {rbx_language}')
