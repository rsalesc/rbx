import asyncio
import tempfile
from pathlib import Path
from typing import Any, Callable, List, Optional

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Select, Static

from rbx.box.schema import ExpectedOutcome
from rbx.box.tooling.boca.scraper import (
    BocaDetailedRun,
    BocaProblem,
    BocaRun,
    BocaScraper,
    get_boca_scraper,
)
from rbx.box.ui.widgets.code_box import CodeBox
from rbx.box.ui.widgets.diff_box import DiffBox
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
            width: 2fr;
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
            height: 3;
            padding: 0 1;
            margin: 0 1;
        }
        #problem_select { width: 24; }
        #verdict_select { width: 20; }
        #refresh_label { width: 18; }
        #refresh_input { width: 8; }
        #mode_indicator {
            height: 1;
            padding: 0 1;
            margin: 0 1;
        }
        DataTable {
            height: 1fr;
        }
        """

    mode: reactive[str] = reactive('judged')
    pending_requests: reactive[int] = reactive(0)
    verdict_filter: reactive[Optional[str]] = reactive(None)
    problem_filter: reactive[Optional[str]] = reactive(None)
    refresh_interval: reactive[int] = reactive(30)

    def __init__(self, scraper: Optional[BocaScraper] = None):
        super().__init__()
        self.scraper = scraper or get_boca_scraper()
        self._problems: List[BocaProblem] = []
        self._runs: List[BocaRun] = []
        self._tmp_dir = Path(tempfile.gettempdir()) / 'rbx_boca_viewer'
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        self._selected_key: Optional[str] = None
        self._highlighted_key: Optional[str] = None
        # Serialize all scraper calls to avoid crashes caused by parallelism
        self._scraper_lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        # Global loading indicator (reflects any in-flight network requests)
        yield Static('', id='loading_indicator')
        with Horizontal():
            with Vertical(id='left_panel'):
                yield Static('', id='mode_indicator')
                with Horizontal(id='filters'):
                    yield Select([], prompt='Problem', id='problem_select')
                    yield Select([], prompt='Verdict', id='verdict_select')
                    yield Static('Auto-refresh (s):', id='refresh_label')
                    yield Input(
                        str(self.refresh_interval), id='refresh_input', placeholder='30'
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
                )
                table.cursor_type = 'row'
                yield table
            with Vertical(id='right_panel'):
                # Shows which submission is currently selected
                yield Static('No run selected.', id='selection_info')
                self.code_box = CodeBox()
                yield self.code_box
        yield Footer()

    async def on_mount(self) -> None:
        self.log('on_mount: scheduling login and initial refresh in background')
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
        # Start auto-refresh loop
        self._start_auto_refresh_task()

    async def _initial_load(self) -> None:
        try:
            await self._ensure_login()
            await self._refresh_runs()
        except Exception:
            # Errors are logged by Textual's default handler; ensure indicator decrements
            self.log('_initial_load: encountered exception during startup')

    async def _ensure_login(self) -> None:
        self.log('ensure_login: logging into BOCA via scraper')
        await self._run_scraper(self.scraper.login)
        self.log('ensure_login: login complete')

    def _populate_filters(self) -> None:
        problem_select = self.query_one('#problem_select', Select)
        verdict_select = self.query_one('#verdict_select', Select)

        problem_values = sorted({r.problem_shortname for r in self._runs})
        problem_options = [('All', '__all__')] + [
            (name, name) for name in problem_values
        ]
        current_problem_value = getattr(problem_select, 'value', None)
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
        verdict_select.value = '__all__'

    async def _refresh_runs(self) -> None:
        self.log(f'_refresh_runs: fetching runs (mode={self.mode})')
        only_judged = True if self.mode == 'judged' else False
        runs = await self._run_scraper(self.scraper.list_runs, only_judged)
        if self.mode == 'queue':
            runs = [r for r in runs if (r.outcome is None or r.status != 'judged')]
        elif self.mode == 'judged':
            runs = [r for r in runs if r.outcome is not None]
        else:  # both
            # Keep all returned runs
            pass
        self._runs = runs
        self.log(f'_refresh_runs: fetched {len(self._runs)} runs')
        # refresh problem filter based on current runs
        self._populate_filters()
        self._reload_table()
        self._update_mode_indicator()

    def _passes_filters(self, run: BocaRun) -> bool:
        if self.problem_filter and self.problem_filter != '__all__':
            if run.problem_shortname != self.problem_filter:
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

    def _outcome_to_expected(self, outcome: Outcome) -> ExpectedOutcome:
        if outcome == Outcome.ACCEPTED:
            return ExpectedOutcome.ACCEPTED
        if outcome == Outcome.WRONG_ANSWER:
            return ExpectedOutcome.WRONG_ANSWER
        if outcome in (Outcome.TIME_LIMIT_EXCEEDED, Outcome.IDLENESS_LIMIT_EXCEEDED):
            return ExpectedOutcome.TIME_LIMIT_EXCEEDED
        if outcome == Outcome.MEMORY_LIMIT_EXCEEDED:
            return ExpectedOutcome.MEMORY_LIMIT_EXCEEDED
        if outcome == Outcome.RUNTIME_ERROR:
            return ExpectedOutcome.RUNTIME_ERROR
        if outcome == Outcome.OUTPUT_LIMIT_EXCEEDED:
            return ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED
        if outcome == Outcome.JUDGE_FAILED:
            return ExpectedOutcome.JUDGE_FAILED
        # Fallback
        return ExpectedOutcome.INCORRECT

    def _reload_table(self) -> None:
        table = self.query_one('#runs_table', DataTable)
        table.clear()
        rows_added = 0
        first_key: Optional[str] = None
        for run in self._runs:
            if not self._passes_filters(run):
                continue
            if run.outcome is not None:
                expected = self._outcome_to_expected(run.outcome)
                verdict = Text.from_markup(expected.full_markup())
            else:
                verdict = '—'
            time_s = _format_time(run.time)
            row_key = f'{run.run_number}:{run.site_number}'
            self.log(
                f'_reload_table: add row key={row_key} problem={run.problem_shortname} team={(run.user or "").strip()} verdict={verdict} status={run.status}'
            )
            table.add_row(
                str(run.run_number),
                str(run.site_number),
                run.problem_shortname,
                verdict,
                time_s,
                run.status,
                run.user or '',
                key=row_key,
            )
            rows_added += 1
            if first_key is None:
                first_key = row_key
        self.log(f'_reload_table: added {rows_added} rows')
        if self._highlighted_key is None and first_key is not None:
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
                    await self._refresh_runs()
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
        ('s', 'show_diff', 'Show diff'),
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
        self, run: BocaRun, detailed: Optional[BocaDetailedRun] = None
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
        self.query_one('#selection_info', Static).update('\n'.join(info))

    def _update_mode_indicator(self) -> None:
        indicator = self.query_one('#mode_indicator', Static)
        label = {
            'judged': 'Judged',
            'queue': 'Queue',
            'both': 'Both',
        }.get(self.mode, self.mode)
        indicator.update(f'Mode: {label} (press "m" to change)')

    async def action_refresh(self) -> None:
        await self._refresh_runs()

    def action_quit(self) -> None:
        self.exit()

    async def action_show_diff(self) -> None:
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

        # Find latest previous run for same problem and team (same site),
        # ordered by time, tie-broken by run number
        candidates = [
            r
            for r in self._runs
            if r.problem_shortname == problem
            and (r.user or '').strip() == team
            and r.site_number == site_number
            and r.outcome is not None
            # and r.outcome != Outcome.ACCEPTED
            and (
                (r.time < run.time)
                or (r.time == run.time and r.run_number < run.run_number)
            )
        ]

        if not candidates:
            self.notify(
                'No previous non-AC run found for this team and problem.',
                severity='error',
            )
            return

        prev = max(candidates, key=lambda r: (r.time, r.run_number))

        try:
            detailed_current, detailed_prev = await asyncio.gather(
                self._run_scraper(self.scraper.retrieve_run, run),
                self._run_scraper(self.scraper.retrieve_run, prev),
            )
        except Exception:
            self.notify('Failed to retrieve runs for diff.', severity='error')
            return

        try:
            path_current = self._write_temp_code(detailed_current)
            path_prev = self._write_temp_code(detailed_prev)
        except Exception:
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
            detailed: BocaDetailedRun = await self._run_scraper(
                self.scraper.retrieve_run, run
            )
            path = self._write_temp_code(detailed)
            if expected_key is None or self._selected_key == expected_key:
                self.code_box.path = path
                # Update info with filename after loading
                self._update_selection_info(run, detailed)
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
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Run a scraper call with serialization to prevent parallel execution.

        This wraps the blocking scraper function to ensure only one scraper
        operation is in-flight at a time, while still leveraging the common
        thread-offloading and pending-request tracking.
        """
        async with self._scraper_lock:
            return await self._run_in_thread(func, *args, **kwargs)

    def watch_pending_requests(self, value: int) -> None:  # called on change
        self._update_loading_indicator()

    def _update_loading_indicator(self) -> None:
        try:
            indicator = self.query_one('#loading_indicator', Static)
        except Exception:
            return
        if self.pending_requests > 0:
            indicator.update('⏳ Loading…')
        else:
            indicator.update('')

    def on_unmount(self) -> None:
        # Ensure background tasks are stopped cleanly
        self._cancel_auto_refresh_task()


def run_app() -> None:
    app = BocaRunsApp()
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
