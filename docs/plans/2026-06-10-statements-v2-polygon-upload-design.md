# Statements v2 — Polygon API upload (S12, #568)

Parent: [#556 — statements v2](https://github.com/rsalesc/rbx/issues/556).
Depends on: #566 (S10, contest join — merged).
Date: 2026-06-10
Status: **approved design**, ready to implement.

## 1. Scope

S12 reworks the **Polygon API upload** path (`rbx package polygon --upload` /
`--validate-statement`) onto statements v2: consume the now-portable,
self-contained overlay TeX, drop the absolute-/temp-path special-casing, and keep
forcing `externalize`/`demacro` at export time (they are no longer schema
fields). It replicates the v1 behavior the setter relied on — **block production**
(the `blocks.*.yml` files in the build dir, the source of truth for Polygon
blocks) and **TikZ production** (externalized per-block figure PDFs uploaded as
resources).

**Out of scope (separate issue):** re-enabling statement embedding in the
*offline* `problem.zip` / `contest.zip` packagers (`_process_statements`, today
commented out). Filed as a follow-up.

## 2. Key idea: the v2 overlay root *is* the "statement dir"

v1's Polygon path keyed everything off
`get_statement_dir(statement, builder_name)` — per-builder scratch subdirs under
`build/statements/<name>/<builder>/` holding `blocks.*.yml` (rbxTeX builder),
`macros.json` and `artifacts/tikz_figures/*.pdf` (TeX2PDF builder). Samples were
injected by **absolute path**, which forced the packager into path special-casing
(design §1).

v2 already stages a single, self-contained overlay per `(language, variant)` at
`build/statements/st/<lang>-<variant>/`, references everything by **relative**
paths, runs `pdflatex` from that root, and — when `externalize`/`demacro` are on
— already drops `macros.json` and `artifacts/tikz_figures/*.pdf` there. So we make
**that overlay root the single Polygon source dir** and persist the block YAMLs
beside the existing artifacts. The per-builder subdirs and absolute/temp paths
collapse into one portable, relative-pathed directory (design §6.5).

The orchestration is already correct: `run_packager` builds **every** statement
with `externalize=True, demacro=True` forced for polygon (via
`get_packager_extra_mergeable_params`) *before* `upload_problem` /
`validate_statements` read the artifacts. The only gaps are (a) producing &
persisting the blocks, and (b) repointing the Polygon readers at the overlay.

The block↔PDF↔`\includegraphics` contract is unchanged and reused verbatim:
`add_labels_to_tikz_nodes(prefix=<block>)` emits `\tikzsetnextfilename{<block>_<i>}`
→ `\tikzexternalize[prefix=artifacts/tikz_figures/]` (added by
`inject_externalization_for_tikz`) emits `artifacts/tikz_figures/<block>_<i>.pdf`
→ `replace_labeled_tikz_nodes` rewrites the labeled TikZ to
`\includegraphics{artifacts/tikz_figures/<block>_<i>}`. Because the externalized
filenames come from labels in the body, **per-block labeling must happen before
the full-doc compile** — so externalization is threaded through
`render_problem_tex` (engine), exactly mirroring v1's `rbxTeXBuilder`.

## 3. Changes

1. **Block production + persistence — `engine.render_problem_tex`,
   `build_statements.build_statement`.** Thread an `externalize` flag into
   `render_problem_tex`. It already extracts blocks; additionally:
   - always write `blocks.yml` (raw extracted blocks — the source of truth);
   - when `externalize`: per-block TikZ labeling (`externalize_blocks` over blocks
     **and** sample explanations) → write `blocks.ext.yml`; render the *labeled*
     blocks into the compiled full doc (so `\tikzexternalize` produces the figure
     PDFs); then `substitute_externalized_blocks` → write `blocks.sub.yml`.
   - All three YAMLs are written for v1 parity / debuggability. They land in
     `problem_root` (= the overlay root for the standalone build, which is the
     only mode Polygon upload uses).
   - Reuses the v1 helpers (`externalize_blocks` / `substitute_externalized_blocks`)
     still in `builders.py`.

2. **Un-stub the Polygon export entry points — `build_statements.py`.**
   - `get_statement_dir(statement)` → the standalone overlay root for
     `(language, variant)` (`_standalone_overlay_root`'s path, without re-wiping).
   - `get_produced_tikz_pdfs(statement)` → glob
     `<overlay>/artifacts/tikz_figures/**/*.pdf`, yielding `(abspath, relpath)`.
   - delete the dead `build_statement_bytes` stub (nothing consumes it once the
     block path is rebuilt; #580 sweeps remaining v1 code).

3. **Rewrite `statement_block_utils.py`.** Read `blocks.sub.yml` + `macros.json`
   from the **single** overlay root (no per-builder subdirs, no
   `rbxTeXBuilder`/`TeX2PDFBuilder` imports). Keep the existing
   defs-macro-collection → macro filter → `convert_to_polygon_tex` pipeline.

4. **Fix `upload.py` for the v2 schema.** `statement.path` → `statement.file`;
   drop the removed `statement.assets`. Statement resources become the whole
   statement-file directory subtree (the v2 asset scope) plus
   `get_produced_tikz_pdfs`. All paths relative.

5. **Packager owns the toggle — `packager.py`.** Move the externalize/demacro
   forcing out of the `if name == 'polygon'` branch in
   `get_packager_extra_mergeable_params` into a `PolygonPackager` method,
   resolving the existing `# TODO: migrate this into the packager class`.

## 4. Testing

- Integration over a contest+problem testdata fixture carrying a `defs` block and
  an inline TikZ picture: `build_statement(..., externalize=True, demacro=True)`
  persists `blocks.yml` / `blocks.ext.yml` / `blocks.sub.yml` + `macros.json` +
  at least one `artifacts/tikz_figures/*.pdf`; `blocks.sub.yml`'s legend has the
  TikZ replaced by `\includegraphics{artifacts/tikz_figures/...}`.
- `get_processed_statement_blocks` returns legend/input/output/notes as
  Polygon-valid TeX (macros expanded/filtered, Polygon conversion applied).
- `get_statement_dir` / `get_produced_tikz_pdfs` overlay mapping.
- Live `--upload` is Polygon-API-bound → verified manually against the authorized
  POLYGON creds, not in CI.

## 5. Follow-up

- Offline Polygon packager statements (re-enable `_process_statements` for
  `problem.zip` / `contest.zip`) — separate issue.
