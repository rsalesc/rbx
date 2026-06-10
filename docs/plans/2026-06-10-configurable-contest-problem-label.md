# Configurable Contest Problem Label Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the problem label shown in the `rbx on` / `rbx each` command-app sidebar configurable (name / title / path) and persistent, with an in-app key to cycle the mode live.

**Architecture:** Add a `ui.problem_label` setting (enum) to the persisted `SetterConfig`. Refactor `naming.get_contest_problem_label` into a pure formatter plus wrappers that read the config and expose all three label variants. Thread the three precomputed variants into `CommandEntry` so the Textual `rbxCommandApp` can swap them with an `l` keybinding that persists the choice.

**Tech Stack:** Python 3, Pydantic v2, Typer, Textual, pytest. Single quotes, absolute imports only (ruff `TID`). Tests via `uv run pytest`.

Design doc: `docs/plans/2026-06-10-configurable-contest-problem-label-design.md`.

---

## Task 1: Add `ProblemLabelMode` + `UIConfig` to SetterConfig

**Files:**
- Modify: `rbx/box/setter_config.py` (add enum, model, field; `enum` is already imported? check — add `import enum` if missing)
- Modify: `rbx/resources/default_setter_config.yml`
- Modify: `rbx/resources/default_setter_config.mac.yml`
- Test: `tests/rbx/box/test_setter_config.py` (create if absent)

**Step 1: Write the failing test**

Check whether `tests/rbx/box/test_setter_config.py` exists. If not, create it. Add:

```python
from rbx.box import setter_config
from rbx.box.setter_config import ProblemLabelMode, SetterConfig


def test_ui_problem_label_defaults_to_name():
    cfg = SetterConfig()
    assert cfg.ui.problem_label is ProblemLabelMode.NAME


def test_ui_config_absent_key_defaults_to_name():
    # Configs predating this change have no `ui:` key.
    cfg = SetterConfig.model_validate({})
    assert cfg.ui.problem_label is ProblemLabelMode.NAME


def test_default_resource_setter_config_parses_with_ui():
    cfg = setter_config.get_default_setter_config()
    assert cfg.ui.problem_label is ProblemLabelMode.NAME
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_setter_config.py -v`
Expected: FAIL with `ImportError` / `AttributeError` (no `ProblemLabelMode` / no `cfg.ui`).

**Step 3: Write minimal implementation**

In `rbx/box/setter_config.py`, ensure `import enum` is present at the top. Add near the other config models (before `class SetterConfig`):

```python
class ProblemLabelMode(str, enum.Enum):
    """What to display after the short name in the contest command-app sidebar.

    Iteration order defines the in-app cycle order.
    """

    NAME = 'name'
    TITLE = 'title'
    PATH = 'path'


class UIConfig(BaseModel):
    problem_label: ProblemLabelMode = Field(
        default=ProblemLabelMode.NAME,
        description='What to show after the short name in the `rbx on`/`rbx each` '
        'sidebar: `name` (problem name), `title` (the single problem title, '
        'falling back to the name), or `path` (problem path relative to the '
        'contest). Press `l` in that UI to cycle this live.',
    )
```

Add the field to `SetterConfig` (after `judging`):

```python
    ui: UIConfig = Field(
        default_factory=UIConfig,
        description='Configuration for the interactive UI.',
    )
```

In BOTH `rbx/resources/default_setter_config.yml` and `default_setter_config.mac.yml`, append:

```yaml

# How problems are labeled in the `rbx on` / `rbx each` command-app sidebar.
# Press `l` in that UI to cycle this setting live.
#
# name:  problem name from problem.rbx.yml (default)
# title: the problem's title, if it has exactly one; otherwise the name
# path:  problem path relative to the contest
ui:
  problem_label: name
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/test_setter_config.py -v`
Expected: PASS (all three).

**Step 5: Commit**

```bash
git add rbx/box/setter_config.py rbx/resources/default_setter_config.yml \
        rbx/resources/default_setter_config.mac.yml tests/rbx/box/test_setter_config.py
git commit -m "feat(config): add ui.problem_label setter setting"
```

---

## Task 2: Pure label formatter + helpers in `naming.py`

**Files:**
- Modify: `rbx/box/naming.py` (add `Dict` to typing import; add `setter_config` import; refactor `get_contest_problem_label`; add `format_contest_problem_label`, `_single_title`, `get_contest_problem_labels`)
- Test: `tests/rbx/box/test_naming.py` (extend `TestGetContestProblemLabel`, add new test classes)

**Step 1: Write the failing tests**

In `tests/rbx/box/test_naming.py`, add `from rbx.box.setter_config import ProblemLabelMode` to imports. Add:

```python
class TestFormatContestProblemLabel:
    def test_name_mode(self):
        assert (
            naming.format_contest_problem_label(
                'A', name='Two Sum', title='T', path=pathlib.Path('A'),
                mode=ProblemLabelMode.NAME,
            )
            == 'A. Two Sum'
        )

    def test_title_mode_uses_title(self):
        assert (
            naming.format_contest_problem_label(
                'A', name='two-sum', title='Two Sum', path=pathlib.Path('A'),
                mode=ProblemLabelMode.TITLE,
            )
            == 'A. Two Sum'
        )

    def test_title_mode_falls_back_to_name(self):
        assert (
            naming.format_contest_problem_label(
                'A', name='two-sum', title=None, path=pathlib.Path('A'),
                mode=ProblemLabelMode.TITLE,
            )
            == 'A. two-sum'
        )

    def test_path_mode(self):
        assert (
            naming.format_contest_problem_label(
                'A', name='two-sum', title='Two Sum',
                path=pathlib.Path('probs/two-sum'), mode=ProblemLabelMode.PATH,
            )
            == 'A. probs/two-sum'
        )

    def test_empty_suffix_falls_back_to_short_name(self):
        assert (
            naming.format_contest_problem_label(
                'B', name=None, title=None, path=None, mode=ProblemLabelMode.NAME,
            )
            == 'B'
        )


class TestSingleTitle:
    def test_one_title(self):
        pkg = Package(name='n', timeLimit=1000, memoryLimit=256, titles={'en': 'Hello'})
        assert naming._single_title(pkg) == 'Hello'

    def test_no_titles(self):
        pkg = Package(name='n', timeLimit=1000, memoryLimit=256)
        assert naming._single_title(pkg) is None

    def test_multiple_titles(self):
        pkg = Package(
            name='n', timeLimit=1000, memoryLimit=256,
            titles={'en': 'Hello', 'pt': 'Ola'},
        )
        assert naming._single_title(pkg) is None


class TestGetContestProblemLabels:
    def test_returns_all_three_variants(self):
        problem = ContestProblem(short_name='A', path=pathlib.Path('probs/two-sum'))
        pkg = Package(
            name='two-sum', timeLimit=1000, memoryLimit=256, titles={'en': 'Two Sum'},
        )
        with patch('rbx.box.naming.package.find_problem_package', return_value=pkg):
            labels = naming.get_contest_problem_labels(problem)
        assert labels == {
            ProblemLabelMode.NAME: 'A. two-sum',
            ProblemLabelMode.TITLE: 'A. Two Sum',
            ProblemLabelMode.PATH: 'A. probs/two-sum',
        }
```

> Verify the `Package` constructor's required fields by checking an existing
> `Package(...)` call in `tests/rbx/box/test_naming.py::TestGetTitle`
> (around line 287). Match its required kwargs (e.g. `timeLimit`, `memoryLimit`)
> exactly; adjust the snippets above if they differ.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_naming.py -k "Format or SingleTitle or Labels" -v`
Expected: FAIL with `AttributeError` (functions not defined yet).

**Step 3: Write minimal implementation**

In `rbx/box/naming.py`:
- Change `from typing import List, Optional, Tuple` → add `Dict`.
- Add `from rbx.box import setter_config` (alongside `from rbx.box import package`). Import `ProblemLabelMode` lazily inside functions OR at top: `from rbx.box.setter_config import ProblemLabelMode`. Verify no import cycle (`setter_config` does not import `naming`).

Replace the existing `get_contest_problem_label` body with:

```python
def format_contest_problem_label(
    short_name: str,
    *,
    name: Optional[str],
    title: Optional[str],
    path: Optional[pathlib.Path],
    mode: ProblemLabelMode,
) -> str:
    """Pure formatter: '<short_name>. <suffix>' or bare short name when empty."""
    if mode is ProblemLabelMode.PATH:
        suffix = str(path) if path is not None else None
    elif mode is ProblemLabelMode.TITLE:
        suffix = title or name
    else:
        suffix = name
    if not suffix:
        return short_name
    return f'{short_name}. {suffix}'


def _single_title(pkg: Package) -> Optional[str]:
    if len(pkg.titles) == 1:
        return next(iter(pkg.titles.values()))
    return None


def get_contest_problem_label(problem: ContestProblem) -> str:
    """Human-readable label for a contest problem, honoring the configured mode.

    Falls back to just the short name when the problem package cannot be
    loaded (e.g. missing or broken problem.rbx.yml) or has no usable suffix.
    """
    mode = setter_config.get_setter_config().ui.problem_label
    pkg = package.find_problem_package(problem.get_path())
    return format_contest_problem_label(
        problem.short_name,
        name=pkg.name if pkg is not None else None,
        title=_single_title(pkg) if pkg is not None else None,
        path=problem.get_path(),
        mode=mode,
    )


def get_contest_problem_labels(
    problem: ContestProblem,
) -> Dict[ProblemLabelMode, str]:
    """All label variants from a single package load, for the command-app UI."""
    pkg = package.find_problem_package(problem.get_path())
    name = pkg.name if pkg is not None else None
    title = _single_title(pkg) if pkg is not None else None
    return {
        mode: format_contest_problem_label(
            problem.short_name, name=name, title=title,
            path=problem.get_path(), mode=mode,
        )
        for mode in ProblemLabelMode
    }
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_naming.py -v`
Expected: PASS, including the pre-existing `TestGetContestProblemLabel` (default mode is `name`, so `'A. Two Sum'` / `'B'` / `'C'` still hold). If those three now require a `ui` config: they patch `find_problem_package` and `get_setter_config()` defaults to `name`, so they pass unchanged. Confirm.

**Step 5: Run ruff**

Run: `uv run ruff check rbx/box/naming.py && uv run ruff format --check rbx/box/naming.py`
Expected: clean (fix import ordering if flagged).

**Step 6: Commit**

```bash
git add rbx/box/naming.py tests/rbx/box/test_naming.py
git commit -m "refactor(naming): configurable contest problem label formatter"
```

---

## Task 3: Honor configured mode in `get_contest_problem_label`

This validates the wiring end-to-end through the config (Task 2 added the code;
this task adds the behavioral test that proves the mode is read).

**Files:**
- Test: `tests/rbx/box/test_naming.py` (add a class that patches the config)

**Step 1: Write the failing/again-passing test**

```python
class TestGetContestProblemLabelHonorsConfig:
    def _patch_mode(self, mode):
        cfg = setter_config.SetterConfig()
        cfg.ui.problem_label = mode
        return patch('rbx.box.naming.setter_config.get_setter_config', return_value=cfg)

    def test_title_mode_single_title(self):
        problem = ContestProblem(short_name='A', path=pathlib.Path('a'))
        pkg = Package(name='two-sum', timeLimit=1000, memoryLimit=256,
                      titles={'en': 'Two Sum'})
        with patch('rbx.box.naming.package.find_problem_package', return_value=pkg), \
             self._patch_mode(setter_config.ProblemLabelMode.TITLE):
            assert naming.get_contest_problem_label(problem) == 'A. Two Sum'

    def test_title_mode_multiple_titles_falls_back_to_name(self):
        problem = ContestProblem(short_name='A', path=pathlib.Path('a'))
        pkg = Package(name='two-sum', timeLimit=1000, memoryLimit=256,
                      titles={'en': 'Two Sum', 'pt': 'Dois Numeros'})
        with patch('rbx.box.naming.package.find_problem_package', return_value=pkg), \
             self._patch_mode(setter_config.ProblemLabelMode.TITLE):
            assert naming.get_contest_problem_label(problem) == 'A. two-sum'

    def test_path_mode(self):
        problem = ContestProblem(short_name='A', path=pathlib.Path('probs/a'))
        pkg = Package(name='two-sum', timeLimit=1000, memoryLimit=256)
        with patch('rbx.box.naming.package.find_problem_package', return_value=pkg), \
             self._patch_mode(setter_config.ProblemLabelMode.PATH):
            assert naming.get_contest_problem_label(problem) == 'A. probs/a'
```

Add `from rbx.box import setter_config` to the test imports if not present.

**Step 2: Run to verify they pass**

Run: `uv run pytest tests/rbx/box/test_naming.py::TestGetContestProblemLabelHonorsConfig -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/rbx/box/test_naming.py
git commit -m "test(naming): cover configured label modes"
```

---

## Task 4: Thread label variants into `CommandEntry` (contest call sites)

**Files:**
- Modify: `rbx/box/ui/command_app.py` (`CommandEntry` dataclass: add `labels` field + import)
- Modify: `rbx/box/contest/main.py:366-374` (`each`) and `:408-415` (`on`)

**Step 1: Add the field**

In `rbx/box/ui/command_app.py`:
- Import at top: `from rbx.box.setter_config import ProblemLabelMode`. Verify no cycle (setter_config imports `rbx.config`, `console`, `utils`, grading — not `box.ui`).
- Add to the `CommandEntry` dataclass (after `placeholder_prefix`):

```python
    labels: Optional[Dict[ProblemLabelMode, str]] = None
```

- Add `Dict` to the typing import line (`from typing import Dict, List, Optional, Tuple`).

**Step 2: Wire the call sites**

In `rbx/box/contest/main.py`, both `CommandEntry(...)` builders (`each` and the
multi-problem branch of `on`) add a `labels=` kwarg:

```python
        CommandEntry(
            argv=argv,
            placeholder_prefix=placeholder_prefix,
            name=naming.get_contest_problem_label(problem),
            labels=naming.get_contest_problem_labels(problem),
            cwd=str(problem.get_path()),
        )
```

(Use `p` instead of `problem` in the `on` branch to match the existing loop var.)

**Step 3: Verify it imports / runs**

Run: `uv run python -c "import rbx.box.ui.command_app, rbx.box.contest.main"`
Expected: no ImportError (no cycle).

Run: `uv run ruff check rbx/box/ui/command_app.py rbx/box/contest/main.py`
Expected: clean.

**Step 4: Commit**

```bash
git add rbx/box/ui/command_app.py rbx/box/contest/main.py
git commit -m "feat(contest): pass all label variants to command app"
```

---

## Task 5: Render the configured label in the sidebar

**Files:**
- Modify: `rbx/box/ui/command_app.py` (`rbxCommandApp.__init__`, `_make_tab_label`, add `_entry_label`)

**Step 1: Seed the mode in `__init__`**

Import at top: `from rbx.box.setter_config import get_setter_config, save_setter_config`
(keep the `ProblemLabelMode` import from Task 4).

In `rbxCommandApp.__init__`, after `self._active_tab = 0`, add:

```python
        self._label_mode = get_setter_config().ui.problem_label
```

**Step 2: Use it when rendering**

Add a helper and update `_make_tab_label`:

```python
    def _entry_label(self, entry: CommandEntry) -> str:
        if entry.labels:
            return entry.labels.get(self._label_mode) or entry.display_name
        return entry.display_name

    def _make_tab_label(self, index: int) -> str:
        tab = self._tabs[index]
        icon = _STATUS_MARKUP[tab.aggregate_status]
        name = self._entry_label(tab.entry)
        return f'{icon} {name}'
```

**Step 3: Verify import/format**

Run: `uv run python -c "import rbx.box.ui.command_app"` → no error.
Run: `uv run ruff check rbx/box/ui/command_app.py` → clean.

**Step 4: Commit**

```bash
git add rbx/box/ui/command_app.py
git commit -m "feat(ui): render configured problem label in command app sidebar"
```

---

## Task 6: `l` keybinding cycles + persists the label mode

**Files:**
- Modify: `rbx/box/ui/command_app.py` (`on_key`, add `_cycle_problem_label`, update `HelpModal`)

**Step 1: Add the cycle action**

In `rbxCommandApp`, add:

```python
    def _cycle_problem_label(self) -> None:
        modes = list(ProblemLabelMode)
        nxt = modes[(modes.index(self._label_mode) + 1) % len(modes)]
        self._label_mode = nxt
        cfg = get_setter_config()
        cfg.ui.problem_label = nxt
        save_setter_config(cfg)
        for i in range(len(self._tabs)):
            self._update_sidebar(i)
        self.notify(f'Problem label: {nxt.value}')
```

**Step 2: Intercept `l` when the sidebar is focused**

In `on_key`, inside the `focused is sidebar` region (after the `right` handler,
before the `?` handler), add:

```python
        if event.character == 'l' and any(t.entry.labels for t in self._tabs):
            event.stop()
            event.prevent_default()
            self._cycle_problem_label()
            return
```

The `any(... labels ...)` guard keeps `l` falling through to vim-nav for
label-less entries (e.g. the `__main__` demo).

**Step 3: Document it in `HelpModal`**

In `HelpModal.compose`, in the "Sidebar (command list)" `Label`, add a line
after the `← / →` row:

```
                '  [b]l[/b]           Cycle problem label (name/title/path)\n'
```

**Step 4: Manual smoke check (no automated TUI harness)**

Run: `uv run python rbx/box/ui/command_app.py`
- The demo entries have no `labels`, so `l` is inert (correct).
- Confirm the app launches, sidebar shows `echo1/echo2/echo3`, `?` shows help,
  `q` quits. (The `l` behavior with real labels is verified via `rbx on`/`each`
  in a contest fixture in Task 8.)

Run: `uv run ruff check rbx/box/ui/command_app.py && uv run ruff format --check rbx/box/ui/command_app.py`
Expected: clean.

**Step 5: Commit**

```bash
git add rbx/box/ui/command_app.py
git commit -m "feat(ui): cycle and persist problem label with l key"
```

---

## Task 7: Full test + lint sweep

**Step 1: Run the affected suites**

Run:
```bash
uv run pytest tests/rbx/box/test_naming.py tests/rbx/box/test_setter_config.py -v
```
Expected: all PASS.

**Step 2: Broader regression (config + naming consumers)**

Run: `uv run pytest tests/rbx/box -k "naming or setter or config or contest" -n auto`
Expected: PASS (or only the known pre-existing failures noted in memory — none
expected to touch this area).

**Step 3: Lint + format the whole change**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

**Step 4: Commit any formatting fixups (if needed)**

```bash
git add -u
git commit -m "style: ruff format"
```

(Skip if nothing changed.)

---

## Task 8: Manual end-to-end verification in a contest fixture

**Goal:** Prove the label modes + `l` cycling work against a real contest.

**Step 1: Find or build a contest fixture**

Look under `tests/` / `testdata/` for a contest package with ≥2 problems and at
least one problem that has a single `titles:` entry. If none exists, create a
throwaway one in a temp dir: a `contest.rbx.yml` with two `problems` (`A`, `B`)
and minimal `problem.rbx.yml` files (one with `titles: {en: "Two Sum"}`).

**Step 2: Run `rbx each` / `rbx on`**

From the contest dir:
```bash
uv run rbx each   # or: uv run rbx on "*"
```
- Sidebar shows `A. <name>` by default.
- Press `l`: cycles to `title` (shows the single title where present, name
  otherwise), then `path`, then back to `name`. A toast shows the mode.
- Quit (`q`), relaunch: the last-cycled mode persists (read from
  `~/.config/rbx/setter_config.yml`).

**Step 3: Confirm persistence on disk**

Run: `uv run rbx config list` (or open the file) → `ui.problem_label` reflects
the last cycled value.

**Step 4: Reset for cleanliness (optional)**

Set it back to `name` via `rbx config edit` or by editing the file, if you
changed your personal config during testing.

---

## Done criteria

- `ui.problem_label` exists in `SetterConfig`, defaults to `name`, documented in
  both resource files; old configs without `ui:` still load.
- `naming` exposes a pure formatter + `get_contest_problem_labels`;
  `get_contest_problem_label` honors the configured mode.
- Command app renders the configured label and cycles+persists with `l`
  (documented in `HelpModal`).
- All new + existing `test_naming.py` / `test_setter_config.py` tests pass;
  ruff clean.
- Manual `rbx each` smoke test confirms cycling + persistence.
