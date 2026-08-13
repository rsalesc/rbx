import typing

from rbx.box.environment import get_environment, get_language_or_nil
from rbx.box.packaging.moj_next.extension import MojLanguage, MojLanguageExtension

# MOJ unified Python under `py`; `py2`/`py3` survive only as legacy spellings, and the
# server normalizes them away. Normalizing here keeps `.moj-meta.json` canonical.
_LEGACY_ALIASES = {'py2': 'py', 'py3': 'py'}


def normalize_moj_language(moj_language: str) -> str:
    """Canonicalize a MOJ language id the way the server does: lowercased, with the
    legacy `py2`/`py3` spellings folded into `py`."""
    lowered = moj_language.lower()
    return _LEGACY_ALIASES.get(lowered, lowered)


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


def get_moj_language_from_rbx_language(rbx_language: str) -> typing.Optional[str]:
    """The MOJ language id an rbx language maps to, or ``None`` when it has no
    counterpart. Mirrors ``get_boca_language_from_rbx_language``, but returns ``None``
    instead of raising: a language with no MOJ id is skipped, not an error."""
    language = get_language_or_nil(rbx_language)
    if language is not None:
        extension = language.get_extension_or_default('moj', MojLanguageExtension)
        primary = extension.primary_language
        if primary:
            return normalize_moj_language(primary)
    # Name fallback, matching get_emitted_moj_languages.
    normalized = normalize_moj_language(rbx_language)
    if normalized in typing.get_args(MojLanguage):
        return normalized
    return None


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
