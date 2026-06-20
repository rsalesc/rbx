# Polygon TikZ depend-on-template Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `rbx package polygon -u` upload every sample-explanation TikZ figure without a dangling reference, by depending on the statement template and guaranteeing the bundled default/fallback preset renders/subimports everything — instead of #590's rejected template-independent externalization pass.

**Architecture:** The Polygon upload references figures by the externalization label the engine assigns (`legend_0`, `i_0`, …). Body blocks always render in the document body, so their figures always externalize. Sample explanations only externalize if the template `\subimport`s them — which the default preset does. Two real fixes: (1) separate-file `samples/<idx>.rbx.tex` explanations are currently staged *unlabeled*, so their subimported figure is produced under the wrong name — thread the already-externalized text into staging so the staged file carries the `i_0` label; (2) drop the dead-weight string-keyed `explanation_<i>` block that produces an unused, never-uploaded label. Then make the acceptance fixture's custom template compliant so the xfail flips to xpass.

**Tech Stack:** Python 3, Pydantic v2, pytest, the statements-v2 engine (`rbx/box/statements/`), the e2e YAML DSL (`tests/e2e/`), pdflatex-marked e2e runs (`mise run test-e2e-pdflatex`).

**Design doc:** `docs/plans/2026-06-20-polygon-tikz-depend-on-template-design.md`

**Commit convention:** This repo enforces commitizen conventional commits (see `.claude/skills/commit.md`). Use the `/commit` workflow for every commit; append the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer. Stage files by name (no `git add -A`).

**Working dir:** the worktree `.claude/worktrees/issue-590-polygon-tikz-template` (already created). All paths below are repo-relative.

---

## Task 1: Drop the dead-weight string-keyed `explanation_<i>` block

The `explanation_<i>` blocks are split into the int-keyed `StatementBlocks.explanations` but left **also** in `.blocks` under the string key. When externalizing, that copy is labeled `explanation_<i>_<fig>` → a PDF that is never produced and never uploaded (the upload only reads `.explanations`). Remove it.

**Files:**
- Modify: `rbx/box/statements/render.py:94-101` (`render_jinja_blocks`)
- Test: `tests/rbx/box/statements/test_render.py`

**Step 1: Write the failing test**

Add to `tests/rbx/box/statements/test_render.py` (place it near the existing explanation test that asserts `0 in blocks.explanations`):

```python
def test_explanation_blocks_are_removed_from_named_blocks(tmp_path):
    # An `explanation_<i>` block is split into `.explanations` and must NOT
    # remain in `.blocks` under its string key (it would otherwise be labeled
    # `explanation_0_0` on externalize -> a PDF never produced or uploaded).
    content = (
        b'%- block legend\nhi\n%- endblock\n'
        b'%- block explanation_0\nwhy sample zero\n%- endblock\n'
    )
    blocks = render.render_jinja_blocks(tmp_path, content, mode='latex')
    assert 0 in blocks.explanations
    assert 'why sample zero' in blocks.explanations[0]
    assert 'explanation_0' not in blocks.blocks
    assert 'legend' in blocks.blocks
```

(Check the file's existing imports — it already imports `render`. Match the existing test's call signature; if the existing test constructs `ProblemRenderContext`/`ContestRenderContext` and calls `extract_blocks`, mirror that instead and assert the same three things.)

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_render.py::test_explanation_blocks_are_removed_from_named_blocks -v`
Expected: FAIL — `assert 'explanation_0' not in blocks.blocks` fails (the key is present).

**Step 3: Write minimal implementation**

In `rbx/box/statements/render.py`, `render_jinja_blocks`, change the tail (lines ~94-101) to pop the matched keys out of `result`:

```python
    pattern = re.compile(r'explanation_(\d+)')
    explanation_keys = []
    for key in result:
        if match := pattern.match(key):
            explanation_keys.append((key, int(match.group(1))))

    # Split per-sample explanations into the int-keyed `explanations` map and
    # remove them from the named `blocks` so they are not double-labeled on
    # externalize (the upload only reads `.explanations`).
    explanations = {value: result.pop(key) for key, value in explanation_keys}
    return StatementBlocks(blocks=result, explanations=explanations)
```

(`pattern.match` anchors at the start; if a real block legitimately starts with `explanation_` but is not a sample explanation, that is already the existing behavior — no change. Keep `match` not `fullmatch` to preserve current semantics.)

**Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/test_render.py -v`
Expected: PASS (new test + the existing explanation test still green).

**Step 5: Run the broader statements + polygon-export unit suites**

Run: `uv run pytest tests/rbx/box/statements/test_render.py tests/rbx/box/statements/test_engine.py tests/rbx/box/statements/test_engine_blocks.py tests/rbx/box/statements/test_polygon_export.py -v`
Expected: PASS. If `test_polygon_export.py` asserts an `explanation_0` key inside `blocks.sub.yml`'s `blocks`, update that assertion to reflect the removed dead-weight label (the int-keyed `explanations` entry is the real one).

**Step 6: Commit**

```bash
git add rbx/box/statements/render.py tests/rbx/box/statements/test_render.py
# + tests/rbx/box/statements/test_polygon_export.py if it needed updating
git commit  # via /commit -> refactor(statements): drop dead-weight string-keyed explanation block
```

---

## Task 2: `stage_samples` honors `extra_explanations` (separate-file label fix, unit)

Give `stage_samples` a new `extra_explanations: Dict[int, str]` map. For a sample whose explanation comes from a **file** (not an inline `explanation_<i>` block), if `extra_explanations[index]` is present, use that text for `explanation.tex` **while still mirroring the source dir** (so the explanation's own figures resolve). This lets the engine feed the already-externalized text so the staged figure externalizes under the label the upload references.

**Files:**
- Modify: `rbx/box/statements/sample_staging.py` (`_resolve_explanation` lines 61-85; `stage_samples` signature lines 88-128)
- Test: `tests/rbx/box/statements/test_sample_staging.py`

**Step 1: Write the failing test**

Add to `tests/rbx/box/statements/test_sample_staging.py`, inside `class TestExplanations`:

```python
    def test_extra_explanation_overrides_file_text_and_still_mirrors_dir(
        self, tmp_path
    ):
        # A separate-file explanation: the staged text comes from
        # `extra_explanations` (the engine's externalized copy), but the source
        # directory is STILL mirrored so the explanation's own figures resolve.
        src = tmp_path / 'src'
        _write(src / '000.in')
        _write(src / '000.tex', 'raw \\includegraphics{diagram}')
        _write(src / 'diagram.png', 'PNG')
        source = SampleSource(
            input_path=src / '000.in',
            explanation_path=src / '000.tex',
        )

        root = tmp_path / 'overlay'
        root.mkdir()
        handles = sample_staging.stage_samples(
            problem_root=root,
            root_prefix='',
            sources=[source],
            extra_explanations={0: 'labeled \\tikzsetnextfilename{0_0} text'},
        )

        explanation = root / '.samples' / '000' / 'explanation.tex'
        assert explanation.read_text() == 'labeled \\tikzsetnextfilename{0_0} text'
        # The source dir was still mirrored for the explanation's figures.
        assert (root / '.samples' / '000' / 'diagram.png').read_text() == 'PNG'
        assert handles[0].explanation_file == 'explanation'

    def test_inline_block_still_wins_over_extra_explanation(self, tmp_path):
        # An inline explanation_<i> block takes precedence over extra_explanations.
        src = tmp_path / 'src'
        _write(src / '000.in')
        source = SampleSource(input_path=src / '000.in')

        root = tmp_path / 'overlay'
        root.mkdir()
        sample_staging.stage_samples(
            problem_root=root,
            root_prefix='',
            sources=[source],
            explanation_blocks={0: 'INLINE'},
            extra_explanations={0: 'EXTRA'},
        )
        assert (root / '.samples' / '000' / 'explanation.tex').read_text() == 'INLINE'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_sample_staging.py -k extra_explanation -v`
Expected: FAIL — `stage_samples() got an unexpected keyword argument 'extra_explanations'`.

**Step 3: Implement**

In `rbx/box/statements/sample_staging.py`:

a) Extend `_resolve_explanation` to consult `extra_explanations` **after** inline blocks, **before** the disk read:

```python
def _resolve_explanation(
    index: int,
    source: SampleSource,
    explanation_blocks: Dict[int, str],
    extra_explanations: Dict[int, str],
    render_text: Optional[RenderText],
    render_blocks: Optional[RenderBlocks],
    lang: str,
    mode: str,
) -> Optional[bytes]:
    """Return the final explanation content for a sample, or None.

    Inline ``explanation_<i>`` blocks take precedence over an authored file.
    ``extra_explanations`` (the engine's already-externalized copy of a
    separate-file explanation) overrides the on-disk text but does NOT suppress
    the source-dir mirror, so the explanation's own figures still resolve.
    """
    if index in explanation_blocks:
        return explanation_blocks[index].encode()
    if index in extra_explanations:
        return extra_explanations[index].encode()
    if source.explanation_path is None or not source.explanation_path.is_file():
        return None
    raw = source.explanation_path.read_bytes()
    if source.explanation_from_blocks and render_blocks is not None:
        blocks = render_blocks(raw, mode)
        selected = blocks.get(lang)
        return selected.encode() if selected is not None else None
    if render_text is not None:
        return render_text(raw, mode)
    return raw
```

b) Add the `extra_explanations` param to `stage_samples` (default `None`), normalize it, and pass it through. In `stage_samples`:

```python
def stage_samples(
    problem_root: pathlib.Path,
    root_prefix: str,
    sources: List[SampleSource],
    *,
    explanation_blocks: Optional[Dict[int, str]] = None,
    extra_explanations: Optional[Dict[int, str]] = None,
    render_text: Optional[RenderText] = None,
    render_explanation_text: Optional[RenderText] = None,
    render_blocks: Optional[RenderBlocks] = None,
    lang: str = 'en',
    mode: str = 'latex',
) -> List[SampleHandle]:
```

After `explanation_blocks = explanation_blocks or {}` add:

```python
    extra_explanations = extra_explanations or {}
```

Update the `_resolve_explanation(...)` call (around line 120) to pass `extra_explanations` positionally/keyword in the new slot.

c) The dir-mirror guard (lines 134-140) keys off `index not in explanation_blocks` and `source.explanation_path.is_file()`. A separate-file explanation supplied via `extra_explanations` is **not** in `explanation_blocks` and **has** an `explanation_path`, so the mirror already fires — **no change needed there**. (Verify this by re-reading lines 134-140; do not add `extra_explanations` to that condition.)

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/test_sample_staging.py -v`
Expected: PASS (new tests + all existing staging tests green).

**Step 5: Commit**

```bash
git add rbx/box/statements/sample_staging.py tests/rbx/box/statements/test_sample_staging.py
git commit  # via /commit -> feat(statements): stage separate-file explanations with externalized label
```

---

## Task 3: Wire the externalized `file_latex_explanations` into staging (engine)

Feed the engine's already-externalized separate-file explanations into `stage_samples` so the staged figure externalizes under the `i_0` label the upload references. Scope to `externalize=True` so the normal PDF build stays byte-identical.

**Files:**
- Modify: `rbx/box/statements/engine.py` (the `stage_samples(...)` call, ~lines 205-214)

**Step 1: Make the change**

In `rbx/box/statements/engine.py`, the `stage_samples` call currently passes `explanation_blocks=latex_explanations`. Add the externalized separate-file map, gated on `externalize`:

```python
        problem.samples = sample_staging.stage_samples(
            problem_root,
            root_prefix,
            sources,
            explanation_blocks=latex_explanations,
            extra_explanations=file_latex_explanations if externalize else None,
            render_text=render_text,
            render_blocks=render_blocks,
            lang=lang,
            mode=mode,
        )
```

Rationale: `file_latex_explanations` is externalized at line 180 only under `externalize`; passing it as `extra_explanations` makes the staged `.samples/<i>/explanation.tex` and the uploaded explanation share one source of truth, so the produced figure name (`i_0`) matches the uploaded `\includegraphics{artifacts/tikz_figures/i_0}`. Inline `explanation_<i>` explanations are unaffected (they take precedence in `_resolve_explanation` and were already correct).

**Step 2: Run the engine + polygon-export unit suites (regression)**

Run: `uv run pytest tests/rbx/box/statements/test_engine.py tests/rbx/box/statements/test_engine_blocks.py tests/rbx/box/statements/test_polygon_export.py -v`
Expected: PASS (no behavior change for inline explanations or non-externalize builds). The new behavior is covered end-to-end in Task 5.

**Step 3: Commit**

```bash
git add rbx/box/statements/engine.py
git commit  # via /commit -> fix(statements): externalize separate-file sample explanations for polygon (#590)
```

---

## Task 4: Make the acceptance fixture compliant and flip the xfail to xpass

`polygon-tikz-assets` uses a custom standalone template that omits the explanation subimport — by-design broken under depend-on-template. Make its template compliant; the inline `explanation_0` block is already staged with its `0_0` label, so `0_0.pdf` is produced with **no production change**. Then flip the assertions and remove the xfail.

**Files:**
- Modify: `tests/e2e/testdata/polygon-tikz-assets/statements/problem-standalone.rbx.tex`
- Modify: `tests/e2e/testdata/polygon-tikz-assets/e2e.rbx.yml` (`polygon-upload-assets` scenario)
- Modify: `tests/e2e/conftest.py` (`_XFAIL_SCENARIOS`)

**Step 1: Make the fixture template subimport explanations**

In `tests/e2e/testdata/polygon-tikz-assets/statements/problem-standalone.rbx.tex`, the sample loop currently renders only `\example{...}{...}`. Add the explanation subimport inside the loop:

```latex
%- if problem.samples
  \subsection*{Examples}
  %- for sample in problem.samples
    \example{\VAR{sample.input}}{\VAR{sample.output if sample.output is not none else ''}}
    %- if sample.explanation_file is not none
      \subimport{\VAR{sample.dir}}{\VAR{sample.explanation_file}}
    %- endif
  %- endfor
%- endif
```

(The template has no `\explanation` macro defined, so `\subimport` is used directly — equivalent for figure production. Keep `\usepackage{import}`/`{tikz}`/`{graphicx}` which are already present.)

**Step 2: Flip the `polygon-upload-assets` assertions**

In `tests/e2e/testdata/polygon-tikz-assets/e2e.rbx.yml`, scenario `polygon-upload-assets`:

- In `notes_contains`, replace the dangling line `"\\includegraphics{artifacts/tikz_figures/0_0}"` with `"\\includegraphics{artifacts__tikz_figures__0_0.pdf}"`.
- In `resources_present`, add `"artifacts__tikz_figures__0_0.pdf"`.
- In `resources_absent`, remove `"artifacts__tikz_figures__0_0.pdf"` and `"artifacts/tikz_figures/0_0.pdf"` (keep `"samples__000.in"`).
- Update the scenario `description` so it no longer claims the explanation TikZ is un-externalized (it now is). Note the template now subimports the explanation.

**Step 3: Remove the xfail registration**

In `tests/e2e/conftest.py`, delete the `'polygon-upload-assets-referential-integrity'` entry from `_XFAIL_SCENARIOS` (lines ~89-…). The scenario `polygon-upload-assets-referential-integrity` now passes normally.

**Step 4: Run the affected e2e scenarios with pdflatex**

Run: `mise run test-e2e-pdflatex`
Expected: `polygon-upload-assets` PASS with the flipped assertions; `polygon-upload-assets-referential-integrity` PASS (no longer xfail). If `mise run test-e2e-pdflatex` runs the whole pdflatex suite, confirm no other scenario regressed.

(If a filter is supported, scope to the fixture, e.g. `mise run test-e2e-pdflatex -- -k polygon_tikz_assets` or the project's documented selector — check `tests/e2e/README.md`.)

**Step 5: Commit**

```bash
git add tests/e2e/testdata/polygon-tikz-assets/statements/problem-standalone.rbx.tex \
        tests/e2e/testdata/polygon-tikz-assets/e2e.rbx.yml \
        tests/e2e/conftest.py
git commit  # via /commit -> test(e2e): make polygon-tikz-assets template compliant, flip referential-integrity to xpass
```

---

## Task 5: Cover the separate-file explanation TikZ fix end-to-end (default preset)

Guard the Task 2/3 fix: a **separate-file** `samples/<idx>.rbx.tex` explanation containing TikZ, built with the **default preset** chrome, must upload with a consistent reference. The `polygon-default-preset/A` fixture already has a no-TikZ separate-file explanation (`samples/000.rbx.tex`); add TikZ to it and assert referential consistency.

**Files:**
- Modify: `tests/e2e/testdata/polygon-default-preset/A/statement/samples/000.rbx.tex`
- Modify: `tests/e2e/testdata/polygon-default-preset/e2e.rbx.yml` (`problem-polygon-upload` scenario)

**Step 1: Add TikZ to the separate-file explanation**

In `tests/e2e/testdata/polygon-default-preset/A/statement/samples/000.rbx.tex`, append a TikZ picture inside the `en` block:

```latex
%- block en
In the first sample, $A = 3$ and $B = 7$, so the answer is $A + B = 10$.

\begin{tikzpicture}
  \draw (0,0) -- (1,1) -- (2,0) -- cycle;
\end{tikzpicture}
%- endblock
```

**Step 2: Assert referential consistency + the produced figure**

In `tests/e2e/testdata/polygon-default-preset/e2e.rbx.yml`, scenario `problem-polygon-upload`, extend the `polygon_upload` expectation:

```yaml
          polygon_upload:
            statements:
              english:
                legend_contains: ["A", "B"]
                notes_contains: "In the first sample"
            resources_present:
              - "artifacts__tikz_figures__0_0.pdf"
            resources_referenced_consistent: true
```

(Match the existing YAML shape for `resources_present`/`resources_referenced_consistent` used by `polygon-tikz-assets`. The separate-file explanation is sample index 0 → label `0_0`.)

**Step 3: Run the scenario with pdflatex (the TDD red→green for the integration)**

Run: `mise run test-e2e-pdflatex`
Expected: `problem-polygon-upload` PASS. To prove the guard bites, temporarily revert Task 3's engine change and confirm this scenario goes RED (`0_0.pdf` produced under an auto-name; reference dangling) — then restore.

**Step 4: Commit**

```bash
git add tests/e2e/testdata/polygon-default-preset/A/statement/samples/000.rbx.tex \
        tests/e2e/testdata/polygon-default-preset/e2e.rbx.yml
git commit  # via /commit -> test(e2e): cover separate-file explanation tikz under default preset (#590)
```

---

## Task 6: Document the template contract

**Files:**
- Modify: `rbx/box/statements/CLAUDE.md` (Polygon export section)
- Modify: the user-facing statements docs (find under `docs/`; check `mkdocs.yml` nav for the statements/Polygon page)

**Step 1: Update the module CLAUDE.md**

In `rbx/box/statements/CLAUDE.md`, under "## Polygon export (S12, #568)", add a short paragraph:

> **Template contract (#590):** TikZ externalization depends on the statement
> template. A block's or explanation's TikZ (or static image) is uploaded to
> Polygon only if the template renders/subimports it. Body blocks
> (legend/input/output/interaction/notes) render directly, so their figures
> always externalize; sample explanations externalize only when the template
> `\subimport`s them. The bundled default/fallback preset
> (`_problem-body.rbx.tex`) renders all blocks and subimports every explanation,
> so default and contest-less-fallback uploads are referentially complete.
> Custom standalone templates that omit an explanation subimport ship a dangling
> reference by design — there is no runtime guard. Separate-file
> (`samples/<idx>.rbx.tex`) and inline (`explanation_<i>`) explanations are both
> staged carrying their `i_0` externalization label, so either source produces
> the figure the upload references.

**Step 2: Update the user-facing docs**

Locate the statements / Polygon-packaging docs page (grep `docs/` for "subimport", "explanation", or "Polygon"). Add a note in the author-facing voice: to get a sample-explanation figure onto Polygon with a custom standalone template, the template must `\subimport` the explanation (as the default preset does); the bundled preset already does this.

**Step 3: Verify docs build**

Run the project's docs build (non-strict, per repo convention — strict has ~9 pre-existing unrelated warnings). Check `mkdocs.yml` / `mise` tasks for the command (e.g. `uv run mkdocs build`).
Expected: builds; the new page content renders. Ignore the known pre-existing strict warnings.

**Step 4: Commit**

```bash
git add rbx/box/statements/CLAUDE.md docs/  # + the specific docs file
git commit  # via /commit -> docs(statements): document polygon tikz template contract (#590)
```

---

## Final verification

Run the full relevant suites and confirm green:

```bash
uv run pytest tests/rbx/box/statements -v
mise run test-e2e-pdflatex
```

Expected:
- All statements unit tests pass.
- `polygon-upload-assets` passes with flipped assertions; `polygon-upload-assets-referential-integrity` passes (no longer xfail); `problem-polygon-upload` (default preset) passes with the new TikZ explanation referenced consistently.

Then finish the branch per superpowers:finishing-a-development-branch (PR referencing #590; note the design doc and that #590's template-independent approach was deliberately rejected).

## Notes / gotchas

- The pdflatex e2e runs are slow and need a real `pdflatex` on PATH; the fast TDD loop is the unit tests in Tasks 1–2. Tasks 4–5 are integration guards run once.
- Do NOT add a runtime referential-integrity guard for non-compliant custom templates — that was explicitly rejected (design "Out of scope").
- Per repo memory: some C++ checker/validator/sandbox/docker tests fail pre-existingly on this machine and are unrelated; don't chase them.
