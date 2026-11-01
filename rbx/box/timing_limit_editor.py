"""`rbx time --edit`: tune the time limits of an estimated profile by hand.

The editor runs nothing. Every limit it offers is judged against the evidence the
estimate left in the profile (`rbx.box.timing_edit`), on every keystroke, and the
preview is the same limits table `rbx time` prints -- built the way the group
picker builds its own (`timing.build_preview_renderer`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional

import typer

from rbx import console
from rbx.box import estimation_checksum, limits_info, package, timing_edit
from rbx.box.formatting import href
from rbx.box.schema import InferenceRole, LimitsProfile, TimingGroupReport

if TYPE_CHECKING:
    from prompt_toolkit.formatted_text import AnyFormattedText

# Step used when the profile records no `timeResolution` (a formula estimate).
DEFAULT_STEP_MS = 100


def legend_lines(step: int) -> List[str]:
    return [
        'Adjust the time limit of each group; the preview checks it against what '
        'the estimate measured.',
        '',
        f'↑/↓ or k/j move · ←/→, h/l or -/+ step {step} ms · type digits + enter '
        'to set · r back to estimate · R undo all · enter save · q cancel',
    ]


class LimitEditorState:
    """Rows are the base limit (`None`) followed by each group of the profile."""

    def __init__(self, profile: LimitsProfile):
        self.initial = profile.model_copy(deep=True)
        self.profile = profile.model_copy(deep=True)
        self.targets: List[Optional[int]] = [None] + list(
            range(len(profile.groups or []))
        )
        self.cursor = 0
        # Digits typed so far for an exact value; None while not typing.
        self.typed: Optional[str] = None
        # Set once the user confirms, to drop the preview from the final paint.
        self.done = False
        multipliers = profile.multipliers
        self.step = multipliers.timeResolution if multipliers else DEFAULT_STEP_MS

    @property
    def target(self) -> Optional[int]:
        return self.targets[self.cursor]

    def _report(self, target: Optional[int]) -> Optional[TimingGroupReport]:
        if target is None:
            return self.profile.baseEstimate
        assert self.profile.groups is not None
        return self.profile.groups[target]

    def time_limit(self, target: Optional[int]) -> int:
        if target is None:
            return self.profile.timeLimit or 0
        report = self._report(target)
        assert report is not None
        return report.timeLimit

    def estimate(self, target: Optional[int]) -> int:
        """The limit the row's evidence was measured against."""
        report = self._report(target)
        if report is None:
            # A base with no estimate recorded: its starting value is all there is.
            return self.initial.timeLimit or 0
        return timing_edit.evidence_limit(report)

    def label(self, target: Optional[int]) -> str:
        if target is None:
            return '(base)'
        report = self._report(target)
        assert report is not None
        languages = ', '.join(report.languages)
        if report.isLeftover:
            languages = f'{limits_info.LEFTOVER_MARKER}{languages}'
        return languages

    def move(self, delta: int) -> None:
        self.typed = None
        self.cursor = max(0, min(len(self.targets) - 1, self.cursor + delta))

    def set_time_limit(self, time_limit: int) -> None:
        time_limit = max(1, time_limit)
        self.profile = timing_edit.with_time_limit(
            self.profile, self.target, time_limit
        )

    def step_by(self, delta: int) -> None:
        """Move to the next multiple of the step in ``delta``'s direction, so a
        limit off the grid lands back on it."""
        self.typed = None
        current = self.time_limit(self.target)
        if delta > 0:
            new = (current // self.step + 1) * self.step
        else:
            new = ((current - 1) // self.step) * self.step
        if new >= self.step:
            self.set_time_limit(new)

    def type_key(self, data: str) -> None:
        if data in ('\x7f', '\b'):
            if self.typed:
                self.typed = self.typed[:-1]
            return
        if data.isdigit() and len(data) == 1:
            self.typed = (self.typed or '') + data

    def commit_typed(self) -> None:
        if self.typed:
            value = int(self.typed)
            if value > 0:
                self.set_time_limit(value)
        self.typed = None

    def cancel_typed(self) -> None:
        self.typed = None

    def revert(self) -> None:
        self.typed = None
        self.set_time_limit(self.estimate(self.target))

    def reset(self) -> None:
        self.typed = None
        self.profile = self.initial.model_copy(deep=True)

    def is_dirty(self) -> bool:
        return self.profile != self.initial

    def preview_text(self, preview):
        if self.done or preview is None:
            return ''
        return preview(self.profile, self.target)

    def render_fragments(self):
        width = max(len(self.label(target)) for target in self.targets)
        fragments = []
        for i, target in enumerate(self.targets):
            selected = i == self.cursor
            row_style = 'class:current' if selected else 'class:row'
            fragments.append((row_style, '❯ ' if selected else '  '))
            fragments.append((row_style, self.label(target).ljust(width)))
            if selected and self.typed is not None:
                fragments.append(('class:typing', f'  [{self.typed}▏] ms'))
            else:
                value = self.time_limit(target)
                fragments.append(('class:limit', f'  {value:>6} ms'))
                estimate = self.estimate(target)
                if value != estimate:
                    fragments.append(('class:adjusted', f'  (estimated {estimate} ms)'))
            fragments.append((row_style, '\n'))
        return fragments


_SOLUTION_STATUS = {
    timing_edit.SolutionStatus.OK: '[success]✓[/success]',
    timing_edit.SolutionStatus.THIN: '[warning]⚠ thin margin[/warning]',
    timing_edit.SolutionStatus.FAILS: '[error]✗ fails[/error]',
    timing_edit.SolutionStatus.PASSES: '[error]✗ passes[/error]',
    timing_edit.SolutionStatus.UNVERIFIED: '[warning]? unverified[/warning]',
    timing_edit.SolutionStatus.UNCHECKED: '[dim]– unchecked[/dim]',
}

NO_TIMINGS_HINT = (
    '[dim]This profile records no per-solution timings: it was estimated before '
    'rbx kept them. Re-run [item]rbx time[/item] on it to see each solution here.'
    '[/dim]'
)


def _row_report(
    profile: LimitsProfile, target: Optional[int]
) -> Optional[TimingGroupReport]:
    if target is None:
        return profile.baseEstimate
    assert profile.groups is not None
    return profile.groups[target]


def _time_limit(profile: LimitsProfile, target: Optional[int]) -> int:
    if target is None:
        return profile.timeLimit or 0
    report = _row_report(profile, target)
    assert report is not None
    return report.timeLimit


def build_solutions_table(profile: LimitsProfile, target: Optional[int]):
    """Every recorded solution of the selected row, checked at its current limit.

    Only the editor shows this: it is what makes a hand-set limit legible -- which
    solution a step breaks, and how close the others are -- and nothing else
    needs that much detail. Falls back to a hint on a profile that recorded no
    timings.
    """
    import rich.markup
    import rich.table

    timings = timing_edit.group_solutions(profile, _row_report(profile, target))
    if timings is None:
        return NO_TIMINGS_HINT
    time_limit = _time_limit(profile, target)
    multipliers = profile.multipliers
    label = (
        'base'
        if target is None
        else ', '.join(
            _row_report(profile, target).languages  # type: ignore[union-attr]
        )
    )
    table = rich.table.Table(
        title=f'Solutions ({label}) at {time_limit} ms',
        title_style='bold bright_white',
        header_style='bold bright_white',
    )
    table.add_column('Solution', style='bold blue')
    table.add_column('Expected')
    table.add_column('Time', justify='right')
    table.add_column('Allows', justify='right')
    table.add_column('Ratio', justify='right')
    table.add_column('Check')
    if not timings:
        table.caption = 'No solution of these languages was timed.'
    for check in timing_edit.check_solutions(timings, multipliers, time_limit):
        lower = check.role == InferenceRole.LOWER
        if check.time is not None:
            time = f'{check.time} ms'
        elif check.survived_at is not None:
            time = f'> {check.survived_at} ms'
        else:
            time = '[dim]not run[/dim]'
        if check.min_ms is not None:
            allows = f'≥ {check.min_ms} ms'
        elif check.max_ms is not None:
            allows = f'≤ {check.max_ms} ms'
        else:
            allows = ''
        required = None
        if multipliers is not None:
            required = (
                multipliers.acToTimeLimit if lower else multipliers.timeLimitToTle
            )
        if check.ratio is not None:
            ratio = f'{check.ratio:.2f}×'
        elif check.survived_at is not None and time_limit:
            ratio = f'> {check.survived_at / time_limit:.2f}×'
        else:
            ratio = ''
        if ratio and required is not None:
            ratio += f' [dim](≥ {required:g}×)[/dim]'
        table.add_row(
            rich.markup.escape(check.path),
            'accepted' if lower else 'too slow',
            time,
            allows,
            ratio,
            _SOLUTION_STATUS[check.status],
        )
    return table


def build_preview(
    width: Optional[int] = None,
) -> Callable[[LimitsProfile, Optional[int]], object]:
    from prompt_toolkit.formatted_text import ANSI
    from rich.console import Group

    def _render(profile: LimitsProfile, target: Optional[int] = None):
        table = limits_info.build_limits_table(
            profile, title='Preview', show_check=True
        )
        solutions = build_solutions_table(profile, target)
        return ANSI(console.capture_ansi(Group(table, solutions), width=width))

    return _render


async def prompt_limits_edit(
    profile: LimitsProfile,
    input=None,
    output=None,
    preview: Optional[
        Callable[[LimitsProfile, Optional[int]], AnyFormattedText]
    ] = None,
) -> Optional[LimitsProfile]:
    """Interactive editor. Returns the edited profile, or None if cancelled."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    state = LimitEditorState(profile)
    legend = legend_lines(state.step)

    def _header_fragments():
        last = len(legend) - 1
        return [
            (
                'class:header' if i == 0 else 'class:hint' if i == last else '',
                line + '\n',
            )
            for i, line in enumerate(legend)
        ]

    kb = KeyBindings()
    typing = Condition(lambda: state.typed is not None)

    @kb.add('up')
    @kb.add('k', filter=~typing)
    def _(event):
        state.move(-1)

    @kb.add('down')
    @kb.add('j', filter=~typing)
    def _(event):
        state.move(1)

    @kb.add('right', filter=~typing)
    @kb.add('l', filter=~typing)
    @kb.add('+', filter=~typing)
    @kb.add('=', filter=~typing)
    def _(event):
        state.step_by(1)

    @kb.add('left', filter=~typing)
    @kb.add('h', filter=~typing)
    @kb.add('-', filter=~typing)
    def _(event):
        state.step_by(-1)

    for _digit in '0123456789':

        @kb.add(_digit)
        def _(event, _digit=_digit):
            state.type_key(_digit)

    @kb.add('backspace', filter=typing)
    def _(event):
        state.type_key('\x7f')

    @kb.add('escape', filter=typing)
    def _(event):
        state.cancel_typed()

    @kb.add('enter', filter=typing)
    def _(event):
        state.commit_typed()

    @kb.add('r', filter=~typing)
    def _(event):
        state.revert()

    @kb.add('R', filter=~typing)
    def _(event):
        state.reset()

    @kb.add('enter', filter=~typing)
    def _(event):
        state.done = True
        event.app.exit(result=state.profile)

    @kb.add('c-c')
    @kb.add('q', filter=~typing)
    @kb.add('escape', filter=~typing)
    def _(event):
        event.app.exit(result=None)

    windows = [
        Window(
            content=FormattedTextControl(_header_fragments),
            height=len(legend),
            always_hide_cursor=True,
        ),
        Window(
            content=FormattedTextControl(
                state.render_fragments, focusable=True, show_cursor=False
            ),
            height=len(state.targets),
            always_hide_cursor=True,
        ),
    ]
    if preview is not None:
        windows.append(
            Window(
                content=FormattedTextControl(lambda: state.preview_text(preview)),
                always_hide_cursor=True,
                dont_extend_height=True,
            )
        )
    style = Style.from_dict(
        {
            'header': 'bold',
            'hint': 'ansibrightblack',
            'current': 'bold reverse',
            'row': '',
            'limit': 'ansiyellow bold',
            'typing': 'ansicyan bold',
            'adjusted': 'ansibrightblack',
        }
    )
    app = Application(
        layout=Layout(HSplit(windows)),
        key_bindings=kb,
        style=style,
        full_screen=False,
        input=input,
        output=output,
    )
    return await app.run_async()


def load_editable_profile(profile: str) -> LimitsProfile:
    """The saved profile to edit, or exit explaining why there is none."""
    saved = limits_info.get_saved_limits_profile(profile)
    if saved is None:
        console.console.print(
            f'[error]No limits profile [item]{profile}[/item] to edit. Run '
            f'[item]rbx time -p {profile}[/item] to estimate one first.[/error]'
        )
        raise typer.Exit(1)
    if not timing_edit.is_editable(saved):
        console.console.print(
            f'[error]Limits profile [item]{profile}[/item] was not estimated, so '
            f'there is nothing to check a time limit against. Run '
            f'[item]rbx time -p {profile}[/item] to estimate it, or '
            f'[item]rbx time -p {profile} -s custom[/item] to set a limit '
            f'without checks.[/error]'
        )
        raise typer.Exit(1)
    # The cached model is shared between callers; the editor works on copies.
    return saved.model_copy(deep=True)


async def edit_time_limits(profile: str = 'local', dry: bool = False) -> None:
    saved = load_editable_profile(profile)
    # The evidence predates the package when this fires, so a limit checked
    # against it is checked against solutions that may no longer exist.
    estimation_checksum.warn_if_stale(profile)

    edited = await prompt_limits_edit(
        saved, preview=build_preview(width=console.console.size.width)
    )
    if edited is None:
        console.console.print('[warning]Cancelled; nothing was written.[/warning]')
        return
    if edited == saved:
        console.console.print('No time limit changed; nothing was written.')
        return

    limits_path = package.get_limits_file(profile)
    if dry:
        console.console.print(
            f'[warning]Dry run: not writing the timing profile to '
            f'[item]{href(limits_path)}[/item].[/warning]'
        )
    else:
        console.console.print(
            f'[success]Writing the following timing profile to '
            f'[item]{href(limits_path)}[/item].[/success]'
        )
        limits_path.parent.mkdir(parents=True, exist_ok=True)
        limits_path.write_text(limits_info.profile_to_yaml(edited))

    limits_info.render_limits_table(
        edited, title=f'Time limits ({profile})', show_check=True
    )
    if any(not check.ok for check in timing_edit.adjusted_checks(edited)):
        console.console.print(
            f'Run [item]rbx run -p {profile}[/item] to check every solution '
            f'against these limits.'
        )
