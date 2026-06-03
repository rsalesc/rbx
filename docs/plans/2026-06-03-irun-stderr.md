# Show stderr in `rbx irun` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let problem setters see a solution's `stderr` in `rbx irun` — in a separate colored section by default, or interleaved in true line order with the solution output via a `--merge-stderr` / `-e` flag.

**Architecture:** Reuse the existing interaction-capture machinery (`line_tee.py` → `merged_capture` file → `parse_interaction` → `print_interaction`). Add `stderr` as a third stream: pipe id `2`, prefix marker `!`, its own color. The default view reads the already-captured `stderr` file and prints it in a section; the interleaved view tees `stderr` (and, for batch problems, `stdout`) into a merged-capture file so streams render in true write order. The clean `stdout` file the checker reads is never polluted.

**Tech Stack:** Python 3, Typer (CLI), Pydantic v2, Rich (terminal rendering), pytest. Design doc: `docs/plans/2026-06-03-irun-stderr-design.md`.

**Phasing (value-first, risk-isolated):**
- **Phase 1** — parsing/rendering primitives for a 3rd stream (pure, fully unit-tested).
- **Phase 2** — default separate "Stderr" section in `irun` (delivers the core ask, no sandbox changes).
- **Phase 3** — `--merge-stderr` / `-e` flag + true line-order interleave (the sandbox teeing work).

Each phase is independently shippable. Stop after Phase 2 if Phase 3 proves too costly.

---

## Conventions for this repo (read first)

- **Single quotes** for strings; absolute imports only (ruff `TID`). Run `uv run ruff format .` and `uv run ruff check --fix .` before committing.
- **Commits:** MUST follow Conventional Commits via commitizen. Use the `/commit` workflow in `.claude/skills/commit.md`. Stage files by name. Append the `Co-Authored-By:` trailer. Never amend; on hook rejection, make a new commit.
- **Tests:** `uv run pytest <path>`. Reuse fixtures from `tests/rbx/conftest.py` and `tests/rbx/box/conftest.py`. Note (from memory): some C++/sandbox/docker tests fail pre-existingly on this machine — that is NOT your change.
- **Test isolation rule:** any new module-level `@functools.cache` in `rbx/box/` must be added to `rbx.testing_utils.clear_all_functools_cache`. (This plan does not add any.)

---

## Phase 1 — Parsing & rendering a third stream (stderr)

The interaction model lives in `rbx/box/testcase_utils.py`:
- `TestcaseInteractionEntry(data: str, pipe: int)` — `pipe` is `0` = interactor, `1` = solution.
- `parse_interaction(file)` — `.interaction` files use hardcoded prefixes `<` (pipe 0) / `>` (pipe 1); other suffixes (`.pio`) read the two prefixes from the first two lines.
- `print_interaction(interaction)` — colors entries: pipe `0` → `status`, else → `info`.

We add **pipe `2` = stderr, prefix `!`**, colored with the `error` style (red). The 2-element `prefixes` tuple and the first-two-lines `.pio` header format are kept backward-compatible: `!` is a fixed, predetermined stderr prefix recognized in addition to whatever the header declares.

### Task 1.1: stderr lines parse to pipe 2

**Files:**
- Modify: `rbx/box/testcase_utils.py` (`parse_interaction`, ~163-202)
- Test: `tests/rbx/box/testcase_utils_test.py` (create if absent; check first with `ls tests/rbx/box/ | grep testcase`)

**Step 1: Write the failing test**

```python
import pathlib

from rbx.box import testcase_utils


def test_parse_interaction_recognizes_stderr_prefix(tmp_path: pathlib.Path):
    f = tmp_path / 'sample.interaction'
    f.write_text('< 3\n! reading n\n> 1 2 3\n! done\n')

    interaction = testcase_utils.parse_interaction(f)

    assert [(e.pipe, e.data) for e in interaction.entries] == [
        (0, '3'),
        (2, 'reading n'),
        (1, '1 2 3'),
        (2, 'done'),
    ]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/testcase_utils_test.py::test_parse_interaction_recognizes_stderr_prefix -v`
Expected: FAIL — currently raises `TestcaseInteractionParsingError` on the `!` line.

**Step 3: Implement**

In `parse_interaction`, define a fixed stderr prefix and branch on it BEFORE the error case. Keep it independent of the interactor/solution prefixes so it works for both `.interaction` and `.pio`:

```python
STDERR_PREFIX = '!'
```
(module-level constant near the top of `testcase_utils.py`)

Inside the `while line := f.readline().strip():` loop, add a branch:

```python
        while line := f.readline().strip():
            if line.startswith(interactor_prefix):
                stripped = line[len(interactor_prefix):].rstrip()
                entries.append(TestcaseInteractionEntry(data=stripped, pipe=0))
            elif line.startswith(solution_prefix):
                stripped = line[len(solution_prefix):].rstrip()
                entries.append(TestcaseInteractionEntry(data=stripped, pipe=1))
            elif line.startswith(STDERR_PREFIX):
                stripped = line[len(STDERR_PREFIX):].rstrip()
                entries.append(TestcaseInteractionEntry(data=stripped, pipe=2))
            else:
                raise TestcaseInteractionParsingError(...)  # unchanged
```

Note: order the `STDERR_PREFIX` branch so it cannot be shadowed if a caller ever sets `solution_prefix='!'` — in practice the comm tees use `<`/`>`, so `!` is free. If `interactor_prefix`/`solution_prefix` could equal `!`, keep the stderr branch last (as above) so explicit interactor/solution prefixes win.

Also update the docstring to mention the `!` stderr prefix.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/testcase_utils_test.py::test_parse_interaction_recognizes_stderr_prefix -v`
Expected: PASS

**Step 5: Commit**

```bash
uv run ruff format rbx/box/testcase_utils.py tests/rbx/box/testcase_utils_test.py
git add rbx/box/testcase_utils.py tests/rbx/box/testcase_utils_test.py
git commit  # feat(irun): parse stderr lines (prefix '!') as interaction pipe 2
```

### Task 1.2: stderr entries render in a distinct color

**Files:**
- Modify: `rbx/box/testcase_utils.py` (`print_interaction`, ~220-227)
- Test: `tests/rbx/box/testcase_utils_test.py`

**Step 1: Write the failing test** — assert the stderr entry is styled with the error color. `print_interaction` builds `rich.text.Text(entry.data)` then `.stylize(...)`. Capture style via a Rich console recording or by refactoring the style choice into a small pure helper (preferred — easier to test):

```python
from rbx.box import testcase_utils
from rbx.box.testcase_utils import TestcaseInteractionEntry


def test_interaction_entry_style_per_pipe():
    assert testcase_utils.interaction_entry_style(0) == 'status'
    assert testcase_utils.interaction_entry_style(1) == 'info'
    assert testcase_utils.interaction_entry_style(2) == 'error'
```

**Step 2: Run** — FAIL (`interaction_entry_style` not defined).

**Step 3: Implement** — add the pure helper and use it in `print_interaction`:

```python
def interaction_entry_style(pipe: int) -> str:
    if pipe == 0:
        return 'status'
    if pipe == 2:
        return 'error'
    return 'info'


def print_interaction(interaction: TestcaseInteraction):
    for entry in interaction.entries:
        text = rich.text.Text(entry.data)
        text.stylize(interaction_entry_style(entry.pipe))
        console.console.print(text)
```

Verify `error` exists in the Rich theme: `grep -n "error" rbx/box/console.py`. If not present, use an explicit `'red'`.

**Step 4: Run** — PASS.

**Step 5: Commit** — `feat(irun): color stderr interaction lines distinctly`.

---

## Phase 2 — Default separate "Stderr" section in `irun`

Delivers the core ask with no sandbox changes: when `-p` is set, print the already-captured `stderr` in its own colored section after Output/Interaction.

Relevant code in `rbx/box/solutions.py`, `run_and_print_interactive_solutions` (~872-973):
- With `print` set, it prints the Output (and Interaction for COMMUNICATION) section (~939-955).
- `eval.log.stderr_absolute_path` already points to the captured stderr file (used at ~969 to print the *path* when `-p` is NOT set).

### Task 2.1: helper that prints a stderr section

**Files:**
- Modify: `rbx/box/testcase_utils.py` (new `print_stderr_section`)
- Test: `tests/rbx/box/testcase_utils_test.py`

**Step 1: Write the failing test**

```python
import pathlib

import rich.console

from rbx.box import testcase_utils


def test_print_stderr_section_prints_contents(tmp_path, monkeypatch):
    err = tmp_path / 'run.stderr'
    err.write_text('debug: hello\n')

    rec = rich.console.Console(record=True, force_terminal=False, width=80)
    monkeypatch.setattr(testcase_utils.console, 'console', rec)

    printed = testcase_utils.print_stderr_section(err)

    assert printed is True
    out = rec.export_text()
    assert 'debug: hello' in out


def test_print_stderr_section_skips_empty(tmp_path, monkeypatch):
    err = tmp_path / 'run.stderr'
    err.write_text('')
    rec = rich.console.Console(record=True, width=80)
    monkeypatch.setattr(testcase_utils.console, 'console', rec)

    assert testcase_utils.print_stderr_section(err) is False
```

(Confirm the console import path: in `testcase_utils.py` look for `from rbx.box import console` / `console.console`. Adjust `monkeypatch.setattr` target accordingly.)

**Step 2: Run** — FAIL (`print_stderr_section` not defined).

**Step 3: Implement** in `testcase_utils.py`:

```python
def print_stderr_section(stderr_path: Optional[pathlib.Path]) -> bool:
    """Print captured stderr in its own section. Returns True if anything printed."""
    if stderr_path is None or not stderr_path.is_file():
        return False
    content = stderr_path.read_text()
    if not content.strip():
        return False
    console.console.rule('Stderr', style='error')
    console.console.print(rich.text.Text(content.rstrip('\n'), style='error'))
    return True
```

**Step 4: Run** — PASS.

**Step 5: Commit** — `feat(irun): add helper to print captured stderr section`.

### Task 2.2: call the stderr section from `irun` when `-p`

**Files:**
- Modify: `rbx/box/solutions.py` (`run_and_print_interactive_solutions`, in the `if print and stdout_path is not None:` block, ~940-955)
- Test: an `irun`-level test. First check existing coverage: `grep -rn "run_and_print_interactive_solutions\|def test.*irun" tests/`. If a direct unit test is impractical (it drives sandbox runs), rely on the Phase-1/2.1 unit tests plus a manual smoke test, and add an e2e case in Task 2.3.

**Step 1:** After the existing Output rendering inside the `if print ...` branch, add:

```python
            # After the Output / Interaction sections:
            if eval.log.stderr_absolute_path is not None:
                testcase_utils.print_stderr_section(eval.log.stderr_absolute_path)
```

Confirm `testcase_utils` is imported in `solutions.py` (`grep -n "import testcase_utils\|from rbx.box.testcase_utils" rbx/box/solutions.py`); `print_best_output` is already imported from it, so add `print_stderr_section` to that import or call via the module.

**Step 2:** Manual smoke test — create/throwaway a problem where a solution writes to stderr, run:
`uv run rbx irun <sol> -t 0/0 -p -v4` and confirm a red "Stderr" section appears under the output.

**Step 3: Commit** — `feat(irun): show captured stderr section when printing (#266)`.

### Task 2.3: e2e coverage (if the e2e harness fits)

**Files:**
- Read: `tests/e2e/README.md` for the YAML DSL.
- Add/extend: an `e2e.rbx.yml` fixture with a solution that writes to stderr, asserting the printed output contains the stderr text when run with `-p`.

Run: `mise run test-e2e` (or the documented single-fixture invocation). If the DSL can't assert on `irun -p` output, skip this task and note it in the commit/PR. Commit — `test(irun): e2e for stderr section in irun`.

---

## Phase 3 — `--merge-stderr` / `-e` flag (true line-order interleave)

The heavy part: tee streams into a `merged_capture` file so stderr and stdout render in true write order. Render via the Phase-1 parser/printer.

### Task 3.1: add the CLI flag (off by default), thread to the runner

**Files:**
- Modify: `rbx/box/cli.py` (`irun`, ~610-741) — add the option and pass it through.
- Modify: `rbx/box/solutions.py` (`run_and_print_interactive_solutions` signature, ~872-884) — accept `merge_stderr: bool = False`.

**Step 1:** In `irun`, add after the `print` option (~665-667):

```python
    merge_stderr: bool = typer.Option(
        False,
        '--merge-stderr',
        '-e',
        help='Interleave stderr with the solution output in true line order '
        '(colored distinctly). Requires -p. Default: stderr is shown in a '
        'separate section.',
    ),
```

Pass `merge_stderr=merge_stderr` into `run_and_print_interactive_solutions(...)` (~727-741). If `merge_stderr and not print`, print a `[warning]` that `--merge-stderr` requires `-p` and fall back to the default section (do not error).

**Step 2:** No automated test for arg wiring alone; verified via Task 3.4. Commit — `feat(irun): add --merge-stderr/-e flag (#266)`.

### Task 3.2: capture stderr into the merged file — COMMUNICATION path

For interactive problems, `run_coordinated` (`rbx/grading/steps.py:873`) already produces a `merged_capture` via `sandbox.run_communication` + the tees (`stupid_sandbox.py:209-309`). The solution's stderr currently goes to `subprocess.DEVNULL`/its stderr file. We route the solution's stderr through a tee that appends to `merged_capture` with the `!` marker.

**Files:**
- Modify: `rbx/grading/judge/sandboxes/stupid_sandbox.py` (`run_communication`, the teeing setup ~284-309; `_get_tee_program` ~209-230) so the solution's stderr is tee'd into `merged_capture` with prefix `!` while still writing the solution's own stderr file.
- Modify: `rbx/grading/judge/sandboxes/line_tee.py` (and/or `tee.py`) only if the marker char isn't already parameterized — it is passed as `char` in `_get_tee_command` (`stupid_sandbox.py:196-207`), so reuse with `char='!'`.

**Investigation step (do first):** read `line_tee.py` / `tee.py` end-to-end and `run_communication` (`stupid_sandbox.py:253-360+`) to confirm exactly how `merged_capture` lines get their `<`/`>` prefixes, then mirror that for a stderr tee with `!`.

**Step 1 (test):** A grading-level test under `tests/rbx/grading/` that runs a tiny program writing to both stdout and stderr through the communication path with `merged_capture` set, then asserts the merged file contains a `!`-prefixed line with the stderr text and a `>`-prefixed line with stdout, and that the standalone stdout file is clean (no stderr). Model it on existing `run_communication`/`run_coordinated` tests (`grep -rln "run_coordinated\|run_communication\|merged_capture" tests/`).

**Step 2:** Run — FAIL.

**Step 3:** Implement the stderr tee wiring. Keep clean stdout intact (checker correctness).

**Step 4:** Run — PASS.

**Step 5: Commit** — `feat(grading): tee solution stderr into merged capture (#266)`.

### Task 3.3: capture into a merged file — BATCH path

Batch problems use `steps.run` (`steps.py:833`) → `sandbox.run` (`stupid_sandbox.py:237`), which does **no teeing**. Add an opt-in path: when a `merged_capture` is requested, tee `stdout` → (clean stdout file + merged, marker `>`) and `stderr` → (stderr file + merged, marker `!`).

**Files:**
- Modify: `rbx/grading/judge/sandbox.py` — extend `SandboxParams` (or add a param) to carry an optional `merged_capture: Optional[pathlib.Path]` and `tee_mode` for the simple run, mirroring `CommunicationParams`.
- Modify: `rbx/grading/judge/sandboxes/stupid_sandbox.py` (`run`, ~237-251) — when `merged_capture` is set, spawn line-tees for stdout and stderr (reuse `_get_tee_program`/`_get_tee_command` with chars `>` and `!`), preserving the clean stdout/stderr files.
- Modify: `rbx/grading/steps.py` (`run`, ~833-863) — accept and forward `merged_capture`/`line_capture`, analogous to `run_coordinated`.

**Investigation step (do first):** confirm whether `sandbox.run`'s output redirection can be combined with tee processes the same way `run_communication` composes them. This is the riskiest task; budget time to read `_get_io`, `_get_program_params`, and how `stdout_file` is honored. If composing tees into `run` proves disproportionately complex, fall back: for BATCH, capture stdout and stderr to their two files (already available) and produce the merged file post-run by **best-effort timestamp-free concatenation is NOT acceptable** (loses ordering) — instead, document that batch interleave is deferred and keep batch on the Phase-2 separate-section path. Record this decision in the PR.

**Steps:** TDD as in 3.2 — a `tests/rbx/grading/` test that runs a program interleaving stdout/stderr writes and asserts the merged file ordering, plus clean stdout. FAIL → implement → PASS. Commit — `feat(grading): support merged stdout/stderr capture for batch runs (#266)`.

### Task 3.4: wire the merged capture through `irun` and render it

**Files:**
- Modify: `rbx/box/solutions.py`:
  - `SolutionReportSkeleton` — add a `merge_stderr: bool = False` field (near `capture_pipes`, ~128) so the flag rides with the run skeleton (prevents stale cached merged captures; `irun` only caches with explicit `--testcase`).
  - `_get_interactive_skeleton` (~826-869) — set `merge_stderr` from the new param.
  - `run_solution_on_testcase` / `_run_solution` / `_run_interactive_solutions` — thread `merge_stderr` and pass a `merged_capture` path (e.g. `output_dir / 'merged.interaction'`) into the run calls when set. (Search the run plumbing: `grep -n "merged_capture\|capture_pipes\|run_coordinated\|steps.run(" rbx/box/solutions.py`.)
  - In `run_and_print_interactive_solutions` (~939-973): when `print and merge_stderr` and a merged-capture file exists, render it with `print_interaction(parse_interaction(merged_path))` under an `Output`/`Interaction` rule INSTEAD of the plain output + separate stderr section. Otherwise keep the Phase-2 behavior.

**Step 1 (manual smoke):** With a batch solution that writes interleaved stdout/stderr:
- `uv run rbx irun <sol> -t 0/0 -p -v4` → separate red Stderr section (default).
- `uv run rbx irun <sol> -t 0/0 -p -e -v4` → interleaved view, stderr lines red, in true order; checker still runs on clean output.
- Repeat for a COMMUNICATION problem; confirm stderr folds into the interaction as a 3rd color.

**Step 2: Commit** — `feat(irun): render interleaved stderr with --merge-stderr (#266)`.

### Task 3.5: full verification

- `uv run pytest tests/rbx/box/testcase_utils_test.py -v`
- `uv run pytest --ignore=tests/rbx/box/cli` (note pre-existing C++/sandbox/docker failures per memory — confirm only those fail).
- `uv run ruff check . && uv run ruff format --check .`
- Update docs: search for `irun` in `docs/` and add the `--merge-stderr`/`-e` option; verify with a non-strict mkdocs build (per memory, ignore the ~9 pre-existing `--strict` warnings).
- Commit docs — `docs(irun): document --merge-stderr/-e option`.

---

## Out of scope (YAGNI)

- Applying stderr display to the full `rbx run` report (issue is `irun`-only).
- Configurable colors or per-stream filtering.
- Timestamped interleave (line-tee ordering is sufficient).
