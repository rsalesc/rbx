# "Profiling time limits" walkthrough — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship `docs/setters/contest-profiling-walkthrough.md` — step 2 of the **Delivering a
contest** track — with two asciinema recordings, and cut the profiling material out of
`packaging-walkthrough.md` in the same change.

**Architecture:** A new cast fixture (`casts/fixtures/summer-cup/`) provides the contest the
page narrates: three problems whose timing shapes differ, sharing one pinned environment at
the contest root. Two casts are recorded against it — one interactive `rbx time -p boca` in a
single problem, one `rbx each time -p boca --auto` sweep. The page is written last, against
recordings that already exist, so nothing it claims is unverified.

**Tech stack:** mkdocs-material, the repo's own cast recorder (`scripts/record.py`, driven by
`mise run record`), `rbx` itself.

**Design doc:** [`2026-08-24-contest-profiling-walkthrough-design.md`](2026-08-24-contest-profiling-walkthrough-design.md)

---

## Background the executor needs

Read these before starting. They are short and the plan assumes them:

- [`docs/plans/docs-writing-style-guide.md`](docs-writing-style-guide.md) — the voice. Every
  page in `docs/` is written in it, and a page that isn't reads as foreign.
- [`casts/README.md`](../../casts/README.md) — the spec format, `speed`/`x8` pacing,
  `expect_contains`, and the warning about recording on a busy machine.
- `docs/setters/contest-scaffolding-walkthrough.md` — step 1 of this track. The new page
  continues its contest and must not contradict it.
- `docs/setters/profiling/*.md` — the six-page feature guide. The new page **links** to these
  instead of restating them; know what is already there before writing a paragraph.

Two facts established during the brainstorm, both load-bearing:

1. `presets.find_local_preset` (`rbx/box/presets/__init__.py:264`) walks **up** from the
   current directory, so a single `.local.rbx/` at the contest root serves every problem
   nested under it. The fixture pins its environment once, not three times.
2. The default preset's problem `.gitignore` ignores `.limits/local.yml` **only**, so
   `.limits/boca.yml` is tracked the moment it is written. The page's "commit it" section
   explains that asymmetry rather than fighting it.

---

## Task 1: Build the `summer-cup` cast fixture

**Files:**
- Create: `casts/fixtures/summer-cup/contest.rbx.yml`
- Create: `casts/fixtures/summer-cup/.local.rbx/env.rbx.yml`, `.local.rbx/preset.rbx.yml`
- Create: `casts/fixtures/summer-cup/problems/chocolate/**`
- Create: `casts/fixtures/summer-cup/problems/gardens/**`
- Create: `casts/fixtures/summer-cup/problems/sum-of-n/**`

**Step 1: Lay down the contest root**

The names come from step 1 of the track and must match it exactly.

```yaml title="casts/fixtures/summer-cup/contest.rbx.yml"
name: "summer-cup"
titles:
  en: "Summer Cup 2026"

problems:
  - short_name: "A"
    path: "problems/chocolate"
  - short_name: "B"
    path: "problems/gardens"
  - short_name: "C"
    path: "problems/sum-of-n"
```

No `statements:` block. This fixture is about timing; the statement chrome would only add
LaTeX that has to compile for no benefit here.

**Step 2: Pin the environment once, at the contest root**

```bash
mkdir -p casts/fixtures/summer-cup/.local.rbx
cp casts/fixtures/timing-problem/.local.rbx/env.rbx.yml casts/fixtures/summer-cup/.local.rbx/
cp casts/fixtures/timing-problem/.local.rbx/preset.rbx.yml casts/fixtures/summer-cup/.local.rbx/
```

Why: `timing.multipliers` and `timing.groups` only exist in `env.rbx.yml`, and every number
the page prints is derived from them. Leaning on the installed default environment would make
the recording show whatever the recording machine happened to have. `casts/README.md` says
this about `timing-problem`; it applies here for the same reason.

**Step 3: Populate the three problems**

| Problem | Source to copy | Change |
| :-- | :-- | :-- |
| `problems/gardens` | `casts/fixtures/timing-problem/` (minus its `.local.rbx/` and `broken/`) | `name: gardens` in `problem.rbx.yml` |
| `problems/chocolate` | `casts/fixtures/ab-problem/` | `name: chocolate`; keep only the accepted solution, drop the overflowing one |
| `problems/sum-of-n` | `casts/fixtures/sum-problem/` | `name: sum-of-n` |

`gardens` is the one the page profiles interactively, and it is the only one that can carry
that section: it has a C++ accepted solution, a Python accepted solution (so the
language-group screen has something to say) and a quadratic `tle` solution (so the
upper-bound check has something to check). `chocolate` is deliberately dull — a problem with
nothing to say is what makes the sweep look like a real contest. `sum-of-n` mirrors
First steps, which is where step 1 said it came from.

**Step 4: Verify each problem builds standalone**

Run, from the repo root:

```bash
cd casts/fixtures/summer-cup/problems/gardens && uv run rbx download testlib && uv run rbx build
cd ../chocolate && uv run rbx build
cd ../sum-of-n && uv run rbx build
```

Expected: three clean builds. If `gardens` fails on a missing `testlib.h`, the
`rbx download testlib` step is what fixes it — the pinned environment declares testlib and
the default checker includes it.

**Step 5: Verify the contest sees all three**

```bash
cd casts/fixtures/summer-cup && uv run rbx contest summary
```

Expected: a three-row table, letters A/B/C, with each problem's declared limits and solution
counts.

**Step 6: Clean the generated artifacts and commit**

```bash
cd casts/fixtures/summer-cup
rm -rf problems/*/build problems/*/.rbx problems/*/rbx.h
git status   # must show nothing but the fixture's own source files
```

```bash
git add casts/fixtures/summer-cup
git commit -m "docs(casts): add the summer-cup contest fixture"
```

---

## Task 2: Verify `rbx each time` end to end

This is the verification item [#439] asks for, and section 5 of the page cannot be written
until it is answered. Do it before writing any prose.

**DONE — it works.** Verified 2026-08-24 against the Task 1 fixture. Findings below are
established fact; the rest of the plan depends on them.

1. **`rbx time -p boca --auto` is fully unattended in one problem.** It skips the strategy
   menu (`rbx/box/cli.py:840` forces `strategy = 'estimate'` under `--auto`) *and* the
   language-group picker (`rbx/box/timing.py:849` returns an empty pick under `--auto`, so
   the environment's own partition stands).
2. **`rbx each time -p boca --auto` works end to end.** One tab per problem, all three runs
   complete with zero input, all three `.limits/boca.yml` written. ~50 s wall on a warm
   fixture. No affordance issue needed.
3. **The sweep leaves the TUI open when it finishes.** Nothing exits on its own; `q` quits.
   The page must say so, and any cast driving it must end with `q` — `casts/README.md`
   requires keys to leave the program exited or the instruction hits its timeout.
4. **A failed tab does not block the others.** The queue is sequential per terminal, but one
   problem erroring out leaves the rest to finish.
5. **`rbx on` has two shapes.** `rbx on A,C time -p boca --auto` (two problems) opens the
   command app; `rbx on B time -p boca --auto` (one problem, one command) takes the
   plain-terminal fast path at `rbx/box/contest/main.py:508` with no TUI at all.
6. **Every problem needs `rbx download testlib` before `rbx time`, `chocolate` included.**
   It declares no checker, so rbx falls back to the bundled `wcmp.cpp`, which includes
   `testlib.h`; the checker is compiled only when solutions actually run, so `rbx build`
   never trips on it and `rbx time` does. Getting this wrong shows A red in the payoff frame.
7. **Filming:** record at **≥140 columns**. The sidebar eats ~38 columns and the time-limits
   table wraps inside the remaining pane regardless, so the unwrapped-table shot belongs to
   the single-problem cast, not the sweep.

The fixture ships without profiles; the casts create them on camera. If a run leaves any
behind, `rm -rf casts/fixtures/summer-cup/problems/*/.limits` before committing.

---

## Task 3: Record the single-problem cast

**Files:**
- Create: `casts/contest-time-profile.yml`
- Create (generated): `docs/assets/casts/contest-time-profile.cast`

**Step 1: Write the spec**

Model it on `casts/time-estimate.yml`, which drives the same command interactively. The
differences: it runs inside the contest, and it asks for a named profile.

```yaml title="casts/contest-time-profile.yml"
fixture: summer-cup
title: Profiling one problem of a contest for the judge
width: 100
timeout: 300s
setup:
  # The pinned environment declares testlib, and the bundled wcmp checker
  # includes it. Materializing it here keeps the recording about profiling
  # rather than about a missing header.
  - cd problems/gardens && rbx download testlib
  - cd problems/gardens && rbx build
instructions:
  - !Interactive
    command: cd problems/gardens && rbx time -p boca
    keys:
      - 4s        # read the strategy prompt
      - '^M'      # take `estimate`, the default
      - x8        # the timing runs are the long, dull part
      - 40s
      - x1
      - '^M'      # accept the default bucketing
      - 12s       # the upper-bound check
  - !Wait 2s
  - !Clear
  - !Command
    command: cd problems/gardens && cat .limits/boca.yml
    height: 24
  - !Wait 4s
expect_contains:
  - Select how you want to define the time limits
  - Time limits (boca)
  - confirmed too slow
  - .limits/boca.yml
  - acToTimeLimit
```

Note each instruction carries its own `cd`: every instruction runs on its own pty rooted at
the fixture, so a bare `cd` does not survive into the next one. `casts/contest-scaffold.yml`
does the same thing for the same reason.

**Step 2: Record it**

Close `mkdocs serve` and anything else expensive first — a cast's timeline is real elapsed
time, so a recording made on a busy machine is permanently a slower recording.

```bash
mise run record contest-time-profile
```

Expected: the recorder writes `docs/assets/casts/contest-time-profile.cast` and every
`expect_contains` string is found. A failed expectation leaves the previous file untouched
and says which string was missing.

**Step 3: Watch it back**

```bash
asciinema play docs/assets/casts/contest-time-profile.cast
```

Judge it as a reader would: is the strategy prompt on screen long enough to read? Does the
profile at the end fit the window? Adjust the dwells or `height` and re-record until it does.

**Step 4: Commit**

```bash
git add casts/contest-time-profile.yml docs/assets/casts/contest-time-profile.cast
git commit -m "docs(casts): record profiling one problem of a contest"
```

---

## Task 4: Record the contest-sweep cast

**Files:**
- Create: `casts/contest-time-sweep.yml`
- Create (generated): `docs/assets/casts/contest-time-sweep.cast`

**Step 1: Write the spec**

Shaped against what Task 2 actually observed: `--auto` never prompts, the app sits idle when
the sweep finishes, and `q` is what exits it.

```yaml title="casts/contest-time-sweep.yml"
fixture: summer-cup
title: Profiling every problem of a contest at once
# The sidebar eats ~38 columns, so the pane needs the rest to show a table.
width: 140
height: 45
timeout: 900s
setup:
  # ALL THREE problems, chocolate included: it declares no checker, so rbx
  # falls back to the bundled wcmp.cpp, which includes testlib.h. `rbx build`
  # never compiles the checker; `rbx time` does. Skip one and its tab goes red.
  - cd problems/chocolate && rbx download testlib
  - cd problems/gardens && rbx download testlib
  - cd problems/sum-of-n && rbx download testlib
instructions:
  - !Interactive
    command: rbx each time -p boca --auto
    keys:
      - 3s        # the command app opens, one tab per problem
      - x8        # three problems' worth of timing runs, ~50s warm
      - 90s
      - x1
      - 5s        # rest on the payoff frame: three ticks and a Done badge
      - q         # nothing exits on its own; the keys must leave it exited
  - !Wait 2s
  - !Clear
  - ls problems/*/.limits
  - !Wait 3s
expect_contains:
  # Match one uninterrupted run of plain text -- Rich splits styled phrases
  # with escape sequences, so a longer phrase that is plainly on screen may
  # still never match.
  - chocolate
  - gardens
  - sum-of-n
  - boca.yml
```

The warm-up matters for pacing as well as correctness: `rbx download testlib` is hidden in
`setup`, so the recording opens on the sweep itself rather than on three library fetches.

**Step 2: Record, watch, adjust**

```bash
mise run record contest-time-sweep
asciinema play docs/assets/casts/contest-time-sweep.cast
```

The payoff frame is the last one: three problems, three profiles. If the command app's tab
switching is illegible at `x8`, drop to `x4` for the stretch that matters.

**Step 3: Commit**

```bash
git add casts/contest-time-sweep.yml docs/assets/casts/contest-time-sweep.cast
git commit -m "docs(casts): record profiling a whole contest"
```

---

## Task 5: Register the fixture in the casts README

**Files:**
- Modify: `casts/README.md` (the Fixtures table, and the note about `timing-problem`
  carrying its own environment)

Add a `summer-cup` row: *"Three-problem contest — a dull C++-only problem, a timing-shaped
one with a Python accepted solution and a too-slow one, and the sum-of-N problem. Used by
both contest-profiling recordings."* Note that it carries its own `.local.rbx/` at the
**contest** root, for the same reason `timing-problem` does, and that the nested problems
find it because preset lookup walks up.

```bash
git add casts/README.md
git commit -m "docs(casts): document the summer-cup fixture"
```

---

## Task 6: Write the page

**Files:**
- Create: `docs/setters/contest-profiling-walkthrough.md`
- Modify: `mkdocs.yml` (nav, under **Delivering a contest**, between Scaffolding and
  Packaging)
- Modify: `docs/setters/contest-scaffolding-walkthrough.md` (its "Next steps" card currently
  points at Packaging; re-point the *continue the track* card here)

Write the eight sections from the design doc, in order. Rules that matter more than the
outline:

- **Walkthrough register.** Prerequisite note at the top, running story, `!!! info` pointing
  at the feature guide rather than restating it, closing "Next steps" grid cards. The style
  guide's examples are `custom-checker-walkthrough.md` and `stress-testing-walkthrough.md`.
- **Introduce before you use.** Never name a mechanism the reader hasn't met — the style
  guide's single hardest rule.
- **Do not re-teach the feature guide.** Strategies, ratio arithmetic and `modifiers` syntax
  are linked, not restated. If a paragraph starts to grow a table, it belongs in
  `profiling/`.
- `{{ asciinema("contest-time-profile") }}` in section 3, `{{ asciinema("contest-time-sweep") }}`
  in section 5.
- Every command on the page must be one that was actually run in Tasks 2–4.

```bash
git add docs/setters/contest-profiling-walkthrough.md mkdocs.yml \
        docs/setters/contest-scaffolding-walkthrough.md
git commit -m "docs(walkthrough): write the 'profiling time limits' walkthrough"
```

---

## Task 7: Cut profiling out of the packaging walkthrough (#436)

**Files:**
- Modify: `docs/setters/packaging-walkthrough.md` (delete Step 1, ~lines 24–143; renumber
  Steps 2 and 3; rewrite the page's opening paragraph and its "Overview" list)

The page currently opens *"from profiling time limits all the way to uploading"* and lists
profiling as stage 1 of three. After the cut it starts from a problem that already has a
`boca` profile, and says where that profile came from with a link back to the new page.

Check nothing else broke:

```bash
grep -rn "packaging-walkthrough" docs mkdocs.yml | grep -v "^docs/plans"
```

Nothing outside the file links to its `{: #profiling }` anchor today, but re-run this after
editing rather than trusting it.

```bash
git add docs/setters/packaging-walkthrough.md
git commit -m "docs(walkthrough): drop profiling from the packaging walkthrough"
```

---

## Task 8: Verify the whole change

**Step 1: Build the docs**

```bash
uv run mkdocs build
```

Expected: a successful build. Note that `--strict` fails on ~9 pre-existing warnings
unrelated to this change, so build without it and read the warning list for anything naming
a file you touched.

**Step 2: Revert the regenerated CLI reference**

`mkdocs build` regenerates `docs/setters/reference/cli.md` in place. If it shows up modified
and this change did not touch the CLI, revert it:

```bash
git checkout -- docs/setters/reference/cli.md
```

**Step 3: Check every cast reference resolves**

```bash
mise run record-check
```

Expected: both new casts reported as referenced, no orphans, no leftover `TODO(record)`.

**Step 4: Run the cast macro tests**

```bash
uv run pytest tests/casts/test_macro.py -v
```

Expected: PASS. Run only this file — a full suite run is slow here and produces spurious
sandbox timeouts.

**Step 5: Read the two pages end to end**

Both of them, as a reader who has just finished step 1. The failure mode this catches is the
one no command does: a page that is individually correct and collectively contradictory.

---

## Task 9: Open the PR

```bash
git push -u origin worktree-issue-439-profiling-walkthrough
gh pr create --draft --title "docs(walkthrough): add the 'profiling time limits' walkthrough"
```

The body should close [#439], close [#436] (its work rides along in Task 7), and link any
affordance issue Task 2 filed.

If `gh pr create` fails on a classic-Projects GraphQL error, fall back to
`gh api -X POST repos/rsalesc/rbx/pulls`.

[#436]: https://github.com/rsalesc/rbx/issues/436
[#439]: https://github.com/rsalesc/rbx/issues/439
