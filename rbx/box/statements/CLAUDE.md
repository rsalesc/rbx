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

- **`resolver.py`** (S7) — contest-aware resolution. `resolve_standalone` (picks the
  single matching contest statement, or falls back to the bundled default chrome when
  none matches / there is no contest — S15 / #571; an *unselected dispatcher* still
  errors); `select_standalone_contest_statement` (the single contest statement whose
  `(language, variant)` carries a `standaloneProblemTemplate` — 0/>1 are errors);
  `select_problem_statement` (join match by `(language, variant)` + matching rbx type).
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
- **`render.py`** (S8) — the low-level render primitives, driven by the v2
  context. Owns the rbxTeX block-extraction helpers (`StatementBlocks`,
  `render_jinja`, `render_jinja_blocks`) and the TikZ externalize/substitute
  helpers (`externalize_blocks` / `substitute_externalized_blocks`) — these moved
  here from the deleted `builders.py` (#580). Higher-level entry points:
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
- **Tutorials (editorials)** are the parallel `tutorials` section (design §3),
  built by the same code via a `StatementKind` arg threaded through
  `build_statement` / `execute_build` (problem) and `build_statement` (contest):
  it selects `expanded_tutorials` over `expanded_statements` on both sides and the
  `tutorial-<lang>` output prefix. The CLI exposes them as a parallel `tutorials,
  tut` app — `rbx tut b` / `rbx contest tut b` (`tutorials_app` in
  `build_statements.py` / `contest/statements.py`); `documents` build only under
  the statements command.

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

## v1 removed (#580)

The legacy v1 build machinery has been **deleted** now that v2 (incl. the Polygon
export path, #568) owns every live build:

- `builders.py` — the `StatementBuilder` classes + `StatementBuilderProblem/Contest`
  and the v1 builder-chain. The handful of still-live low-level helpers
  (`StatementBlocks`, `render_jinja`, `render_jinja_blocks`, `externalize_blocks`,
  `substitute_externalized_blocks`) moved into `render.py`.
- `joiners.py` — the v1 contest-join builders (v2 joins via `\subimport`).
- `statement_utils.py` — `get_relative_assets` (the v2 overlay mirrors whole asset
  dirs; no relative-asset enumeration needed).
- `build_statements.py` lost its dead v1 builder-chain resolver (`get_builders`
  et al.).
- `schema.py` lost the dead conversion/joiner models (`JinjaTeX`, `rbxMarkdownToTeX`,
  `JoinerType`, `JoinTexToPDF`, `Joiner`). The export-time vocabulary that survives
  is `ConversionType` / `ConversionStep` / `rbxToTeX` / `TexToPDF` (the packager's
  externalize/demacro toggles — design §2 decision 6).

## Polygon export (S12, #568) — `build_statements` + `polygon/statement_block_utils`

The Polygon API upload (`rbx package polygon --upload` / `--validate-statement`)
consumes the v2 overlay directly. The standalone overlay root
(`build/statements/st/<lang>-<variant>/`) **is** the Polygon "statement dir":

- The packager forces `externalize`+`demacro` via
  `PolygonPackager.statement_export_params()`; `run_packager` builds every
  statement with them before reading the artifacts.
- `engine.render_problem_tex(externalize=...)` always writes `blocks.yml` (the
  raw blocks — source of truth) and, when externalizing, labels per-block TikZ
  before the compile (so `\tikzexternalize` emits one PDF per figure) and writes
  `blocks.ext.yml` (labeled) / `blocks.sub.yml` (TikZ → `\includegraphics`).
- `build_statements.get_statement_dir(statement)` returns that overlay root;
  `get_produced_tikz_pdfs` globs its `artifacts/tikz_figures/*.pdf`.
- `polygon/statement_block_utils.get_processed_statement_blocks` reads
  `blocks.sub.yml` + `macros.json` from that single dir, expands/filters macros
  and converts to Polygon TeX (`polygon_utils.py`). No per-builder subdirs, no
  absolute/temp paths.

The **offline** Polygon packager (embedding PDFs in `problem.zip` /
`contest.zip`) is a separate follow-up (#583).

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

Helpers extracting/validating statement sections for Polygon upload
(`convert_to_polygon_tex`, `validate_polygon_tex`, `PolygonTeXConfig`) — consumed
by the S12 export path (see "Polygon export" above).
