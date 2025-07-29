import os
from typing import Optional

import typer

from rbx import console, utils
from rbx.box import package
from rbx.box.environment import VerificationLevel
from rbx.box.schema import LimitsProfile
from rbx.grading.limits import Limits


def _get_timelimit_for_language(
    limits_profile: LimitsProfile, language: Optional[str]
) -> int:
    assert limits_profile.timeLimit is not None
    res = limits_profile.timeLimit
    if language is not None and language in limits_profile.modifiers:
        modifier = limits_profile.modifiers[language]
        if modifier.time is not None:
            res = modifier.time
        if modifier.timeMultiplier is not None:
            res = int(res * float(modifier.timeMultiplier))
    if 'RBX_TIME_MULTIPLIER' in os.environ:
        res = int(res * float(os.environ['RBX_TIME_MULTIPLIER']))
    return res


def _get_memorylimit_for_language(
    limits_profile: LimitsProfile, language: Optional[str]
) -> int:
    assert limits_profile.memoryLimit is not None
    res = limits_profile.memoryLimit
    if language is None:
        return res
    if language not in limits_profile.modifiers:
        return res
    modifier = limits_profile.modifiers[language]
    if modifier.memory is not None:
        return modifier.memory
    return res


def _expand_limits_profile(limits_profile: LimitsProfile) -> LimitsProfile:
    pkg = package.find_problem_package_or_die()
    res = LimitsProfile(
        timeLimit=pkg.timeLimit,
        memoryLimit=pkg.memoryLimit,
        outputLimit=pkg.outputLimit,
    )
    for language, modifier in pkg.modifiers.items():
        res.modifiers[language] = modifier.model_copy(deep=True)

    if limits_profile.inheritFromPackage:
        return res

    time_is_overridden = limits_profile.timeLimit is not None
    memory_is_overridden = limits_profile.memoryLimit is not None
    output_is_overridden = limits_profile.outputLimit is not None
    if time_is_overridden:
        res.timeLimit = limits_profile.timeLimit
    if memory_is_overridden:
        res.memoryLimit = limits_profile.memoryLimit
    if output_is_overridden:
        res.outputLimit = limits_profile.outputLimit

    for modifier in res.modifiers.values():
        # Clean up modifiers coming from the package that are not overridden
        # by the base limits profile.
        if time_is_overridden:
            modifier.time = None
        if memory_is_overridden:
            modifier.memory = None

    for language, modifier in limits_profile.modifiers.items():
        if modifier.time is not None:
            res.modifiers[language].time = modifier.time
        if modifier.timeMultiplier is not None:
            res.modifiers[language].timeMultiplier = modifier.timeMultiplier
        if modifier.memory is not None:
            res.modifiers[language].memory = modifier.memory
    return res


def _get_limits_from_profile(
    language: Optional[str],
    limits_profile: LimitsProfile,
    source_profile: Optional[str],
    verification: VerificationLevel,
) -> Limits:
    limits_profile = _expand_limits_profile(limits_profile)
    return Limits(
        time=_get_timelimit_for_language(limits_profile, language),
        memory=_get_memorylimit_for_language(limits_profile, language),
        output=limits_profile.outputLimit,
        isDoubleTL=verification.value >= VerificationLevel.FULL.value,
        profile=source_profile,
    )


def get_limits_profile(profile: str = 'local') -> Optional[LimitsProfile]:
    limits_path = package.get_limits_file(profile)
    if not limits_path.exists():
        return None
    return utils.model_from_yaml(LimitsProfile, limits_path.read_text())


def get_package_limits_profile(
    verification: VerificationLevel = VerificationLevel.NONE,
) -> Limits:
    profile = LimitsProfile(inheritFromPackage=True)
    return _get_limits_from_profile(
        language=None,
        limits_profile=profile,
        source_profile=None,
        verification=verification,
    )


def get_limits(
    language: Optional[str] = None,
    profile: Optional[str] = None,
    fallback_to_package_profile: bool = True,
    verification: VerificationLevel = VerificationLevel.NONE,
) -> Limits:
    source_profile = None
    limits_profile = LimitsProfile(inheritFromPackage=True)
    if profile is not None:
        specified_limits_profile = get_limits_profile(profile)
        if specified_limits_profile is not None:
            limits_profile = specified_limits_profile
            source_profile = profile
        elif not fallback_to_package_profile:
            console.console.print(
                f'[error]Limits profile [item]{profile}[/item] not found.[/error]'
            )
            raise typer.Exit(1)

    res = _get_limits_from_profile(
        language, limits_profile, source_profile, verification
    )
    return res
