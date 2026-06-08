# Test-list filtering + fancy search box Implementation Plan (#548)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `RunTestExplorerScreen`'s test list filterable (failing-only) and searchable (fuzzy box that doubles as goto), via a reusable predicate-based filter model in `get_entries_options`.

**Architecture:** Add an optional `predicate` to `get_entries_options` (`run_ui.py`) that emits a filtered option list while preserving the #464 divider/index invariant. The screen precomputes per-entry outcomes once, builds a combined predicate (failing-only AND fuzzy/numeric search), and rebuilds the `OptionList` on each change. A dockable `Input` (`/`) live-filters; Enter commits a goto; Esc restores.

**Tech Stack:** Python, Textual 8.0 (`OptionList`, `Input`, `textual.fuzzy.Matcher`), Pydantic, pytest (Textual `run_test` pilot).

**Design doc:** `docs/plans/2026-06-08-ui-test-filter-search-design.md`

**Conventions:** single quotes; absolute imports; commit with the `/commit` workflow (`.claude/skills/commit.md`) — conventional commits, co-author trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Run `uv run ruff check . && uv run ruff format .` before each commit.

---

## Task 1: Add `predicate` to `get_entries_options` (filter/index model)

**Files:**
- Modify: `rbx/box/ui/utils/run_ui.py` (`get_entries_options`, currently line ~73)
- Test: `tests/rbx/box/ui/test_run_ui.py`

### Step 1: Write the failing tests

Add to `tests/rbx/box/ui/test_run_ui.py` (reuse the existing module-level `_entry(group, index)` helper near line 128):

```python
def test_predicate_filters_entries_and_keeps_alignment_across_groups():
    """#464: expanded_entries stays aligned with OptionList indices after filtering."""
    from textual.widgets import OptionList

    entries = [
        _entry('group-a', 0),
        _entry('group-a', 1),
        _entry('group-b', 0),
        _entry('group-b', 1),
    ]
    # Keep only index 1 of every group.
    keep = {(e.group_entry.group, e.group_entry.index) for e in (entries[1], entries[3])}
    options, expanded_entries = get_entries_options(
        entries,
        predicate=lambda e: (e.group_entry.group, e.group_entry.index) in keep,
    )

    option_list = OptionList(*options)
    assert len(expanded_entries) == option_list.option_count

    selectable = [
        expanded_entries[i]
        for i in range(option_list.option_count)
        if not option_list.get_option_at_index(i).disabled
    ]
    assert selectable == [entries[1], entries[3]]


def test_predicate_emptying_a_group_drops_its_header_and_divider():
    from textual.widgets import OptionList

    entries = [_entry('group-a', 0), _entry('group-b', 0)]
    # Drop group-b entirely.
    options, expanded_entries = get_entries_options(
        entries, predicate=lambda e: e.group_entry.group == 'group-a'
    )
    option_list = OptionList(*options)
    header_texts = [
        option_list.get_option_at_index(i).prompt
        for i in range(option_list.option_count)
        if option_list.get_option_at_index(i).disabled
    ]
    rendered = ' '.join(str(t) for t in header_texts)
    assert 'group-a' in rendered
    assert 'group-b' not in rendered
    # No divider/entry slot leaked for the dropped group.
    assert all(e is None or e.group_entry.group == 'group-a' for e in expanded_entries)


def test_predicate_recomputes_points_total_over_visible_groups(tmp_path):
    from unittest import mock

    from rbx.box.solutions import GroupSkeleton

    entries = [_entry('g1', 0), _entry('g2', 0)]
    skeleton = _make_skeleton(tmp_path / 'runs', tmp_path / 'tests', stems=['g1-0'])
    skeleton.groups = [
        GroupSkeleton(name='g1', score=50, deps=[], testcases=[]),
        GroupSkeleton(name='g2', score=50, deps=[], testcases=[]),
    ]
    sol = skeleton.solutions[0]

    fake_report = mock.Mock()
    fake_report.gotScorePerGroup = {'g1': 50, 'g2': 50}
    with mock.patch(
        'rbx.box.ui.utils.run_ui.get_solution_outcome_report', return_value=fake_report
    ):
        options, _ = get_entries_options(
            entries,
            skeleton=skeleton,
            solution=sol,
            predicate=lambda e: e.group_entry.group == 'g1',
        )

    texts = ' '.join(
        str(o.prompt) for o in options if hasattr(o, 'prompt')
    )
    # TOTAL reflects only the visible group's score (50/50), not 100.
    assert 'TOTAL' in texts
    assert '100' not in texts
```

### Step 2: Run tests to verify they fail

Run: `uv run pytest tests/rbx/box/ui/test_run_ui.py -k "predicate" -v`
Expected: FAIL — `get_entries_options() got an unexpected keyword argument 'predicate'`.

### Step 3: Implement the predicate

In `rbx/box/ui/utils/run_ui.py`, update the signature and loop. Add `Callable` to the typing import.

```python
from typing import Callable, Dict, List, Optional, Tuple, Union
```

```python
def get_entries_options(
    entries: List[GenerationTestcaseEntry],
    skeleton: Optional[SolutionReportSkeleton] = None,
    solution: Optional[SolutionSkeleton] = None,
    predicate: Optional[Callable[[GenerationTestcaseEntry], bool]] = None,
) -> Tuple[
    List[Union[VisualType, Option, None]], List[Optional[GenerationTestcaseEntry]]
]:
```

Inside the per-group loop, filter first and skip empty groups. Rename the loop
variable to avoid shadowing the `entries` parameter:

```python
    for group, group_entries in entries_per_group.items():
        visible_entries = [
            entry
            for entry in group_entries
            if predicate is None or predicate(entry)
        ]
        if not visible_entries:
            # Filtered to empty: drop the header AND its divider, and do not
            # count this group toward the POINTS total.
            continue

        score_str = ''
        if skeleton is not None:
            group_skeleton = skeleton.find_group_skeleton(group)
            if group_skeleton is not None and group_skeleton.score > 0:
                max_score += group_skeleton.score
                got_score = 0
                if report is not None:
                    got_score = report.gotScorePerGroup.get(group, 0)
                total_got_score += got_score
                score_str = (
                    f' {get_solution_score_markup(got_score, group_skeleton.score)}'
                )
        _add(
            Option(console.expand_markup(f'[b]{group}[/b] {score_str}'), disabled=True)
        )
        for entry in visible_entries:
            if solution is not None and skeleton is not None:
                _add(
                    console.expand_markup(
                        get_run_testcase_markup(skeleton, solution, entry)
                    ),
                    entry,
                )
            else:
                _add(console.expand_markup(f'{entry}'), entry)
        _add(None)
```

The `_add`/`expanded_entries` invariant is untouched, so alignment is preserved.

### Step 4: Run tests to verify they pass

Run: `uv run pytest tests/rbx/box/ui/test_run_ui.py -v`
Expected: PASS (new predicate tests + existing #464/alignment tests).

### Step 5: Commit

```bash
uv run ruff check rbx/box/ui/utils/run_ui.py tests/rbx/box/ui/test_run_ui.py
uv run ruff format rbx/box/ui/utils/run_ui.py tests/rbx/box/ui/test_run_ui.py
git add rbx/box/ui/utils/run_ui.py tests/rbx/box/ui/test_run_ui.py
git commit  # type: feat(ui): add predicate filter to get_entries_options (#548)
```

---

## Task 2: Failing-only toggle (`f`)

**Files:**
- Modify: `rbx/box/ui/screens/run_test_explorer.py`
- Test: `tests/rbx/box/ui/test_run_test_explorer.py`

### Step 1: Add the filterable test harness + failing tests

At the top of `tests/rbx/box/ui/test_run_test_explorer.py`, add imports:

```python
from textual.widgets import Input  # noqa: F401  (used in later tasks)
from rbx.box.generation_schema import GeneratorScriptEntry
from rbx.box.schema import GeneratorCall
from rbx.grading.limits import Limits
from rbx.grading.steps import CheckerResult, Evaluation, Outcome, TestcaseIO, TestcaseLog
```

Add a multi-group skeleton builder and a "real filtering" mount helper. Unlike the
existing `_mounted_run_test_explorer`, this does **not** mock `get_entries_options`
(filtering must run for real); instead it controls per-entry outcomes by mocking
`get_solution_evals`, and mocks `get_solution_entry_prefix` only so the detail pane
does not read missing files.

```python
def _gen_entry(group, index, *, generator_call=None, content=None, script=None,
               copied_from=None):
    te = TestcaseEntry(group=group, index=index)
    md = GenerationMetadata(
        copied_to=Testcase(inputPath=pathlib.Path(f'{group}-{index}.in')),
        generator_call=generator_call,
        content=content,
        generator_script=script,
        copied_from=copied_from,
    )
    return GenerationTestcaseEntry(group_entry=te, subgroup_entry=te, metadata=md)


def _eval(outcome):
    return Evaluation(
        result=CheckerResult(outcome=outcome),
        log=TestcaseLog(),
        testcase=TestcaseIO(index=0),
    )


def _make_multi_skeleton(tmp_path, entries):
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    sol_skel = SolutionSkeleton(**solution.model_dump(), runs_dir=tmp_path / 'runs')
    skeleton = SolutionReportSkeleton(
        solutions=[sol_skel],
        entries=entries,
        groups=[],
        limits={'cpp': Limits(time=1000, memory=256, profile=None, isDoubleTL=False)},
        compiled_solutions={'sol.cpp': 'digest'},
        verification=VerificationLevel.FULL,
    )
    return skeleton, sol_skel


def _mounted_filterable(tmp_path, monkeypatch, entries, outcomes):
    """Mount the screen with REAL get_entries_options filtering.

    ``outcomes`` is a list aligned with ``entries`` (an Outcome or None per entry);
    it drives the precomputed outcome map the failing-only predicate consults.
    """
    from rbx.box.ui.screens import run_test_explorer

    monkeypatch.chdir(tmp_path)
    skeleton, solution = _make_multi_skeleton(tmp_path, entries)

    pkg = mock.Mock()
    pkg.type = TaskType.BATCH
    evals = [(_eval(o) if o is not None else None) for o in outcomes]
    patches = _all(
        mock.patch.object(
            run_test_explorer.package, 'find_problem_package_or_die', return_value=pkg
        ),
        mock.patch.object(
            run_test_explorer.package, 'get_main_solution', return_value=None
        ),
        mock.patch.object(
            run_test_explorer, 'get_solution_evals', return_value=evals
        ),
        mock.patch.object(
            run_test_explorer.SolutionReportSkeleton,
            'get_solution_entry_prefix',
            return_value=tmp_path / 'runs' / 'prefix',
        ),
        mock.patch.object(
            TestcaseEntry, 'get_prefix_path', return_value=tmp_path / 'tests' / 'prefix'
        ),
    )
    screen = run_test_explorer.RunTestExplorerScreen(skeleton, solution)
    return screen, patches


def _row_texts(screen):
    option_list = screen.query_one('#test-list', OptionList)
    return [
        str(option_list.get_option_at_index(i).prompt)
        for i in range(option_list.option_count)
    ]


async def test_f_filters_to_failing_tests_and_drops_ac_and_empty_headers(
    tmp_path, monkeypatch
):
    from rbx.box.ui.main import rbxApp

    entries = [_gen_entry('g1', 0), _gen_entry('g1', 1), _gen_entry('g2', 0)]
    outcomes = [Outcome.ACCEPTED, Outcome.WRONG_ANSWER, Outcome.ACCEPTED]
    screen, patches = _mounted_filterable(tmp_path, monkeypatch, entries, outcomes)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            await pilot.press('f')
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            # Only the WA test in g1 survives; g2 (all AC) header is gone.
            assert 'g1/1' in texts
            assert 'g1/0' not in texts
            assert 'g2' not in texts
            assert 'failing only' in str(
                screen.query_one('#test-list').border_title
            )

            await pilot.press('f')  # toggle back
            await pilot.pause()
            texts = ' '.join(_row_texts(screen))
            assert 'g1/0' in texts and 'g2/0' in texts
            assert str(screen.query_one('#test-list').border_title) == 'Tests'
```

### Step 2: Run to verify it fails

Run: `uv run pytest tests/rbx/box/ui/test_run_test_explorer.py -k "f_filters" -v`
Expected: FAIL — no `f` binding / `failing_only` / outcome precompute yet (rows unchanged after `f`).

### Step 3: Implement failing-only

In `rbx/box/ui/screens/run_test_explorer.py`:

Update imports:
```python
from rbx.box.ui.utils.run_ui import (
    get_entries_options,
    get_run_testcase_metadata_markup,
    get_solution_evals,
    is_main_solution,
)
from rbx.grading.steps import Outcome
```

Add the binding (in `BINDINGS`):
```python
        Binding('f', 'toggle_failing_only', 'Failing only', show=False),
```

Add reactive + state (near `side_by_side`):
```python
    failing_only: reactive[bool] = reactive(False)
```
In `__init__`, after `self._option_entries = []`:
```python
        self._search_query: str = ''
        self._outcomes: dict = {}
```

In `on_mount`, before `await self._update_tests()`, precompute outcomes:
```python
        evals = get_solution_evals(self.skeleton, self.solution)
        self._outcomes = {
            (entry.group_entry.group, entry.group_entry.index): (
                eval.result.outcome if eval is not None else None
            )
            for entry, eval in zip(self.skeleton.entries, evals)
        }
```

Refactor `_update_tests` to set up the watch once and delegate to `_rebuild_options`:
```python
    async def _update_tests(self):
        self.watch(
            self.query_one('#test-list', OptionList),
            'highlighted',
            self._update_selected_test,
        )
        self._rebuild_options()
```

Add the predicate/rebuild/title helpers:
```python
    def _entry_outcome(self, entry: GenerationTestcaseEntry) -> Optional[Outcome]:
        return self._outcomes.get(
            (entry.group_entry.group, entry.group_entry.index)
        )

    def _build_predicate(self):
        failing = self.failing_only
        if not failing:
            return None

        def predicate(entry: GenerationTestcaseEntry) -> bool:
            # Keep non-AC; a missing eval (incomplete run) is treated as not-AC.
            return self._entry_outcome(entry) != Outcome.ACCEPTED

        return predicate

    def _list_title(self) -> str:
        bits = []
        if self.failing_only:
            bits.append('failing only')
        if self._search_query.strip():
            bits.append('search')
        return 'Tests' + (f' ({", ".join(bits)})' if bits else '')

    def _rebuild_options(self) -> None:
        options, self._option_entries = get_entries_options(
            self.skeleton.entries,
            skeleton=self.skeleton,
            solution=self.solution,
            predicate=self._build_predicate(),
        )
        option_list = self.query_one('#test-list', OptionList)
        option_list.clear_options()
        option_list.add_options(options)
        self.query_one('#test-list').border_title = self._list_title()

    def action_toggle_failing_only(self) -> None:
        self.failing_only = not self.failing_only

    def watch_failing_only(self, value: bool) -> None:
        if not self.is_mounted:
            return
        self._rebuild_options()
```

### Step 4: Run to verify it passes

Run: `uv run pytest tests/rbx/box/ui/test_run_test_explorer.py -k "f_filters" -v`
Expected: PASS.
Also: `uv run pytest tests/rbx/box/ui/test_run_test_explorer.py -v` (existing tests still pass — `get_entries_options` mock still returns its tuple; `border_title` becomes `Tests`).

### Step 5: Commit

```bash
uv run ruff check rbx/box/ui/screens/run_test_explorer.py tests/rbx/box/ui/test_run_test_explorer.py
uv run ruff format rbx/box/ui/screens/run_test_explorer.py tests/rbx/box/ui/test_run_test_explorer.py
git add rbx/box/ui/screens/run_test_explorer.py tests/rbx/box/ui/test_run_test_explorer.py
git commit  # feat(ui): failing-only test filter in run explorer (#548)
```

---

## Task 3: Fuzzy search box (`/`, live filter, highlight best)

**Files:**
- Modify: `rbx/box/ui/screens/run_test_explorer.py`
- Modify: `rbx/box/ui/css/app.tcss`
- Test: `tests/rbx/box/ui/test_run_test_explorer.py`

### Step 1: Write failing tests

```python
async def test_slash_opens_and_focuses_search_box(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [_gen_entry('g1', 0)]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            search = screen.query_one('#test-search', Input)
            assert search.display is False

            await pilot.press('slash')
            await pilot.pause()
            assert search.display is True
            assert search.has_focus


async def test_search_filters_by_generator_call_and_highlights_best(
    tmp_path, monkeypatch
):
    from rbx.box.ui.main import rbxApp

    entries = [
        _gen_entry('g1', 0, generator_call=GeneratorCall(name='gen_small', args='1')),
        _gen_entry('g1', 1, generator_call=GeneratorCall(name='gen_huge', args='999')),
    ]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            await pilot.press('slash')
            search = screen.query_one('#test-search', Input)
            search.value = 'huge'
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            assert 'g1/1' in texts
            assert 'g1/0' not in texts


async def test_search_matches_inline_content_and_script_location(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [
        _gen_entry('g1', 0, content='alpha beta gamma'),
        _gen_entry(
            'g1', 1,
            script=GeneratorScriptEntry(path=pathlib.Path('gen.txt'), line=42),
        ),
    ]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            search = screen.query_one('#test-search', Input)

            search.value = 'gamma'
            await pilot.pause()
            assert 'g1/0' in ' '.join(_row_texts(screen))
            assert 'g1/1' not in ' '.join(_row_texts(screen))

            search.value = 'gen.txt'
            await pilot.pause()
            assert 'g1/1' in ' '.join(_row_texts(screen))
            assert 'g1/0' not in ' '.join(_row_texts(screen))


async def test_numeric_query_matches_group_index(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [_gen_entry('g1', 0), _gen_entry('g1', 1), _gen_entry('g2', 1)]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED] * 3
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            search = screen.query_one('#test-search', Input)
            search.value = '1'
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            assert 'g1/1' in texts and 'g2/1' in texts
            assert 'g1/0' not in texts
```

### Step 2: Run to verify they fail

Run: `uv run pytest tests/rbx/box/ui/test_run_test_explorer.py -k "search or slash or numeric" -v`
Expected: FAIL — no `#test-search`, no `slash` binding.

### Step 3: Implement the search box

Imports:
```python
from textual.widgets import Footer, Header, Input, OptionList
from textual.fuzzy import Matcher
```

Add binding:
```python
        Binding('slash', 'focus_search', 'Search', show=False),
```

In `compose`, add the Input at the top of the list container:
```python
            with Vertical(id='test-list-container'):
                yield Input(id='test-search', placeholder='Search tests…')
                yield OptionList(id='test-list')
```

In `on_mount`, after setting the list border title, hide + title the search box:
```python
        search = self.query_one('#test-search', Input)
        search.display = False
        search.border_title = 'Search'
```

Extend `_build_predicate` to compose failing-only AND search:
```python
    def _search_text(self, entry: GenerationTestcaseEntry) -> str:
        md = entry.metadata
        parts = [f'{entry.group_entry.group}/{entry.group_entry.index}']
        if md.generator_call is not None:
            parts.append(str(md.generator_call))
        if md.copied_from is not None:
            parts.append(str(md.copied_from.inputPath))
        if md.content is not None:
            parts.append(md.content)
        if md.generator_script is not None:
            parts.append(str(md.generator_script))
        return ' '.join(parts)

    def _build_predicate(self):
        failing = self.failing_only
        query = self._search_query.strip()
        if not failing and not query:
            return None

        numeric = int(query) if query.isdigit() else None
        matcher = Matcher(query) if (query and numeric is None) else None

        def predicate(entry: GenerationTestcaseEntry) -> bool:
            if failing and self._entry_outcome(entry) == Outcome.ACCEPTED:
                return False
            if numeric is not None:
                return entry.group_entry.index == numeric
            if matcher is not None:
                return matcher.match(self._search_text(entry)) > 0
            return True

        return predicate
```

Add highlight-best after a rebuild driven by search, and the focus action +
Changed handler:
```python
    def _first_selectable_index(self) -> Optional[int]:
        for i, entry in enumerate(self._option_entries):
            if entry is not None:
                return i
        return None

    def _highlight_best_match(self) -> None:
        option_list = self.query_one('#test-list', OptionList)
        query = self._search_query.strip()
        best_index = None
        if query and not query.isdigit():
            matcher = Matcher(query)
            best_score = 0.0
            for i, entry in enumerate(self._option_entries):
                if entry is None:
                    continue
                score = matcher.match(self._search_text(entry))
                if score > best_score:
                    best_score = score
                    best_index = i
        if best_index is None:
            best_index = self._first_selectable_index()
        if best_index is not None:
            option_list.highlighted = best_index

    def action_focus_search(self) -> None:
        search = self.query_one('#test-search', Input)
        search.display = True
        search.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != 'test-search':
            return
        self._search_query = event.value
        self._rebuild_options()
        self._highlight_best_match()
```

### Step 4: CSS

In `rbx/box/ui/css/app.tcss`, inside the `TestExplorerScreen, RunTestExplorerScreen`
block (near the `#test-list` rule), add:
```css
        #test-search {
                display: none;
                width: 1fr;
                border: solid $accent;
        }
```

### Step 5: Run to verify they pass

Run: `uv run pytest tests/rbx/box/ui/test_run_test_explorer.py -k "search or slash or numeric" -v`
Expected: PASS.

### Step 6: Commit

```bash
uv run ruff check rbx/box/ui/screens/run_test_explorer.py tests/rbx/box/ui/test_run_test_explorer.py
uv run ruff format rbx/box/ui/screens/run_test_explorer.py tests/rbx/box/ui/test_run_test_explorer.py
git add rbx/box/ui/screens/run_test_explorer.py rbx/box/ui/css/app.tcss tests/rbx/box/ui/test_run_test_explorer.py
git commit  # feat(ui): fuzzy test search box in run explorer (#548)
```

---

## Task 4: Goto (Enter) + Esc cancel + compose with failing-only

**Files:**
- Modify: `rbx/box/ui/screens/run_test_explorer.py`
- Test: `tests/rbx/box/ui/test_run_test_explorer.py`

### Step 1: Write failing tests

```python
async def test_enter_commits_goto_restores_list_and_keeps_match(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [
        _gen_entry('g1', 0, generator_call=GeneratorCall(name='gen_small', args='1')),
        _gen_entry('g1', 1, generator_call=GeneratorCall(name='gen_huge', args='9')),
    ]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            screen.query_one('#test-search', Input).value = 'huge'
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()

            search = screen.query_one('#test-search', Input)
            option_list = screen.query_one('#test-list', OptionList)
            assert search.display is False
            # Full list restored (both rows present)...
            assert 'g1/0' in ' '.join(_row_texts(screen))
            # ...and the matched test is highlighted.
            assert option_list.highlighted is not None
            entry = screen._option_entries[option_list.highlighted]
            assert entry is not None and entry.group_entry.index == 1
            assert option_list.has_focus


async def test_escape_restores_list_without_jumping(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [_gen_entry('g1', 0), _gen_entry('g1', 1)]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            screen.query_one('#test-search', Input).value = '1'
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()

            search = screen.query_one('#test-search', Input)
            assert search.display is False
            assert search.value == ''
            assert 'g1/0' in ' '.join(_row_texts(screen))
            assert str(screen.query_one('#test-list').border_title) == 'Tests'


async def test_search_and_failing_only_compose(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [
        _gen_entry('g1', 0, generator_call=GeneratorCall(name='gen_x', args='1')),
        _gen_entry('g1', 1, generator_call=GeneratorCall(name='gen_x', args='2')),
    ]
    # index 0 AC, index 1 WA -> failing-only keeps index 1; both match 'gen_x'.
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.WRONG_ANSWER]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('f')
            await pilot.press('slash')
            screen.query_one('#test-search', Input).value = 'gen_x'
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            assert 'g1/1' in texts
            assert 'g1/0' not in texts  # filtered by failing-only despite matching
```

### Step 2: Run to verify they fail

Run: `uv run pytest tests/rbx/box/ui/test_run_test_explorer.py -k "enter_commits or escape_restores or compose" -v`
Expected: FAIL — no Submitted/escape handling.

### Step 3: Implement goto + cancel

Add `escape` binding:
```python
        Binding('escape', 'cancel_search', 'Cancel search', show=False),
```

Add a suppression guard in `__init__`:
```python
        self._suppress_search_change: bool = False
```

Guard the Changed handler so programmatic resets do not re-trigger filtering:
```python
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != 'test-search' or self._suppress_search_change:
            return
        self._search_query = event.value
        self._rebuild_options()
        self._highlight_best_match()
```

Add helpers + handlers:
```python
    def _highlighted_entry(self) -> Optional[GenerationTestcaseEntry]:
        option_list = self.query_one('#test-list', OptionList)
        index = option_list.highlighted
        if index is None or index >= len(self._option_entries):
            return None
        return self._option_entries[index]

    def _option_index_of(
        self, target: GenerationTestcaseEntry
    ) -> Optional[int]:
        for i, entry in enumerate(self._option_entries):
            if entry is target:
                return i
        return None

    def _close_search(self) -> None:
        search = self.query_one('#test-search', Input)
        self._suppress_search_change = True
        search.value = ''
        self._suppress_search_change = False
        search.display = False
        self._search_query = ''

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'test-search':
            return
        event.stop()
        target = self._highlighted_entry()
        self._close_search()
        self._rebuild_options()
        option_list = self.query_one('#test-list', OptionList)
        if target is not None:
            index = self._option_index_of(target)
            if index is not None:
                option_list.highlighted = index
        option_list.focus()

    def action_cancel_search(self) -> None:
        search = self.query_one('#test-search', Input)
        if not (search.display or search.has_focus):
            return
        self._close_search()
        self._rebuild_options()
        self.query_one('#test-list', OptionList).focus()
```

Note: `Input` binds `enter` to `submit` (verified) and does **not** bind `escape`,
so the screen-level `escape` binding fires while the box is focused.

### Step 4: Run to verify they pass

Run: `uv run pytest tests/rbx/box/ui/test_run_test_explorer.py -k "enter_commits or escape_restores or compose" -v`
Expected: PASS.

### Step 5: Commit

```bash
uv run ruff check rbx/box/ui/screens/run_test_explorer.py tests/rbx/box/ui/test_run_test_explorer.py
uv run ruff format rbx/box/ui/screens/run_test_explorer.py tests/rbx/box/ui/test_run_test_explorer.py
git add rbx/box/ui/screens/run_test_explorer.py tests/rbx/box/ui/test_run_test_explorer.py
git commit  # feat(ui): goto + cancel for test search box (#548)
```

---

## Task 5: Full-suite verification + help-panel sanity

**Files:** none expected (verification only; small tweaks if needed).

### Step 1: Run the full UI test module and the run_ui module

Run:
```bash
uv run pytest tests/rbx/box/ui/test_run_test_explorer.py tests/rbx/box/ui/test_run_ui.py tests/rbx/box/ui/test_help_panel.py tests/rbx/box/ui/test_vim_nav.py -v
```
Expected: all PASS. The new `f` / `/` / `escape` bindings appear in the help panel
under the `Run Test Explorer` group automatically (they are screen `BINDINGS` with
`BINDING_GROUP_TITLE` already set); confirm `test_help_panel.py` still passes.

### Step 2: Lint + format the whole tree

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

### Step 3: Broader regression (UI + box, exclude slow CLI)

Run: `uv run pytest tests/rbx/box/ui --ignore=tests/rbx/box/cli -q`
Expected: PASS (pre-existing C++/sandbox/docker failures, if any, are environmental
per project memory — confirm they are unrelated to these files).

### Step 4: Manual smoke (optional, if a built package is handy)

`uv run rbx ui` → run results → pick a solution → press `f` (failing only), `/`
(search: type a generator name / number, Enter to jump, Esc to clear).

### Step 5: Commit any fixups, then finish

If Steps 1–3 required changes, commit them (`fix(ui): …` or `test(ui): …`).
Otherwise proceed to `superpowers:finishing-a-development-branch` to open the PR
(`feat(ui): test-list filtering + fancy search box (#548)`), referencing #548 and
the umbrella #326, and noting the B-before-C sequencing for #549.

---

## Risks / watch-outs

- **#464 invariant** is the highest-risk area — Task 1's alignment test is the guard.
  Never give a `None` divider an `expanded_entries` slot.
- **Reactive watcher timing**: `watch_failing_only` must early-return before mount
  (`self.is_mounted`) or `query_one` raises during construction.
- **Programmatic `Input.value` resets** re-fire `Input.Changed`; the
  `_suppress_search_change` guard prevents a double rebuild / lost highlight.
- **Existing screen tests** mock `get_entries_options` (returns a fixed tuple) and do
  not mock `get_solution_evals`; the new on-mount precompute reads zero `.eval`
  files and yields an all-`None` outcome map — harmless. Keep that behavior.
- **Detail-pane rendering** on highlight needs `get_solution_entry_prefix` mocked in
  the filterable tests (done) so it never reads missing files.
