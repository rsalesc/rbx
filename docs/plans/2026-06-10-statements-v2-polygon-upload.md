# Statements v2 — Polygon API upload (S12, #568) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each task.

**Goal:** Make `rbx package polygon --upload` / `--validate-statement` work on statements v2 by replicating v1's block + TikZ production on the portable overlay, persisting `blocks.*.yml` as the source of truth.

**Architecture:** The standalone overlay root (`build/statements/st/<lang>-<variant>/`) becomes the single Polygon "statement dir". `render_problem_tex` gains an `externalize` flag that persists `blocks.yml` (always) plus `blocks.ext.yml`/`blocks.sub.yml` (when externalizing, via the existing v1 TikZ-label/substitute helpers). The stubbed `get_statement_dir`/`get_produced_tikz_pdfs` are repointed at that overlay; `statement_block_utils.py` and `upload.py` consume it.

**Tech Stack:** Python, Pydantic v2, Typer, pytest, TexSoup, pdflatex (mocked in unit tests).

Design: `docs/plans/2026-06-10-statements-v2-polygon-upload-design.md`.

---

### Task 1: Test fixture — a statement with `defs` + TikZ blocks

**Files:**
- Create: `rbx/testdata/contests/statements_v2_polygon/contest.rbx.yml`
- Create: `rbx/testdata/contests/statements_v2_polygon/statements/contest.rbx.tex`
- Create: `rbx/testdata/contests/statements_v2_polygon/statements/problem-standalone.rbx.tex`
- Create: `rbx/testdata/contests/statements_v2_polygon/A/problem.rbx.yml`
- Create: `rbx/testdata/contests/statements_v2_polygon/A/statement/statement.rbx.tex`

A minimal contest + one problem A. The problem statement carries `defs`, `legend`,
`input`, `output`, `notes` blocks; `legend` contains a `tikzpicture`. The
standalone template is a full document splicing the blocks. Model it on
`rbx/testdata/contests/statements_v2` (same contest/problem shape), adding:

`A/statement/statement.rbx.tex`:
```latex
%- block defs
\newcommand{\NN}{\mathbb{N}}
%- endblock
%- block legend
Problem A by \VAR{vars.author}. Numbers in $\NN$.
\begin{tikzpicture}\draw (0,0) -- (1,1);\end{tikzpicture}
%- endblock
%- block input
A single integer $n$.
%- endblock
%- block output
Print $n$.
%- endblock
%- block notes
Be careful.
%- endblock
```

The standalone template (`statements/problem-standalone.rbx.tex`) must
`\documentclass`, load tikz, and emit `\BLOCK{ for ... }` of `blocks` — copy the
structure from `rbx/testdata/contests/statements_v2/statements/problem-standalone.rbx.tex`
and ensure it splices legend/input/output/notes.

**Step 1:** Create the files. No test yet — used by later tasks.
**Step 2:** Sanity: `uv run pytest tests/rbx/box/statements/test_standalone_build.py -q` still passes (existing fixture untouched).
**Step 3:** Commit: `test(statements): add polygon-blocks v2 testdata fixture`.

---

### Task 2: `render_problem_tex` persists blocks YAML + per-block externalization

**Files:**
- Modify: `rbx/box/statements/engine.py` (`render_problem_tex`)
- Test: `tests/rbx/box/statements/test_engine_blocks.py` (new)

**Step 1: Write failing test** — build the problem statement to TeX with
`externalize=True` and assert the three YAMLs land in the overlay and the
substituted legend replaced TikZ with `\includegraphics`.

```python
import pathlib
import pytest
from rbx import utils
from rbx.box import cd, package, package_utils
from rbx.box.statements import build_statements
from rbx.box.statements.builders import StatementBlocks
from rbx.box.statements.schema import (
    ConversionType, StatementType, TexToPDF, rbxToTeX)


@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_render_persists_block_yamls_with_externalization(
    cleandir_with_testdata,
):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        statement = pkg.expanded_statements[0]
        await build_statements.build_statement(
            statement, pkg, output_type=StatementType.TeX, use_samples=False,
            extra_mergeable_params=[
                rbxToTeX(type=ConversionType.rbxToTex, externalize=True),
                TexToPDF(type=ConversionType.TexToPDF, externalize=True, demacro=True),
            ],
        )
        overlay = build_statements.get_statement_dir(statement)
        assert (overlay / 'blocks.yml').is_file()
        assert (overlay / 'blocks.ext.yml').is_file()
        assert (overlay / 'blocks.sub.yml').is_file()
        sub = utils.model_from_yaml(StatementBlocks, (overlay / 'blocks.sub.yml').read_text())
        assert '\\includegraphics' in sub.blocks['legend']
        assert 'tikzpicture' not in sub.blocks['legend']
        raw = utils.model_from_yaml(StatementBlocks, (overlay / 'blocks.yml').read_text())
        assert 'tikzpicture' in raw.blocks['legend']
```

**Step 2: Run, expect FAIL** (YAMLs not written; `get_statement_dir` stubbed —
Task 3 un-stubs it, so until then this test will error on `get_statement_dir`. To
keep Task 2 self-contained, compute the overlay path inline in the test as
`pathlib.Path('build')/'statements'/'st'/f'{statement.language}-{statement.variant}'`
and switch to `get_statement_dir` in Task 3.)

Run: `uv run pytest tests/rbx/box/statements/test_engine_blocks.py -q`

**Step 3: Implement** in `engine.py`:
- Add `externalize: bool = False` param to `render_problem_tex`.
- After block extraction (`blocks = render.extract_blocks(...)`), always write
  `blocks.yml` to `problem_root` (`(problem_root/'blocks.yml').write_text(utils.model_to_yaml(blocks))`).
- When `externalize`: build a labeled copy via
  `builders.externalize_blocks(blocks.blocks)` and
  `builders.externalize_blocks(blocks.explanations)`; write `blocks.ext.yml`;
  set `problem.blocks` from the labeled blocks (so the compiled full doc carries
  `\tikzsetnextfilename`); pass the labeled explanations to sample staging; after
  the render, compute `builders.substitute_externalized_blocks(...)` on the
  labeled blocks + explanations and write `blocks.sub.yml`.
- Reuse the existing markdown handling (the rbxMarkdown path converts blocks to
  LaTeX before splicing; externalization runs on the LaTeX-form blocks).

Imports: `from rbx import utils`; `externalize_blocks` / `substitute_externalized_blocks`
are already in `rbx.box.statements.builders`.

**Step 4: Run, expect PASS.**
**Step 5: Commit:** `feat(statements): persist block yamls + per-block tikz externalization`.

---

### Task 3: Un-stub `get_statement_dir` + `get_produced_tikz_pdfs`

**Files:**
- Modify: `rbx/box/statements/build_statements.py`
- Test: `tests/rbx/box/statements/test_polygon_export.py` (new)

**Step 1: Write failing tests:**
```python
import pathlib
import pytest
from rbx.box import cd, package, package_utils
from rbx.box.statements import build_statements
from rbx.box.statements.texsoup_utils import EXTERNALIZATION_DIR


@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_get_statement_dir_is_overlay_root(cleandir_with_testdata):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        st = package.find_problem_package_or_die().expanded_statements[0]
        d = build_statements.get_statement_dir(st)
        assert d == pathlib.Path('build')/'statements'/'st'/'en-default'


@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_get_produced_tikz_pdfs_globs_externalization_dir(cleandir_with_testdata):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        st = package.find_problem_package_or_die().expanded_statements[0]
        d = build_statements.get_statement_dir(st)
        (d/EXTERNALIZATION_DIR).mkdir(parents=True, exist_ok=True)
        (d/EXTERNALIZATION_DIR/'legend_0.pdf').write_bytes(b'%PDF-1.5')
        produced = list(build_statements.get_produced_tikz_pdfs(st))
        assert len(produced) == 1
        abspath, rel = produced[0]
        assert rel == pathlib.Path(EXTERNALIZATION_DIR)/'legend_0.pdf'
        assert abspath.is_file()
```

**Step 2: Run, expect FAIL** (`NotImplementedError`).

**Step 3: Implement** (replace stubs):
```python
def _standalone_overlay_path(statement: Statement) -> pathlib.Path:
    return (
        package.get_statements_build_path()
        / 'st'
        / f'{statement.language}-{statement.variant}'
    )

def get_statement_dir(statement: Statement) -> pathlib.Path:
    """The standalone overlay root for this statement — the v2 Polygon source dir
    holding blocks.*.yml, macros.json and artifacts/tikz_figures/*.pdf."""
    d = _standalone_overlay_path(statement)
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_produced_tikz_pdfs(statement):
    from rbx.box.statements.texsoup_utils import EXTERNALIZATION_DIR
    d = get_statement_dir(statement)
    for pdf in sorted((d / EXTERNALIZATION_DIR).glob('**/*.pdf')):
        yield d / pdf.relative_to(d), pdf.relative_to(d)
```
- Refactor `_standalone_overlay_root` to call `_standalone_overlay_path` then wipe+mkdir.
- Delete the `build_statement_bytes` stub and its now-unused docstring constant references.

**Step 4: Run, expect PASS.** Update Task 2's test to use `get_statement_dir`.
**Step 5: Commit:** `feat(statements): un-stub polygon get_statement_dir/get_produced_tikz_pdfs`.

---

### Task 4: Rewrite `statement_block_utils.py` to read the overlay root

**Files:**
- Modify: `rbx/box/packaging/polygon/statement_block_utils.py`
- Test: extend `tests/rbx/box/statements/test_polygon_export.py`

**Step 1: Write failing test** — after building with externalize+demacro, the
processed blocks are Polygon-valid TeX (legend/input/output present; TikZ became
`\includegraphics`; the `\NN` macro expanded since it is not Polygon-allowed):
```python
@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_get_processed_statement_blocks_v2(cleandir_with_testdata):
    from rbx.box.packaging.polygon import statement_block_utils as sbu
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        st = pkg.expanded_statements[0]
        await build_statements.build_statement(
            st, pkg, output_type=StatementType.TeX, use_samples=False,
            extra_mergeable_params=[
                rbxToTeX(type=ConversionType.rbxToTex, externalize=True),
                TexToPDF(type=ConversionType.TexToPDF, externalize=True, demacro=True),
            ],
        )
        blocks = sbu.get_processed_statement_blocks(st)
        assert 'legend' in blocks.blocks and 'input' in blocks.blocks
        assert '\\includegraphics' in blocks.blocks['legend']
```
(Uses TeX output → no pdflatex; `macros.json` absent → processor returns the
substituted blocks, exercising the no-macros branch + polygon conversion.)

**Step 2: Run, expect FAIL** (imports the stubbed `get_statement_dir(..., builder_name=...)`).

**Step 3: Implement:**
- `get_substituted_statement_blocks(statement)`: read `get_statement_dir(statement)/'blocks.sub.yml'`
  (fallback to `blocks.yml` if `.sub` absent). Error message uses
  `f'{statement.language}-{statement.variant}'` (problem statements have no `name`).
- `get_processed_statement_blocks(statement)`: `macros_file = get_statement_dir(statement)/'macros.json'`;
  drop the `'polygon'` debug subdir writes (or write into `get_statement_dir(statement)/'polygon'`).
  Remove the `rbxTeXBuilder`/`TeX2PDFBuilder` imports.
- `validate_statements` / `process_statements`: replace remaining `statement.name`
  in messages with `f'{statement.language}/{statement.variant}'`.

**Step 4: Run, expect PASS.**
**Step 5: Commit:** `refactor(polygon): read v2 overlay blocks in statement_block_utils`.

---

### Task 5: Fix `upload.py` for the v2 schema

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py` (`_upload_statement_resources`)

**Step 1:** No new unit test (API-bound). Replace
`get_relative_assets(statement.path, statement.assets)` with v2 asset
enumeration: walk the statement-file directory subtree
(`statement.file.parent`), yielding `(abspath, relpath_to_that_dir)` for every
file except the `.samples`/build artifacts, then `extend(get_produced_tikz_pdfs(statement))`.
Implement a small helper `_statement_assets(statement)` in `upload.py` (or reuse
the overlay: assets are everything under `get_statement_dir(statement)` excluding
`blocks.*.yml`, `macros.json`, `statement.tex`, `.samples`, the externalization
PDFs already added). Keep the resource-key normalization logic intact.

**Step 2:** `import` fix: drop `statement.assets`/`statement.path` references; the
file is `statement.file`. Verify module imports: `uv run python -c "import rbx.box.packaging.polygon.upload"`.

**Step 3:** Commit: `fix(polygon): consume v2 statement assets + tikz pdfs in upload`.

---

### Task 6: `PolygonPackager` owns the externalize/demacro toggle

**Files:**
- Modify: `rbx/box/packaging/packager.py` (`get_packager_extra_mergeable_params`)
- Modify: `rbx/box/packaging/polygon/packager.py` (add method)
- Test: extend an existing packaging test or `test_polygon_export.py`

**Step 1: Write test** asserting `PolygonPackager.statement_export_params()` returns
externalize+demacro steps and `BocaPackager` returns `[]`.

**Step 2: Run, expect FAIL.**

**Step 3: Implement:** add classmethod/method
`statement_export_params(self) -> List[ConversionStep]` on `BasePackager`
(default `[]`) and override in `PolygonPackager` to return the rbxToTeX/TexToPDF
externalize+demacro steps. In `run_packager`, call
`packager.statement_export_params()` instead of
`get_packager_extra_mergeable_params(packager_cls)`. Keep
`get_packager_extra_mergeable_params` as a thin shim or delete it (update import).

**Step 4: Run, expect PASS.**
**Step 5: Commit:** `refactor(packaging): polygon packager owns statement export toggles`.

---

### Task 7: Full verification

**Step 1:** `uv run pytest tests/rbx/box/statements tests/rbx/box/packaging -q`
**Step 2:** `uv run ruff check rbx/box/statements rbx/box/packaging && uv run ruff format --check .`
**Step 3:** `uv run python -c "import rbx.box.packaging.polygon.upload, rbx.box.packaging.polygon.statement_block_utils, rbx.box.packaging.main"`
**Step 4:** Manual live smoke (not CI): `rbx package polygon --upload --validate-statement` against the authorized POLYGON creds on the fixture problem; confirm blocks + a TikZ resource upload. Report outcome.
**Step 5:** Update `rbx/box/statements/CLAUDE.md` + `rbx/box/packaging/CLAUDE.md` to note S12 is done (overlay = polygon statement dir; entry points un-stubbed).
**Step 6:** Commit docs; open PR referencing #568, mention #583 follow-up.
