import contextvars
import pathlib
from typing import Callable, Dict, List, Optional

import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import package
from rbx.box.environment import VerificationLevel
from rbx.box.schema import LimitModifiers, LimitsProfile, TimingGroupOrigin
from rbx.box.yaml_validation import load_yaml_model
from rbx.grading.limits import Limits

profile_var = contextvars.ContextVar[Optional[str]]('profile', default=None)


def get_active_profile() -> Optional[str]:
    return profile_var.get()


class use_profile:
    def __init__(
        self, profile: Optional[str], when: Optional[Callable[[], bool]] = None
    ):
        self.profile = profile
        self.token = None
        self.when = when

    def __enter__(self):
        if self.when is None or self.when():
            self.token = profile_var.set(self.profile)

    def __exit__(self, exc_type, exc_value, traceback):
        if self.token is not None:
            profile_var.reset(self.token)


def _expand_limits_profile(
    limits_profile: LimitsProfile, root: pathlib.Path
) -> LimitsProfile:
    pkg = package.find_problem_package_or_die(root=root)
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
            res.modifiers.setdefault(language, LimitModifiers()).time = modifier.time
        if modifier.timeMultiplier is not None:
            res.modifiers.setdefault(
                language, LimitModifiers()
            ).timeMultiplier = modifier.timeMultiplier
        if modifier.memory is not None:
            res.modifiers.setdefault(
                language, LimitModifiers()
            ).memory = modifier.memory
    return res


def _get_limits_from_profile(
    language: Optional[str],
    limits_profile: LimitsProfile,
    source_profile: Optional[str],
    verification: VerificationLevel,
    root: pathlib.Path,
) -> Limits:
    limits_profile = _expand_limits_profile(limits_profile, root=root)
    return Limits(
        time=limits_profile.timelimit_for_language(language),
        memory=limits_profile.memorylimit_for_language(language),
        output=limits_profile.outputLimit,
        isDoubleTL=verification.value >= VerificationLevel.FULL.value,
        profile=source_profile,
    )


def get_saved_limits_profile(
    profile: str = 'local', root: pathlib.Path = pathlib.Path()
) -> Optional[LimitsProfile]:
    limits_path = package.get_limits_file(profile, root=root)
    if not limits_path.exists():
        return None
    return load_yaml_model(limits_path, LimitsProfile)


def get_display_limits_profile(
    profile: str, root: pathlib.Path = pathlib.Path()
) -> Optional[LimitsProfile]:
    """Resolved limits profile for presentation: expanded to absolute base +
    per-language limits (filled from the package when inheriting), with the saved
    group metadata preserved so the per-group table can be rendered."""
    saved = get_saved_limits_profile(profile, root=root)
    if saved is None:
        return None
    display = get_limits_profile(profile, root=root)
    display.groups = saved.groups
    return display


def get_package_limits_profile(root: pathlib.Path = pathlib.Path()) -> LimitsProfile:
    profile = LimitsProfile(inheritFromPackage=True)
    return _expand_limits_profile(profile, root=root)


def get_package_limits(
    verification: VerificationLevel = VerificationLevel.NONE,
    root: pathlib.Path = pathlib.Path(),
) -> Limits:
    return _get_limits_from_profile(
        language=None,
        limits_profile=get_package_limits_profile(root=root),
        source_profile=None,
        verification=verification,
        root=root,
    )


def get_limits_profile(
    profile: Optional[str] = None,
    fallback_to_package_profile: bool = True,
    root: pathlib.Path = pathlib.Path(),
) -> LimitsProfile:
    if profile is None:
        return get_package_limits_profile(root=root)
    saved_profile = get_saved_limits_profile(profile, root=root)
    if saved_profile is None:
        if fallback_to_package_profile:
            return get_package_limits_profile(root=root)
        console.console.print(
            f'[error]Limits profile [item]{profile}[/item] not found.[/error]'
        )
        raise typer.Exit(1)
    return _expand_limits_profile(saved_profile, root=root)


def get_available_profile_names(root: pathlib.Path = pathlib.Path()) -> list[str]:
    limits_dir = package.get_limits_dir(root)
    if not limits_dir.is_dir():
        return []

    profiles = []
    for path in limits_dir.glob('*.yml'):
        if path.is_file():
            profiles.append(path.stem)

    return sorted(profiles)


def get_available_limits_profiles(
    root: pathlib.Path = pathlib.Path(),
) -> Dict[str, LimitsProfile]:
    profiles = get_available_profile_names(root)
    return {name: get_limits_profile(name, root=root) for name in profiles}


def get_limits(
    language: Optional[str] = None,
    profile: Optional[str] = None,
    fallback_to_package_profile: bool = True,
    verification: VerificationLevel = VerificationLevel.NONE,
    root: pathlib.Path = pathlib.Path(),
) -> Limits:
    source_profile = None
    limits_profile = LimitsProfile(inheritFromPackage=True)
    if profile is not None:
        specified_limits_profile = get_saved_limits_profile(profile, root=root)
        if specified_limits_profile is not None:
            limits_profile = specified_limits_profile
            source_profile = profile
        elif not fallback_to_package_profile:
            console.console.print(
                f'[error]Limits profile [item]{profile}[/item] not found.[/error]'
            )
            raise typer.Exit(1)

    res = _get_limits_from_profile(
        language, limits_profile, source_profile, verification, root=root
    )
    return res


def pretty_print_profile(profile: LimitsProfile):
    console.console.print(f'[status]Time limit:[/status] {profile.timeLimit} ms')
    console.console.print(f'[status]Modifiers:[/status] {profile.modifiers}')
    if profile.inheritFromPackage:
        console.console.print('[status]Inherits from package.[/status]')


class LimitsTableRow(BaseModel):
    languages: str
    solutions: Optional[int]
    time_limit_ms: int
    source: str
    defaulted: bool = False


def build_limits_table_rows(profile: LimitsProfile) -> List[LimitsTableRow]:
    rows: List[LimitsTableRow] = []
    if profile.groups:
        for report in profile.groups:
            if report.origin == TimingGroupOrigin.ESTIMATED:
                source = (
                    f'estimated (fastest {report.fastest} / slowest {report.slowest})'
                )
            elif report.origin == TimingGroupOrigin.MULTIPLIER:
                ref = report.relativeToLanguage or 'base'
                source = f'×{report.multiplier} of {ref}'
            else:
                source = 'DEFAULTED to base'
            rows.append(
                LimitsTableRow(
                    languages=', '.join(report.languages),
                    solutions=report.solutionCount,
                    time_limit_ms=report.timeLimit,
                    source=source,
                    defaulted=report.origin == TimingGroupOrigin.DEFAULTED,
                )
            )
        return rows
    # Degraded view: base row + each per-language modifier override.
    base = profile.timeLimit or 0
    rows.append(
        LimitsTableRow(
            languages='(base)', solutions=None, time_limit_ms=base, source='base'
        )
    )
    for lang, mod in sorted(profile.modifiers.items()):
        if mod.time is not None:
            rows.append(
                LimitsTableRow(
                    languages=lang,
                    solutions=None,
                    time_limit_ms=mod.time,
                    source='override',
                )
            )
        elif mod.timeMultiplier is not None:
            rows.append(
                LimitsTableRow(
                    languages=lang,
                    solutions=None,
                    time_limit_ms=int(base * mod.timeMultiplier),
                    source=f'override (×{mod.timeMultiplier} of base)',
                )
            )
    return rows


def _source_markup(source: str) -> str:
    if source.startswith('estimated'):
        return f'[success]{source}[/success]'
    if source.startswith('×'):
        return f'[item]{source}[/item]'
    return source


def build_limits_table(profile: LimitsProfile, title: str = 'Time limits'):
    """Build a styled rich Table of the resolved per-language/group limits.

    Structural column/header styles use literal rich style strings (the resolved
    values of the project theme names: ``item`` -> ``bold blue``,
    ``status`` -> ``bright_white``, ``bstatus`` -> ``bold bright_white``) so the
    table renders correctly on any console, including non-themed ones used in
    tests. Cell-level markup still uses theme names (``warning``/``success``/
    ``item``), which resolve through the markup path.
    """
    import rich.table

    table = rich.table.Table(
        title=title,
        title_style='bold bright_white',
        header_style='bold bright_white',
        show_lines=False,
    )
    table.add_column('Languages', style='bold blue')
    table.add_column('Solutions', justify='right', style='bright_white')
    table.add_column('Time Limit', justify='right', style='bold bright_white')
    table.add_column('Source', style='bright_white')
    for row in build_limits_table_rows(profile):
        sols = '' if row.solutions is None else str(row.solutions)
        tl = f'{row.time_limit_ms} ms'
        if row.defaulted:
            table.add_row(
                f'[warning]{row.languages}[/warning]',
                f'[warning]{sols}[/warning]',
                f'[warning]{tl}[/warning]',
                f'[warning]⚠ {row.source}[/warning]',
            )
        else:
            table.add_row(row.languages, sols, tl, _source_markup(row.source))
    return table


def render_limits_table(profile: LimitsProfile, title: str = 'Time limits') -> None:
    console.console.print(build_limits_table(profile, title))
