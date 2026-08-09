# Statements docs restructure — design

**Status:** approved 2026-07-29 (brainstorm). Scope is the **reference / feature-guide** Statements section only.
**Tracking:** [#570 — statements v2: docs update](https://github.com/rsalesc/rbx/issues/570).
**Source of truth for the model:** [`docs/plans/2026-06-09-statements-v2-design.md`](2026-06-09-statements-v2-design.md) and `rbx/box/statements/CLAUDE.md`.

## 1. Motivation

The statement engine was rewritten (internally "statements v2", shipped in rbx 1.0). Every hand-written page under **Feature Guide → Statements** still documents the *pre-v2* schema — `name`/`path`/`configure`/`match`/`joiner`/`override` and statement-level `vars` — none of which exist anymore. The auto-generated Reference schema pages (mkdocstrings over the live Pydantic models) are already correct, so the fix is a **content rewrite of the guide pages**, plus a **light reshape of the section** to fit the new model and cover surface that has no page today (`tutorials`, `documents`, `variant`, the namespace split, `standaloneProblemTemplate`/`contestProblemTemplate`).

This doc defines the target page structure and each page's section breakdown. It does **not** write the page prose — that follows as an implementation plan.

## 2. Decisions

1. **Scope: feature-guide only.** The narrative walkthrough "Building contest statements" ([#438](https://github.com/rsalesc/rbx/issues/438)) is a separate Delivering-a-contest track effort and is **out of scope** here. We only link to it once it exists.
2. **No version label in user-facing docs.** "rbx v1" is already taken by `docs/migrating-to-v1.md` (BOCA/`env.rbx.yml` only, unrelated). "v2" is an internal name. The guide documents *the* statement system as it is today, with no version framing.
3. **Formats are one page, rbxTeX-first.** No page-per-format. `rbxTeX` gets the depth; Markdown / Jinja / plain LaTeX / PDF are short sections (escape hatches).
4. **Reference stays auto-generated.** Guide pages carry concepts + examples and link to the auto-generated schema reference for exhaustive field lists — no duplicated field tables.
5. **Five pages** (see §4), organized around the v2 mental model.

## 3. Target nav

```
Feature Guide → Statements
├── Overview            setters/statements/index.md          (keep path, rewrite)
├── Writing statements  setters/statements/writing.md        (NEW — consolidates formats/*)
├── Template context    setters/statements/context.md        (NEW)
├── Contest statements  setters/statements/contest.md        (keep path, heavy rewrite)
└── Tutorials           setters/statements/tutorials.md      (NEW)
```

Retired: `setters/statements/formats/{rbxtex,latex,pdf}.md` and `setters/statements/templates.md` (folded; redirects — see §6).

## 4. Page breakdowns

### 4.1 Overview — `index.md` (rewrite)

The mental model + orientation. Landing page.

- What a statement is: a `(language, variant)` source of some `type`, rendered to PDF. One entry per language.
- The three kinds — `statements` · `tutorials` (editorials) · `documents` (contest-only). Small table.
- Where they're declared: minimal `problem.rbx.yml` + `contest.rbx.yml` snippets.
- **Formats at a glance** — table of `type` values → one-line "when to use" + which can join (rbx\*). Links into *Writing statements*.
- Building: `rbx st b` / `rbx contest st b` / `rbx tut b` (termynal), with `-l` / `-p`.
- Refreshed pipeline mermaid diagram; a note that the contest owns the chrome (with the no-contest fallback).
- "Where to go next" links to the other four pages.

### 4.2 Writing statements — `writing.md` (new; consolidates `formats/*`)

Authoring source content, rbxTeX-first.

- rbxTeX: what & why (the recommended format).
- **Blocks** — `%- block … endblock`; default/semantic blocks table (`legend`, `input`, `output`, `interaction`, `notes`, `explanation_N`); custom blocks.
- **Variables & logic** — `\VAR{}`, `%#` comments, `%- … %-` loops/conditionals, filters (`sci`). Cross-links *Template context*.
- **Samples & explanations** — the 3 explanation sources; recommend the `<sample>.rbx.tex` sibling with per-language `%- block <lang>`; the "not both `.rbx.tex` and `.tex`" error.
- **Assets & resources** — the golden rule (put files next to your `.tex`, they resolve; rbx builds a portable overlay, no `\graphicspath`); the `assets` glob for out-of-tree files. *(User-level treatment of #570's overlay/path-resolution topic — no temp-dir internals.)*
- Short sections: **Markdown** (`rbxmd`) · **Jinja** (`jinja-tex`/`jinja-md`) · **plain LaTeX/MD** (`tex`/`md`) · **PDF** passthrough.

### 4.3 Template context — `context.md` (new)

The reference for what's available inside `\VAR{}` / `\BLOCK{}` and templates.

- **Namespaces don't merge** — the headline change. Full table: `params` · `vars` · `contest` · `problem` · `problems` · `lang`/`languages`/`keyed_languages`.
- `params` vs `vars` — why separate; side-by-side example (`\VAR{params.show_limits}` vs `\VAR{vars.author}`).
- The `problem` namespace + `problem.blocks.<name>` to pull statement content into a template.
- Per-sample handles — `sample.input`/`output`, `sample.dir`, `sample.explanation_file`, interaction chunks.
- Link out to the auto-generated schema reference for exhaustive fields.

### 4.4 Contest statements — `contest.md` (heavy rewrite)

How problems assemble into a contest PDF; where templates live.

- **The contest owns the templates** — `standaloneProblemTemplate` (full doc, `rbx st b`) vs `contestProblemTemplate` (fragment, the join). Why two.
- Declaring contest statements — `name` (unique) / `language` / `variant` / `file` / `type` / templates / `params`; YAML.
- **The (language, variant) join** — how contest ↔ problem statements match; `variant` pairs them; exactly-one-standalone-candidate rule (0 / >1 = hard error).
- Building `rbx contest st b`; the no-contest fallback + "dispatcher must be selected with `-C`" caveat.
- **Documents** (infosheets/covers) — never join; `DOCUMENT_TYPES` only; metadata-only `problems` (per-problem limits-table example).
- `location` / `date` per language.
- **Reusing recipes with `extends`** — contest by `name`; problem-level `extends: en` / `{language, variant}`; allowlist merge (build recipe only, never identity); cross-language example.

### 4.5 Tutorials (editorials) — `tutorials.md` (new)

- Same model as statements, separate list, `tutorial-<lang>.pdf` output.
- Declaring `tutorials` on problem + contest; building with `rbx tut b` / `rbx contest tut b`.
- What carries over (everything on the other pages) vs what differs (documents are statements-only, not tutorials).

## 5. Where #570's four topics land

| #570 topic | Home |
|---|---|
| schema | Overview + examples throughout; exhaustive fields via the auto-generated reference |
| namespaces | Template context (§4.3) |
| overlay / path-resolution | "Assets & resources" on Writing (§4.2, user-level) + the join mechanics on Contest (§4.4) |
| `extends` | "Reusing recipes" section on Contest (§4.4), covering both contest- and problem-level |

## 6. Open implementation details (resolve in the plan)

- **Consolidated page path + redirects.** `writing.md` replaces `formats/{rbxtex,latex,pdf}.md`; `templates.md` folds into `contest.md`. Add redirects for the retired URLs (check whether `mkdocs-redirects` is wired; if not, decide add-plugin vs accept-URL-change).
- **Macros.** `{{rbxtex}}` / `{{rbxTeX}}` in `mkdocs.yml` currently point at `/setters/statements/formats/rbxtex`; repoint to `writing`.
- **Nav update** in `mkdocs.yml` to express the five-page structure.

## 7. Content-accuracy sweep (applies to every rewritten example)

Rename/remove throughout: `path` → `file`; statement-level `vars` → `params`; drop `name` from **problem** statements (contest statements keep `name`); drop `configure` / `match` / `joiner` / `override` / `steps` / `inheritFromContest`. Do **not** document `steps`/`configure` — the conversion vocabulary (`externalize`/`demacro`) is export-time only and no longer user-facing.

**Ancillary (secondary to the five pages):** correct the stale `statements` snippet in `setters/cheatsheet.md`. `setters/first-steps.md` is walkthrough-track and out of scope here.

## 8. Verify against code before writing prose

Flagged by the docs/code map; confirm exact surface at authoring time rather than trusting the old pages:

- Exact per-sample handle names exposed by `rbx/box/statements/context.py` (old docs showed `sample.inputPath`/`outputPath` + `.read_text()`; v2 design says `sample.input`/`output` root-relative). 
- The `problem` namespace field list actually populated by `context.py`.
- The default/semantic block names as consumed by the Polygon path (`blocks.yml`) so the blocks table is accurate.
- The no-contest fallback behavior (#571) as implemented (fallback + warning; dispatcher error), which differs from the original design doc's "contest required".

## 9. Out of scope

- The #438 "Building contest statements" narrative walkthrough (separate track).
- Inner `rbx/box/statements/CLAUDE.md` refresh — related to #570 but a code-facing doc, tracked separately if needed.
- Any change to the auto-generated Reference schema pages (already correct).
