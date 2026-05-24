# Stress-testing Walkthrough Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a narrative "Stress-testing your solutions" walkthrough page (issue #437) under Walkthrough → Authoring a problem, continuing the sum-of-N problem from First steps.

**Architecture:** Pure docs. One new Markdown page written in the house style of `docs/setters/first-steps.md` (tabbed code blocks, admonitions, `{{ asciinema(...) }}` macro). Wire it into `mkdocs.yml` nav, repoint a next-steps card in First steps, and leave a follow-up note on issue #442. Persistence in step 4 uses the existing `rbx stress` add-to-test-group prompt, not the unbuilt #442 affordance.

**Tech Stack:** MkDocs + Material theme + `mkdocs-macros-plugin` (the `asciinema` macro is defined in `main.py:8`).

**Reference docs to read before starting:**
- `docs/setters/first-steps.md` — the page this continues; match its voice and formatting.
- `docs/setters/stress-testing.md` — the reference page; the walkthrough links here, must NOT duplicate it.
- `docs/plans/2026-05-24-stress-testing-walkthrough-design.md` — the approved design.
- `rbx/box/cli.py:957-1035` — the exact add-to-test-group prompt flow described in step 4.

**Verification used throughout:** `uv run mkdocs build --strict` must pass (it fails on broken internal links and pages missing from nav). There are no unit tests for docs.

---

### Task 1: Create the walkthrough page

**Files:**
- Create: `docs/setters/stress-testing-walkthrough.md`

**Step 1: Write the page.**

Write `docs/setters/stress-testing-walkthrough.md` with the structure below. Match `first-steps.md` style: `=== "path"` tabbed code blocks, `!!! note` / `!!! tip` admonitions, `{{rbx}}`/`{{testlib}}` macro abbreviations where natural.

Required content, in order:

1. **Title + intro callout.** `# Stress-testing your solutions`. Open with a `!!! note` linking back to First steps: this picks up the sum-of-N problem from [First steps](first-steps.md), where `sols/main.cpp` is correct and `sols/wa-overflow.cpp` accumulates into an `int32_t` that overflows. Do NOT use "Step 3 of 3" numbering. One sentence on the goal: find a tiny input that breaks `wa-overflow.cpp`.

2. **Section "Describing the search".** Explain the two expressions briefly (generator expression + finder), then link to the reference for the full operator set: "See [Stress testing](stress-testing.md) for the complete operator reference." Show:
   - Generator expression: `gens/gen [1..5] <A.max> @` — explain that `[1..5]` keeps the count tiny, `<A.max>` pulls the upper bound from `vars`, and `@` randomizes each run. State why small suffices: int32 overflows once the sum passes ~2.1×10⁹, so a handful of ~10⁹ values is enough.
   - Finder expression: `[sols/wa-overflow.cpp] ~ INCORRECT`, and note `sols/wa-overflow.cpp` is the shorthand.

3. **Section "Running the stress".** Show the command in a `bash` block:
   ```bash
   rbx stress -g "gens/gen [1..5] <A.max> @" -f "sols/wa-overflow.cpp"
   ```
   Add the asciinema macro on its own line (placeholder id, see Task 2):
   ```
   {{ asciinema("REPLACE_ME_CAST_ID") }}
   ```
   Immediately above the macro line, add an HTML comment:
   ```
   <!-- TODO(#437): record the rbx stress run (kickoff -> counterexample) and replace REPLACE_ME_CAST_ID. -->
   ```
   One paragraph: by default it runs ~10s and stops at the first match; `-n`/`-t` tune that (link reference, don't re-document).

4. **Section "Inspecting the counterexample".** Describe the printed report and that the failing generator call + input are shown. Walk the reader through reading the input — a few large numbers whose true sum exceeds the int32 range, which `main.cpp` gets right and `wa-overflow.cpp` gets wrong. Keep it conceptual; do not invent exact captured numbers (the asciinema cast carries the live values).

5. **Section "Making it stick".** This is the persistence beat. Describe the real flow from `rbx/box/cli.py:961`:
   - After a match, `rbx stress` asks: *"Do you want to add the tests that were found to a test group?"* — answer yes.
   - It lists test groups backed by a `.txt` generator script, plus `(create new script)` and `(skip)`. Choose `(create new script)` and name it `testplan/corner.txt`.
   - It appends the found generator call to `testplan/corner.txt` with a `# Obtained by running rbx stress ...` comment, and adds a `corner` group to `problem.rbx.yml`. Show the resulting `problem.rbx.yml` testcases entry and the `testplan/corner.txt` contents in tabbed blocks:
     ```
     === "problem.rbx.yml"
     === "testplan/corner.txt"
     ```
   - Then `rbx build` regenerates it, so the counterexample is now a permanent test. Add a `!!! tip` explaining that because testlib seeds from argv, the saved generator call reproduces the *exact same* input every build.
   - Add a `!!! note` forward-pointer: a future `rbx` release will let you promote a finding to a `manual_tests/` file in one step (#442); for now the test-group route above is the way.

6. **Section "Next steps".** A `<div class="grid cards" markdown>` block matching the one at the end of `first-steps.md`, with cards linking to:
   - Stress testing reference (`/setters/stress-testing`) — fuzzing, `--slowest`, saved `stresses:` blocks.
   - Generators (`/setters/testset/generators`).
   - `problem.rbx.yml` reference (`/setters/reference/package`).

**Step 2: Verify links resolve.**

Run: `uv run mkdocs build --strict`
Expected: build succeeds. (At this point the new page is not in nav yet, so mkdocs will emit an "exists in docs but not in nav" WARNING but `--strict` on the *unreferenced page* warning will fail — that is expected and fixed in Task 3. If `--strict` fails ONLY on the not-in-nav warning for this file, proceed to Task 3; any other error must be fixed first.)

---

### Task 2: Add the asciinema placeholder marker (folded into Task 1)

This is covered inside Task 1, Step 1.3. No separate file work. The deliverable is: the page contains exactly one `{{ asciinema("REPLACE_ME_CAST_ID") }}` and one `<!-- TODO(#437): ... -->` comment so the maintainer can find and replace it. Confirm with:

Run: `grep -n "REPLACE_ME_CAST_ID\|TODO(#437)" docs/setters/stress-testing-walkthrough.md`
Expected: two matching lines.

---

### Task 3: Wire the page into the nav

**Files:**
- Modify: `mkdocs.yml` (the `Walkthrough → Authoring a problem` list, around line 12-13)

**Step 1: Add the nav entry.**

Under `Authoring a problem`, after the `First steps` line, add:
```yaml
          - "Stress-testing your solutions": "setters/stress-testing-walkthrough.md"
```

**Step 2: Verify strict build passes.**

Run: `uv run mkdocs build --strict`
Expected: PASS with no warnings about the new page.

**Step 3: Commit.**

```bash
git add docs/setters/stress-testing-walkthrough.md mkdocs.yml
git commit -m "docs(walkthrough): add stress-testing walkthrough page"
```
(Use the `/commit` skill workflow per CLAUDE.md; append the co-author trailer.)

---

### Task 4: Repoint the First steps next-steps card

**Files:**
- Modify: `docs/setters/first-steps.md:423-429` (the "Stress test" card)

**Step 1: Change the card link.**

The card currently links to `/setters/stress-testing`. Repoint it to the walkthrough so the authoring story flows forward:
- Change the link target to `/setters/stress-testing-walkthrough`.
- Optionally tweak the blurb to read as the narrative next step (e.g. "Walk through finding a counterexample for a buggy solution.").

**Step 2: Verify strict build passes.**

Run: `uv run mkdocs build --strict`
Expected: PASS.

**Step 3: Commit.**

```bash
git add docs/setters/first-steps.md
git commit -m "docs(walkthrough): link first steps to stress-testing walkthrough"
```

---

### Task 5: Visual review of the rendered page

**Step 1: Serve and eyeball.**

Run: `uv run mkdocs serve` (background), open `http://127.0.0.1:8000/setters/stress-testing-walkthrough/`.
Check: tabbed code blocks render, admonitions render, the asciinema placeholder area is visibly marked pending, next-steps cards render in a grid, all in-page links resolve. Stop the server.

**Step 2: Confirm reference page is untouched.**

Run: `git status` and `git diff --stat`
Expected: only `docs/setters/stress-testing-walkthrough.md`, `mkdocs.yml`, `docs/setters/first-steps.md`, and the design/plan docs changed. `docs/setters/stress-testing.md` must NOT appear.

---

### Task 6: Leave the follow-up note on #442

**Step 1: Comment on the issue.**

Run:
```bash
gh issue comment 442 --body "When this lands, update step 4 (\"Making it stick\") of the new stress-testing walkthrough (docs/setters/stress-testing-walkthrough.md) to use the one-command promote-to-manual_tests/ flow instead of the current add-to-test-group prompt. Tracked from #437."
```
Expected: comment URL printed.

---

### Task 7: Finish the branch

Use superpowers:finishing-a-development-branch to decide merge vs PR. The asciinema cast remains a maintainer follow-up (placeholder id is intentional and documented in the page + design doc) — call this out in the PR/merge summary.
