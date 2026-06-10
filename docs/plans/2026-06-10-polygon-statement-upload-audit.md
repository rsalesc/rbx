# Audit: Polygon API statement-upload path (statements v2) — #586

Date: 2026-06-10

This audit grills the `rbx package polygon -u` statement-upload path introduced
by statements v2 (S12, #568). It was produced alongside a new `pdflatex` e2e
category (`mise run test-e2e-pdflatex`) that exercises the path end-to-end against
a recording Polygon fake (no network). Each finding cites the e2e scenario (under
`tests/e2e/testdata/`) that demonstrates it.

Per the issue's directive, **bugs are documented here and fixed in a separate PR**.
Where an e2e scenario would otherwise be red on a confirmed bug, the suite encodes
the *current* behavior (green) and a companion scenario asserting the *desired*
behavior is registered `xfail` (non-strict) in `tests/e2e/conftest.py`, so it flips
to `xpass` the moment the bug is fixed.

## Data-flow recap

`rbx package polygon -u` (`packaging/main.py`) →
`run_packager(PolygonPackager, samples_only=True, skip_packaging=True)` builds the
samples and each statement's **standalone overlay** with `externalize=True` +
`demacro=True` (`PolygonPackager.statement_export_params`), producing
`build/statements/st/<lang>-<variant>/{blocks.sub.yml, macros.json,
artifacts/tikz_figures/*.pdf}`. Then `upload.upload_problem` →
`_upload_statement` reads those via
`statement_block_utils.get_processed_statement_blocks` (macro expand/filter →
Polygon-TeX), uploads assets via `_upload_statement_resources`, rewrites block
asset references, and calls `problem.save_statement` with
`legend/input/output/interaction/notes` (no PDF). Sample explanations are merged
into `notes`.

## Findings

| # | Severity | Area | Verdict |
|---|----------|------|---------|
| 1 | **High** | Standalone overlay collision (default preset) | **Bug** |
| 2 | **High** | Sample-explanation TikZ not externalized | **Bug** |
| 3 | High | `\includegraphics[opts]{}` mangled by Polygon-TeX conversion | **Bug** |
| 4 | Medium | Separate `<idx>.rbx.tex` explanations never reach `notes` | **Gap** |
| 5 | Low | Sample I/O + explanation sources uploaded as resources | **Bug (noise)** |
| 6 | Low–Med | Root-vs-subdir resource remap asymmetry; naive `str.replace` | **Suspicious** |
| 7 | Low | Existing `default-preset` e2e fixture broken post-v2 | **Test bug** |

### 1. The default preset's Polygon upload is broken by an overlay collision — **Bug (High)**

`rbx package polygon -u` (and `rbx st b`) on a default-preset problem fail before
any upload with:

```
Asset name collision while merging the contest chrome into the problem overlay:
  - editorial.rbx.tex
```

The standalone overlay (`overlay.stage_standalone_overlay`) merges the **contest
chrome** (the directory of the contest statement `file` = `statements/`, which
contains the editorial template `editorial.rbx.tex`) with the **problem statement
asset scope** (the directory of the problem statement `file` = `statement/`, which
contains the problem's `editorial.rbx.tex`). Both land at the overlay root with the
same basename → the merge’s collision guard aborts. Because the Polygon export
builds this same standalone overlay (forced externalize), the upload cannot run for
any problem created from the shipped default preset.

- **Evidence:** `tests/e2e/testdata/polygon-default-preset/` scenario
  `problem-polygon-upload-collision` (green, asserts the failure);
  `problem-polygon-upload` (xfail, the desired success). `contest-statement-build`
  shows `rbx contest st b` is unaffected (the join overlay isolates each problem
  under `.problems/<SHORT>/`).
- **Suggested fix:** give the contest editorial template and the problem editorial
  a non-colliding name in the bundled preset (e.g. ship the contest template as
  `editorial-template.rbx.tex`), or have the standalone overlay namespace the
  contest chrome separately from the problem asset scope so equal basenames in the
  two roots do not collide. The preset templates are very recent (#567/#577), so
  the standalone path was likely never exercised against them.

### 2. Sample-explanation TikZ pictures are not externalized/uploaded — **Bug (High)**

An inline `%- block explanation_0` containing a `\tikzpicture` is merged into the
uploaded `notes` as:

```
\begin{center}\includegraphics{artifacts/tikz_figures/0_0}\end{center}
```

but **no `artifacts/tikz_figures/0_0.pdf` is ever produced or uploaded** (only the
legend's `artifacts__tikz_figures__legend_0.pdf` exists). So the notes reference a
resource that does not exist — Polygon would render a broken image. Two sub-issues:

1. The explanation block's TikZ is substituted to an externalized `\includegraphics`
   path even though it is never compiled (the standalone template renders the
   legend, not the explanation), so no externalized PDF is emitted.
2. The substituted reference (`artifacts/tikz_figures/0_0`) is **not** normalized to
   the uploaded `__`-joined form, and is **not** in the resource remap — unlike the
   legend's TikZ (`legend_0` → `artifacts__tikz_figures__legend_0.pdf`). Note also
   the label scheme differs (`0_0` vs `legend_0`).

By contrast the explanation's *image* (`\includegraphics{figs/expl}`) **is** handled
correctly: remapped to `figs__expl.png`, uploaded, and rewritten in `notes`.

- **Evidence:** `tests/e2e/testdata/polygon-tikz-assets/` scenario
  `polygon-upload-assets` (green; asserts the broken `artifacts/tikz_figures/0_0`
  reference is present and the `__`-PDF is absent) and
  `polygon-upload-assets-referential-integrity` (xfail; the desired "every
  `\includegraphics` resolves").
- **Suggested fix:** externalize TikZ inside explanation blocks the same way as the
  named blocks (label + compile + emit a PDF, with a `explanation_<i>`-namespaced
  filename), and route the substituted reference through the resource remap so the
  uploaded name matches an uploaded resource.

### 3. `\includegraphics[opts]{file}` is mangled into `\includegraphics{opts}{file}` — **Bug (High)**

With an optional argument, the Polygon-TeX conversion
(`statements/polygon_utils.convert_to_polygon_tex`) turns
`\includegraphics[width=1cm]{pic}` into `\includegraphics{width=1cm}{pic}` — the
optional `[...]` becomes a second mandatory `{...}` group, which is invalid and
would break the asset reference on Polygon.

- **Evidence:** observed in the captured `legend` while developing the
  `polygon-tikz-assets` fixture (the committed fixture uses option-less
  `\includegraphics{...}` so the asset-resolution assertions stay clean). Reproduce
  by adding `[width=1cm]` to any image in `A/statement/statement.rbx.tex` and
  inspecting the captured statement.
- **Suggested fix:** preserve `\includegraphics` optional arguments through the
  Polygon-TeX conversion (or strip them), never convert `[...]` to `{...}`.

### 4. Separate `<idx>.rbx.tex` sample-explanation files never reach `notes` — **Gap (Medium)**

Only **inline** `%- block explanation_<i>` blocks populate
`StatementBlocks.explanations` and thus the uploaded `notes`. The default preset
ships sample explanations as **separate** `statement/samples/<idx>.rbx.tex` files
(resolved at sample-staging time for the PDF). Those are *not* extracted into
`explanations`, so the explanation text is **absent from the Polygon notes** — while
the raw `.rbx.tex` source is uploaded as a resource (see #5).

- **Evidence:** the first `polygon-tikz-assets` iteration (separate
  `samples/000.rbx.tex`) produced `notes` with no explanation; switching to an inline
  `explanation_0` block made it appear.
- **Suggested fix:** when building the Polygon blocks, fold separate-file sample
  explanations into `explanations` (keyed by sample index) so both authoring styles
  upload identically.

### 5. Sample I/O and explanation sources are uploaded as statement resources — **Bug (noise, Low)**

`_upload_statement_resources` ships *every* file under the statement dir
(`_statement_asset_files`), so `statement/samples/000.in` →
`samples__000.in` and `statement/samples/000.rbx.tex` → `samples__000.rbx.tex` are
uploaded as Polygon statement resources. These are sample test inputs and an
explanation *source*, not statement assets — pure noise on Polygon (and the sample
I/O is uploaded separately as tests).

- **Evidence:** capture in `polygon-upload-assets` lists `samples__000.in` among the
  uploaded resources.
- **Suggested fix:** restrict statement resources to referenced assets (e.g.
  image/PDF extensions, or only paths actually referenced by `\includegraphics`),
  excluding `*.in`/`*.out`/`*.rbx.tex`/sample dirs.

### 6. Root-vs-subdir resource remap asymmetry + naive substring rewrite — **Suspicious (Low–Med)**

`_upload_statement_resources` only records a key→normalized-name remap entry for
assets in a **subdirectory** (`img/diagram` → `img__diagram.png`); a **root-level**
asset (`pic.png`) is uploaded under its bare name with **no** remap entry, so the
block keeps `\includegraphics{pic}`. It happens to resolve only because `pic` is the
stem of `pic.png`. Separately, `_replace_resources` rewrites blocks with a naive
per-key `str.replace`, which is order-dependent and risks substring collisions
between asset keys (e.g. `a` inside `aa`).

- **Evidence:** capture in `polygon-upload-assets` (`pic` kept as-is vs
  `img__diagram.png` rewritten).
- **Suggested fix:** make the remap uniform (record every uploaded asset, root
  included) and rewrite references by parsing `\includegraphics` arguments rather
  than substring replacement.

### 7. The existing `default-preset` e2e fixture is broken post-v2 — **Test bug (Low)**

`tests/e2e/testdata/default-preset` seeds only the preset *problem* and runs
`rbx st b`, but statements v2 requires a contest
(`resolver.require_contest_for_problem` hard-errors), so the `st b` step fails. It
was masked locally by an earlier offline build failure (no `testlib.h`), and e2e
tests are excluded from the default CI suite (`mise run test`), so it went
unnoticed. The new `ensure_compilation_deps` testlib provisioning makes the offline
build pass, surfacing the `st b` failure.

- **Suggested fix (separate):** convert `default-preset` into a contest+problem
  layout (as `polygon-default-preset` does), or drop the `st b` step.

## What works correctly (verified)

- Legend TikZ externalization + upload + reference rewrite
  (`artifacts__tikz_figures__legend_0.pdf`).
- Subdirectory statement images: remapped (`img/diagram` → `img__diagram.png`) and
  referenced consistently.
- Sample-explanation **images** (inline block): remapped (`figs/expl` →
  `figs__expl.png`), uploaded, and rewritten in `notes`.
- Sample explanations (inline `explanation_<i>`) merged into `notes` with a
  "Explanation for example N" heading.
- `rbx contest st b` for the default preset (the join overlay isolates problems, so
  no editorial collision).

## Prioritized follow-up fixes (separate PR)

1. **#1** — unbreak the default preset's standalone/Polygon path (overlay collision).
2. **#2** — externalize + correctly reference explanation-block TikZ.
3. **#3** — stop mangling `\includegraphics` optional arguments.
4. **#4** — fold separate-file explanations into Polygon `notes`.
5. **#5/#6** — scope uploaded resources to real assets; uniform, parser-based
   reference rewriting.
6. **#7** — fix the pre-existing `default-preset` e2e fixture.
