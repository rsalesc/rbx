# Lean Default Preset Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Slim the default preset down to a bare, buildable A+B problem, reorganize its directory layout, document capabilities in-preset, and make the e2e test exercise the real preset instead of a verbatim copy.

**Architecture:** Edit the in-repo resources preset at `rbx/resources/presets/default/`. Restructure both `problem/` and `contest/` to use a `documents/` folder (statement + assets + samples) and a `tests/` folder (testplan + generators). Strip `stresses`/`unitTests`/extra solution files from `problem.rbx.yml` while keeping the outcome declarations. Update every path reference (`problem.rbx.yml`, `contest.rbx.yml`, `preset.rbx.yml` tracking). Replace the e2e `default-preset` fixture with a thin scenario that runs `rbx create --preset default --local`.

**Tech Stack:** rbx CLI (Typer), Pydantic schemas, YAML config, testlib C++, the YAML-DSL e2e harness under `tests/e2e/`.

**Design doc:** `docs/plans/2026-06-03-lean-default-preset-design.md`

**Working dir:** worktree `issue-413-lean-preset`. The preset root is
`rbx/resources/presets/default/` (referred to below as `$PRESET`).

---

## Notes for the implementer

- The preset directory carries committed cruft (`.box/`, `.DS_Store`, `build/`
  PDFs/evals). **Do not touch it** — cleanup is explicitly out of scope. Only
  move/edit the source files named in each task. When using `git mv`, move the
  named files only, not the cruft folders.
- In the source preset, `problem/statement/` physically contains only
  `statement.rbx.tex`. `icpc.sty` and `template.rbx.tex` are *not* present as
  files there — they are materialized at create time from `shared/` via the
  `tracking:` block in `preset.rbx.yml`. So "move the statement folder" for the
  problem means moving `statement.rbx.tex` (and the samples), then retargeting
  tracking. The contest's `statement/` *does* physically contain `icpc.sty`,
  `template.rbx.tex`, `logo.png`, etc.
- The primary verification harness is `rbx build` inside the preset's `problem/`
  and the e2e scenario. There is no unit-level test to write first for a
  resources reorg; the e2e scenario (Task 8) is the regression test, and an
  interim manual `rbx build` is the per-step check.

---

## Task 1: Restructure the problem directory (file moves only)

**Files:**
- Move: `$PRESET/problem/statement/statement.rbx.tex` → `$PRESET/problem/documents/statement.rbx.tex`
- Move: `$PRESET/problem/manual_tests/samples/` → `$PRESET/problem/documents/samples/`
- Move: `$PRESET/problem/testplan/random.txt` → `$PRESET/problem/tests/testplan.txt`
- Move: `$PRESET/problem/gens/gen.cpp` → `$PRESET/problem/tests/gens/gen.cpp`
- Delete: `$PRESET/problem/sols/wa-overflow.cpp`
- Delete: `$PRESET/problem/testplan/random.py`

**Step 1: Create new folders and move source files**

```bash
cd rbx/resources/presets/default/problem
mkdir -p documents tests/gens
git mv statement/statement.rbx.tex documents/statement.rbx.tex
git mv manual_tests/samples documents/samples
git mv testplan/random.txt tests/testplan.txt
git mv gens/gen.cpp tests/gens/gen.cpp
git rm sols/wa-overflow.cpp testplan/random.py
```

**Step 2: Remove now-empty source folders if git left them**

```bash
# statement/, manual_tests/, testplan/, gens/ should now hold only the (gitignored)
# build/cache cruft, if anything. Do NOT delete cruft; just confirm the tracked
# source files are gone from them.
git status
```

Expected: the moved files appear as renames; `wa-overflow.cpp` and `random.py`
deleted. No edits to `.box/`, `build/`, `.DS_Store`.

**Step 3: Commit**

```bash
git add -A
git commit -m "refactor(presets): restructure default problem into documents/ and tests/"
```

---

## Task 2: Update `problem.rbx.yml`

**Files:**
- Modify: `$PRESET/problem/problem.rbx.yml`

**Step 1: Rewrite the file**

Replace the full contents with the lean version below. Key changes vs. current:
- `samples` glob → `documents/samples/*.in`.
- `random` group renamed to `testplan`, `generatorScript.path` → `tests/testplan.txt`.
- `program-random` group removed.
- `solutions:` outcome declarations **kept** (only `main.cpp` ships as a file).
- `stresses:` and `unitTests:` removed.
- `vars` kept (`author`, `N`).
- Statement `path`, `assets`, `configure.template` → under `documents/`.
- Add a short top-of-file comment pointing at the docs.

```yaml
---
# yaml-language-server: $schema=https://rsalesc.github.io/rbx/schemas/Package.json
# Minimal A+B problem. See the README in this preset, and the rbx docs at
# https://rsalesc.github.io/rbx/ for everything you can add.
name: "new-problem"
timeLimit: 1000 # ms
memoryLimit: 256 # MiB
titles:
  en: "New problem"
checker: {path: "wcmp.cpp"} # Download others from testlib with `rbx download checker`
validator: {path: "validator.cpp"}
testcases:
  - name: "samples"
    testcaseGlob: "documents/samples/*.in" # Pattern for the sample inputs.
  - name: "testplan"
    generatorScript:
      path: "tests/testplan.txt" # Static generator script (testplan).
solutions:
  - path: "sols/main*.*"
    outcome: "ACCEPTED"
  - path: "sols/ac-*.*"
    outcome: "ACCEPTED"
  - path: "sols/wa-*.*"
    outcome: "WRONG_ANSWER"
  - path: "sols/tle-*.*"
    outcome: "TIME_LIMIT_EXCEEDED"
  - path: "sols/mle-*.*"
    outcome: "MEMORY_LIMIT_EXCEEDED"
  - path: "sols/re-*.*"
    outcome: "RUNTIME_ERROR"
  - path: "sols/fail-*.*"
    outcome: "INCORRECT"
statements:
  - name: "statement-en"
    path: "documents/statement.rbx.tex" # Open this file to edit your statement.
    type: "rbxTeX"
    language: "en"
    assets: # Define assets for the statement.
      - "documents/icpc.sty"
      - "documents/*.png"
    configure:
      - type: "rbx-tex" # Convert rbxTeX to TeX
        template: "documents/template.rbx.tex"
    vars:
      # Set to false to hide time limits and memory limits in the problem statement.
      show_limits: true
# Variables usable in the validator, checker, interactor, stress tests and statement.
vars:
  # Author name to be displayed in the editorial.
  author: "John Doe"
  # Constraints of the problem.
  N:
    min: 1
    max: 1000000000
```

**Step 2: Commit**

```bash
git add rbx/resources/presets/default/problem/problem.rbx.yml
git commit -m "refactor(presets): slim default problem.rbx.yml to bare A+B"
```

---

## Task 3: Make `tests/testplan.txt` commented-only

**Files:**
- Modify: `$PRESET/problem/tests/testplan.txt`

**Step 1: Replace contents**

```
# Call a generator to produce random tests, one invocation per line.
# Uncomment the lines below (or add your own) to generate tests.
# Docs: https://rsalesc.github.io/rbx/setters/testset/
# tests/gens/gen 123456
# tests/gens/gen 12345678
```

**Step 2: Add a doc pointer to the generator**

Modify `$PRESET/problem/tests/gens/gen.cpp` — add a one-line comment under the
includes pointing at the generators docs:

```cpp
#include "testlib.h"

// Reference random generator. Docs: https://rsalesc.github.io/rbx/setters/testset/
using namespace std;
```

**Step 3: Add a doc pointer to the validator**

Modify `$PRESET/problem/validator.cpp` — add a one-line comment under the
includes:

```cpp
#include "rbx.h"
#include "testlib.h"

// Validates the input format. Docs: https://rsalesc.github.io/rbx/setters/testset/
using namespace std;
```

**Step 4: Commit**

```bash
git add rbx/resources/presets/default/problem/tests/testplan.txt \
        rbx/resources/presets/default/problem/tests/gens/gen.cpp \
        rbx/resources/presets/default/problem/validator.cpp
git commit -m "docs(presets): make testplan commented-only and add doc pointers"
```

---

## Task 4: Restructure the contest directory

**Files:**
- Move: `$PRESET/contest/statement/` → `$PRESET/contest/documents/`

**Step 1: Move the folder**

```bash
cd rbx/resources/presets/default/contest
git mv statement documents
git status
```

Expected: `contest.rbx.tex`, `info.rbx.tex`, `instructions.tex`, `logo.png`,
`icpc.sty`, `template.rbx.tex` all renamed under `documents/`.

**Step 2: Update `contest/contest.rbx.yml`**

Replace every `statement/` path prefix with `documents/`:
- `path: "statement/contest.rbx.tex"` → `documents/contest.rbx.tex`
- assets `statement/icpc.sty`, `statement/*.png`, `statement/instructions.tex`
  → `documents/...`
- `template: "statement/template.rbx.tex"` → `documents/template.rbx.tex`
- `path: "statement/info.rbx.tex"` (info-en) → `documents/info.rbx.tex`

**Step 3: Commit**

```bash
git add -A
git commit -m "refactor(presets): rename contest statement folder to documents"
```

---

## Task 5: Update `preset.rbx.yml` tracking

**Files:**
- Modify: `$PRESET/preset.rbx.yml`

**Step 1: Retarget tracking paths**

Update the `tracking:` block so both problem and contest reference `documents/`:

```yaml
tracking:
  problem:
    - path: ".gitignore"
    - path: "documents/icpc.sty"
    - path: "documents/template.rbx.tex"
  contest:
    - path: ".gitignore"
    - path: "documents/icpc.sty"
    - path: "documents/template.rbx.tex"
    - path: "documents/contest.rbx.tex"
      symlink: true
```

**Step 2: Commit**

```bash
git add rbx/resources/presets/default/preset.rbx.yml
git commit -m "refactor(presets): point tracking at documents/ folders"
```

---

## Task 6: Verify the preset builds and judges

**Step 1: Build the problem standalone**

```bash
cd rbx/resources/presets/default/problem
uv run rbx build
```

Expected: build succeeds. The `samples` group produces 2 tests from
`documents/samples/*.in`; the `testplan` group produces **0** tests (all
commented) without erroring.

**Step 2: Run solutions**

```bash
uv run rbx run
```

Expected: `sols/main.cpp` judges ACCEPTED on the samples; no other solution
files exist, so the other outcome declarations match nothing.

**Step 3: Confirm no cruft was re-committed**

```bash
cd -   # back to worktree root
git status
```

Expected: clean (the preset `.gitignore` covers `.box/`, `build/`). If `rbx
build` created tracked files, investigate before continuing. Do not commit
build artifacts.

**Step 4: If build fails**

Use superpowers:systematic-debugging. The most likely culprit is a stale path
in `problem.rbx.yml` (statement assets/template or the testplan/sample globs).
Cross-check against Task 2.

---

## Task 7: Add the preset README

**Files:**
- Create: `$PRESET/README.md`

**Step 1: Write the README**

Keep it short. List capabilities as one-liners that link to rbx docs. Suggested
content:

```markdown
# rbx default preset

A minimal A+B problem to start from. Build it with `rbx build`, run solutions
with `rbx run`. Everything below is optional — add what you need.

## Layout

- `documents/` — statement (`statement.rbx.tex`), its assets, and `samples/`.
- `tests/` — `testplan.txt` (static generator script) and `gens/` (generators).
- `sols/` — solutions. `main.cpp` is the reference accepted solution.
- `validator.cpp`, `wcmp.cpp` — input validator and checker.

## Adding more

The `problem.rbx.yml` already declares solution patterns by outcome
(`ac-*`, `wa-*`, `tle-*`, `mle-*`, `re-*`, `fail-*`) — drop files matching those
names into `sols/` and they are picked up automatically.

- Generate tests: uncomment lines in `tests/testplan.txt`.
  See https://rsalesc.github.io/rbx/setters/testset/
- Programmatic generators & generator scripts:
  https://rsalesc.github.io/rbx/setters/testset/
- Stress testing: https://rsalesc.github.io/rbx/setters/stress-testing/
- Validator & checker unit tests:
  https://rsalesc.github.io/rbx/setters/verification/
- Variables: https://rsalesc.github.io/rbx/setters/variables/
- Statements (more languages, formats):
  https://rsalesc.github.io/rbx/setters/statements/
- Full config reference: https://rsalesc.github.io/rbx/setters/reference/
```

> NOTE before writing: verify each docs URL resolves against the actual
> `docs/setters/` tree (e.g. `verification/`, `stress-testing.md`,
> `variables.md`, `testset/`, `statements/`, `reference/`). Adjust slugs to the
> real published paths; do not ship dead links.

**Step 2: Commit**

```bash
git add rbx/resources/presets/default/README.md
git commit -m "docs(presets): add README for the lean default preset"
```

---

## Task 8: Replace the e2e `default-preset` fixture

**Files:**
- Delete: everything under `tests/e2e/testdata/default-preset/` **except** a new
  `e2e.rbx.yml` (i.e. remove the verbatim-copy package files).
- Rewrite: `tests/e2e/testdata/default-preset/e2e.rbx.yml`

**Step 1: Inspect the e2e harness contract**

Read `tests/e2e/README.md` and `tests/e2e/runner.py` / `tests/e2e/spec.py` to
confirm: (a) a fixture dir with only `e2e.rbx.yml` is collected, (b) the
`cwd:` step field works for stepping into the created `prob/` dir, (c) how
pdflatex is mocked for `st b`. Confirm the `solutions:` and `files_exist:`
expect fields exist (they are used by the current scenario).

**Step 2: Remove the copied package files**

```bash
cd tests/e2e/testdata/default-preset
git rm -r problem.rbx.yml sols gens testplan manual_tests statement \
         validator.cpp wcmp.cpp testlib.h
# keep .gitignore if present; keep (and rewrite) e2e.rbx.yml
git status
```

Adjust the file list to whatever the fixture actually contains (see the dir
listing). The goal: leave only `e2e.rbx.yml` (and `.gitignore` if any).

**Step 3: Write the new scenario**

```yaml
scenarios:
  - name: works
    description: >
      Verifies the real default preset (referenced via `rbx create --local`,
      not replicated here) builds tests, builds its statement, and judges the
      reference solution as accepted.
    steps:
      - cmd: create --name prob --preset default --local
      - cmd: run
        cwd: prob
        expect:
          solutions:
            sols/main.cpp: ac
      - cmd: st b
        cwd: prob
        expect:
          files_exist:
            - prob/build/statement-en.pdf
```

**Step 4: Run the scenario**

```bash
cd -   # worktree root
uv run pytest tests/e2e/testdata/default-preset/ -v
```

Expected: PASS.

**Step 5: If `create --local` does not resolve inside the harness**

Use superpowers:systematic-debugging. Check whether the runner's tmpdir cwd and
the `--local` resolution find the in-repo preset. If it genuinely cannot work
under the harness, fall back to a minimal **copied lean** fixture (a small
package mirroring the new lean preset) and a scenario doing `run` + `st b` — but
prefer the `create --local` approach. Document whichever path you took in the
scenario `description`.

**Step 6: Confirm clean tree and commit**

```bash
git status   # ensure no .box/ or build/ artifacts staged
git add tests/e2e/testdata/default-preset/
git commit -m "test(e2e): reference real default preset instead of copying it"
```

---

## Task 9: Sweep for stale references

**Step 1: Grep for old paths that may now be broken**

```bash
cd <worktree root>
grep -rn "manual_tests/samples\|testplan/random\|wa-overflow\|presets/default/.*statement/" \
  --include="*.py" --include="*.md" --include="*.yml" \
  rbx tests docs | grep -v "/.box/\|/build/\|2026-06-03-lean-default-preset"
```

Expected: review each hit. Fix any docs page or test that documents/asserts the
old default-preset layout. Likely candidates: `docs/setters/presets/`,
`docs/setters/first-steps.md`. If a doc walks through the default preset's
contents, update it to the new layout.

**Step 2: Commit any fixes**

```bash
git add <fixed files>
git commit -m "docs: update references to the restructured default preset"
```

---

## Task 10: Full verification pass

**Step 1: Run the non-CLI test suite**

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto
```

Expected: PASS (or only the known pre-existing local C++/sandbox/docker
failures noted in project memory — those are unrelated to this change).

**Step 2: Run the e2e suite**

```bash
mise run test-e2e
```

Expected: the `default-preset/works` scenario passes.

**Step 3: Lint & format**

```bash
uv run ruff check . && uv run ruff format --check .
```

Expected: clean.

**Step 4: Final status check**

```bash
git status && git log --oneline -10
```

Expected: clean tree, conventional-commit history covering each task.

---

## Out of scope / follow-up issues to file

- Add a complete, unlinked example problem inside the contest dir of the default
  preset (reference problem kept around, not added to `contest.rbx.yml`).
- Add a dedicated `complete-problem` e2e fixture covering WA verdicts, unit
  tests, stresses, and BOCA/Polygon packaging (the coverage dropped from the old
  `default-preset` fixture).
- Clean committed cruft (`.box/`, `.DS_Store`, `build/`) from the preset.
