# Statements Module (`rbx/box/statements/`)

Builds problem & contest statements (and contest documents) from rbxTeX / LaTeX /
Markdown / Jinja sources into PDF (primarily; TeX/MD too).

This module is **statements v2** (design: `docs/plans/2026-06-09-statements-v2-design.md`,
issue #556). v2 simplified the YAML surface and reworked path resolution around a
**temp-dir overlay** that every asset resolves into by a plain relative path, joined
with `\subimport`. There is **no migration** from v1.

## Core decisions (design §2)

- **A contest is required** to build an *rbx* problem statement: the contest owns
  the templates. Static types (`tex`/`md`/`pdf`) build standalone without one.
- **Namespaces don't merge:** `params` (statement's own), `vars` (problem/package
  or contest), `contest.*` are separate template namespaces (§4).
- **Path resolution = full overlay, everything relative.** No user TeX is parsed
  or rewritten; the only injected construct is `\subimport`. pdflatex runs from
  the overlay **root**, so the generated TeX is portable (§6).

## Schema (`schema.py`)

- **`StatementType`** (AutoEnum): `rbxTeX` (default), `rbxMarkdown`, `TeX`,
  `Markdown`, `JinjaTeX`, `JinjaMarkdown`, `PDF`. `is_rbx()` → the joinable types.
- **`BaseStatement`** — shared fields: `language`, `variant`, `title`, `file`,
  `type`, `params` (own namespace), `samples`. `expanded_params` expands `params`.
- **`Statement`** (problem) — no `name`; identified by `(language, variant)`
  (unique within a problem). `extends` by language string or `{language, variant}`.
- **`ContestStatement`** (contest) — adds `name` (unique), `location`, `date`,
  `standaloneProblemTemplate`, `contestProblemTemplate` (rbx-only). `(language,
  variant)` need not be unique. `extends` by `name`.
- **`Document`** (contest) — like a contest statement but never joins; restricted
  to `DOCUMENT_TYPES` (jinja/static).

`expander.py` resolves `extends` via an **allowlist merge** (only the build recipe
— `type`/`file`/`params` + contest templates — never identity); topo sort with
cycle/dangling errors. Problem: `Package.expanded_statements`/`expanded_tutorials`;
contest: `Contest.expanded_statements`/`expanded_tutorials`/`expanded_documents`.

## v2 engine modules

The build is a pipeline of small, unit-tested pieces:

- **`resolver.py`** (S7) — contest-aware resolution. `require_contest_for_problem`
  (hard error outside a contest); `select_standalone_contest_statement` (the single
  contest statement whose `(language, variant)` carries a `standaloneProblemTemplate`
  — 0/>1 are errors); `select_problem_statement` (join match by `(language, variant)`
  + matching rbx type).
- **`overlay.py`** (S4) — the stager. `mirror_tree`/`merge_tree`;
  `stage_standalone_overlay` (merged root, collision-detected);
  `stage_join_problem` (isolated `.problems/<SHORT>/`); `stage_chrome` (contest
  chrome at root). The *directory containing a statement `file`* is its asset scope.
- **`context.py`** (S5) — namespaced Jinja kwargs. `ProblemRenderContext` /
  `ContestRenderContext` / `SampleHandle`; `problem_jinja_kwargs` /
  `contest_jinja_kwargs` build the `params`/`vars`/`contest`/`problem`/`problems`
  namespaces + `problem.import_dir`/`import_file` join handles.
- **`sample_staging.py`** (S6) — per-sample `.samples/<idx>/` folders: `in`/`out`
  mirrored (root-relative for `\VerbatimInput`), explanation rendered to
  `explanation.tex` with its source dir overlaid for figures (base-relative for
  `\subimport`), interactive chunks. Input is the light `SampleSource`.
- **`render.py`** (S8) — reuses the v1 primitives (block extraction, the LaTeX
  Jinja env, the `tex→pdf` pdflatex loop) driven by the v2 context.
  `extract_blocks`, `render_problem_document` (full doc OR fragment),
  `render_contest_document` (join), `render_jinja_document`, `compile_pdf`,
  `md_to_pdf`.
- **`engine.py`** — `render_problem_tex` ties extraction → sample staging →
  template render for one problem; shared by standalone and join so the same
  problem rendering is valid in both contexts.

## Build entry points

- **`build_statements.py`** (S9) — standalone `rbx st b`:
  `execute_build` → `execute_build_on_statements` → `build_statement`. For an rbx
  statement it resolves the contest, stages the merged overlay (contest chrome +
  problem dir), renders the `standaloneProblemTemplate` (a *full* document),
  compiles, and writes `build/statement-<lang>[-<variant>].pdf`. Static types are
  emitted directly.
- **`contest/build_contest_statements.py`** (S10) — `rbx contest st b`:
  `build_statement` stages chrome, renders each problem's `contestProblemTemplate`
  into `.problems/<SHORT>/statement.tex` (a *fragment*), then renders the contest
  `file` which `\subimport`s each via the import handles; compiles from the root.
  `build_document` emits documents without joining their statements/samples, but
  passes a **metadata-only** `problems` list (via `_collect_problem_metadata`:
  title/short_name/limits/profiles/groups, no blocks/samples/import handles) so a
  Jinja document can render e.g. an info sheet's per-problem limits table.

## Path resolution (design §6) — the contract proved by the spike (#557)

- `\subimport`, `\includegraphics`, `\input` are **import-base-relative**;
  `import.sty` rebases them at every nesting depth (no `\graphicspath`).
- `\VerbatimInput` (sample I/O) does **not** honor the import base → sample
  `input`/`output` handles are **root-relative**; the explanation goes through
  `\subimport` (base-relative). Both are relative → the overlay is portable.

## LaTeX integration (unchanged)

- `latex.py` — `Latex.build_pdf(temp_dir)` writes `statement.tex` and runs
  `pdflatex` with `cwd=temp_dir` (= the overlay root); rerun loop for cross-refs.
- `latex_jinja.py` — the LaTeX-flavored Jinja2 env (`\VAR{}`, `%-`, `\BLOCK{}`),
  `JinjaDictWrapper`/`JinjaGroupsGetter`, strict undefined.

## `builders.py` (legacy, kept for the deferred Polygon path)

The v1 `StatementBuilder` classes + `StatementBuilderProblem/Contest` and the
low-level helpers (`render_jinja`, `render_jinja_blocks`, `StatementBlocks`, TikZ
externalize helpers) live here. v2 `render.py` reuses the helpers; the builder
*classes* remain only because the Polygon export path (S12, #568) still imports
them. `build_statements.get_statement_dir` / `get_produced_tikz_pdfs` /
`build_statement_bytes` stay stubbed (`NotImplementedError`) until S12.

## Template context namespaces (design §4)

| Name | Contents | Where |
|---|---|---|
| `params` | the statement's own params | all renders |
| `vars` | problem/package vars (problem) or contest vars (contest) | all renders |
| `contest` | `title`, `location`, `date`, `contest.vars` | always |
| `problem` | `title`, `short_name`, `limits`, `profiles`, `groups`, `samples`, `blocks`, `import_dir`, `import_file` | problem renders |
| `problems` | list of the above (full) for a contest join; **metadata only** (title/short_name/limits/profiles/groups) for a document | contest join; documents |
| `lang`, `languages`, `keyed_languages` | env languages | all renders |

Per-sample handles: `sample.input`/`output` (root-relative), `sample.dir` +
`sample.explanation_file` (base-relative `\subimport`), `sample.interaction.chunks`.

## Polygon integration (`polygon_utils.py`)

Helpers extracting statement sections for Polygon upload — consumed by the
deferred S12 export path.
