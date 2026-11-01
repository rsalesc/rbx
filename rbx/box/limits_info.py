import contextvars
import functools
import pathlib
import re
from typing import Callable, Dict, List, Optional

import typer
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import package, timing_edit
from rbx.box.environment import VerificationLevel
from rbx.box.schema import (
    LimitModifiers,
    LimitsProfile,
    TimingGroupOrigin,
    TimingGroupReport,
)
from rbx.box.yaml_validation import load_yaml_model
from rbx.grading.limits import Limits

profile_var = contextvars.ContextVar[Optional[str]]('profile', default=None)


def get_active_profile() -> Optional[str]:
    return profile_var.get()


# The profile a solution run falls back to when none was named. `rbx time` writes
# this one by default, so it is the profile of the *default* workflow rather than
# a fallback for an unusual one.
DEFAULT_RUN_PROFILE = 'local'


def get_run_profile() -> str:
    """The profile a solution run is actually judged against.

    Deliberately not `get_active_profile()`, which is None when nothing was
    named: a plain `rbx run` still resolves its limits from `local`. Every
    consumer that asks "which profile is this run using?" -- limit resolution,
    and the staleness check that has to agree with it -- must go through here, or
    the two answer differently for the commonest invocation there is.
    """
    return get_active_profile() or DEFAULT_RUN_PROFILE


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
    time = limits_profile.timelimit_for_language(language)
    return Limits(
        time=time,
        # The declared TL is preserved here so it survives later enforcement
        # nulling (see ``get_limits_for_language``) and stays available to
        # display/reporting.
        configuredTime=time,
        memory=limits_profile.memorylimit_for_language(language),
        output=limits_profile.outputLimit,
        isDoubleTL=verification.value >= VerificationLevel.FULL.value,
        profile=source_profile,
    )


@functools.lru_cache(maxsize=64)
def _parse_limits_profile(limits_path: pathlib.Path, source: str) -> LimitsProfile:
    """Parse one limits profile, memoized on the file's own contents.

    ``source`` is in the key -- not the path plus an mtime -- so the cache is
    incapable of going stale: a rewritten profile is a different key, and two
    packages whose profiles happen to be byte-identical share a result that is
    identical anyway. That matters because the writers here are in-process
    (``rbx timing``, the TUI limits editor) and the key would otherwise need an
    invalidation hook at every one of them.

    The path is kept in the key only so diagnostics raised by
    ``load_yaml_model`` name the right file; it does not affect the value.
    """
    return load_yaml_model(limits_path, LimitsProfile)


def get_saved_limits_profile(
    profile: str = 'local', root: pathlib.Path = pathlib.Path()
) -> Optional[LimitsProfile]:
    """The profile saved under ``.limits/<profile>.yml``, or None if there is none.

    ``rbx run`` asks for this once per testcase, where the YAML parse plus
    pydantic validation dominated the call (#658); the read below is roughly two
    orders of magnitude cheaper than the parse it now usually replaces.

    The returned model is shared between callers -- treat it as read-only.
    """
    limits_path = package.get_limits_file(profile, root=root)
    try:
        source = limits_path.read_text()
    except OSError:
        # Missing profile: the overwhelmingly common case, and the one the
        # per-testcase path hits on a package that never ran `rbx timing`.
        return None
    return _parse_limits_profile(limits_path, source)


SOLUTIONS_HEADER = (
    '# What each solution measured during the estimation, for `rbx time --edit`.\n'
    '# Presentation-only: never used to resolve a limit.\n'
)


def profile_to_yaml(profile: LimitsProfile) -> str:
    """A limits profile as written to `.limits/<name>.yml`.

    The per-solution timings go last, one solution per line, under a comment
    saying what they are for: they are the longest and least read part of the
    file, and a setter opening it is there for the limits above them.
    """
    import yaml

    if not profile.solutions:
        return utils.model_to_yaml(profile)
    head = profile.model_copy()
    head.solutions = None
    entries = [
        # The role in the spelling a setter writes in `problem.rbx.yml`
        # (`inference: lower`); `InferenceRole` reads either back.
        {
            **timing.model_dump(mode='json', exclude_none=True),
            'role': timing.role.value.lower(),
        }
        for timing in profile.solutions
    ]
    tail = yaml.dump(
        {'solutions': entries},
        Dumper=getattr(yaml, 'CSafeDumper', yaml.SafeDumper),
        sort_keys=False,
        allow_unicode=True,
        # Flow style for scalar-only collections: each entry on one line.
        default_flow_style=None,
        width=10_000,
    )
    return utils.model_to_yaml(head) + '\n' + SOLUTIONS_HEADER + tail


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
    display.baseEstimate = saved.baseEstimate
    # The table judges a limit set by hand against the ratios it was estimated
    # with; the expansion above starts from the package and does not carry them.
    display.multipliers = saved.multipliers
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


# Prefix marking the leftover group's languages cell; explained in the table
# caption. Kept as one constant so the marker and its footer can't drift apart.
LEFTOVER_MARKER = '* '


class LimitsTableRow(BaseModel):
    languages: str
    solutions: Optional[int]
    time_limit_ms: int
    source: str
    defaulted: bool = False
    is_leftover: bool = False
    # Slow solutions of this group confirmed to be too slow for its limit.
    confirmed_upper: List[str] = []
    # Slow solutions of this group that finished within its limit times
    # `timeLimitToTle`, so they do not respect the upper bound.
    violating_upper: List[str] = []
    # Set when the group's own accepted solutions do not fit its time limit:
    # the smallest limit they allow, and the one that takes the longest.
    lower_violation_ms: Optional[int] = None
    lower_violation_solution: Optional[str] = None
    # The group's slowest accepted solution, to tell a limit its solutions
    # outright fail from one they merely clear without the configured margin.
    slowest_ms: Optional[int] = None
    # The limit was set by hand (`rbx time --edit`) away from this estimate.
    adjusted_from: Optional[int] = None
    # Slow solutions only confirmed too slow at the estimate, below this limit.
    unverified_upper: List[str] = []
    # The limit judged against the group's recorded evidence; absent on rows
    # that carry none (the degraded per-modifier view).
    check: Optional[timing_edit.GroupCheck] = None

    @property
    def violates_lower(self) -> bool:
        """Whether this row's limit is below what its own accepted solutions
        allow -- a limit no good solution of the group can be judged under as
        the setter intended."""
        return self.lower_violation_ms is not None

    @property
    def rejects_own_solutions(self) -> bool:
        """Whether the group's own accepted solutions do not pass at all, as
        opposed to passing without the configured margin."""
        return self.slowest_ms is not None and self.slowest_ms > self.time_limit_ms


def _bounds_note(report: TimingGroupReport) -> str:
    """The range the group's limit had to fit in, and who set each side.

    The lower bound is shown only when a solution set it: a derived one merely
    restates the limit the multiplier source already names.

    The solution paths land here verbatim: this is a data field, and escaping
    them for rich would bake one renderer's syntax into it. ``build_limits_table``
    escapes the whole cell instead.
    """
    parts: List[str] = []
    lower = report.lowerBound
    if lower is not None and lower.solution is not None:
        parts.append(f'≥ {lower.value} ms from {lower.solution}')
    upper = report.upperBound
    if upper is not None:
        note = f'≤ {upper.value} ms'
        if upper.solution is not None:
            note += f' from {upper.solution}'
        parts.append(note)
    if not parts:
        return ''
    return ' [' + ', '.join(parts) + ']'


def _violation_note(report: TimingGroupReport) -> str:
    """What the group's own accepted solutions need, when its limit denies it.

    Spelled out beside the limit rather than left to the caption: the caption
    counts the groups, this says which row and by how much.
    """
    violation = report.lowerViolation
    if violation is None:
        return ''
    note = f'needs ≥ {violation.value} ms'
    if violation.solution is not None and report.slowest is not None:
        note += f' ({violation.solution} takes {report.slowest} ms)'
    elif violation.solution is not None:
        note += f' from {violation.solution}'
    return f' ⚠ {note}'


def _report_source(report: TimingGroupReport) -> str:
    if report.origin == TimingGroupOrigin.ESTIMATED:
        source = (
            f'estimated (fastest {report.fastest} ms / slowest {report.slowest} ms)'
        )
    elif report.origin == TimingGroupOrigin.MULTIPLIER:
        ref = report.relativeToLanguage or 'base'
        source = f'×{report.multiplier} of {ref}'
        if report.increment is not None:
            source += f' + {report.increment} ms'
    else:
        source = 'DEFAULTED to base'
    return source + _bounds_note(report) + _violation_note(report)


def _row_from_report(
    report: TimingGroupReport,
    languages: str,
    profile: LimitsProfile,
    time_limit: Optional[int] = None,
) -> LimitsTableRow:
    """One table row out of a group report.

    A limit set by hand is judged afresh against the report's evidence: what was
    recorded about the *estimated* limit -- which slow solutions it confirmed,
    which ones broke it -- is not what holds for the limit now in force. A row
    left at its estimate keeps the recorded data verbatim.
    """
    check = timing_edit.assess(
        report,
        profile.multipliers,
        time_limit,
        solutions=timing_edit.group_solutions(profile, report),
    )
    source = _report_source(report)
    validation = report.upperValidation
    confirmed = list(validation.confirmed) if validation is not None else []
    violating = (
        [bound.solution for bound in validation.violating if bound.solution]
        if validation is not None
        else []
    )
    lower_violation = report.lowerViolation
    unverified: List[str] = []
    adjusted_from = check.estimated
    if adjusted_from is not None:
        source += f' · set by hand, estimated {adjusted_from} ms'
        confirmed = list(check.confirmed)
        violating = [bound.solution for bound in check.violating if bound.solution]
        unverified = list(check.unverified)
    return LimitsTableRow(
        languages=languages,
        solutions=report.solutionCount,
        time_limit_ms=check.time_limit,
        source=source,
        defaulted=report.origin == TimingGroupOrigin.DEFAULTED,
        is_leftover=report.isLeftover,
        confirmed_upper=confirmed,
        violating_upper=violating,
        lower_violation_ms=lower_violation.value if lower_violation else None,
        lower_violation_solution=(
            lower_violation.solution if lower_violation else None
        ),
        slowest_ms=report.slowest,
        adjusted_from=adjusted_from,
        unverified_upper=unverified,
        check=check,
    )


def _base_row(profile: LimitsProfile) -> LimitsTableRow:
    """The fallback row: the base time limit applied when nothing else does.

    When the profile was estimated, the base is itself pooled across every
    solution, so it carries the same ``estimated (fastest / slowest)`` provenance
    as the group rows; otherwise it is just the configured base.
    """
    if profile.baseEstimate is not None:
        row = _row_from_report(
            profile.baseEstimate,
            '(base)',
            profile,
            time_limit=profile.timeLimit or 0,
        )
        # The base is a fallback, never a defaulted group or the leftover one.
        row.defaulted = False
        row.is_leftover = False
        return row
    return LimitsTableRow(
        languages='(base)',
        solutions=None,
        time_limit_ms=profile.timeLimit or 0,
        source='base',
    )


def build_limits_table_rows(profile: LimitsProfile) -> List[LimitsTableRow]:
    rows: List[LimitsTableRow] = []
    if profile.groups:
        for report in profile.groups:
            languages = ', '.join(report.languages)
            if report.isLeftover:
                languages = f'{LEFTOVER_MARKER}{languages}'
            rows.append(_row_from_report(report, languages, profile))
        # Leftover group is shown first; stable sort keeps the rest in order.
        rows.sort(key=lambda r: not r.is_leftover)
        # Base (fallback) row always leads the table.
        return [_base_row(profile), *rows]
    # Degraded view: base row + each per-language modifier override.
    base = profile.timeLimit or 0
    rows.append(_base_row(profile))
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


# Matches a time figure like "1000 ms" so the number can be highlighted while
# the unit is dimmed; applied uniformly to the Time Limit column and to the
# fastest/slowest figures inside the Source column. The guards keep it off
# solution names, which the Source column also carries: `tle_2000ms.cpp` is an
# ordinary name for a solution in a package about timing.
_MS_PATTERN = re.compile(r'(?<![\w.])(\d+)\s*ms(?![\w.])')


def _highlight_ms(text: str) -> str:
    """Colorize every "<number> ms" in ``text``: the figure pops in the
    ``timelimit`` color, the unit is dimmed so the number stands out beside it."""
    return _MS_PATTERN.sub(r'[timelimit]\1[/timelimit] [dim]ms[/dim]', text)


def _subject(rows: List[LimitsTableRow]) -> str:
    """Name the solutions a caption is about, or count their groups when the
    rows carry no name. Always phrased so a singular verb follows."""
    named = [
        row.lower_violation_solution for row in rows if row.lower_violation_solution
    ]
    if not named:
        plural = 's' if len(rows) > 1 else ''
        return f'The slowest accepted solution of {len(rows)} group{plural} is'
    if len(named) == 1:
        return f'{named[0]} is'
    return f'Each of {", ".join(named)} is'


def _range_text(check: timing_edit.GroupCheck) -> str:
    if check.min_ms is not None and check.max_ms is not None:
        return f'{check.min_ms}–{check.max_ms} ms'
    if check.min_ms is not None:
        return f'≥ {check.min_ms} ms'
    if check.max_ms is not None:
        return f'≤ {check.max_ms} ms'
    return ''


def check_cell(check: Optional[timing_edit.GroupCheck]) -> str:
    """The Check column: whether the limit fits what the group's solutions
    allow, and the range they allow it in. Rich markup."""
    if check is None:
        return ''
    allowed = _range_text(check)
    if check.rejects_own_solutions:
        status = '[error]✗ AC fails[/error]'
    elif check.breaks_upper:
        status = '[error]✗ slow passes[/error]'
    elif check.below_min:
        status = '[warning]⚠ thin margin[/warning]'
    elif check.unverified:
        status = f'[warning]? {len(check.unverified)} unverified[/warning]'
    else:
        status = '[success]✓[/success]'
    if not allowed:
        return status
    return f'{status} [dim]{allowed}[/dim]'


def build_limits_table(
    profile: LimitsProfile, title: str = 'Time limits', show_check: bool = False
):
    """Build a styled rich Table of the resolved per-language/group limits.

    Structural column/header styles use literal rich style strings (the resolved
    values of the project theme names: ``item`` -> ``bold blue``,
    ``status`` -> ``bright_white``, ``bstatus`` -> ``bold bright_white``) so the
    table renders correctly on any console, including non-themed ones used in
    tests. Cell-level markup still uses theme names (``warning``/``success``/
    ``item``), which resolve through the markup path.
    """
    import rich.markup
    import rich.table

    rows = build_limits_table_rows(profile)
    adjusted = [row for row in rows if row.adjusted_from is not None]
    # Shown whenever a limit was set by hand, where it is the only place that
    # says whether the hand-set limit still holds; an untouched estimate keeps
    # the table it always had.
    show_check = show_check or bool(adjusted)
    caption_lines: List[str] = []
    if any(row.is_leftover for row in rows):
        caption_lines.append(
            f'{LEFTOVER_MARKER}leftover: languages not assigned to a group, '
            'pooled together (default).'
        )
    if any(row.defaulted for row in rows):
        caption_lines.append(
            '[warning]⚠ DEFAULTED: no accepted solutions and no whenEmpty rule; '
            'fell back to the base time limit.[/warning]'
        )
    # The grouping handed a group a limit its own good solutions cannot meet --
    # the group's limit was derived from elsewhere and its own measurements were
    # never consulted. Split by severity: a limit its solutions outright fail is
    # a different problem from one they clear without the configured margin, and
    # collapsing the two would understate the first.
    derived = [row for row in rows if row.adjusted_from is None]
    rejecting = [
        row for row in derived if row.violates_lower and row.rejects_own_solutions
    ]
    if rejecting:
        caption_lines.append(
            f'[error]⚠ {_subject(rejecting)} accepted, but does not pass at the '
            f'time limit of its own group, which was derived from another group '
            f'instead of estimated from it. Regroup, or drop the reference so the '
            f'group is estimated from its own solutions.[/error]'
        )
    thin = [
        row for row in derived if row.violates_lower and not row.rejects_own_solutions
    ]
    if thin:
        caption_lines.append(
            f'[warning]⚠ {_subject(thin)} accepted and passes at the time limit of '
            f'its own group, but without the margin acToTimeLimit asks for, because '
            f'the limit was derived from another group. See the Source column for '
            f'what each group needs.[/warning]'
        )
    # The same two cases for a limit the setter chose, which nobody derived.
    hand_rejecting = [
        row for row in adjusted if row.violates_lower and row.rejects_own_solutions
    ]
    if hand_rejecting:
        caption_lines.append(
            f'[error]⚠ {_subject(hand_rejecting)} accepted, but does not pass at '
            f'the time limit set by hand for its group.[/error]'
        )
    hand_thin = [
        row for row in adjusted if row.violates_lower and not row.rejects_own_solutions
    ]
    if hand_thin:
        caption_lines.append(
            f'[warning]⚠ {_subject(hand_thin)} accepted and passes at the time '
            f'limit set by hand for its group, but without the margin '
            f'acToTimeLimit asks for.[/warning]'
        )
    above = [row for row in adjusted if row.check is not None and row.check.above_max]
    if above:
        plural = 's' if len(above) > 1 else ''
        caption_lines.append(
            f'[error]⚠ The time limit set by hand for {len(above)} group{plural} '
            f'is above what its solutions expected to be too slow allow: they '
            f'finish within it times timeLimitToTle.[/error]'
        )
    unverified = {solution for row in rows for solution in row.unverified_upper}
    if unverified:
        plural = 's' if len(unverified) > 1 else ''
        caption_lines.append(
            f'[warning]? {len(unverified)} solution{plural} expected to be too slow '
            f'{"were" if plural else "was"} only confirmed too slow for the '
            f'estimated limit, which is below the one set by hand. Run the '
            f'solutions against this profile to check.[/warning]'
        )
    # Terse on purpose: the validation run already reported each offending
    # solution by name, with what to do about it. This only says the table's
    # limits were checked, and where to find against what.
    violating = {solution for row in rows for solution in row.violating_upper}
    if violating:
        plural = 's' if len(violating) > 1 else ''
        caption_lines.append(
            f'[error]⚠ {len(violating)} solution{plural} expected to be too slow '
            f'finished within the estimated limit, so the upper bound is not '
            f'respected; named under upperValidation in the limits profile.[/error]'
        )
    confirmed = {solution for row in rows for solution in row.confirmed_upper}
    if confirmed:
        plural = 's' if len(confirmed) > 1 else ''
        caption_lines.append(
            f'[success]✓ {len(confirmed)} solution{plural} expected to be too slow '
            f'{"were" if plural else "was"} confirmed too slow for the estimated '
            f'limit.[/success]'
        )
    caption = '\n'.join(caption_lines) if caption_lines else None
    table = rich.table.Table(
        title=title,
        title_style='bold bright_white',
        header_style='bold bright_white',
        caption=caption,
        caption_style='bright_black',
        show_lines=False,
    )
    table.add_column('Languages', style='bold blue')
    table.add_column('Solutions', justify='right', style='bright_white')
    table.add_column('Time Limit', justify='right', style='bold bright_white')
    table.add_column('Source', style='bright_white')
    if show_check:
        table.add_column('Check')
    for row in rows:
        extra = [check_cell(row.check)] if show_check else []
        sols = '' if row.solutions is None else str(row.solutions)
        tl = f'{row.time_limit_ms} ms'
        # The Source cell carries setter-controlled text (solution paths), and
        # the cells below are rendered as markup. Escaping happens here, at the
        # one place that renders it, so `row.source` stays the real value for
        # any other consumer -- and before the styling helpers, whose own markup
        # must survive.
        source = rich.markup.escape(row.source)
        if row.violates_lower:
            # Red beats the defaulted yellow: a limit the group's own solutions
            # cannot meet is a broken grouping, not a fallback.
            style = 'error' if row.rejects_own_solutions else 'warning'
            table.add_row(
                f'[{style}]{row.languages}[/{style}]',
                f'[{style}]{sols}[/{style}]',
                f'[{style}]{tl}[/{style}]',
                f'[{style}]{source}[/{style}]',
                *extra,
            )
        elif row.defaulted:
            # Defaulted rows are warnings: the yellow signals the fallback and
            # deliberately overrides the per-figure time highlight.
            table.add_row(
                f'[warning]{row.languages}[/warning]',
                f'[warning]{sols}[/warning]',
                f'[warning]{tl}[/warning]',
                f'[warning]⚠ {source}[/warning]',
                *extra,
            )
        else:
            table.add_row(
                row.languages,
                sols,
                _highlight_ms(tl),
                _highlight_ms(_source_markup(source)),
                *extra,
            )
    return table


def render_limits_table(
    profile: LimitsProfile, title: str = 'Time limits', show_check: bool = False
) -> None:
    console.console.print(build_limits_table(profile, title, show_check=show_check))
