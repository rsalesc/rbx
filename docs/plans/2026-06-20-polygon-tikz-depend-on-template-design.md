# Design: depend-on-template TikZ externalization for Polygon (#590)

Date: 2026-06-20

Split out from #590 (itself #589 audit finding #2, High). When
`rbx package polygon -u` exports a statement whose **sample explanation** contains
a `\tikzpicture`, the uploaded `notes` reference an externalized figure
(`\includegraphics{artifacts/tikz_figures/<sample>_<fig>}`) whose PDF may never be
produced — Polygon renders a broken image.

## Decision: reject template-independence; depend on the template

Issue #590 proposes a **template-independent** fix: a dedicated externalization
pass that compiles every staged explanation in an auxiliary document after the
main render, so figures are produced regardless of the statement template. Its
stated premise:

> The Polygon export therefore **must not depend on the user's template happening
> to render sample explanations**.

**We reject that premise.** A template-independent externalization pass (reusing
the preamble, re-driving `\tikzexternalize` in an overlay) carries real mechanism
risk (preamble reuse / externalization-prefix interaction) for little gain. We
instead make externalization **depend on the statement template**, with one
guarantee:

> **The bundled default/fallback preset template renders or `\subimport`s every
> block and explanation that the Polygon upload references**, so the default and
> fallback (no problem-level template) cases upload with zero dangling references.

Custom standalone templates are the **author's responsibility**: a template that
wants a block's or explanation's TikZ on Polygon must render/subimport it. A
custom template that omits a subimport ships a dangling reference *by design* —
there is **no runtime guard** (decided explicitly; the guard / hard-error
alternatives were considered and dropped in favor of the smallest model).

## What the check found (current behavior)

The upload (`polygon/upload.py:_upload_statement.process_statement`) maps **only**
these to Polygon fields:

- `legend`, `input`, `output`, `interaction`, `notes` — from the **named** body
  blocks (`blocks.blocks`).
- sample explanations — from the **int-keyed** `blocks.explanations` dict,
  appended into `notes`.

In the bundled default body template (`presets/default/contest/statements/
_problem-body.rbx.tex`):

- legend / input / output / interaction / notes render **directly in the body**
  (`\VAR{...}`), so their TikZ externalizes under `legend_0`, `input_0`, … →
  the PDF is **always** produced, independent of any subimport. ✓
- every sample explanation is `\subimport`-ed (line 49). An **inline**
  `explanation_<i>` block is externalized (`engine.py`) and staged carrying its
  `i_0` label, so the subimported figure produces `i_0.pdf`. ✓

So for body blocks + inline explanations the default preset is already
**referentially complete** — exactly the "preset problems happen to work" the
issue admits. The #590 bug only manifests for a *custom* template that omits the
explanation subimport, which under this design is the author's responsibility.

### Gap 1 — separate-file explanations are staged unlabeled (real bug)

A **separate-file** sample explanation (`samples/<idx>.rbx.tex`, #589 finding #4)
breaks **even under the default preset**. The `i_0` externalization label is
applied only to the upload-side copy (`engine.py` externalizes
`file_latex_explanations`), but the file the template actually subimports is
staged **unlabeled** (`sample_staging.py:_resolve_explanation` → `render_text`,
no externalize). A separate-file explanation containing TikZ therefore produces a
figure under an auto-name (`<jobname>-figureN.pdf`) while the upload references
`i_0` → dangling, default preset notwithstanding. This must be fixed for the
default-preset guarantee to be airtight. (Currently untested: the
`polygon-default-preset` fixture's separate-file explanation has no TikZ.)

### Gap 2 — dead-weight dual label (harmless under this design)

`extract_blocks` (`render.py`) splits inline `explanation_<i>` blocks into the
int-keyed `.explanations` dict **but leaves the same content in `.blocks` under
the string key `explanation_<i>`**. When externalizing, that string-keyed copy is
labeled `explanation_<i>_<fig>` → a PDF that is never produced (no body/subimport
renders `blocks.explanation_<i>`) and never uploaded (the upload only reads the
int-keyed dict). It is pure dead weight in `blocks.sub.yml`, not a dangling
reference. Verified: no template or production path reads
`problem.blocks.explanation_<i>`.

## Changes

### 1. Production fix — stage separate-file explanations with their label

- `engine.py`: thread the already-externalized `file_latex_explanations` into
  `sample_staging.stage_samples` (new `extra_explanations` param), scoped to
  `externalize=True` builds.
- `sample_staging.py`: `_resolve_explanation` returns `extra_explanations[index]`
  when present (the externalized text), **before** the disk read. The index is
  not in `explanation_blocks`, so the existing source-dir mirror still runs (so
  static images in the explanation still resolve).
- Effect: the staged `.samples/<i>/explanation.tex` and the uploaded explanation
  now share one source of truth (`file_latex_explanations`), so the subimported
  figure externalizes under `i_0` — the exact name the upload references. The
  default preset becomes airtight for **both** inline and separate-file
  explanations. The inline path is untouched (already correct).

### 2. Hygiene — drop the dead-weight dual label

- `render.py:extract_blocks`: remove the `explanation_<i>` keys from
  `StatementBlocks.blocks` (they are already split into the int-keyed
  `.explanations`). `blocks.sub.yml` no longer carries the never-produced,
  never-uploaded `explanation_<i>_<fig>` reference — settling on the single
  int-keyed label scheme the issue's secondary defect asks for. Guarded by the
  verification that nothing reads the string-keyed block.

### 3. Acceptance fixture — make it compliant

The `polygon-tikz-assets` fixture is itself a custom-template-omits-subimport
case (its `statements/problem-standalone.rbx.tex` renders only input/output in the
sample loop). Under this design it is by-design broken, so the issue's
"flip the xfail to xpass" criterion requires making the fixture's template
compliant rather than changing production code:

- `polygon-tikz-assets/statements/problem-standalone.rbx.tex`: add
  `\explanation{\subimport{\VAR{sample.dir}}{\VAR{sample.explanation_file}}}` to
  the sample loop. `0_0.pdf` is now produced (the inline `explanation_0` block is
  already staged with its `0_0` label — **no production change needed** for this
  fixture).
- `polygon-upload-assets` (`e2e.rbx.yml`): flip assertions — `notes_contains`
  references `\includegraphics{artifacts__tikz_figures__0_0.pdf}`;
  `resources_present` gains `artifacts__tikz_figures__0_0.pdf`; drop the two
  `0_0.pdf` entries from `resources_absent`.
- `tests/e2e/conftest.py`: remove `polygon-upload-assets-referential-integrity`
  from `_XFAIL_SCENARIOS` → it becomes a real **xpass**.

### 4. Coverage for the production fix (§1)

- Add a **separate-file** `samples/<idx>.rbx.tex` explanation containing a
  `\tikzpicture` to a default-preset e2e scenario (`polygon-default-preset` or a
  new sibling), asserting `resources_referenced_consistent: true` and the
  produced `i_0.pdf` resource present. Without this the §1 fix is unexercised.

### 5. Documentation

- `rbx/box/statements/CLAUDE.md` + the statements docs: state the contract — for
  a block's or explanation's TikZ (or static image) to externalize and upload to
  Polygon, the statement template must render/subimport it; the bundled
  default/fallback preset satisfies this for all blocks and explanations; a custom
  standalone template that omits a subimport ships a dangling reference (author's
  responsibility, no runtime guard).

## Acceptance / verification

- `polygon-upload-assets-referential-integrity` flips from xfail to **xpass**
  (every `\includegraphics` resolves to an uploaded resource).
- `polygon-upload-assets` green with the flipped assertions.
- New separate-file-explanation-with-TikZ scenario green (guards §1).
- Run: `mise run test-e2e-pdflatex` + the statements unit tests
  (`uv run pytest tests/rbx/box/statements`).

## Out of scope

- Template-independent externalization (the issue's auxiliary-document pass) —
  explicitly rejected above.
- A runtime referential-integrity guard for non-compliant custom templates
  (strip-and-warn / hard-error) — considered and dropped.
- Offline Polygon `problem.zip`/`contest.zip` statement embedding (#583).
