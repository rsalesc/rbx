import typing

from rbx.box.environment import get_environment
from rbx.box.packaging.moj_next.extension import MojLanguage, MojLanguageExtension


def get_rbx_language_from_moj_language(moj_language: str) -> typing.Optional[str]:
    """The rbx language declaring ``moj_language``, or ``None`` when none does."""
    for language in get_environment().languages:
        extension = language.get_extension_or_default('moj', MojLanguageExtension)
        if moj_language in extension.resolved_languages:
            return language.name
    return None


def get_moj_language_extension(moj_language: str) -> MojLanguageExtension:
    """The extension of the rbx language declaring ``moj_language``, or an empty one
    when no rbx language claims it."""
    rbx_name = get_rbx_language_from_moj_language(moj_language)
    if rbx_name is None:
        return MojLanguageExtension()
    for language in get_environment().languages:
        if language.name == rbx_name:
            return language.get_extension_or_default('moj', MojLanguageExtension)
    return MojLanguageExtension()


def get_moj_template_name(moj_language: str) -> str:
    """The on-disk template dir to source scripts from when emitting
    ``moj_language``. Falls back to the id itself when no rbx language claims it."""
    return get_moj_language_extension(moj_language).resolved_template or moj_language


def get_emitted_moj_languages() -> typing.List[MojLanguage]:
    """The ordered, deduplicated MOJ language ids to emit script dirs for.

    For each rbx language in ``env.languages``: contribute every entry of its `moj`
    extension's ``languages``, or -- for a zero-config language declaring none -- its
    own name when that name is itself a MOJ id. Order is first-seen.
    """
    seen: typing.Dict[str, None] = {}
    moj_literals = set(typing.get_args(MojLanguage))

    for language in get_environment().languages:
        extension = language.get_extension_or_default('moj', MojLanguageExtension)
        resolved = extension.resolved_languages
        if resolved:
            for moj_lang in resolved:
                seen.setdefault(moj_lang, None)
        elif language.name in moj_literals:
            # Name-fallback safety net for zero-config users.
            seen.setdefault(language.name, None)

    return typing.cast(typing.List[MojLanguage], list(seen.keys()))
