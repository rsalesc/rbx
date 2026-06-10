# Design: Grill the Polygon API statement-upload logic (#586)

Date: 2026-06-10

## Problem

Statements v2 changed how a problem's statement is uploaded to Polygon via the
API (`rbx package polygon -u`). The uploaded statement is defined very
differently from the local PDF build: Polygon receives **only TeX code blocks**
(`legend`, `input`, `output`, `interaction`, `notes`) — no PDF. TikZ pictures
must be externalized to one PDF per figure and uploaded as statement resources,
static images and sample-explanation assets must be renamed (subdirectories
flattened) and uploaded, and `\includegraphics{...}` references inside the
blocks must be rewritten to the uploaded resource names. There is a lot that can
silently go wrong here, and today there is **no test coverage** of the
`rbx package polygon -u` statement path.

Issue #586 asks us to (1) review this path carefully, and (2) add a special
category of e2e tests — runnable via a separate mise command — that exercise it.

## Goals

1. **Audit** the Polygon statement-upload path and capture findings/risks in a
   written document. Bugs found are documented here and fixed in a **separate**
   PR (not this one).
2. **A new `pdflatex` e2e category** that runs against a *real* `pdflatex`
   (with TikZ externalization), isolated behind its own mise command and never
   run in the default CI suite.
3. **Two e2e suites** verifying the upload payload without any network:
   - Suite 1: the default preset (`rbx contest st b`, `rbx st b`,
     `rbx package polygon -u`).
   - Suite 2: a bespoke problem exercising, simultaneously, a TikZ picture in the
     statement, a static image in the statement, a TikZ picture in a sample
     explanation, and an image in a sample explanation — to ensure the uploaded
     assets ultimately make sense.

## Non-goals

- No real network calls to Polygon. The API is mocked at a single seam.
- No CI changes (the pdflatex suite stays a separate, locally-runnable command).
- No fixes to upload logic in this PR — bugs go to a follow-up PR.

## Decisions (confirmed with the user)

- **Deliverable**: e2e tests **plus** a written audit doc; fixes are separate.
- **Verification mechanism**: a recording fake at `_get_polygon_api()` that
  serializes captured calls to disk; assertions via the e2e YAML DSL (extended
  with a small `polygon_upload` matcher).
- **CI**: a separate `mise test-e2e-pdflatex` command; CI workflows untouched.

## Relevant code map

Upload path (`rbx/box/packaging/polygon/`):
- `main.py:14` — `polygon` CLI command; `-u/--upload` → `upload_problem(...)`.
- `upload.py:694` — `upload_problem()` orchestrator (files → checker/validator →
  solutions → testcases → statements → commit).
- `upload.py:71` — `_get_polygon_api()` — **the single factory** that builds the
  `api.Polygon` client from `POLYGON_API_KEY`/`POLYGON_API_SECRET`. This is the
  mock seam.
- `upload.py:639` — `_upload_statement()` builds the per-language `api.Statement`
  (legend/input/output/interaction/notes) and calls `problem.save_statement(...)`.
- `upload.py:593` — `_upload_statement_resources()` uploads statement-dir assets
  + externalized `artifacts/tikz_figures/*.pdf`, normalizing subdir paths
  (`a/b.png` → `a__b.png`) and returning a key→normalized-name remap.
- `upload.py:563`/`:660` — sample explanations formatted ("Explanation for
  example N") and merged into `notes`.
- `polygon/statement_block_utils.py:45` — `get_processed_statement_blocks()`
  reads `blocks.sub.yml` (TikZ already substituted to `\includegraphics`),
  expands/filters macros, converts to Polygon TeX.
- `polygon_api.py:212/246` — `problem.save_statement` / `save_statement_resource`.
- `polygon_api.py:1232` — `requests.post(...)` (the only HTTP call).

Statements v2 (`rbx/box/statements/`):
- `engine.py:62` — `render_problem_tex()`: extract blocks → `blocks.yml`;
  if `externalize`, label TikZ → `blocks.ext.yml`; stage samples; render; then
  substitute TikZ → `blocks.sub.yml`.
- `render.py:107/118` — `externalize_blocks()` / `substitute_externalized_blocks()`.
- `texsoup_utils.py` — `EXTERNALIZATION_DIR='artifacts/tikz_figures/'`, label and
  replace TikZ nodes.
- `build_statements.py:73-92` — `get_statement_dir()`, `get_produced_tikz_pdfs()`.

e2e harness (`tests/e2e/`):
- `spec.py` — Pydantic DSL: `E2ESpec` → `Scenario` → `Step` → `Expect`;
  `_ALLOWED_MARKERS = {'slow', 'docker'}`.
- `runner.py` — copies package to tmpdir, runs steps via Typer `CliRunner`,
  dispatches `_GENERIC_CHECKS`.
- `assertions.py` — matcher implementations.
- `conftest.py:70` — `mock_pdflatex` (session-scoped autouse) stubs
  `Latex.build_pdf` to return an empty PDF.
- `mise.toml:37` — `test-e2e = pytest -m 'e2e and not docker'`.

## Part 1 — Audit document

A separate doc, `docs/plans/2026-06-10-polygon-statement-upload-audit.md`, with a
verdict (correct / suspicious / bug) per risk area, each cross-referenced to the
test that exercises it:

1. **Resource-name rewriting** — `_replace_resources` does naive per-key
   `block.replace(key, value)`. Check substring collisions (`a.png` inside
   `aa.png`), replacement order, and that the "key" matches what
   `\includegraphics{...}` actually contains.
2. **TikZ externalization round-trip** — the `\includegraphics{artifacts/
   tikz_figures/<label>}` written into `blocks.sub.yml` must be rewritten to the
   normalized uploaded PDF name. Verify key ↔ reference equality.
3. **Subdirectory asset flattening** (`/`→`__`) rewritten consistently in blocks.
4. **Sample-explanation assets** — figures/TikZ *inside* an explanation:
   externalized, uploaded, and path-rewritten when merged into `notes`?
5. **Macro filtering/expansion**, **notes merge ordering**, **interaction only
   for COMMUNICATION tasks**, **`upload_as_english` language mapping**,
   **255-char comment cap**.

When a test exposes a real bug, the test is marked `xfail` (non-strict) with a
reason linking the audit finding, so the suite stays green and the bug is
documented and ready to flip when fixed in the follow-up PR.

## Part 2 — e2e infrastructure changes

1. Add `'pdflatex'` to `_ALLOWED_MARKERS` (`tests/e2e/spec.py`); register the
   marker in `pytest.ini`.
2. **Conditional `mock_pdflatex`**: convert to function-scoped autouse that does
   *not* patch `Latex.build_pdf` when the current item carries the `pdflatex`
   marker (those scenarios use the real binary). Skip the scenario with a clear
   message if `pdflatex` / TikZ is unavailable.
3. **mise**: add `test-e2e-pdflatex = pytest -m 'e2e and pdflatex and not docker'`;
   change `test-e2e` to `pytest -m 'e2e and not docker and not pdflatex'`. The
   default `test` task already excludes `e2e`.
4. **Recording fake**: an autouse e2e fixture patches
   `rbx.box.packaging.polygon.upload._get_polygon_api()` to return a
   `RecordingPolygon`. It satisfies the full surface `upload_problem()` touches
   (problem find/create, file/solution/test/script saves, statement reads return
   empty collections so the flow completes) and serializes every
   `save_statement` / `save_statement_resource` call — statement fields, resource
   names, and resource bytes — into `.rbx/polygon_capture/` in the package
   tmpdir. No HTTP and no credentials are required.
5. **New `polygon_upload` DSL matcher** (`Expect.polygon_upload`):
   - `statements: {<lang>: {name_contains, legend_contains, input_contains,
     output_contains, interaction_contains, notes_contains}}` (str or list).
   - `resources: {present: [...], absent: [...]}` (normalized names).
   - `resources_referenced_consistent: bool` — parse every `\includegraphics{X}`
     across all statement fields and assert each `X` was uploaded as a resource.
     This is the core "the uploaded assets make sense" assertion.

   Implemented as a Pydantic model + an assertion function registered in
   `_GENERIC_CHECKS`, reading the `.rbx/polygon_capture/` manifest.

## Part 3 — Fixture packages (`tests/e2e/testdata/`)

- **Suite 1 — default preset** (`polygon-default-preset/`): a contest seeded from
  the `default` preset (statements v2 requires a contest; verify the preset ships
  contest statement templates). Steps: `contest st b`, `st b`,
  `package polygon -u`. Assert blocks render and the upload payload is
  well-formed (non-empty legend/input/output; consistent resources).
- **Suite 2 — bespoke asset problem** (`polygon-tikz-assets/`): one contest +
  problem containing, simultaneously: a TikZ picture in the legend; a static PNG
  in a subdirectory (to exercise `/`→`__`); a TikZ picture in a sample
  explanation; and an image in a sample explanation. A tiny valid PNG is
  committed. Steps: `st b` (real externalize), `package polygon -u`. Assert: the
  externalized TikZ PDFs and images all upload under correct normalized names and
  every `\includegraphics` reference resolves to an uploaded resource.

## Risks / open verifications (resolved during implementation)

- Whether the `default` preset ships contest-level statement templates (Suite 1
  depends on it). If not, Suite 1's fixture supplies a minimal contest.
- The exact read-method return shapes `RecordingPolygon` must provide for
  `upload_problem()` to complete without HTTP.
- Whether `upload_problem()` aborts on blank credentials before reaching the
  faked client; if so, the fixture sets dummy env vars.

## Testing

- `mise test-e2e-pdflatex` runs both suites against real pdflatex.
- The recording-fake / `polygon_upload` matcher itself is covered by the suites
  (no separate unit test of the harness unless the matcher logic warrants it).
- Default `mise test` and `mise test-e2e` are unchanged in scope (pdflatex suite
  excluded).
