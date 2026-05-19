import typing

from rbx.box.environment import (
    get_environment,
    get_language,
    get_language_by_extension_or_nil,
)
from rbx.box.packaging.boca.extension import BocaLanguage, BocaLanguageExtension


def get_rbx_language_from_boca_language(boca_language: BocaLanguage) -> str:
    # First by BOCA language membership in the rbx language's resolved targets.
    for language in get_environment().languages:
        language_extension = language.get_extension_or_default(
            'boca', BocaLanguageExtension
        )
        if boca_language in language_extension.resolved_boca_languages:
            return language.name
    # Then by rbx language extension.
    language_by_extension = get_language_by_extension_or_nil(boca_language)
    if language_by_extension is not None:
        return language_by_extension.name
    # Then by rbx language name.
    return boca_language


def get_boca_language_from_rbx_language(rbx_language: str) -> BocaLanguage:
    language = get_language(rbx_language)
    language_extension = language.get_extension_or_default(
        'boca', BocaLanguageExtension
    )
    primary = language_extension.primary_boca_language
    if primary:
        return typing.cast(BocaLanguage, primary)
    env = get_environment()
    if (
        env.extensions is not None
        and env.extensions.boca is not None
        and rbx_language.lower() in env.extensions.boca.languages
    ):
        return typing.cast(BocaLanguage, rbx_language.lower())
    if rbx_language.lower() in typing.get_args(BocaLanguage):
        return typing.cast(BocaLanguage, rbx_language.lower())
    raise ValueError(f'No Boca language found for Rbx language {rbx_language}')
