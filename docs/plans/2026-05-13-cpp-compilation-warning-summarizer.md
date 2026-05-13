# C/C++ Compilation-Warning Summarizer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a C/C++ compilation-warning summarizer that distills GCC/clang stderr into a short, flag-frequency line shown beside `WARNINGS` in compilation `LiveTasks`.

**Architecture:** Replace the language-keyed `_SUMMARIZERS` registry in `rbx/box/sanitizers/compilation_warnings.py` with a compiler-predicate registry (matched against `log.cmd[0]` via existing `is_cxx_command` helpers in `rbx/grading/steps.py`). The C/C++ summarizer parses warning lines, deduplicates, and renders `N× -Wflag[, M× -Wbar][ (+k more)]`. Truncation is handled by the renderer via a new `flexible_columns` mechanism on `TaskGrid` that uses Rich's `overflow='ellipsis'`.

**Tech Stack:** Python 3, pydantic v2, Rich (`rich.table`, `rich.text`), pytest.

**Design doc:** `docs/plans/2026-05-13-cpp-compilation-warning-summarizer-design.md`

---

## Conventions for every task

- **TDD:** Each behavior change is `test → fail → implement → pass → commit`.
- **Run tests:** `uv run pytest <path> -v` (use the precise nodeid). Default exclude path remains `tests/rbx/box/cli`.
- **Lint:** When a task introduces non-trivial Python, finish with `uv run ruff check . && uv run ruff format .`. Fix in-place.
- **Single quotes** (ruff-enforced). **Absolute imports only**.
- **Commit style:** Conventional Commits via the project's `/commit` skill. Example types in use here: `refactor`, `feat`, `test`. Add `(#446)` to subjects so issues link cleanly.
- **Imports inside functions are allowed only when necessary to break import cycles** (the existing `apply_warning_status` already does this for `code` / `warning_stack` / `live_tasks`; keep that pattern).

---

## Task 1: Extract shared first-party warning-file filter

**Why:** The skip rule (`testlib`/`jngen`/`tgen`/`stresslib`/`.h`) currently lives inline in `_check_for_compilation_warnings_in_line`. The new summarizer must apply the identical rule; extracting prevents drift.

**Files:**
- Modify: `rbx/grading/steps.py` (around the `_WARNING_RE` block, lines ~647–675)
- Test: `tests/rbx/grading/test_steps_warning_filter.py` (create)

**Step 1: Write the failing test**

```python
# tests/rbx/grading/test_steps_warning_filter.py
from rbx.grading.steps import _is_first_party_warning_file


def test_first_party_paths_pass():
    assert _is_first_party_warning_file('sol.cpp')
    assert _is_first_party_warning_file('src/Solution.cc')


def test_third_party_libraries_filtered():
    assert not _is_first_party_warning_file('testlib.h')
    assert not _is_first_party_warning_file('vendor/jngen/jngen.h')
    assert not _is_first_party_warning_file('include/tgen/tgen.h')
    assert not _is_first_party_warning_file('stresslib.cpp')


def test_header_files_filtered():
    assert not _is_first_party_warning_file('foo.h')
    assert not _is_first_party_warning_file('Foo.H')


def test_case_insensitive_and_trimmed():
    assert not _is_first_party_warning_file('  TESTLIB.cpp  ')
```

**Step 2: Run and verify it fails**

```
uv run pytest tests/rbx/grading/test_steps_warning_filter.py -v
```
Expected: `ImportError` / `AttributeError` on `_is_first_party_warning_file`.

**Step 3: Implement**

In `rbx/grading/steps.py`, add right above `_check_for_compilation_warnings_in_line`:

```python
def _is_first_party_warning_file(file: str) -> bool:
    file = file.strip().lower()
    if 'testlib' in file or 'jngen' in file or 'tgen' in file or 'stresslib' in file:
        return False
    if file.endswith('.h'):
        return False
    return True
```

Refactor `_check_for_compilation_warnings_in_line` to use it:

```python
def _check_for_compilation_warnings_in_line(line: str) -> bool:
    if line.startswith('./'):
        return False
    line = utils.strip_ansi_codes(line)
    match = _WARNING_RE.match(line)
    if match is None:
        return False
    return _is_first_party_warning_file(match.group(1))
```

**Step 4: Run all related tests**

```
uv run pytest tests/rbx/grading/test_steps_warning_filter.py -v
uv run pytest tests/rbx/grading -v --ignore=tests/rbx/box/cli
```
Both: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add rbx/grading/steps.py tests/rbx/grading/test_steps_warning_filter.py
# Use the /commit skill
```
Suggested message: `refactor(grading): extract first-party warning-file filter (#446)`

---

## Task 2: Swap the summarizer registry to predicate-based dispatch

**Why:** GCC and clang share the diagnostic format and `find_language_name` doesn't tell us which binary actually runs. Keying by compiler predicate (`is_cxx_command`, etc.) is more correct.

**Files:**
- Modify: `rbx/box/sanitizers/compilation_warnings.py` (whole file rewrite — small)
- Test: `tests/rbx/box/sanitizers/test_compilation_warnings_registry.py` (create)

**Step 1: Write the failing tests**

```python
# tests/rbx/box/sanitizers/test_compilation_warnings_registry.py
from typing import List, Optional

from rbx.box.sanitizers import compilation_warnings as cw
from rbx.grading.steps import PreprocessLog


class _Dummy(cw.CompilationWarningSummarizer):
    def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
        return 'dummy'


def test_default_summarizer_when_no_match():
    s = cw.get_compilation_warning_summarizer_for(['python3', 'foo.py'])
    assert s.summarize([]) is None


def test_default_summarizer_when_cmd_empty():
    s = cw.get_compilation_warning_summarizer_for([])
    assert s.summarize([]) is None


def test_predicate_dispatch(monkeypatch):
    monkeypatch.setattr(cw, '_SUMMARIZERS', [(lambda exe: 'g++' in exe, _Dummy())])
    assert cw.get_compilation_warning_summarizer_for(['g++', 'foo.cpp']).summarize([]) == 'dummy'
    assert cw.get_compilation_warning_summarizer_for(['python3']).summarize([]) is None


def test_dispatch_uses_first_match(monkeypatch):
    a = _Dummy()
    b = _Dummy()
    monkeypatch.setattr(cw, '_SUMMARIZERS', [
        (lambda exe: 'clang' in exe, a),
        (lambda exe: True, b),
    ])
    assert cw.get_compilation_warning_summarizer_for(['/usr/bin/clang++']) is a
    assert cw.get_compilation_warning_summarizer_for(['python3']) is b
```

**Step 2: Run and verify failure**

```
uv run pytest tests/rbx/box/sanitizers/test_compilation_warnings_registry.py -v
```
Expected: `AttributeError` on `get_compilation_warning_summarizer_for` / `_SUMMARIZERS` shape mismatch.

**Step 3: Implement the registry change**

Rewrite the body of `rbx/box/sanitizers/compilation_warnings.py` (keep the
file path / module). The C++ summarizer registration is added in Task 4 —
for now the list stays empty.

```python
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple

from rbx.grading.steps import PreprocessLog, get_exe_from_command

if TYPE_CHECKING:
    from rbx.box.parallel.live_tasks import CompilationTask


class CompilationWarningSummarizer:
    """Turns the compiler logs that produced warnings into a short, single-line
    summary to show next to the ``WARNINGS`` status in the compilation live view.

    The base implementation returns ``None`` (no extra line). Compiler-specific
    subclasses register themselves in ``_SUMMARIZERS`` via :func:`register`,
    keyed by a predicate over the compiler executable string.
    """

    def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
        return None


_DEFAULT_SUMMARIZER = CompilationWarningSummarizer()

# Ordered list of (predicate, summarizer). Predicates run against the
# executable portion of ``log.cmd`` (see :func:`get_exe_from_command`).
_SUMMARIZERS: List[Tuple[Callable[[str], bool], CompilationWarningSummarizer]] = []


def register(
    predicate: Callable[[str], bool], summarizer: CompilationWarningSummarizer
) -> None:
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


def apply_warning_status(task: 'CompilationTask') -> None:
    """If ``task.item`` compiled with warnings (per the warning stack), flip the
    task to ``WARNINGS`` and attach a compiler-specific summary line.
    """
    from rbx.box.parallel.live_tasks import CompilationStatus
    from rbx.box.sanitizers import warning_stack

    stack = warning_stack.get_warning_stack()
    if task.item.path not in stack.warnings:
        return
    task.status = CompilationStatus.WARNINGS

    logs = stack.warning_logs.get(task.item.path, [])
    warning_logs = [log for log in logs if log.warnings]
    if not warning_logs:
        return
    summarizer = get_compilation_warning_summarizer_for(warning_logs[0].cmd)
    task.warning_summary = summarizer.summarize(warning_logs)
```

Notes:
- Removed the `find_language_name` import (no longer needed).
- `apply_warning_status` keeps its lazy imports to avoid the cycle with `live_tasks`.

**Step 4: Run tests**

```
uv run pytest tests/rbx/box/sanitizers/test_compilation_warnings_registry.py -v
uv run pytest tests/rbx/box/sanitizers -v
```
Both: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add rbx/box/sanitizers/compilation_warnings.py tests/rbx/box/sanitizers/test_compilation_warnings_registry.py
```
Suggested message: `refactor(sanitizers): key warning summarizers by compiler predicate (#446)`

---

## Task 3: Parser — extract warnings from GCC/clang stderr

**Why:** The summarizer needs structured warning entries (file, line, flag, message) before it can group them. Build this as a standalone module-level function with thorough tests.

**Files:**
- Modify: `rbx/box/sanitizers/compilation_warnings.py` (add parser + dataclass)
- Test: `tests/rbx/box/sanitizers/test_cpp_warning_parser.py` (create)
- Fixture: `tests/rbx/box/sanitizers/testdata/gcc_unused.txt`, `clang_mixed.txt`, `with_testlib.txt`, `noflag.txt` (create)

**Step 1: Create the fixture files**

`tests/rbx/box/sanitizers/testdata/gcc_unused.txt`:
```
sol.cpp: In function 'int main()':
sol.cpp:5:9: warning: unused variable 'x' [-Wunused-variable]
    5 |     int x = 0;
      |         ^
```

`tests/rbx/box/sanitizers/testdata/clang_mixed.txt`:
```
sol.cpp:5:9: warning: unused variable 'x' [-Wunused-variable]
    int x = 0;
        ^
sol.cpp:7:14: warning: comparison of integers of different signedness: 'int' and 'unsigned int' [-Wsign-compare]
    if (a < b)
        ~ ^ ~
sol.cpp:12:5: warning: unused variable 'y' [-Wunused-variable]
    int y = 1;
        ^
3 warnings generated.
```

`tests/rbx/box/sanitizers/testdata/with_testlib.txt`:
```
testlib.h:1234:5: warning: unused parameter 'n' [-Wunused-parameter]
sol.cpp:3:9: warning: unused variable 'q' [-Wunused-variable]
```

`tests/rbx/box/sanitizers/testdata/noflag.txt`:
```
sol.cpp:8:1: warning: control reaches end of non-void function
```

**Step 2: Write failing tests**

```python
# tests/rbx/box/sanitizers/test_cpp_warning_parser.py
import pathlib

from rbx.box.sanitizers.compilation_warnings import _parse_cpp_warnings

TESTDATA = pathlib.Path(__file__).parent / 'testdata'


def _read(name: str) -> str:
    return (TESTDATA / name).read_text()


def test_parses_gcc_warning():
    parsed = _parse_cpp_warnings(_read('gcc_unused.txt'))
    assert len(parsed) == 1
    assert parsed[0].file == 'sol.cpp'
    assert parsed[0].line == 5
    assert parsed[0].flag == '-Wunused-variable'
    assert 'unused variable' in parsed[0].msg


def test_parses_multiple_clang_warnings():
    parsed = _parse_cpp_warnings(_read('clang_mixed.txt'))
    flags = sorted(p.flag for p in parsed)
    assert flags == ['-Wsign-compare', '-Wunused-variable', '-Wunused-variable']


def test_filters_testlib_paths():
    parsed = _parse_cpp_warnings(_read('with_testlib.txt'))
    assert len(parsed) == 1
    assert parsed[0].file == 'sol.cpp'


def test_warning_without_flag():
    parsed = _parse_cpp_warnings(_read('noflag.txt'))
    assert len(parsed) == 1
    assert parsed[0].flag is None
    assert 'control reaches end' in parsed[0].msg


def test_ignores_notes_and_carets_and_in_file_included_from():
    log = (
        "In file included from sol.cpp:1:\n"
        "sol.cpp:5:9: warning: unused variable 'x' [-Wunused-variable]\n"
        "    5 |     int x = 0;\n"
        "      |         ^\n"
        "sol.cpp:6:1: note: previous declaration here\n"
    )
    parsed = _parse_cpp_warnings(log)
    assert len(parsed) == 1
    assert parsed[0].flag == '-Wunused-variable'


def test_strips_ansi_color_codes():
    log = "\x1b[1msol.cpp:5:9:\x1b[m \x1b[35mwarning:\x1b[m unused variable 'x' [-Wunused-variable]"
    parsed = _parse_cpp_warnings(log)
    assert len(parsed) == 1
    assert parsed[0].flag == '-Wunused-variable'
```

**Step 3: Run and verify failure**

```
uv run pytest tests/rbx/box/sanitizers/test_cpp_warning_parser.py -v
```
Expected: ImportError on `_parse_cpp_warnings`.

**Step 4: Implement the parser**

Add to `rbx/box/sanitizers/compilation_warnings.py` (top-level, just below the imports):

```python
import dataclasses
import re

from rbx import utils
from rbx.grading.steps import _is_first_party_warning_file


@dataclasses.dataclass(frozen=True)
class _ParsedWarning:
    file: str
    line: int
    flag: Optional[str]
    msg: str


_CPP_WARNING_RE = re.compile(
    r'^(?P<file>[^:\n]+):(?P<line>\d+):(?:\d+:)?\s+warning:\s+'
    r'(?P<msg>.*?)(?:\s+\[(?P<flag>-W[^\]]+)\])?\s*$'
)


def _parse_cpp_warnings(log: str) -> List[_ParsedWarning]:
    results: List[_ParsedWarning] = []
    for raw_line in log.splitlines():
        line = utils.strip_ansi_codes(raw_line).rstrip()
        if not line or line.startswith('./'):
            continue
        match = _CPP_WARNING_RE.match(line)
        if match is None:
            continue
        file = match.group('file').strip()
        if not _is_first_party_warning_file(file):
            continue
        results.append(
            _ParsedWarning(
                file=file,
                line=int(match.group('line')),
                flag=match.group('flag'),
                msg=match.group('msg').strip(),
            )
        )
    return results
```

Confirm `rbx/utils.py` exports `strip_ansi_codes` — it's the same helper used by `_check_for_compilation_warnings_in_line`. If it lives in a different module in this codebase, import from wherever `steps.py` imports it; do a quick `grep -n 'strip_ansi_codes' rbx/` if uncertain.

**Step 5: Run tests**

```
uv run pytest tests/rbx/box/sanitizers/test_cpp_warning_parser.py -v
```
PASS.

**Step 6: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add rbx/box/sanitizers/compilation_warnings.py tests/rbx/box/sanitizers/test_cpp_warning_parser.py tests/rbx/box/sanitizers/testdata/
```
Suggested message: `feat(sanitizers): parse GCC/clang warning lines into structured entries (#446)`

---

## Task 4: C/C++ summarizer — flag-frequency rendering

**Why:** Turn parsed warnings into the user-visible string with the agreed format. Register the summarizer against `is_cxx_command`.

**Files:**
- Modify: `rbx/box/sanitizers/compilation_warnings.py`
- Test: `tests/rbx/box/sanitizers/test_cpp_warning_summarizer.py` (create)

**Step 1: Write failing tests**

```python
# tests/rbx/box/sanitizers/test_cpp_warning_summarizer.py
from typing import List

from rbx.box.sanitizers.compilation_warnings import (
    CppCompilationWarningSummarizer,
    get_compilation_warning_summarizer_for,
)
from rbx.grading.steps import PreprocessLog
from rbx.grading.judge.sandbox import SandboxBase


def _log(stderr: str, cmd: List[str] | None = None) -> PreprocessLog:
    return PreprocessLog(
        exitcode=0,
        exitstatus=SandboxBase.EXIT_OK,
        time=0.0,
        wall_time=0.0,
        memory=0,
        warnings=True,
        cmd=cmd or ['g++', 'sol.cpp', '-o', 'sol'],
        log=stderr,
    )


def test_empty_logs_returns_none():
    s = CppCompilationWarningSummarizer()
    assert s.summarize([]) is None


def test_all_filtered_returns_none():
    s = CppCompilationWarningSummarizer()
    stderr = "testlib.h:1:1: warning: unused parameter 'n' [-Wunused-parameter]\n"
    assert s.summarize([_log(stderr)]) is None


def test_single_flag():
    s = CppCompilationWarningSummarizer()
    stderr = (
        "sol.cpp:1:1: warning: unused variable 'x' [-Wunused-variable]\n"
        "sol.cpp:2:1: warning: unused variable 'y' [-Wunused-variable]\n"
    )
    assert s.summarize([_log(stderr)]) == '2× -Wunused-variable'


def test_unflagged_warnings_bucket():
    s = CppCompilationWarningSummarizer()
    stderr = (
        "sol.cpp:1:1: warning: control reaches end of non-void function\n"
        "sol.cpp:2:1: warning: control reaches end of non-void function\n"
    )
    # Different lines → distinct entries, but no flag → bucketed together.
    assert s.summarize([_log(stderr)]) == '2 warnings'


def test_two_flags_sorted_by_count_then_name():
    s = CppCompilationWarningSummarizer()
    stderr = (
        "sol.cpp:1:1: warning: unused variable 'x' [-Wunused-variable]\n"
        "sol.cpp:2:1: warning: unused variable 'y' [-Wunused-variable]\n"
        "sol.cpp:3:1: warning: sign compare [-Wsign-compare]\n"
    )
    assert s.summarize([_log(stderr)]) == '2× -Wunused-variable, 1× -Wsign-compare'


def test_three_or_more_flags_appends_overflow():
    s = CppCompilationWarningSummarizer()
    stderr = (
        "sol.cpp:1:1: warning: a [-Wfoo]\n"
        "sol.cpp:2:1: warning: a [-Wfoo]\n"
        "sol.cpp:3:1: warning: b [-Wbar]\n"
        "sol.cpp:4:1: warning: c [-Wbaz]\n"
    )
    assert s.summarize([_log(stderr)]) == '2× -Wfoo, 1× -Wbar (+1 more)'


def test_dedup_across_logs():
    s = CppCompilationWarningSummarizer()
    stderr = "sol.cpp:5:9: warning: unused variable 'x' [-Wunused-variable]\n"
    # Same warning appears in two PreprocessLogs (e.g. precompile + recompile).
    assert s.summarize([_log(stderr), _log(stderr)]) == '1× -Wunused-variable'


def test_registered_for_cxx_commands():
    s_gpp = get_compilation_warning_summarizer_for(['g++', 'sol.cpp'])
    s_clangpp = get_compilation_warning_summarizer_for(['/usr/bin/clang++', 'sol.cpp'])
    s_gcc = get_compilation_warning_summarizer_for(['gcc', 'sol.c'])
    s_py = get_compilation_warning_summarizer_for(['python3', 'sol.py'])
    assert isinstance(s_gpp, CppCompilationWarningSummarizer)
    assert isinstance(s_clangpp, CppCompilationWarningSummarizer)
    assert isinstance(s_gcc, CppCompilationWarningSummarizer)
    assert not isinstance(s_py, CppCompilationWarningSummarizer)
```

Note on `PreprocessLog` construction: confirm the field names by re-reading `rbx/grading/steps.py:280` (the `class PreprocessLog(RunLog):` block) and `RunLog` (line 250). Adjust the constructor in `_log()` if the test fails for pydantic validation reasons.

**Step 2: Run and verify failure**

```
uv run pytest tests/rbx/box/sanitizers/test_cpp_warning_summarizer.py -v
```
Expected: `ImportError` on `CppCompilationWarningSummarizer`.

**Step 3: Implement the summarizer**

Append to `rbx/box/sanitizers/compilation_warnings.py`:

```python
from collections import Counter


class CppCompilationWarningSummarizer(CompilationWarningSummarizer):
    _UNFLAGGED = '<unflagged>'

    def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
        seen = set()
        parsed: List[_ParsedWarning] = []
        for log in logs:
            for w in _parse_cpp_warnings(log.log):
                key = (w.file, w.line, w.flag, w.msg)
                if key in seen:
                    continue
                seen.add(key)
                parsed.append(w)

        if not parsed:
            return None

        counts = Counter(w.flag or self._UNFLAGGED for w in parsed)
        # Sort by count desc, then flag name asc (with unflagged last).
        ordered = sorted(
            counts.items(),
            key=lambda kv: (-kv[1], kv[0] == self._UNFLAGGED, kv[0]),
        )

        def _render(flag: str, count: int) -> str:
            if flag == self._UNFLAGGED:
                return f'{count} warnings' if count != 1 else '1 warning'
            return f'{count}× {flag}'

        head = ordered[:2]
        rendered = ', '.join(_render(f, c) for f, c in head)
        remaining = len(ordered) - len(head)
        if remaining > 0:
            rendered += f' (+{remaining} more)'
        return rendered
```

Then register at module bottom (below the C++ class definitions):

```python
from rbx.grading.steps import is_cxx_command  # noqa: E402

register(is_cxx_command, CppCompilationWarningSummarizer())
```

(If ruff complains about `# noqa: E402`, move the import up to the top group and the `register(...)` call to the bottom — what matters is that registration runs at module import and the class is defined first.)

**Step 4: Run tests**

```
uv run pytest tests/rbx/box/sanitizers/test_cpp_warning_summarizer.py -v
uv run pytest tests/rbx/box/sanitizers -v
```
Both: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add rbx/box/sanitizers/compilation_warnings.py tests/rbx/box/sanitizers/test_cpp_warning_summarizer.py
```
Suggested message: `feat(sanitizers): add C/C++ compilation-warning summarizer (#446)`

---

## Task 5: `TaskGrid` flexible columns + 3-column compilation row

**Why:** Final piece — render the summary in the live view with Rich-driven ellipsizing. Keeps summarizers pure (no width knowledge) and lets terminals resize naturally.

**Files:**
- Modify: `rbx/box/parallel/live_tasks.py` (TaskGrid + LiveTasks + CompilationTask)
- Modify: `rbx/box/solutions.py` (pass `flexible_columns`)
- Modify: `rbx/box/generators.py` (pass `flexible_columns`)
- Test: `tests/rbx/box/parallel/test_live_tasks_flexible_columns.py` (create)

**Step 1: Write failing tests**

```python
# tests/rbx/box/parallel/test_live_tasks_flexible_columns.py
import pathlib

from rich.console import Console
from rich.text import Text

from rbx.box.parallel.live_tasks import (
    CompilationStatus,
    CompilationTask,
    TaskGrid,
    TaskRenderable,
)
from rbx.box.schema import CodeItem


def _render(grid: TaskGrid, width: int) -> str:
    console = Console(width=width, force_terminal=False, record=True)
    console.print(grid)
    return console.export_text()


def test_flexible_column_ellipsizes_when_too_narrow():
    long_summary = '5× -Wunused-variable, 3× -Wsign-compare (+2 more)'
    grid = TaskGrid(
        renderables=[
            TaskRenderable(columns=[Text('short'), Text('STATUS'), Text(long_summary)])
        ],
        flexible_columns={2},
        rule_title=False,
    )
    out = _render(grid, width=30)
    assert '…' in out  # Rich's ellipsis glyph
    assert 'short' in out
    assert 'STATUS' in out


def test_non_flexible_column_unchanged():
    # When the summary fits, no ellipsis.
    grid = TaskGrid(
        renderables=[TaskRenderable(columns=[Text('a'), Text('b'), Text('c')])],
        flexible_columns={2},
        rule_title=False,
    )
    out = _render(grid, width=80)
    assert '…' not in out


def test_compilation_task_render_includes_summary_column():
    item = CodeItem(path=pathlib.Path('sol.cpp'))
    task = CompilationTask(item=item)
    task.status = CompilationStatus.WARNINGS
    task.warning_summary = '1× -Wunused-variable'
    r = task.render()
    assert r is not None
    assert len(r.columns) == 3
    # Third column carries the parenthesized summary.
    rendered_third = r.columns[2]
    assert '1× -Wunused-variable' in rendered_third.plain  # `Text.plain`


def test_compilation_task_render_empty_summary_when_no_warning():
    item = CodeItem(path=pathlib.Path('sol.cpp'))
    task = CompilationTask(item=item)
    task.status = CompilationStatus.FAILED
    r = task.render()
    assert r is not None
    assert len(r.columns) == 3
    assert r.columns[2].plain == ''
```

**Step 2: Run and verify failure**

```
uv run pytest tests/rbx/box/parallel/test_live_tasks_flexible_columns.py -v
```
Expected: failure — `TaskGrid.__init__` rejects `flexible_columns` or the third column isn't there.

**Step 3: Modify `TaskGrid`**

In `rbx/box/parallel/live_tasks.py`:

- Add to `TaskGrid.__init__`:

```python
flexible_columns: Optional[Set[int]] = None,
```

(plus appropriate `from typing import Set` if not already imported)

- Store on instance:
```python
self.flexible_columns = set(flexible_columns or ())
```

- Update `_make_table`:

```python
def _make_table(self, col_widths: List[int]) -> Table:
    table = Table.grid(padding=self.padding, collapse_padding=True, pad_edge=False)
    for i, w in enumerate(col_widths):
        if i in self.flexible_columns:
            table.add_column(
                max_width=w,
                overflow='ellipsis',
                no_wrap=True,
                justify=self.align or 'left',
            )
        else:
            table.add_column(
                width=w,
                justify=self.align or 'left',
            )
    return table
```

**Step 4: Plumb `flexible_columns` through `LiveTasks`**

Add to `LiveTasks.__init__`:

```python
flexible_columns: Optional[Set[int]] = None,
```

Store as `self._flexible_columns = set(flexible_columns or ())` and pass into the `TaskGrid(...)` construction inside `update()`:

```python
TaskGrid(
    renderables,
    panel_indent=self._panel_indent,
    title=self._title,
    rule_title=self._rule_title,
    skip_empty=self._skip_empty,
    flexible_columns=self._flexible_columns,
)
```

**Step 5: Update `CompilationTask.render()` to emit 3 columns**

Modify `CompilationTask.render()` so it always returns 3 columns:

```python
def render(self) -> Optional[TaskRenderable]:
    if self.status in (CompilationStatus.PENDING, CompilationStatus.SUCCESS):
        return None
    href = ...  # existing
    summary_cell = Text('')
    if self.status == CompilationStatus.WARNINGS and self.warning_summary:
        summary_cell = Text(f' ({self.warning_summary})', style='warning')
    return TaskRenderable(
        columns=[
            Text.from_markup(f'Compiling [item]{href}[/item]...'),
            Text.from_markup(self.status.markup()),
            summary_cell,
        ],
        panel=...,  # existing
    )
```

(Reference the existing implementation to preserve the panel-on-exception behaviour and the SKIPPED-override path; just add the third column.)

**Step 6: Wire callsites**

`rbx/box/solutions.py:307` — change to:

```python
with live_tasks.LiveTasks(
    ...existing args...,
    flexible_columns={2},
) as ...:
```

`rbx/box/generators.py:299` — same edit.

Confirm by re-reading those blocks; do not change anything else in them.

**Step 7: Run tests**

```
uv run pytest tests/rbx/box/parallel -v
uv run pytest tests/rbx/box/sanitizers -v
uv run pytest --ignore=tests/rbx/box/cli -n auto
```
All PASS. The last run is the full suite (minus the slow CLI tests) — catches any incidental regressions in solutions/generators that use the live view.

**Step 8: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add rbx/box/parallel/live_tasks.py rbx/box/solutions.py rbx/box/generators.py tests/rbx/box/parallel/test_live_tasks_flexible_columns.py
```
Suggested message: `feat(live-tasks): ellipsize warning summary via flexible TaskGrid columns (#446)`

---

## Task 6: End-to-end smoke test against a fixture compilable (optional but recommended)

**Why:** Tasks 1–5 unit-test every layer in isolation. This task ties them together against a real `compile_item` invocation, ensuring the live view actually shows `WARNINGS (1× -Wunused-variable)` on a fixture that emits a real GCC/clang warning.

**Files:**
- Reuse: the warning-fixture compilable added in #397 (under `tests/.../testdata`). Locate via `grep -rn 'unused variable' tests/`. If #397 didn't ship a fixture, create a minimal `.cpp` that triggers `-Wunused-variable` and a setter config with `warnings.enabled: true`.
- Test: `tests/rbx/box/sanitizers/test_warning_summary_e2e.py` (create)

**Step 1: Write the test**

Pattern after the existing #397 end-to-end test (find it with `grep -rn 'CompilationStatus.WARNINGS' tests/`). Run `compile_solutions()` over the warning fixture; assert that, for the warning-bearing task, `task.warning_summary` matches `1× -Wunused-variable` (or the appropriate flag, depending on the fixture).

**Step 2: Run, fix, commit**

```
uv run pytest tests/rbx/box/sanitizers/test_warning_summary_e2e.py -v
uv run ruff check . && uv run ruff format .
git add tests/rbx/box/sanitizers/test_warning_summary_e2e.py
```
Suggested message: `test: end-to-end smoke for C/C++ warning summary (#446)`

---

## Final verification

After all tasks:

```
uv run ruff check . && uv run ruff format .
uv run pytest --ignore=tests/rbx/box/cli -n auto
```

Expected: all PASS. If anything in `tests/rbx/box/solutions` or `tests/rbx/box/generators` breaks because the live render changed columns from 2 to 3, those tests likely measured renderable shape — update them to match the new column count.

Open a PR titled: `feat: C/C++ compilation-warning summarizer (#446)`. Body should link the design doc and mention that the registry is now compiler-predicate based, opening the door for follow-up Java/Kotlin summarizers.
