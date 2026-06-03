# Lean Default Preset — Design

**Issue:** [#413 — Change default preset to be lean](https://github.com/rsalesc/rbx/issues/413)
**Date:** 2026-06-03

## Problem

The default preset (`rbx/resources/presets/default/`) is maximalist. Its
`problem.rbx.yml` declares samples plus two generator-script groups, seven
solution-outcome patterns, a validator, a checker, stresses, validator/checker
unit tests, and a `vars` block. It ships example solutions
(`sols/wa-overflow.cpp`), a programmatic generator (`testplan/random.py`), and a
static testplan with live generator calls.

The original intent was for the preset to demonstrate everything possible, but
in practice chief setters delete most of it on every new problem. The preset
should instead be a lean, buildable A+B starting point, with discoverability
moved into in-preset documentation that points at the real rbx docs.

## Goals

- Default preset is a bare, buildable A+B problem.
- All capability still discoverable, but via short docs/comments, not scaffolding.
- Directory layout reorganized for clarity and consistency.
- Tests continue to verify the default preset actually works, without
  replicating the preset's contents.

## Non-goals (explicitly deferred / out of scope)

- **Deferred to a new issue:** a complete, richly-featured example problem living
  *inside the contest dir* of the default preset (a reference problem that is
  **not** linked into `contest.rbx.yml` but kept around).
- **Deferred to a new issue:** a dedicated `complete-problem` e2e fixture that
  exercises WA verdicts, unit tests, stresses, and packaging.
- **Out of scope:** cleaning committed cruft from the preset (`.box/` cache,
  `.DS_Store`, `build/` artifacts).

## Design

### 1. `problem/problem.rbx.yml`

- **Keep all `solutions:` outcome declarations** (`sols/main*.*`, `sols/ac-*.*`,
  `sols/wa-*.*`, `sols/tle-*.*`, `sols/mle-*.*`, `sols/re-*.*`, `sols/fail-*.*`).
  They document the naming convention. Only `sols/main.cpp` is shipped as an
  actual file, so the other patterns match nothing until a setter adds files.
- **Remove** the `program-random` testcase group (the Python generator), the
  entire `stresses:` block, and the entire `unitTests:` block.
- **Keep** `vars` (`author`, `N.min`, `N.max`) — the validator and statement
  read `N.min`/`N.max`, and the editorial uses `author`.
- Rename the `random` testcase group to **`testplan`**, with
  `generatorScript.path: tests/testplan.txt`.
- Update paths for the directory restructure below.

### 2. Directory restructure (problem)

Three organizing folders; validator, checker, and headers stay at root.

```
problem/
  problem.rbx.yml
  validator.cpp
  wcmp.cpp
  testlib.h, rbx.h
  documents/
    statement.rbx.tex
    samples/{000.in, 000.rbx.tex, 001.in}
    icpc.sty, template.rbx.tex        # statement assets / template
  tests/
    testplan.txt                      # commented-only example, references tests/gens/gen
    gens/gen.cpp                       # reference generator (folded under tests/)
  sols/
    main.cpp
```

- `samples` group glob → `documents/samples/*.in`.
- `testplan` group `generatorScript.path` → `tests/testplan.txt`.
- Generators fold into `tests/gens/`; the testplan references `tests/gens/gen`.
- `testplan.txt` contains only **commented** example invocations plus a short
  doc pointer, e.g.:

  ```
  # Call a generator to produce random tests. Uncomment to use.
  # See the testset docs: https://rsalesc.github.io/rbx/setters/testset/
  # tests/gens/gen 123456
  # tests/gens/gen 12345678
  ```

  The `testplan` group therefore exists and is wired, but generates nothing
  until a setter uncomments a line.
- Statement `path`, `assets`, and `configure.template` move under `documents/`.

### 3. Directory restructure (contest)

For consistency, rename `contest/statement/` → `contest/documents/`. Update all
referencing paths in `contest/contest.rbx.yml` (`contest.rbx.tex`,
`info.rbx.tex`, `instructions.tex`, `logo.png`, `icpc.sty`, `template.rbx.tex`).

### 4. `preset.rbx.yml` tracking

Update `tracking:` entries to match the new layout:

- Problem: `documents/icpc.sty`, `documents/template.rbx.tex` (was
  `statement/icpc.sty`, `statement/template.rbx.tex`).
- Contest: `documents/icpc.sty`, `documents/template.rbx.tex`,
  `documents/contest.rbx.tex` (symlink) (was under `statement/`).

### 5. In-preset documentation

- New `README.md` at the preset root (`rbx/resources/presets/default/README.md`):
  short. States this is a minimal starting point and lists "what you can add"
  as one-liners, each linking to the relevant rbx docs page (more solutions by
  outcome, stresses, validator/checker unit tests, programmatic/multiple
  generators, more vars, additional statements/languages).
- Brief top-of-file comments in `problem.rbx.yml`, `tests/gens/gen.cpp`,
  `validator.cpp`, and `tests/testplan.txt` — each one or two lines pointing at
  the corresponding docs rather than explaining inline.

### 6. e2e test

Replace the current `tests/e2e/testdata/default-preset/` fixture (today a
verbatim copy of the preset) with a thin scenario that references the **real**
preset instead of replicating it:

```yaml
scenarios:
  - name: works
    steps:
      - cmd: create --name prob --preset default --local   # materializes the real preset, no network
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

The fixture dir holds only `e2e.rbx.yml` (no `problem.rbx.yml`/`contest.rbx.yml`,
since `rbx create` refuses to run inside a contest). Scope of the scenario: the
default preset builds tests, builds statements, and runs solutions correctly.

**Implementation caveats to verify:**

- `rbx create --local` resolves the in-repo preset under the harness's
  tmpdir + `CliRunner` setup. If it does not, the fallback is a minimal copied
  lean fixture — but referencing the real preset is preferred.
- The existing `tests/e2e/testdata/.gitignore` (covering `*/.box/`, `*/build/`,
  headers) keeps `git status` clean after the scenario runs.

## Risks

- The directory restructure touches many path references (`problem.rbx.yml`,
  `contest.rbx.yml`, `preset.rbx.yml` tracking, statement assets/template).
  Each must be updated together; a missed path breaks `rbx build`.
- The `testplan` group with an all-commented testplan must not error at build
  time (expected: zero generated tests). Verify during implementation.
- Other tests or docs that reference the old default-preset layout
  (`statement/`, `testplan/random.py`, `sols/wa-overflow.cpp`) may need updates.

## Verification

- `cd rbx/resources/presets/default/problem && uv run rbx build` succeeds.
- Statement builds (mocked pdflatex) and `sols/main.cpp` judges AC.
- The new `default-preset` e2e scenario passes via `mise run test-e2e`.
- `git status` clean after building (no cruft re-committed).
