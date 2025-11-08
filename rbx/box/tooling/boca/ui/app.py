import asyncio
import difflib
import json
import tempfile
from pathlib import Path
from typing import Any, Callable, List, Optional

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Select, Static

from rbx.box.schema import ExpectedOutcome
from rbx.box.solutions import (
    get_full_ui_friendly_outcome_markup_verdict,
)
from rbx.box.tooling.boca.scraper import (
    BocaDetailedRun,
    BocaProblem,
    BocaRun,
    BocaScraper,
    get_boca_scraper,
)
from rbx.box.ui.widgets.code_box import CodeBox
from rbx.box.ui.widgets.diff_box import DiffBox
from rbx.config import get_app_path
from rbx.grading.steps import Outcome


def _format_time(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    return f'{hours:02d}:{mins:02d}'


class BocaRunsApp(App):
    CSS_PATH = None

    # Compact layout styling for filters, mode indicator and teams panel
    CSS = """
        #left_panel {
            width: 3fr;
        }
        #right_panel {
            width: 3fr;
        }
            #loading_indicator {
                height: 1;
                padding: 0 1;
                margin: 0 1;
            }
        #filters {
            padding: 0 1;
            margin: 0 1;
        }
        #filters_row1 { }
        #filters_row2 { }
        #problem_select { width: 24; }
        #verdict_select { width: 20; }
        #refresh_label { width: 6; }
        #refresh_input { width: 12; }
        #diff_label { width: 4; }
        #diff_input { width: 10; }
            #team_input { width: 1fr; }
        #mode_indicator {
            height: 1;
            padding: 0 1;
            margin: 0 1;
        }
        #runs_table { height: 3fr; }
        """

    mode: reactive[str] = reactive('judged')
    pending_requests: reactive[int] = reactive(0)
    verdict_filter: reactive[Optional[str]] = reactive(None)
    problem_filter: reactive[Optional[str]] = reactive(None)
    team_filter: reactive[Optional[str]] = reactive(None)
    refresh_interval: reactive[int] = reactive(30)
    contest_id: reactive[Optional[str]] = reactive(None)

    def __init__(
        self, scraper: Optional[BocaScraper] = None, contest_id: Optional[str] = None
    ):
        super().__init__()
        self.scraper = scraper or get_boca_scraper()
        self._problems: List[BocaProblem] = []
        self._runs: List[BocaRun] = []
        # Indexes for fast lookup/filtering
        self._runs_by_problem: dict[str, List[BocaRun]] = {}
        self._runs_by_team: dict[str, List[BocaRun]] = {}
        self._runs_by_problem_user: dict[tuple[str, str], List[BocaRun]] = {}
        self._tmp_dir = Path(tempfile.gettempdir()) / 'rbx_boca_viewer'
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        self._selected_key: Optional[str] = None
        self._highlighted_key: Optional[str] = None
        # Background tasks
        self._refresh_task: Optional[asyncio.Task] = None
        # Persistent cache
        self._cache_base: Optional[Path] = None
        self._runs_dir: Optional[Path] = None
        self._prefetch_inflight: set[str] = set()
        # Small diff detection cache: run_key -> is_small_diff
        self._small_diff_flags: dict[str, bool] = {}
        # Prioritized scraper executor (serializes calls, honors priority)
        self.PRIORITY_USER = 0
        self.PRIORITY_NORMAL = 5
        self.PRIORITY_PREFETCH = 10
        self._scraper_queue: 'asyncio.PriorityQueue[tuple[int, int, Callable[..., Any], tuple[Any, ...], dict[str, Any], asyncio.Future]]' = asyncio.PriorityQueue()  # type: ignore[type-arg]
        self._scraper_seq: int = 0
        self._scraper_worker_task: Optional[asyncio.Task] = None
        # Small diff result cache: run_key -> metadata/results
        # Used to avoid recomputing on every refresh and to drive UI status.
        self._small_diff_cache: dict[str, dict[str, Any]] = {}
        # Contest id provided externally (defaults to 'default' if not provided)
        self.contest_id = str(contest_id).strip() if contest_id else 'default'
        # Track last "team zoom" to allow restoring previous filter
        self._team_zoom_prev_filter: Optional[str] = None
        self._team_zoom_active_team: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        # Global loading indicator (reflects any in-flight network requests)
        yield Static('', id='loading_indicator')
        with Horizontal():
            with Vertical(id='left_panel'):
                yield Static('', id='mode_indicator')
                with Vertical(id='filters'):
                    with Horizontal(id='filters_row1'):
                        yield Select([], prompt='Problem', id='problem_select')
                        yield Select([], prompt='Verdict', id='verdict_select')
                    with Horizontal(id='filters_row2'):
                        yield Static('Ref:', id='refresh_label')
                        yield Input(
                            str(self.refresh_interval),
                            id='refresh_input',
                            placeholder='30',
                        )
                        yield Static('Δ:', id='diff_label')
                        yield Input(
                            str(self.small_diff_threshold),
                            id='diff_input',
                            placeholder='5',
                        )
                        yield Input(
                            placeholder='Team filter (substring, case-insensitive)',
                            id='team_input',
                        )
                table = DataTable(id='runs_table')
                table.add_columns(
                    'Run',
                    'Site',
                    'Problem',
                    'Verdict',
                    'Time',
                    'Status',
                    'Team',
                    'BG',
                )
                table.cursor_type = 'row'
                yield table
                yield Static('', id='left_spacer')
            with Vertical(id='right_panel'):
                # Shows which submission is currently selected
                yield Static('No run selected.', id='selection_info')
                self.code_box = CodeBox()
                yield self.code_box
        yield Footer()

    async def on_mount(self) -> None:
        # Initialize cache paths based on pre-configured contest id
        self._init_cache_paths()
        self.log(f'on_mount: using contest_id={self.contest_id!r}')
        # Run initial login + refresh in background to avoid blocking UI render
        asyncio.create_task(self._initial_load())
        self._update_mode_indicator()
        # Set initial focus to the runs table
        try:
            table = self.query_one('#runs_table', DataTable)
            self.set_focus(table)
            self.log('on_mount: focus set to runs_table')
        except Exception:
            self.log('on_mount: failed to set focus to runs_table')
        self.log('on_mount: completed')
        # Start auto-refresh loop and scraper worker
        self._start_auto_refresh_task()
        self._start_scraper_worker()

    # Contest id is now provided externally (CLI); in-app prompt removed

    async def _initial_load(self) -> None:
        try:
            await self._ensure_login()
            await self._refresh_runs()
        except Exception:
            # Errors are logged by Textual's default handler; ensure indicator decrements
            self.log('_initial_load: encountered exception during startup')

    async def _ensure_login(self) -> None:
        self.log('ensure_login: logging into BOCA via scraper')
        await self._run_scraper(self.scraper.login, priority=self.PRIORITY_USER)
        self.log('ensure_login: login complete')

    def _populate_filters(self) -> None:
        problem_select = self.query_one('#problem_select', Select)
        verdict_select = self.query_one('#verdict_select', Select)

        problem_values = sorted({r.problem_shortname for r in self._runs})
        problem_options = [('All', '__all__')] + [
            (name, name) for name in problem_values
        ]
        # Prefer the stored filter value if present; otherwise use current widget value
        current_problem_value = (
            self.problem_filter
            if self.problem_filter is not None
            else getattr(problem_select, 'value', None)
        )
        problem_select.set_options(problem_options)
        valid_values = {v for _, v in problem_options}
        problem_select.value = (
            current_problem_value
            if current_problem_value in valid_values
            else '__all__'
        )

        verdict_options = [('All', '__all__')] + [
            (eo.name.replace('_', ' ').title(), eo.name) for eo in ExpectedOutcome
        ]
        verdict_select.set_options(verdict_options)
        # Preserve verdict selection similarly
        current_verdict_value = (
            self.verdict_filter
            if self.verdict_filter is not None
            else getattr(verdict_select, 'value', None)
        )
        verdict_valid_values = {v for _, v in verdict_options}
        verdict_select.value = (
            current_verdict_value
            if current_verdict_value in verdict_valid_values
            else '__all__'
        )

    async def _refresh_runs(self) -> None:
        self.log(f'_refresh_runs: fetching runs (mode={self.mode})')
        only_judged = True if self.mode == 'judged' else False
        runs = await self._run_scraper(
            self.scraper.list_runs, only_judged, priority=self.PRIORITY_NORMAL
        )
        if self.mode == 'queue':
            runs = [r for r in runs if (r.outcome is None or r.status != 'judged')]
        elif self.mode == 'judged':
            runs = [r for r in runs if r.outcome is not None]
        else:  # both
            # Keep all returned runs
            pass
        self._runs = runs
        self.log(f'_refresh_runs: fetched {len(self._runs)} runs')
        # rebuild indexes for fast queries
        self._rebuild_run_indexes()
        # refresh problem filter based on current runs
        self._populate_filters()
        self._reload_table()
        self._update_mode_indicator()
        # Prefetch codes for runs not yet cached (non-blocking)
        asyncio.create_task(self._prefetch_missing_runs())
        # Compute small-diff markers in background (non-blocking)
        asyncio.create_task(self._compute_small_diffs())

    def _rebuild_run_indexes(self) -> None:
        by_problem: dict[str, List[BocaRun]] = {}
        by_team: dict[str, List[BocaRun]] = {}
        by_problem_user: dict[tuple[str, str], List[BocaRun]] = {}
        for run in self._runs:
            problem = run.problem_shortname
            team = (run.user or '').strip()
            by_problem.setdefault(problem, []).append(run)
            by_team.setdefault(team, []).append(run)
            by_problem_user.setdefault((problem, team), []).append(run)

        # Sort each list to allow efficient previous-run scans
        def _key_fn(r: BocaRun):
            return (r.time, r.run_number)

        for lst in by_problem.values():
            lst.sort(key=_key_fn)
        for lst in by_team.values():
            lst.sort(key=_key_fn)
        for lst in by_problem_user.values():
            lst.sort(key=_key_fn)
        self._runs_by_problem = by_problem
        self._runs_by_team = by_team
        self._runs_by_problem_user = by_problem_user

    def _passes_filters(self, run: BocaRun) -> bool:
        if self.problem_filter and self.problem_filter != '__all__':
            if run.problem_shortname != self.problem_filter:
                return False
        if self.team_filter:
            team_name = (run.user or '').strip()
            if self.team_filter.lower() not in team_name.lower():
                return False
        if self.mode in ('judged', 'both'):
            if self.verdict_filter and self.verdict_filter != '__all__':
                try:
                    expected = ExpectedOutcome[self.verdict_filter]
                except KeyError:
                    return False
                if run.outcome is None:
                    return False
                if not expected.match(run.outcome):
                    return False
        return True

    def _reload_table(self) -> None:
        table = self.query_one('#runs_table', DataTable)
        # Remember current highlighted key to restore after reload
        prev_highlight = self._highlighted_key
        table.clear()
        rows_added = 0
        first_key: Optional[str] = None
        for run in self._runs:
            if not self._passes_filters(run):
                continue
            if run.outcome is not None:
                verdict = Text.from_markup(
                    get_full_ui_friendly_outcome_markup_verdict(run.outcome)
                )
            else:
                verdict = '—'
            time_s = _format_time(run.time)
            row_key = f'{run.run_number}:{run.site_number}'
            self.log(
                f'_reload_table: add row key={row_key} problem={run.problem_shortname} team={(run.user or "").strip()} verdict={verdict} status={run.status}'
            )
            star = ''
            if run.outcome is not None and run.outcome == Outcome.ACCEPTED:
                flag = self._small_diff_flags.get(row_key)
                if flag:
                    star = '[red]*[/red]'
            table.add_row(
                f'{run.run_number}{star}',
                str(run.site_number),
                run.problem_shortname,
                verdict,
                time_s,
                run.status,
                run.user or '',
                self._bg_status_for_run(run),
                key=row_key,
            )
            rows_added += 1
            if first_key is None:
                first_key = row_key
        self.log(f'_reload_table: added {rows_added} rows')
        # Try to restore previously highlighted row if it still exists
        if prev_highlight is not None:
            try:
                row_idx = table.get_row_index(prev_highlight)
                table.cursor_coordinate = Coordinate(row=row_idx, column=0)
                self._highlighted_key = prev_highlight
            except Exception:
                # Fallback to first row if previous no longer exists
                if first_key is not None:
                    try:
                        row_idx = table.get_row_index(first_key)
                        table.cursor_coordinate = Coordinate(row=row_idx, column=0)
                        self._highlighted_key = first_key
                    except Exception:
                        # As a last resort, just record the key
                        self._highlighted_key = first_key
        else:
            if first_key is not None:
                try:
                    row_idx = table.get_row_index(first_key)
                    table.cursor_coordinate = Coordinate(row=row_idx, column=0)
                except Exception:
                    pass
                self._highlighted_key = first_key

    # --- Auto-refresh management ---
    def _cancel_auto_refresh_task(self) -> None:
        task = self._refresh_task
        if task is not None and not task.done():
            task.cancel()
        self._refresh_task = None

    def _start_auto_refresh_task(self) -> None:
        self._cancel_auto_refresh_task()

        async def _runner() -> None:
            while True:
                try:
                    await asyncio.sleep(max(1, int(self.refresh_interval)))
                    if self.refresh_interval > 0:
                        await self._refresh_runs()
                    else:
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    break
                except Exception:
                    # Ignore intermittent failures and keep the loop running
                    pass

        self._refresh_task = asyncio.create_task(_runner())

    def watch_refresh_interval(self, value: int) -> None:  # called on change
        # Restart the loop to apply the new interval immediately
        self._start_auto_refresh_task()

    async def action_toggle_mode(self) -> None:
        if self.mode == 'judged':
            self.mode = 'queue'
        elif self.mode == 'queue':
            self.mode = 'both'
        else:
            self.mode = 'judged'
        self._update_mode_indicator()
        await self._refresh_runs()

    BINDINGS = [
        ('r', 'refresh', 'Refresh'),
        ('m', 'toggle_mode', 'Toggle mode'),
        ('d', 'show_diff', 'Last diff'),
        ('D', 'show_non_ac_diff', 'Last non-AC diff'),
        ('p', 'toggle_problem_filter', 'Toggle problem filter'),
        ('t', 'toggle_team_filter', 'Toggle team filter'),
        ('q', 'quit', 'Quit'),
    ]

    def _extract_key_str(self, key: object) -> Optional[str]:
        if key is None:
            self.log('_extract_key_str: key is None')
            return None
        if isinstance(key, str):
            self.log(f'_extract_key_str: key is str -> {key}')
            return key
        # Extract the underlying string from Textual's RowKey wrapper when necessary
        value = getattr(key, 'value', None)
        if isinstance(value, str):
            self.log(f'_extract_key_str: key has .value -> {value}')
            return value
        try:
            # Fallback to string conversion
            as_str = str(key)
            if ':' in as_str:
                self.log(f'_extract_key_str: key fallback str -> {as_str}')
                return as_str
            self.log(f'_extract_key_str: key fallback str has no colon -> {as_str}')
            return None
        except Exception:
            self.log('_extract_key_str: exception while converting key to str')
            return None

    def _run_from_row_key(self, key: object) -> Optional[BocaRun]:
        key_str = self._extract_key_str(key)
        if key_str is None or ':' not in key_str:
            self.log(f'_run_from_row_key: invalid key_str -> {key_str}')
            return None
        run_number_str, site_number_str = key_str.split(':', 1)
        run = next(
            (
                r
                for r in self._runs
                if str(r.run_number) == run_number_str
                and str(r.site_number) == site_number_str
            ),
            None,
        )
        if run is None:
            self.log(f'_run_from_row_key: no run found for key {key_str}')
        else:
            self.log(
                f'_run_from_row_key: resolved run {run.run_number}-{run.site_number} ({run.problem_shortname})'
            )
        return run

    def _update_selection_info(
        self,
        run: BocaRun,
        detailed: Optional[BocaDetailedRun] = None,
        *,
        loading: bool = False,
    ) -> None:
        info = []
        verdict = run.outcome.name if run.outcome is not None else '—'
        team = (run.user or '').strip()
        info.append(
            f'Run {run.run_number}-{run.site_number} | Problem {run.problem_shortname} | Team {team}'
        )
        info.append(
            f'Verdict {verdict} | Time {_format_time(run.time)} | Status {run.status}'
        )
        if detailed is not None:
            info.append(f'File {detailed.filename.name}')
        if loading:
            info.append('⏳ [yellow]Loading code…[/yellow]')
        self.query_one('#selection_info', Static).update('\n'.join(info))

    def _update_mode_indicator(self) -> None:
        indicator = self.query_one('#mode_indicator', Static)
        label = {
            'judged': 'Judged',
            'queue': 'Queue',
            'both': 'Both',
        }.get(self.mode, self.mode)
        indicator.update(
            f'Contest: {self.contest_id or "?"} | Mode: {label} (press "m" to change)'
        )

    async def action_refresh(self) -> None:
        await self._refresh_runs()

    def action_toggle_problem_filter(self) -> None:
        # Toggle between "All" and highlighted run's problem
        try:
            problem_select = self.query_one('#problem_select', Select)
        except Exception:
            return
        # Zoom out first regardless of highlight state
        if self.problem_filter and self.problem_filter != '__all__':
            self.problem_filter = '__all__'
            problem_select.value = '__all__'
            self._reload_table()
            return
        # Zoom in requires a highlighted row
        key_str = self._highlighted_key
        run = self._run_from_row_key(key_str) if key_str is not None else None
        if run is None:
            try:
                self.notify('Highlight a run first.', severity='error')
            except Exception:
                pass
            return
        self.problem_filter = run.problem_shortname
        problem_select.value = run.problem_shortname
        self._reload_table()

    def action_toggle_team_filter(self) -> None:
        # First press: save current filter and zoom to highlighted team.
        # Second press: restore the saved filter.
        try:
            team_input = self.query_one('#team_input', Input)
        except Exception:
            return
        # Zoom out (restore previous) does not require highlight
        if self._team_zoom_prev_filter is not None:
            prev = self._team_zoom_prev_filter
            self._team_zoom_prev_filter = None
            self._team_zoom_active_team = None
            team_input.value = prev
            self.team_filter = prev if prev else None
            self._reload_table()
            return
        # Zoom in requires a highlighted row
        key_str = self._highlighted_key
        run = self._run_from_row_key(key_str) if key_str is not None else None
        if run is None:
            try:
                self.notify('Highlight a run first.', severity='error')
            except Exception:
                pass
            return
        team_name = (run.user or '').strip()
        # Save current filter and zoom into highlighted team
        current_value = (team_input.value or '').strip()
        self._team_zoom_prev_filter = current_value
        self._team_zoom_active_team = team_name
        team_input.value = team_name
        self.team_filter = team_name if team_name else None
        self._reload_table()

    def action_quit(self) -> None:
        self.exit()

    async def action_show_options(self) -> None:
        # Open options without waiting; handle result in on_screen_dismissed
        try:
            self.push_screen(
                _OptionsScreen(self.refresh_interval, self.small_diff_threshold)
            )
        except Exception:
            return

    def on_screen_dismissed(self, event) -> None:  # type: ignore[override]
        # Capture result from options modal
        if isinstance(event.screen, _OptionsScreen):
            result = getattr(event, 'result', None)
            self.log(f'on_screen_dismissed: options result={result!r}')
            if not isinstance(result, dict):
                return
            try:
                new_refresh = int(result.get('refresh_interval', self.refresh_interval))
                if new_refresh > 0:
                    self.refresh_interval = new_refresh
                    self.log(f'on_screen_dismissed: applied refresh={new_refresh}')
            except Exception:
                pass
            try:
                new_delta = int(
                    result.get('small_diff_threshold', self.small_diff_threshold)
                )
                if new_delta > 0:
                    self.small_diff_threshold = new_delta
                    self.log(f'on_screen_dismissed: applied diff={new_delta}')
            except Exception:
                pass
            try:
                self.notify('Options saved', severity='information')
            except Exception:
                pass

    async def action_show_non_ac_diff(self) -> None:
        await self.action_show_diff(last_non_ac=True)

    async def action_show_diff(self, last_non_ac: bool = False) -> None:
        # Use currently highlighted row; selection not required
        key_str = self._highlighted_key
        if key_str is None:
            self.notify('Highlight a run first to diff.', severity='error')
            return
        run = self._run_from_row_key(key_str)
        if run is None:
            self.notify('Could not resolve selected run.', severity='error')
            return

        team = (run.user or '').strip()
        problem = run.problem_shortname
        site_number = run.site_number

        # Find latest previous run according to chosen mode
        if last_non_ac:
            prev = self._find_last_non_ac_before(run)
            if prev is None:
                self.notify(
                    'No previous non-AC run found for this team and problem.',
                    severity='error',
                )
                return
        else:
            # Use indexed runs for (problem, team) and filter by site/time
            indexed = self._runs_by_problem_user.get((problem, team), [])
            candidates = [
                r
                for r in indexed
                if r.site_number == site_number
                and r.outcome is not None
                and (
                    (r.time < run.time)
                    or (r.time == run.time and r.run_number < run.run_number)
                )
            ]
            if not candidates:
                self.notify(
                    'No previous run found for this team and problem.', severity='error'
                )
                return
            prev = max(candidates, key=lambda r: (r.time, r.run_number))

        try:
            path_current, path_prev = await asyncio.gather(
                self._ensure_cached_run(
                    run, is_prefetch=False, priority=self.PRIORITY_USER
                ),
                self._ensure_cached_run(
                    prev, is_prefetch=False, priority=self.PRIORITY_USER
                ),
            )
        except Exception:
            self.notify('Failed to prepare runs for diff.', severity='error')
            return

        if path_current is None or path_prev is None:
            self.notify('Failed to prepare files for diff.', severity='error')
            return

        self.push_screen(_BocaDifferScreen(path_prev, path_current))

    @on(Select.Changed, '#problem_select')
    async def _on_problem_changed(self, event: Select.Changed) -> None:
        value = event.value
        self.problem_filter = None if value is None else str(value)
        self._reload_table()

    @on(Input.Changed, '#refresh_input')
    def _on_refresh_interval_changed(self, event: Input.Changed) -> None:
        raw = (event.value or '').strip()
        try:
            new_value = int(raw)
            if new_value <= 0:
                return
            self.refresh_interval = new_value
        except ValueError:
            # Ignore non-integer inputs
            return

    @on(Select.Changed, '#verdict_select')
    async def _on_verdict_changed(self, event: Select.Changed) -> None:
        value = event.value
        self.verdict_filter = None if value is None else str(value)
        self._reload_table()

    @on(Input.Changed, '#diff_input')
    def _on_small_diff_threshold_changed(self, event: Input.Changed) -> None:
        raw = (event.value or '').strip()
        try:
            new_value = int(raw)
            if new_value <= 0:
                return
            self.small_diff_threshold = new_value
        except ValueError:
            return

    @on(Input.Changed, '#team_input')
    def _on_team_filter_changed(self, event: Input.Changed) -> None:
        raw = (event.value or '').strip()
        self.team_filter = raw if raw else None
        self._reload_table()

    # --- Small diff threshold configuration ---
    small_diff_threshold: reactive[int] = reactive(5)

    def watch_small_diff_threshold(self, value: int) -> None:  # called on change
        # Recompute markers with new threshold
        asyncio.create_task(self._compute_small_diffs())

    @on(DataTable.RowSelected, '#runs_table')
    async def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        self.log(f'RowSelected: event.row_key={event.row_key!r}')
        key_str = self._extract_key_str(event.row_key)
        run = self._run_from_row_key(event.row_key)
        if run is None:
            self.log('RowSelected: run is None (ignoring)')
            return
        # Remember selection to prevent stale updates
        self._selected_key = key_str
        # Show selection info immediately
        self._update_selection_info(run)
        self.log(
            f'RowSelected: retrieving run code for {run.run_number}-{run.site_number}'
        )
        # Start background load; do not block the UI
        asyncio.create_task(self._load_and_display_run(run, key_str))

    async def _load_and_display_run(
        self, run: BocaRun, expected_key: Optional[str]
    ) -> None:
        try:
            # If already cached, use immediately
            cached = self._find_cached_run_path(run)
            if cached is not None:
                if expected_key is None or self._selected_key == expected_key:
                    self.code_box.path = cached
                    # Ensure selection info reflects final (not loading) state
                    self._update_selection_info(run, loading=False)
                else:
                    self.log(
                        f'_load_and_display_run: discard stale cached expected={expected_key} current={self._selected_key}'
                    )
                return

            # Otherwise, ensure cached in background and then display
            # Indicate loading on the right panel and in the code box
            if expected_key is None or self._selected_key == expected_key:
                try:
                    self._update_selection_info(run, loading=True)
                except Exception:
                    pass
            path = await self._ensure_cached_run(
                run, is_prefetch=False, priority=self.PRIORITY_USER
            )
            if path is None:
                return
            if expected_key is None or self._selected_key == expected_key:
                self.code_box.path = path
                # Clear loading indicator now that code is displayed
                self._update_selection_info(run, loading=False)
            else:
                self.log(
                    f'_load_and_display_run: discard stale result expected={expected_key} current={self._selected_key}'
                )
        except Exception:
            self.log('_load_and_display_run: error while retrieving or displaying run')

    @on(DataTable.RowHighlighted, '#runs_table')
    async def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # Track highlighted key for diff action
        self._highlighted_key = self._extract_key_str(event.row_key)
        await self._on_row_selected(event)  # pyright: ignore[reportArgumentType]
        self.log(
            f'RowHighlighted: event.row_key={event.row_key!r} -> highlighted={self._highlighted_key!r}'
        )

    def _write_temp_code(self, detailed: BocaDetailedRun) -> Path:
        filename = detailed.filename.name
        # Ensure unique file per run
        safe_name = f'{detailed.run_number}-{detailed.site_number}-{filename}'
        path = self._tmp_dir / safe_name
        path.write_text(detailed.code)
        self.log(f'_write_temp_code: wrote code to {path} (len={len(detailed.code)})')
        return path

    # --- Previous run helpers ---
    def _find_last_non_ac_before(self, run: BocaRun) -> Optional[BocaRun]:
        team = (run.user or '').strip()
        problem = run.problem_shortname
        site_number = run.site_number
        # Use pre-indexed list for (problem, team)
        indexed = self._runs_by_problem_user.get((problem, team), [])
        # List is sorted by (time, run_number); scan from the end for efficiency
        for prev in reversed(indexed):
            if prev.site_number != site_number:
                continue
            if prev.outcome is None or prev.outcome == Outcome.ACCEPTED:
                continue
            if (prev.time < run.time) or (
                prev.time == run.time and prev.run_number < run.run_number
            ):
                return prev
        return None

    # --- Request management & loading indicator ---
    async def _run_in_thread(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        self.pending_requests += 1
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        finally:
            self.pending_requests -= 1

    async def _run_scraper(
        self,
        func: Callable[..., Any],
        *args: Any,
        priority: int = 5,
        **kwargs: Any,
    ) -> Any:
        """Schedule a scraper call with priority; executes serially in a worker."""
        # Create a future to await result
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        # Use sequence to keep FIFO within same priority
        self._scraper_seq += 1
        item = (priority, self._scraper_seq, func, args, kwargs, fut)
        await self._scraper_queue.put(item)
        # Ensure worker is running
        self._start_scraper_worker()
        return await fut

    def _start_scraper_worker(self) -> None:
        if (
            self._scraper_worker_task is not None
            and not self._scraper_worker_task.done()
        ):
            return

        async def _worker() -> None:
            while True:
                try:
                    (
                        priority,
                        seq,
                        func,
                        args,
                        kwargs,
                        fut,
                    ) = await self._scraper_queue.get()  # type: ignore[misc]
                except asyncio.CancelledError:
                    break
                except Exception:
                    # Should not happen; continue loop
                    await asyncio.sleep(0)
                    continue
                try:
                    if not fut.cancelled():
                        result = await self._run_in_thread(func, *args, **kwargs)
                        fut.set_result(result)
                except asyncio.CancelledError:
                    if not fut.cancelled():
                        fut.set_exception(asyncio.CancelledError())
                    break
                except Exception as exc:
                    if not fut.cancelled():
                        fut.set_exception(exc)
                finally:
                    self._scraper_queue.task_done()

        self._scraper_worker_task = asyncio.create_task(_worker())

    def _cancel_scraper_worker(self) -> None:
        task = self._scraper_worker_task
        if task is not None and not task.done():
            task.cancel()
        self._scraper_worker_task = None

    def watch_pending_requests(self, value: int) -> None:  # called on change
        self._update_loading_indicator()

    def _update_loading_indicator(self) -> None:
        try:
            indicator = self.query_one('#loading_indicator', Static)
        except Exception:
            return
        prefetch_count = 0
        try:
            prefetch_count = len(self._prefetch_inflight)
        except Exception:
            prefetch_count = 0
        if self.pending_requests > 0:
            if prefetch_count > 0:
                indicator.update(f'⏳ Loading… (prefetch {prefetch_count})')
            else:
                indicator.update('⏳ Loading…')
        elif prefetch_count > 0:
            indicator.update(f'Prefetch in-flight: {prefetch_count}')
        else:
            indicator.update('')

    def on_unmount(self) -> None:
        # Ensure background tasks are stopped cleanly
        self._cancel_auto_refresh_task()
        self._cancel_scraper_worker()

    # --- Persistent cache helpers ---
    def _init_cache_paths(self) -> None:
        base = get_app_path() / 'boca' / 'contests' / (self.contest_id or 'default')
        runs_dir = base / 'runs'
        runs_dir.mkdir(parents=True, exist_ok=True)
        self._cache_base = base
        self._runs_dir = runs_dir

    def _run_key(self, run: BocaRun) -> str:
        return f'{run.run_number}:{run.site_number}'

    def _find_cached_run_path(self, run: BocaRun) -> Optional[Path]:
        if self._runs_dir is None:
            return None
        try:
            candidate = self._runs_dir / f'{run.run_number}-{run.site_number}'
            if candidate.is_file():
                return candidate
        except Exception:
            return None
        return None

    # --- Failed fetch sentinel helpers ---
    def _failure_sentinel_path(self, run: BocaRun) -> Optional[Path]:
        if self._runs_dir is None:
            return None
        return self._runs_dir / f'{run.run_number}-{run.site_number}.fail'

    def _read_failure_attempts(self, run: BocaRun) -> int:
        """Return number of failed fetch attempts recorded for this run."""
        try:
            path = self._failure_sentinel_path(run)
            if path is None or not path.is_file():
                return 0
            raw = path.read_text().strip()
            try:
                return max(0, int(raw))
            except Exception:
                # If contents are unexpected, treat as 1 failed attempt
                return 1
        except Exception:
            return 0

    def _record_fetch_failure(self, run: BocaRun) -> None:
        """Increment failure counter for this run (prefetch skip uses this)."""
        try:
            path = self._failure_sentinel_path(run)
            if path is None:
                return
            attempts = self._read_failure_attempts(run) + 1
            path.write_text(str(attempts))
        except Exception:
            # Best-effort only
            pass

    def _clear_fetch_failure(self, run: BocaRun) -> None:
        """Clear failure sentinel for this run after a successful fetch."""
        try:
            path = self._failure_sentinel_path(run)
            if path is not None and path.exists():
                path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except Exception:
            # Ignore cleanup errors
            pass

    async def _ensure_cached_run(
        self, run: BocaRun, *, is_prefetch: bool, priority: int
    ) -> Optional[Path]:
        # Check existing
        existing = self._find_cached_run_path(run)
        if existing is not None:
            return existing
        key = self._run_key(run)
        # Track only prefetch tasks in the inflight set (for UI)
        if is_prefetch:
            self._prefetch_inflight.add(key)
            self._update_loading_indicator()
        try:
            detailed: BocaDetailedRun = await self._run_scraper(
                self.scraper.retrieve_run, run, priority=priority
            )
            if self._runs_dir is None:
                return None
            # Write code file with simplified name '<run>-<site>'
            base_name = f'{detailed.run_number}-{detailed.site_number}'
            path = self._runs_dir / base_name
            path.write_text(detailed.code)
            # Write metadata sidecar JSON with same stem
            meta = {
                'run_number': detailed.run_number,
                'site_number': detailed.site_number,
                'filename': str(getattr(detailed.filename, 'name', '')),
                'language': str(getattr(detailed, 'language_repr', '') or ''),
            }
            try:
                (self._runs_dir / f'{base_name}.json').write_text(
                    json.dumps(meta, ensure_ascii=False)
                )
            except Exception:
                # Metadata failures should not break caching
                pass
            self.log(
                f'_ensure_cached_run: cached code to {path} (len={len(detailed.code)})'
            )
            # Successful fetch -> clear any prior failure sentinel
            self._clear_fetch_failure(run)
            return path
        except Exception:
            # Only count failures that raise here
            self._record_fetch_failure(run)
            return None
        finally:
            if is_prefetch:
                self._prefetch_inflight.discard(key)
                self._update_loading_indicator()

    async def _prefetch_missing_runs(self) -> None:
        # Sequentially prefetch to honor scraper serialization
        for run in list(self._runs):
            try:
                if self._find_cached_run_path(run) is None:
                    # Skip prefetch if we've already failed 3 times for this run
                    if self._read_failure_attempts(run) >= 3:
                        continue
                    await self._ensure_cached_run(
                        run, is_prefetch=True, priority=self.PRIORITY_PREFETCH
                    )
            except Exception:
                # Ignore individual failures
                pass

    def _is_small_diff_done_for_run(self, run: BocaRun) -> bool:
        if run.outcome is None or run.outcome != Outcome.ACCEPTED:
            return False
        key = self._run_key(run)
        entry = self._small_diff_cache.get(key)
        if entry is None:
            return False
        try:
            return (
                int(entry.get('threshold', -1)) == int(self.small_diff_threshold)
                and entry.get('verdict') == run.outcome.name
            )
        except Exception:
            return False

    def _bg_status_for_run(self, run: BocaRun) -> str:
        has_p = self._find_cached_run_path(run) is not None
        has_d = self._is_small_diff_done_for_run(run)
        # Show 'X' when this run has reached the failure cap (>= 3 attempts)
        has_x = self._read_failure_attempts(run) >= 3
        parts: list[str] = []
        if has_p:
            parts.append('P')
        if has_d:
            parts.append('D')
        if has_x:
            parts.append('X')
        return ''.join(parts)

    async def _compute_small_diffs(self) -> None:
        """Compute and cache 'small diff' markers for AC runs.
        A run is marked if its diff to the last non-AC run for same team/problem/site
        has changed-line count <= small_diff_threshold.
        """
        threshold = int(self.small_diff_threshold)
        # Compute only for runs with missing/invalid cache
        for run in list(self._runs):
            try:
                if run.outcome is None or run.outcome != Outcome.ACCEPTED:
                    continue
                key = self._run_key(run)
                cached = self._small_diff_cache.get(key)
                verdict_name = run.outcome.name
                if cached is not None:
                    if (
                        int(cached.get('threshold', -1)) == threshold
                        and cached.get('verdict') == verdict_name
                    ):
                        # Cache is valid; skip recompute
                        continue
                # 1) If current submission has not been prefetched yet, skip for now
                path_current = self._find_cached_run_path(run)
                if path_current is None:
                    continue
                # 2) Ensure previous candidate is prefetched (fire request if needed)
                prev = self._find_last_non_ac_before(run)
                if prev is None:
                    # No previous non-AC to compare against
                    continue
                path_prev = await self._ensure_cached_run(
                    prev, is_prefetch=True, priority=self.PRIORITY_PREFETCH
                )
                if path_prev is None:
                    continue
                try:
                    a = path_prev.read_text().splitlines()
                    b = path_current.read_text().splitlines()
                except Exception:
                    continue
                diff_iter = difflib.unified_diff(a, b, lineterm='')
                changed = 0
                for line in diff_iter:
                    if not line:
                        continue
                    # Skip headers
                    if (
                        line.startswith('---')
                        or line.startswith('+++')
                        or line.startswith('@@')
                    ):
                        continue
                    if line[0] == '+' or line[0] == '-':
                        changed += 1
                        if changed > threshold:
                            break
                self._small_diff_cache[key] = {
                    'flag': changed <= threshold,
                    'changed': changed,
                    'threshold': threshold,
                    'verdict': verdict_name,
                }
            except Exception:
                # Ignore per-run compute failures
                pass
        # Update flags for current runs from valid cache
        flags: dict[str, bool] = {}
        for run in list(self._runs):
            try:
                if run.outcome is None or run.outcome != Outcome.ACCEPTED:
                    continue
                key = self._run_key(run)
                entry = self._small_diff_cache.get(key)
                if entry is None:
                    continue
                if (
                    int(entry.get('threshold', -1)) == threshold
                    and entry.get('verdict') == run.outcome.name
                ):
                    flags[key] = bool(entry.get('flag', False))
            except Exception:
                pass
        self._small_diff_flags = flags
        try:
            self._reload_table()
        except Exception:
            pass


def run_app(contest_id: Optional[str] = None) -> None:
    app = BocaRunsApp(contest_id=contest_id)
    app.run()


class _BocaDifferScreen(Screen):
    BINDINGS = [
        ('q', 'app.pop_screen', 'Quit'),
    ]

    def __init__(self, path1: Path, path2: Path):
        super().__init__()
        self._path1 = path1
        self._path2 = path2

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Vertical():
            yield DiffBox()

    def on_mount(self) -> None:
        diff = self.query_one(DiffBox)
        diff.paths = (self._path1, self._path2)


class _OptionsScreen(Screen):
    BINDINGS = [
        ('enter', 'save', 'Save'),
        ('escape', 'cancel', 'Cancel'),
        ('q', 'cancel', 'Quit'),
    ]

    def __init__(self, refresh_interval: int, small_diff_threshold: int):
        super().__init__()
        self._initial_refresh = int(refresh_interval)
        self._initial_diff = int(small_diff_threshold)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Vertical():
            yield Static('Options: Set values and press Enter to save')
            yield Static('Auto refresh period (seconds):')
            yield Input(value=str(self._initial_refresh), id='opt_refresh_input')
            yield Static('Delta lines threshold (<= changes):')
            yield Input(value=str(self._initial_diff), id='opt_diff_input')

    def on_mount(self) -> None:
        try:
            inp = self.query_one('#opt_refresh_input', Input)
            self.set_focus(inp)
        except Exception:
            pass

    def _submit(self) -> None:
        try:
            refresh_inp = self.query_one('#opt_refresh_input', Input)
            diff_inp = self.query_one('#opt_diff_input', Input)
            refresh_raw = (refresh_inp.value or '').strip()
            diff_raw = (diff_inp.value or '').strip()
            self.log(
                f'_OptionsScreen._submit: raw values refresh={refresh_raw!r} diff={diff_raw!r}'
            )
        except Exception:
            self.log('_OptionsScreen._submit: failed to read inputs; dismissing None')
            self.dismiss(None)
            return
        # Fallback to initial values on invalid/empty
        try:
            refresh_val = int(refresh_raw) if refresh_raw else self._initial_refresh
            if refresh_val <= 0:
                refresh_val = self._initial_refresh
            self.log(f'_OptionsScreen._submit: parsed refresh={refresh_val}')
        except Exception:
            self.log(
                f'_OptionsScreen._submit: invalid refresh={refresh_raw!r}; using {self._initial_refresh}'
            )
            refresh_val = self._initial_refresh
        try:
            diff_val = int(diff_raw) if diff_raw else self._initial_diff
            if diff_val <= 0:
                diff_val = self._initial_diff
            self.log(f'_OptionsScreen._submit: parsed diff={diff_val}')
        except Exception:
            self.log(
                f'_OptionsScreen._submit: invalid diff={diff_raw!r}; using {self._initial_diff}'
            )
            diff_val = self._initial_diff
        payload = {'refresh_interval': refresh_val, 'small_diff_threshold': diff_val}
        self.log(f'_OptionsScreen._submit: dismissing with {payload!r}')
        self.dismiss(payload)

    @on(Input.Submitted, '#opt_refresh_input')
    def _on_submit_refresh(self, event: Input.Submitted) -> None:
        self._submit()

    @on(Input.Submitted, '#opt_diff_input')
    def _on_submit_diff(self, event: Input.Submitted) -> None:
        self._submit()

    def action_save(self) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)
