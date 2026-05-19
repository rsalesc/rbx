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


def get_boca_template_name(boca_language: BocaLanguage) -> str:
    """Return the on-disk BOCA template dir name (under rbx/resources/packagers/boca/)
    to source per-language scripts from when emitting `boca_language`. Falls back to
    `boca_language` itself when no rbx language declares it (zero-config / env-level
    path)."""
    rbx_language_name = get_rbx_language_from_boca_language(boca_language)
    rbx_language = next(
        (
            lang
            for lang in get_environment().languages
            if lang.name == rbx_language_name
        ),
        None,
    )
    if rbx_language is None:
        return boca_language
    template = rbx_language.get_extension_or_default(
        'boca', BocaLanguageExtension
    ).resolved_boca_template
    return template or boca_language


def get_emitted_boca_languages() -> typing.List[BocaLanguage]:
    """Return the ordered, deduplicated set of BOCA languages to emit per-language
    script dirs for. Computed as a union across two passes:

    1. Per-rbx-language pass — for each language in env.languages:
       - If resolved_boca_languages is non-empty, contribute every entry.
       - Otherwise (zero-config name fallback): if the rbx language name is itself
         a BocaLanguage literal, contribute it.
    2. Env-level pass — append every entry from extensions.boca.languages
       (back-compat for envs that still set the legacy allowlist).

    Order is preserved: entries appear in the order first seen.
    """
    seen: typing.Dict[str, None] = {}
    env = get_environment()
    boca_literals = set(typing.get_args(BocaLanguage))

    for language in env.languages:
        language_extension = language.get_extension_or_default(
            'boca', BocaLanguageExtension
        )
        resolved = language_extension.resolved_boca_languages
        if resolved:
            for boca_lang in resolved:
                seen.setdefault(boca_lang, None)
        elif language.name in boca_literals:
            # Name-fallback safety net for zero-config users.
            seen.setdefault(language.name, None)

    if env.extensions is not None and env.extensions.boca is not None:
        for boca_lang in env.extensions.boca.languages:
            seen.setdefault(boca_lang, None)

    return typing.cast(typing.List[BocaLanguage], list(seen.keys()))
