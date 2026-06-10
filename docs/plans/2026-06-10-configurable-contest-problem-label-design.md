# Configurable contest problem label — Design

Tracking issue: [#582 — The command app UI shown by `rbx on` and `rbx each` should show problem names](https://github.com/rsalesc/rbx/issues/582)
Status: **approved design**, ready for implementation.
Date: 2026-06-10

## 1. Motivation

The command app launched by `rbx on` and `rbx each` shows a sidebar listing the
contest problems. Since #467 each entry already reads `A. {problem_name}` (via
`naming.get_contest_problem_label`), not just the bare short name. The remaining
ask in #582 is to make **what is shown after the short name configurable and
persistent**, with three modes:

- `name` — the problem name from `problem.rbx.yml` (default, current behavior)
- `title` — the problem's statement title, falling back to the name
- `path` — the problem path relative to the contest

## 2. Decisions (resolved during brainstorming)

1. **Config home = `SetterConfig`.** The setting lives in
   `~/.config/rbx/setter_config.yml` (editable via `rbx config edit`), matching
   the existing persistent-preference pattern and the issue's `ui` label. Not in
   `config.json` (that file is about languages/credentials).
2. **In-app cycle key.** Besides the config file, the command app gets a key
   (`l`, mnemonic = **l**abel) that cycles `name → title → path` live and
   persists the choice. Chosen over a config-file-only approach for TUI
   ergonomics.
3. **Separator unchanged.** Labels stay `A. {suffix}` (period + space). The
   issue's `A - {name}` was described loosely ("something like"); keeping `. `
   avoids churn and keeps the three existing `test_naming.py` assertions green.
4. **Title language = auto.** No language-selection field. `title` mode uses the
   problem's title only when the package has **exactly one** title; with zero or
   multiple titles it falls back to the name. (`config.defaultLanguage` is a
   *programming* language, so it cannot drive this; an explicit human-language
   field was rejected as YAGNI for now.)
5. **No new CLI subcommand.** Editing the config file plus the `l` key satisfy
   "persistent option to configure"; a dedicated `rbx config set ...` command is
   out of scope.

## 3. Components

### 3.1 `SetterConfig` (`rbx/box/setter_config.py`)

```python
class ProblemLabelMode(str, enum.Enum):   # iteration order defines the cycle
    NAME = 'name'
    TITLE = 'title'
    PATH = 'path'

class UIConfig(BaseModel):
    problem_label: ProblemLabelMode = Field(
        default=ProblemLabelMode.NAME,
        description=...,
    )

class SetterConfig(BaseModel):
    ...
    ui: UIConfig = Field(default_factory=UIConfig, ...)
```

Documented (with the three modes and the `l`-to-cycle hint) in both
`rbx/resources/default_setter_config.yml` and `default_setter_config.mac.yml`.
Because `ui` has a `default_factory`, existing on-disk configs without a `ui:`
key keep working (defaults to `name`).

### 3.2 Label logic (`rbx/box/naming.py`)

Split the current `get_contest_problem_label` into a pure formatter plus thin
wrappers:

```python
def format_contest_problem_label(
    short_name: str, *, name: Optional[str], title: Optional[str],
    path: Optional[pathlib.Path], mode: ProblemLabelMode,
) -> str:
    if mode is ProblemLabelMode.PATH:
        suffix = str(path) if path is not None else None
    elif mode is ProblemLabelMode.TITLE:
        suffix = title or name
    else:
        suffix = name
    if not suffix:
        return short_name           # preserves today's fallback
    return f'{short_name}. {suffix}'

def _single_title(pkg: Package) -> Optional[str]:
    return next(iter(pkg.titles.values())) if len(pkg.titles) == 1 else None

def get_contest_problem_label(problem: ContestProblem) -> str:
    mode = setter_config.get_setter_config().ui.problem_label
    pkg = package.find_problem_package(problem.get_path())
    return format_contest_problem_label(
        problem.short_name,
        name=pkg.name if pkg else None,
        title=_single_title(pkg) if pkg else None,
        path=problem.get_path(),
        mode=mode,
    )

def get_contest_problem_labels(problem: ContestProblem) -> Dict[ProblemLabelMode, str]:
    """All three variants, computed from a single package load, for the UI."""
    pkg = package.find_problem_package(problem.get_path())
    name = pkg.name if pkg else None
    title = _single_title(pkg) if pkg else None
    return {
        mode: format_contest_problem_label(
            problem.short_name, name=name, title=title,
            path=problem.get_path(), mode=mode)
        for mode in ProblemLabelMode
    }
```

`get_contest_problem_label` keeps driving the single-problem status line
(`contest/main.py:402`). No import cycle: `setter_config` does not import
`naming`.

### 3.3 Live cycle key (`rbx/box/ui/command_app.py`)

- `CommandEntry` gains `labels: Optional[Dict[ProblemLabelMode, str]] = None`.
- `rbxCommandApp.__init__` seeds `self._label_mode` from
  `get_setter_config().ui.problem_label`.
- `_make_tab_label` renders `entry.labels[self._label_mode]` when `labels` is
  set, else falls back to `entry.display_name` (so the non-contest demo and any
  label-less entry are unaffected).
- `on_key`, when the sidebar is focused and at least one entry has `labels`,
  intercepts `l`: advances `self._label_mode`, calls `save_setter_config`,
  refreshes every sidebar item (`_update_sidebar`), and toasts the new mode.
  Guarding on "any entry has labels" keeps `l` falling through to vim-nav
  elsewhere. The new key is added to `HelpModal`.

### 3.4 Call sites (`rbx/box/contest/main.py`)

The two `start_command_app` builders (`each`, multi-problem `on`) add
`labels=naming.get_contest_problem_labels(p)` alongside the existing
`name=naming.get_contest_problem_label(p)`. The package load is
`@functools.cache`d, so computing both is one disk read.

## 4. Data flow

```
contest.rbx.yml problems[]  ─▶ ContestProblem(short_name, path)
  rbx on/each ─▶ naming.get_contest_problem_labels(p)  (loads pkg once)
            ─▶ {NAME: 'A. aplusb', TITLE: 'A. A+B', PATH: 'A. probs/aplusb'}
  CommandEntry(labels=…) ─▶ rbxCommandApp._label_mode (from config)
  sidebar Label = icon + labels[_label_mode]
  press `l` ─▶ advance _label_mode ─▶ save_setter_config ─▶ refresh sidebar
```

## 5. Error handling / edge cases

- Package missing or unloadable ⇒ `name`/`title` are `None`; the formatter
  returns the bare short name (current behavior).
- Empty `pkg.name` ⇒ bare short name (covered by an existing test).
- `title` mode with 0 or ≥2 titles ⇒ falls back to the name.
- `path` mode works even when the package can't load (path comes from
  `ContestProblem.get_path()`).
- On-disk configs predating this change have no `ui:` key ⇒ default `name`.

## 6. Testing

- Pure `format_contest_problem_label`: all three modes × {present, missing}
  name/title/path, plus empty-suffix fallback.
- `_single_title`: 0 / 1 / ≥2 titles.
- `get_contest_problem_labels`: returns the correct three-entry dict (mocking
  `find_problem_package`).
- `get_contest_problem_label`: honors a patched `ui.problem_label` (auto-title
  with 0/1/≥2 titles; path mode). Existing three assertions stay green under the
  default `name` mode.
- The TUI cycle key has no existing harness; its logic is exercised indirectly
  and the keybinding is verified manually.

## 7. Out of scope

- Per-language title selection field.
- A dedicated `rbx config set` command.
- Changing the `A. ` separator.
