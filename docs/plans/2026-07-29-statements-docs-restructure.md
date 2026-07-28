# Statements docs restructure — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite the **Feature Guide → Statements** section to the current (v2) statement model as five focused, example-driven pages.

**Architecture:** Content rewrite + light nav reshape. Guide pages carry concepts + correct examples; exhaustive field lists stay in the auto-generated Reference (mkdocstrings). Formats collapse into one rbxTeX-first *Writing statements* page. Two new pages (*Template context*, *Tutorials*) cover surface with no page today. `index.md` and `contest.md` keep their paths (most-linked); retired pages accept URL changes (no `mkdocs-redirects` dependency added).

**Tech stack:** MkDocs + Material, `mkdocs-macros-plugin`, `mkdocstrings[python]`, `termynal`, `mkdocs-gen-files`. Build: `uv run mkdocs build` (non-strict).

**Design source:** [`2026-07-29-statements-docs-restructure-design.md`](2026-07-29-statements-docs-restructure-design.md). Model source of truth: [`2026-06-09-statements-v2-design.md`](2026-06-09-statements-v2-design.md), `rbx/box/statements/schema.py`, `rbx/box/contest/schema.py`, `rbx/box/statements/CLAUDE.md`.

---

## House conventions (apply to every page)

- **Macros** (from `mkdocs.yml` `extra:`): write `{{rbx}}`, `{{rbxtex}}`, `{{Jinja2}}`, `{{latex}}`, `{{polygon}}`, `{{boca}}`, `{{testlib}}` instead of literal names.
- **Admonitions:** `!!! tip` / `!!! note` / `!!! warning`, titled where useful.
- **Code blocks:** fenced with language + `title=`, e.g. ```` ```yaml title="problem.rbx.yml" ````. Use numbered annotations (`# (1)!` + a matching numbered list) for anything non-obvious.
- **Tabs:** `=== "Tab"` to show `*.rbx.tex` next to `problem.rbx.yml`.
- **CLI:** show full + alias (`rbx statements build` / `rbx st b`); use `termynal` blocks for runnable sequences.
- **Cross-links:** relative `.md` links + `#anchor`.

## Canonical schema facts (never regress these)

- Fields: `language`, `variant` (default `default`), `title`, `file` (**not `path`**), `type`, `params` (**not statement-level `vars`**), `samples`, `assets`, `extends`. **Problem** statements have **no `name`**; **contest** statements/documents **require `name`**.
- Do **not** document `path` / `configure` / `match` / `joiner` / `override` / `steps` / `inheritFromContest` — all removed.
- `type` values (case/hyphen-insensitive; omit when default `rbx-tex`): `rbx-tex`, `rbx-md`, `tex`, `md`, `jinja-tex`, `jinja-md`, `pdf`. Only `rbx-tex`/`rbx-md` can **join** into a contest. `documents` may use only `jinja-tex | jinja-md | tex | md | pdf`.
- Templates live on the **contest** statement: `standaloneProblemTemplate` (full doc, `rbx st b`) and `contestProblemTemplate` (fragment, `rbx contest st b`) — rbx\* types only, alongside `variant`/`params`.

## Verification gate (referenced as "run the gate")

1. `uv run mkdocs build` → **Expected:** completes; **no ERROR** and no new `WARNING` about the page you touched. (Strict mode has ~9 pre-existing unrelated warnings — do **not** use `--strict`.)
2. Staleness grep over the pages you changed:
   `grep -nE '(^|[^a-z])(path|configure|match|joiner|override|inheritFromContest):' <files>` → **Expected:** no hits.
   `grep -nEi 'vars:' <problem-statement-example-files>` → **Expected:** no statement-level `vars:` (problem/contest `vars:` at package level is fine — check context).
3. Eyeball every YAML/tex snippet against the Canonical schema facts.

---

## Task 0: Verify the live surface against code (research only — no commit)

The old pages are stale; confirm these before writing, and keep the findings handy for Tasks 1–5.

**Read / run:**
- `rbx/box/statements/context.py` — exact per-sample handle names and `problem` namespace fields actually populated. Old docs showed `sample.inputPath`/`outputPath` + `.read_text()`; design says `sample.input`/`output` (root-relative), `sample.dir`, `sample.explanation_file`. **Use whatever `context.py` actually exposes.**
- `rbx/box/statements/schema.py` + `rbx/box/contest/schema.py` — re-confirm field docstrings for the tables.
- Default/semantic block names: `grep -rn "blocks" rbx/box/statements/` and inspect the preset `blocks.yml` / Polygon path so the blocks table (`legend`, `input`, `output`, `interaction`, `notes`, `explanation_N`, …) is accurate.
- No-contest fallback (#571): confirm actual behavior in `rbx/box/statements/resolver.py` (fallback + warning; unselected multi-contest dispatcher still errors; `>1` standalone candidate errors).
- CLI: `rbx st b --help`, `rbx contest st b --help`, `rbx tut b --help` for exact flags (`-l`, `-p`) and output filenames (`build/statement-<lang>[-<variant>].pdf`).

**Record** the confirmed handle/field/block names inline as you write each page. No file changes in this task.

---

## Task 1: Overview — rewrite `docs/setters/statements/index.md`

**Files:** Modify `docs/setters/statements/index.md` (keep path).

**Content (sections from design §4.1):**
1. *What a statement is* — a `(language, variant)` source of some `type`, rendered to PDF; one entry per language.
2. *The three kinds* — table:

   | Kind | Where | Joins problems? | Purpose |
   |---|---|---|---|
   | `statements` | problem + contest | contest join | the problem/contest statement |
   | `tutorials` | problem + contest | contest join | editorials |
   | `documents` | contest only | never | infosheets, cover pages |
3. *Where they're declared* — minimal snippets:
   ```yaml title="problem.rbx.yml"
   statements:
     - language: en
       file: statements/statement-en.rbx.tex   # (1)!
   ```
   ```yaml title="contest.rbx.yml"
   statements:
     - name: main-en
       language: en
       file: statements/contest-en.rbx.tex
       standaloneProblemTemplate: statements/problem-standalone.rbx.tex
       contestProblemTemplate: statements/problem-in-contest.rbx.tex
   ```
4. *Formats at a glance* — table of `type` → one-line "when to use" + "joins? (rbx\* only)"; link each to *Writing statements*.
5. *Building* — `termynal` with `rbx st b`, `rbx contest st b`, `rbx tut b`; mention `-l <lang>` and `-p <profile>`; output filenames.
6. *Pipeline* — refresh the existing `mermaid graph LR`; note the contest owns the chrome, with the no-contest fallback (one-line, link *Contest statements*).
7. *Next* — links to the other four pages.

**Verify:** run the gate on `docs/setters/statements/index.md`.

**Commit:** `docs(statements): rewrite statements overview for the current model`

---

## Task 2: Writing statements — new `writing.md`, retire `formats/*`, fix nav + macro

**Files:**
- Create `docs/setters/statements/writing.md`
- Delete `docs/setters/statements/formats/rbxtex.md`, `formats/latex.md`, `formats/pdf.md`
- Modify `mkdocs.yml` (nav + `{{rbxtex}}`/`{{rbxTeX}}` macro target)

**Content (design §4.2), rbxTeX-first:**
1. *rbxTeX — what & why* (the recommended format; a `.rbx.tex` of blocks + `{{Jinja2}}`). Salvage the accurate conceptual prose from the old `formats/rbxtex.md`.
2. *Blocks* — `%- block <name> … %- endblock`; the verified default/semantic block table; custom blocks; note templates read them via `problem.blocks.<name>` (link *Template context*).
   ```latex title="statement.rbx.tex"
   %- block legend
   Given an array of \VAR{vars.n} integers ...
   %- endblock

   %- block input
   The first line contains \VAR{vars.n}.
   %- endblock
   ```
3. *Variables & logic* — `\VAR{...}`, `%#` comments, `%- … %-` loops/conditionals, filters (`sci`). Link *Template context* for what's in scope.
4. *Samples & explanations* — the 3 explanation sources; **recommend** the `<sample>.rbx.tex` sibling with per-language `%- block <langcode>`; the "not both `.rbx.tex` and `.tex`" error; Markdown variants.
5. *Assets & resources* — golden rule: put images / `.sty` / PDFs **in the same directory as your `.tex`**; they resolve by relative path (rbx stages a portable overlay — no `\graphicspath`, no `TEXINPUTS`). The `assets` glob (relative to package root) ships extra/out-of-tree resources. Keep it user-level — **no temp-dir internals**.
6. *Other formats* (short subsections): **Markdown** (`rbx-md`, same blocks/vars, pandoc) · **Jinja** (`jinja-tex`/`jinja-md`, no blocks/joining — for `documents`) · **plain LaTeX / Markdown** (`tex`/`md`, passthrough) · **PDF** (`pdf`, bring your own, copied through).

**mkdocs.yml nav** — replace the `Formats` subtree; the `Statements` block becomes:
```yaml
- "Statements":
    - "Overview": "setters/statements/index.md"
    - "Writing statements": "setters/statements/writing.md"
    - "Template context": "setters/statements/context.md"      # created in Task 3
    - "Contest statements": "setters/statements/contest.md"
    - "Tutorials": "setters/statements/tutorials.md"            # created in Task 5
```
> Add the `context.md` / `tutorials.md` nav lines only once those files exist (Tasks 3/5) to keep every build green — in this task, add just the `writing.md` line and drop the `Formats` group and `templates.md`. (templates.md file itself is removed in Task 4.)

**mkdocs.yml macro** — repoint `{{rbxtex}}`/`{{rbxTeX}}` from `/setters/statements/formats/rbxtex` to `/setters/statements/writing`.

**Verify:** run the gate on `writing.md` + `mkdocs.yml`; also `grep -rn "formats/rbxtex\|formats/latex\|formats/pdf" docs/ mkdocs.yml` → no remaining references.

**Commit:** `docs(statements): consolidate formats into an rbxTeX-first writing guide`

---

## Task 3: Template context — new `context.md`

**Files:** Create `docs/setters/statements/context.md`; add its nav line under `Statements` in `mkdocs.yml`.

**Content (design §4.3):**
1. *Namespaces don't merge* (headline). Table (fill fields from Task 0):

   | Namespace | Contents | Available in |
   |---|---|---|
   | `params` | this statement's own `params` | all renders |
   | `vars` | problem/package `vars` (problem) or contest `vars` (contest) | all renders |
   | `contest` | `title`, `location`, `date`, `contest.vars` | always |
   | `problem` | `title`, `short_name`, `limits`, `profiles`, `groups`, `samples`, `blocks`, `import_dir`, `import_file` | problem renders |
   | `problems` | list of the above (full); metadata-only in `documents` | contest join; documents |
   | `lang`, `languages`, `keyed_languages` | environment languages | all renders |
2. *`params` vs `vars`* — why separate; side-by-side:
   ```latex
   \VAR{params.show_limits}   %# the statement's own param
   \VAR{vars.author}          %# a problem/package var
   \VAR{contest.title}        %# contest metadata
   ```
3. *The `problem` namespace* + `problem.blocks.<name>` to pull statement content into a template.
4. *Per-sample handles* (verified names) — I/O printing vs `\subimport` explanations; interaction chunks.
5. *Full field reference* — link to the auto-generated `setters/reference/package/schema.md` / contest schema.

**Verify:** run the gate on `context.md` + `mkdocs.yml`.

**Commit:** `docs(statements): document the template context namespaces`

---

## Task 4: Contest statements — rewrite `contest.md`, fold `templates.md`

**Files:**
- Modify `docs/setters/statements/contest.md` (keep path; heavy rewrite)
- Delete `docs/setters/statements/templates.md` (folded here); ensure it is no longer in nav (removed in Task 2).

**Content (design §4.4):**
1. *The contest owns the templates* — `standaloneProblemTemplate` (full doc) vs `contestProblemTemplate` (fragment); why two. (Salvage accurate template-authoring prose from the old `templates.md`, rebased onto these two fields.)
2. *Declaring contest statements* —
   ```yaml title="contest.rbx.yml"
   statements:
     - name: main-en                                          # (1)!
       language: en
       variant: default
       file: statements/contest-en.rbx.tex                    # the joined document
       standaloneProblemTemplate: statements/problem-standalone.rbx.tex
       contestProblemTemplate: statements/problem-in-contest.rbx.tex
   ```
3. *The (language, variant) join* — a contest statement renders/imports problem statements sharing its `(language, variant)`; exactly one standalone candidate must match (0 / >1 = hard error).
4. *Building* — `rbx contest st b` (joined PDF + `documents`); `rbx st b` borrows the contest's `standaloneProblemTemplate`. No-contest fallback + "dispatcher must be selected with `-C`".
5. *Documents* — never join; `DOCUMENT_TYPES` only; receive metadata-only `problems`:
   ```yaml title="contest.rbx.yml"
   documents:
     - name: infosheet-en
       language: en
       file: statements/infosheet-en.jinja.tex
       type: jinja-tex
   ```
   Example use: a per-problem limits table.
6. *`location` / `date`* per language.
7. *Reusing recipes with `extends`* — contest by `name`; problem by `extends: en` or `{language, variant}`; allowlist merge (recipe only, never `name`/`language`/`variant`):
   ```yaml title="contest.rbx.yml"
   statements:
     - name: main-en
       language: en
       file: statements/contest-en.rbx.tex
       standaloneProblemTemplate: statements/problem-standalone.rbx.tex
       contestProblemTemplate: statements/problem-in-contest.rbx.tex
     - name: main-pt
       language: pt
       extends: main-en          # inherits type + both templates
       file: statements/contest-pt.rbx.tex
   ```
   ```yaml title="problem.rbx.yml"
   statements:
     - language: en
       file: statements/statement.rbx.tex
       params: { show_limits: true }
     - language: pt
       extends: en               # inherits file + type + params
       params: { show_limits: false }   # override one key
   ```

**Verify:** run the gate on `contest.md`; `grep -rn "templates.md\|statements/templates" docs/ mkdocs.yml` → no remaining references.

**Commit:** `docs(statements): rewrite contest statements around v2 templates and joins`

---

## Task 5: Tutorials — new `tutorials.md`

**Files:** Create `docs/setters/statements/tutorials.md`; add its nav line under `Statements`.

**Content (design §4.5):**
1. Same model as statements, separate `tutorials` list, `tutorial-<lang>.pdf` output.
2. Declaring on problem + contest:
   ```yaml title="problem.rbx.yml"
   tutorials:
     - language: en
       file: statements/tutorial-en.rbx.tex
   ```
3. Building — `rbx tut b` / `rbx contest tut b`.
4. What carries over (everything on *Writing* / *Template context* / *Contest*) vs what differs (`documents` are statements-only, not tutorials).

**Verify:** run the gate on `tutorials.md` + `mkdocs.yml`.

**Commit:** `docs(statements): add tutorials (editorials) guide`

---

## Task 6: Ancillary — fix the stale statements snippet in the cheatsheet

**Files:** Modify `docs/setters/cheatsheet.md` (the "Add statements" section, ~lines 274–332).

**Content:** Replace stale `name`/`path`/`configure`/`template` YAML with the canonical v2 snippets (problem statement, `extends`, PDF). Keep the accurate CLI rows (`rbx st b`, `-l`, `-p`). Do **not** touch `first-steps.md` (walkthrough track, out of scope).

**Verify:** run the gate on `cheatsheet.md` + the staleness grep.

**Commit:** `docs(cheatsheet): correct the statements snippet for the current model`

---

## Task 7: Final audit

**Steps:**
1. Full `uv run mkdocs build` (non-strict) → no ERROR; only the known ~9 pre-existing warnings.
2. Repo-wide staleness sweep: `grep -rnE '(path|configure|match|joiner|override):' docs/setters/statements/ docs/setters/cheatsheet.md` → no statement-config hits.
3. Dead-link/anchor check across the five pages (cross-links resolve; `{{rbxtex}}` renders to `/setters/statements/writing`).
4. Confirm each page reads short-paragraph + example-first (the brief) and links to the auto-generated reference rather than duplicating field tables.
5. `requesting-code-review` (optional): use superpowers:requesting-code-review before opening/finalizing the PR.

**Commit (if any fixes):** `docs(statements): final build + link audit fixes`

---

## Notes for the executor

- DRY: each concept has one home (per the table in design §5) — link, don't repeat.
- YAGNI: no temp-dir/overlay internals in the guide; that lives in the design doc + code.
- Frequent commits: one per task, message prefix `docs(...)` (conventional commits — see `.claude/skills/commit.md`).
- Keep `index.md` and `contest.md` at their current paths; the two most-linked URLs stay stable.
