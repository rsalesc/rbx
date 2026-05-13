# Design: C++ compilation-warning summarizer (#446)

## Problem

Follow-up to #397. That issue added a pluggable `CompilationWarningSummarizer`
registry in `rbx/box/sanitizers/compilation_warnings.py`, but only the no-op
base implementation exists. The compilation `LiveTasks` row therefore shows a
bare `WARNINGS` with no detail. This work adds a C/C++ summarizer that
distills GCC/clang stderr into a short, useful line shown alongside `WARNINGS`.

## Background

- `PreprocessLog` (in `rbx/grading/steps.py`) carries `.cmd: List[str]` and
  `.log: str` (raw compiler stderr).
- `WarningStack` (introduced in #397) records, per `CodeItem`, the
  warning-bearing `PreprocessLog`s.
- `compile_solutions` / `compile_generators` call
  `compilation_warnings.apply_warning_status(task)` after a successful
  compile. That helper consults the registry and stores the resulting summary
  on `task.warning_summary`, which `CompilationTask.render()` displays.
- Existing warning detection lives in
  `_check_for_compilation_warnings_in_line` in `steps.py`, using
  `_WARNING_RE = r'([^:]+):\d+:\d+:[ ]+warning:.*'` and a hard-coded skip list
  (`testlib`/`jngen`/`tgen`/`stresslib`, `.h` files, leading `./`).
- `rbx/grading/steps.py` already exposes compiler-detection predicates:
  `_is_c_command`, `is_cpp_command`, `is_cxx_command`.

## Decisions

- **Output format**: flag-frequency. Top two `-W…` flags sorted by count,
  with an overflow marker when more flags exist.
  Examples:
  - `2× -Wunused-variable`
  - `3× -Wunused-variable, 2× -Wsign-compare`
  - `3× -Wunused-variable, 2× -Wsign-compare (+1 more)`

  Chosen over "first warning + location" because it scales naturally from
  one warning to many, the flag is the actionable bit, and it doesn't depend
  on arbitrary file order.

- **Dispatch by compiler, not language**. The current language-keyed
  registry is replaced with an ordered list of `(predicate, summarizer)`
  pairs. The predicate takes the executable string (matching the existing
  helpers in `steps.py`). Rationale: GCC and clang share the diagnostic
  format, the actual compiler is in the cmd, and `find_language_name` does
  not reflect which binary will run.

- **No truncation in the summarizer**. The summarizer returns the full
  string. Truncation belongs to the renderer.

- **Truncation via Rich's `overflow='ellipsis'`**. `TaskGrid` gains a
  `flexible_columns` parameter; the warning-summary cell is marked flexible
  so Rich shrinks and ellipsizes it automatically when the row exceeds
  console width. Adapts to terminal resize.

- **Shared first-party filter**. The skip rule used in
  `_check_for_compilation_warnings_in_line` is extracted into a small helper
  in `steps.py` so the new parser and the existing detector apply the
  identical filter.

- **Scope**: C/C++ summarizer only. Other languages keep the no-op default.

## Changes

### 1. `rbx/grading/steps.py`

Extract the existing skip rule:

```python
def _is_first_party_warning_file(file: str) -> bool:
    file = file.strip().lower()
    if 'testlib' in file or 'jngen' in file or 'tgen' in file or 'stresslib' in file:
        return False
    if file.endswith('.h'):
        return False
    return True
```

`_check_for_compilation_warnings_in_line` keeps its behaviour; it just
delegates the skip check to the helper.

### 2. `rbx/box/sanitizers/compilation_warnings.py`

Replace the language-keyed dict with a compiler-predicate registry:

```python
from typing import Callable, List, Optional, Tuple
from rbx.grading.steps import (
    PreprocessLog,
    get_exe_from_command,
    is_cxx_command,
)

class CompilationWarningSummarizer:
    def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
        return None

_DEFAULT_SUMMARIZER = CompilationWarningSummarizer()
_SUMMARIZERS: List[Tuple[Callable[[str], bool], CompilationWarningSummarizer]] = []

def register(predicate, summarizer):
    _SUMMARIZERS.append((predicate, summarizer))

def get_compilation_warning_summarizer_for(
    cmd: List[str],
) -> CompilationWarningSummarizer:
    if not cmd:
        return _DEFAULT_SUMMARIZER
    exe = get_exe_from_command(' '.join(cmd))
    if exe:
        for predicate, summarizer in _SUMMARIZERS:
            if predicate(exe):
                return summarizer
    return _DEFAULT_SUMMARIZER
```

`apply_warning_status`:

- Pull warning-bearing logs from the stack (as today).
- Filter to `log.warnings == True` (defensive — the stack should already
  only store these).
- If any remain, dispatch using the first such log's `cmd` and pass *all*
  warning-bearing logs to `summarize`.

Register the C++ summarizer at import time:

```python
register(is_cxx_command, CppCompilationWarningSummarizer())
```

### 3. `CppCompilationWarningSummarizer` (same module)

```python
@dataclasses.dataclass(frozen=True)
class _ParsedWarning:
    file: str
    line: int
    flag: Optional[str]
    msg: str
```

Parsing:

- Regex: `^(?P<file>[^:\n]+):(?P<line>\d+):(?:\d+:)?\s+warning:\s+(?P<msg>.*?)(?:\s+\[(?P<flag>-W[^\]]+)\])?\s*$`
- For each log: strip ANSI via `utils.strip_ansi_codes`, scan lines.
- Apply `_is_first_party_warning_file` (shared helper from step 1) and the
  existing `./` skip.
- Deduplicate across logs by `(file, line, flag, msg)`.

Rendering:

- Group by `flag` (fallback bucket `'<unflagged>'`).
- Sort groups by count desc, then flag name asc.
- 0 groups → `None`.
- 1 group → `N× -Wflag` (or `N warnings` for the unflagged bucket).
- ≥2 groups → top-2 joined with `, `; if more groups exist, append
  ` (+k more)`.

No length cap.

### 4. `rbx/box/parallel/live_tasks.py`

`TaskGrid.__init__` gains:

```python
flexible_columns: Optional[Set[int]] = None
```

In `_make_table`, when adding column `i`:

- If `i in flexible_columns`:
  `table.add_column(max_width=col_widths[i], overflow='ellipsis', no_wrap=True, justify=self.align or 'left')`
- Else: existing behaviour (`width=col_widths[i]`).

`CompilationTask.render()` returns a 3-column `TaskRenderable`:

1. `Compiling [item]{href}[/item]...`
2. status markup
3. when `status == WARNINGS` and `warning_summary` is set:
   `Text(f' ({self.warning_summary})', style='warning')`; otherwise `Text('')`.

### 5. Wiring

In `compile_solutions` (`rbx/box/solutions.py`) and `compile_generators`
(`rbx/box/generators.py`), pass `flexible_columns={2}` to the `TaskGrid`
constructed inside the compilation `LiveTasks`. Other `LiveTasks` callers
are unaffected (default is empty).

## Data flow

`compile_item` populates `artifacts.logs.preprocess[].warnings` →
`WarningStack.add_warning(code, logs)` (#397) → streamer's `succeeded`
callback calls `apply_warning_status(task)` →
`get_compilation_warning_summarizer_for(log.cmd)` returns the C++
summarizer for gcc/g++/clang/clang++ → `summarize(logs)` returns the
flag-frequency string → renderer composes the row, Rich ellipsizes the
summary column to fit the terminal.

## Testing

- **Parser** (`_parse_cpp_warnings`):
  - GCC stderr with `[-Wunused-variable]`.
  - clang stderr (same format).
  - Warning without `[-W…]` tail.
  - Multi-line noise (`In file included from …`, source carets, `note:`
    lines) — only `warning:` lines counted.
  - testlib/jngen/tgen/stresslib paths filtered out.
  - `.h` files filtered out.
  - Same warning appearing in two logs → deduped.

- **Summarizer** (`CppCompilationWarningSummarizer.summarize`):
  - Empty logs → `None`.
  - All warnings filtered → `None`.
  - 1 warning, 1 flag → `1× -Wfoo`.
  - 5 warnings, 1 flag → `5× -Wfoo`.
  - 2 flags, no overflow → `a× -Wfoo, b× -Wbar` (sorted).
  - 3+ flags → top-2 plus `(+k more)`.
  - Unflagged warnings → `N warnings`.

- **Dispatch** (`get_compilation_warning_summarizer_for`):
  - `['g++', 'foo.cpp']` → C++ summarizer.
  - `['/usr/bin/clang++', 'foo.cpp']` → C++ summarizer.
  - `['gcc', 'foo.c']` → C++ summarizer.
  - `['python3', 'foo.py']` → default no-op.
  - `[]` → default no-op.

- **Renderer**:
  - `flexible_columns={2}` ellipsizes the summary cell when the simulated
    console width is narrower than the full row, while keeping columns 0/1
    intact.

- **End-to-end** (reuse the #397 warning-fixture compilable):
  - Solutions compilation: row renders `WARNINGS (1× -Wunused-variable)`.
  - Generators compilation: same.

## Out of scope

- Persisting warnings/summary in `CompilationMetadata` so cached compiles
  retain them. Same cached-run limitation as #397.
- Java/Kotlin/Python summarizers — registry is now extensible by compiler
  predicate; can be added in follow-up issues.
