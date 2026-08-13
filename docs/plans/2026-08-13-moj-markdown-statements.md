# MOJ Markdown Statements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the MOJ packager's dummy `docs/enunciado.md` with the real statement, converted from the Polygon TeX subset to Markdown, with every asset placed where MOJ's renderer can resolve it.

**Architecture:** `build_statement_bundle` from #640 (`rbx/box/statements/export.py`) resolves blocks and assets against a `SubtreeLayout` describing MOJ's tree; each block is then converted TeX → Markdown with pandoc (via the already-present `pypandoc`), and the MOJ packager assembles `docs/enunciado.md` plus `docs/notes/<sample>.md`. PDF-valued assets are rasterized to PNG with poppler, reached through a new general external-tool registry. Design: [`2026-08-13-moj-markdown-statements-design.md`](2026-08-13-moj-markdown-statements-design.md).

**Tech Stack:** Python 3.14, pytest, pydantic v2, `pypandoc` (already a dependency), `pdftoppm` (poppler, new external tool), TexSoup.

---

## Branch state — read this first

This branch is **stacked on #640** (`worktree-statement-export-bundle`) and already carries a **merge of `origin/main`**. That merge is load-bearing and was not optional:

- #640 branched **before** #641, so on #640's head the new MOJ packager still lives at `rbx/box/packaging/moj_next/`.
- `origin/main` (30d09a21) already renamed it to `rbx/box/packaging/moj/`.
- The merge was clean, and `tests/rbx/box/statements/ tests/rbx/box/packaging/moj/` is **419 passed** on the merged tree — verified before this plan was written.

So all paths below are the post-#641 ones (`rbx/box/packaging/moj/...`). Do **not** create anything under `moj_next/`.

When #640 merges to main, rebase this branch onto main and drop the merge commit.

## Background the engineer needs

`rbx` is a CLI for competitive-programming problem setters. "Packaging" exports a built problem to a judge system's format. MOJ (`moj.naquadah.com.br`) consumes a tarball, judged by [`cd-moj/mojtools`](https://github.com/cd-moj/mojtools).

**MOJ renders statements with pandoc.** `mojtools/render-statement.sh` runs `pandoc -f markdown --mathml -s --embed-resources --resource-path=<dir of enunciado>`. Two consequences you must keep in mind throughout:

1. Producing *pandoc-flavored* Markdown is correct, not sloppy. Fenced divs (`::: center`), grid tables and attribute spans (`[x]{.smallcaps}`) all round-trip, because the same tool reads them back.
2. `$…$` math needs **no conversion** — it becomes MathML.

**Sample notes have a different resource base than their own directory.** `mojtools/gen-problem-json.sh` renders `docs/notes/<sample>.md` with `--resource-path="$PKG/docs"`. The note file is in `docs/notes/`, but its images resolve against `docs/`. This is the single most surprising fact in this plan; Task 3 and Task 6 both depend on it.

**The release gate.** `mojtools/validate-problem.sh` hard-requires headings grepped from the **raw file** as `^\s*#{1,3}\s*(entrada|input)` and `…(saída|saida|output)`. It soft-warns on an `## Exemplos`-style heading or any ``` fence (MOJ injects examples itself from `tests/input/sample*`), and on a note with no matching sample.

**No title in the document.** `render-statement.sh` injects `<h1>` from `display_title` in `.moj-meta.json` and strips a legacy `% Title` first line.

If you have `cd-moj/mojtools` checked out, read those three scripts. There is a copy at `/Users/rsalesc/.claude/jobs/c7f335b3/tmp/mojtools` on this machine.

## Conventions

- **Single quotes** for strings. **Absolute imports only** (relative imports are banned by ruff's `TID`).
- Lint/format before every commit: `uv run ruff check --fix . && uv run ruff format .`
- Commits are **conventional commits**, enforced by a pre-commit hook. Use the `/commit` skill; see `.claude/skills/commit.md`.
- Test with `uv run pytest`. Reuse fixtures from `tests/rbx/conftest.py` and `tests/rbx/box/conftest.py`.
- Write the test first, watch it fail, then implement. Commit after each task.

---

### Task 1: The external-tool registry

rbx shells out to several tools with no shared story: `rbx/box/statements/latex.py:42` does an inline `command_exists('pdflatex')` plus an ad-hoc console error, `install_tex_packages` silently no-ops when `texliveonfly` is missing, and `pypandoc` raises a bare `OSError` when pandoc is absent. This task builds the abstraction; Task 2 migrates everyone onto it.

**Files:**
- Create: `rbx/tooling.py`
- Test: `tests/rbx/test_tooling.py`

**Step 1: Write the failing tests**

```python
import subprocess
from unittest import mock

import pytest
import typer

from rbx import tooling


def _tool(**kwargs) -> tooling.ExternalTool:
    defaults = dict(
        name='poppler',
        executable='pdftoppm',
        probe_flags=['-v'],
        purpose='rasterizing PDF figures',
        install_hints={'darwin': 'brew install poppler', 'linux': 'apt install poppler-utils'},
    )
    defaults.update(kwargs)
    return tooling.ExternalTool(**defaults)


def test_is_available_true_when_command_exists():
    with mock.patch('rbx.tooling.command_exists', return_value=True):
        assert _tool().is_available()


def test_is_available_false_when_command_missing():
    with mock.patch('rbx.tooling.command_exists', return_value=False):
        assert not _tool().is_available()


def test_ensure_is_a_noop_when_available():
    with mock.patch('rbx.tooling.command_exists', return_value=True):
        _tool().ensure()


def test_ensure_reports_purpose_and_platform_hint(capsys):
    with (
        mock.patch('rbx.tooling.command_exists', return_value=False),
        mock.patch('rbx.tooling.sys.platform', 'darwin'),
        pytest.raises(typer.Exit),
    ):
        _tool().ensure()
    out = capsys.readouterr().out
    assert 'pdftoppm' in out
    assert 'rasterizing PDF figures' in out
    assert 'brew install poppler' in out


def test_ensure_still_names_the_tool_without_a_hint_for_the_platform(capsys):
    with (
        mock.patch('rbx.tooling.command_exists', return_value=False),
        mock.patch('rbx.tooling.sys.platform', 'sunos'),
        pytest.raises(typer.Exit),
    ):
        _tool().ensure()
    out = capsys.readouterr().out
    assert 'pdftoppm' in out


def test_run_ensures_before_invoking():
    """A missing tool must fail with the actionable error, never a raw
    FileNotFoundError from subprocess."""
    with (
        mock.patch('rbx.tooling.command_exists', return_value=False),
        pytest.raises(typer.Exit),
    ):
        _tool().run(['-png', 'a.pdf'])


def test_run_passes_args_after_the_executable():
    with (
        mock.patch('rbx.tooling.command_exists', return_value=True),
        mock.patch('rbx.tooling.subprocess.run') as run,
    ):
        run.return_value = subprocess.CompletedProcess([], 0)
        _tool().run(['-png', 'a.pdf'])
    assert run.call_args.args[0] == ['pdftoppm', '-png', 'a.pdf']


def test_registry_entries_exist():
    for tool in (tooling.PDFLATEX, tooling.TEXLIVEONFLY, tooling.PANDOC, tooling.PDFTOPPM):
        assert tool.executable
        assert tool.purpose
        assert tool.install_hints
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/test_tooling.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rbx.tooling'`

**Step 3: Implement**

Create `rbx/tooling.py`. Key design points, all of which the tests pin:

- Frozen dataclass with `name`, `executable`, `probe_flags: List[str]`, `purpose`, `install_hints: Dict[str, str]`. Because a frozen dataclass with `Dict`/`List` fields is unhashable-by-default and mutable-by-reference, declare them with `dataclasses.field(default_factory=...)` and never mutate them.
- `is_available()` delegates to `rbx.utils.command_exists` — import it as `from rbx.utils import command_exists` so the tests can patch `rbx.tooling.command_exists`.
- `ensure()` returns `None` when available; otherwise prints via `rbx.console.console.print` in the project's rich theme (`[error]…[/error]`, `[item]…[/item]`) naming the executable, the purpose, and `install_hints.get(sys.platform)` when present, then raises `typer.Exit(1)`.
- `run(args, **kwargs)` calls `ensure()` first, then `subprocess.run([self.executable, *args], **kwargs)`. Calling `ensure()` first is the whole point: it converts a `FileNotFoundError` deep in a packaging run into a message that says what to install.
- Module-level registry constants `PDFLATEX`, `TEXLIVEONFLY`, `PANDOC`, `PDFTOPPM`.

Import `sys` and `subprocess` at module level so the tests can patch `rbx.tooling.sys.platform` and `rbx.tooling.subprocess.run`.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/test_tooling.py -v`
Expected: all PASS

**Step 5: Lint and commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/tooling.py tests/rbx/test_tooling.py
```
Commit with `/commit`: `feat(tooling): add an external tool registry`

---

### Task 2: Migrate the existing call sites onto the registry

**Files:**
- Modify: `rbx/box/statements/latex.py:42-46` (pdflatex), and `install_tex_packages` (texliveonfly)
- Modify: `rbx/box/statements/render.py:260-285` (the two `pypandoc` call sites)
- Test: `tests/rbx/box/statements/test_latex_tooling.py`

**Step 1: Write the failing test**

```python
from unittest import mock

import pytest
import typer

from rbx.box.statements import latex


def test_build_pdf_reports_missing_pdflatex_via_the_registry(tmp_path, capsys):
    with (
        mock.patch('rbx.tooling.command_exists', return_value=False),
        pytest.raises(typer.Exit),
    ):
        latex.Latex('\\documentclass{article}\\begin{document}x\\end{document}').build_pdf(tmp_path)
    assert 'pdflatex' in capsys.readouterr().out
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_latex_tooling.py -v`
Expected: FAIL — the current code patches nothing named `rbx.tooling.command_exists`, so `pdflatex` is found and the test does not raise `typer.Exit`.

**Step 3: Implement**

- In `latex.py`, replace the inline `command_exists('pdflatex', flags=['-v'])` + console error with `tooling.PDFLATEX.ensure()`. Drop the now-unused `command_exists` import if nothing else uses it.
- In `install_tex_packages`, replace `if not command_exists('texliveonfly'): return` with `if not tooling.TEXLIVEONFLY.is_available(): return`. **Keep the silent return** — texliveonfly is genuinely optional, so this is `is_available()`, not `ensure()`. Do not "improve" it into an error.
- In `render.py`, call `tooling.PANDOC.ensure()` before each `pypandoc.convert_text` call, so a missing binary produces the install hint instead of a bare `OSError`.

**Step 4: Verify no regressions**

Run: `uv run pytest tests/rbx/box/statements/ -q`
Expected: all PASS (419-test baseline for statements+moj must not drop)

**Step 5: Lint and commit**

`refactor(statements): route external tools through the registry`

---

### Task 3: Let a document dir be constant in `SubtreeLayout`

`SubtreeLayout.document_dir` currently **requires** an `{index}` placeholder for the `sample_explanation` slot and rejects a constant (`rbx/box/statements/export.py`, `_check_index_placeholder`). MOJ needs a constant `docs`, because mojtools renders every note with `--resource-path=$PKG/docs` regardless of sample. As shipped, the layout cannot express its own intended first consumer.

The rule's rationale — that entries from different samples would "collide into one path" — holds for `asset_roots[SAMPLE]`, where many *files* land, and stays required there. It does not hold for `document_dir`, which is only the **base a remap is computed against**: two samples sharing `docs` derive identical references for shared statement-scope assets (correct — same file) and distinct ones for their own sample-scope assets, which live under `docs/samples/{index}/`.

**Files:**
- Modify: `rbx/box/statements/export.py` (`SubtreeLayout._check_index_placeholder` / `document_dir`, and the class docstring)
- Test: `tests/rbx/box/statements/test_export_layout.py`

**Step 1: Write the failing tests**

```python
def test_sample_explanation_dir_may_be_constant():
    """MOJ renders every note with --resource-path=<pkg>/docs, so the note slot's
    remap base is constant across samples even though the note FILES are per-sample."""
    layout = export.SubtreeLayout(
        asset_roots={export.AssetScope.SAMPLE: 'docs/samples/{index:03d}'},
        document_dirs={'body': 'docs', 'sample_explanation': 'docs'},
    )
    assert layout.document_dir(export.DocumentSlot.sample(1)) == pathlib.PurePosixPath('docs')
    assert layout.document_dir(export.DocumentSlot.sample(2)) == pathlib.PurePosixPath('docs')


def test_sample_explanation_dir_may_still_carry_an_index():
    layout = export.SubtreeLayout(
        asset_roots={export.AssetScope.SAMPLE: 'docs/samples/{index:03d}'},
        document_dirs={'sample_explanation': 'notes/{index:03d}'},
    )
    assert layout.document_dir(export.DocumentSlot.sample(7)) == pathlib.PurePosixPath('notes/007')


def test_sample_asset_root_still_requires_an_index():
    """Relaxing the DOCUMENT slot must not relax the ASSET root, where many files
    really would collide into one directory."""
    layout = export.SubtreeLayout(asset_roots={export.AssetScope.SAMPLE: 'docs/samples'})
    with pytest.raises(export.StatementExportError, match='index'):
        layout.place_asset(_sample_asset(index=1))


def test_body_dir_still_rejects_an_index():
    layout = export.SubtreeLayout(document_dirs={'body': 'docs/{index}'})
    with pytest.raises(export.StatementExportError, match='index'):
        layout.document_dir(export.DocumentSlot.body())
```

Reuse whatever helper the existing file already has for building a sample-scope `ResolvedAsset`; do not invent a second one.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_export_layout.py -v`
Expected: `test_sample_explanation_dir_may_be_constant` FAILS with `StatementExportError` about a required `{index}` placeholder. The other three PASS already — they are the regression guard proving the relaxation is surgical.

**Step 3: Implement**

In `document_dir`, stop passing `needed=True` for the `sample_explanation` slot: `{index}` becomes **optional** there — permitted, but no longer required. Leave `place_asset` untouched, so `asset_roots[AssetScope.SAMPLE]` still requires it. The "rejected where there is no index to interpolate" branch stays exactly as-is for every other slot.

Update the `SubtreeLayout` docstring: it currently states `{index}` is REQUIRED for `document_dirs['sample_explanation']`. Replace that with the reason it is *optional* — a document dir is a remap base, not a destination — and cite MOJ's `--resource-path` as the motivating case. The docstring is the only place a future reader will look before re-adding the constraint.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/ -q`
Expected: all PASS

**Step 5: Lint and commit**

`fix(statements): let a document dir be constant across samples`

---

### Task 4: Rasterize PDF assets to PNG

MOJ renders to HTML and base64-embeds every image, so an `<img src="fig.pdf">` is broken in every browser — and rbx's TikZ externalization produces exactly that. rbx has no rasterizer, and PyMuPDF is AGPL, incompatible with rbx's Apache-2.0, so this shells out to poppler through Task 1's registry.

**Files:**
- Create: `rbx/box/packaging/moj/statement_assets.py`
- Test: `tests/rbx/box/packaging/moj/test_statement_assets.py`

**Step 1: Write the failing tests**

```python
def test_layout_places_a_pdf_asset_as_png():
    """The remap is derived from place_asset, so the extension must change HERE --
    rasterizing after materialize would leave every reference pointing at a .pdf."""
    inner = export.SubtreeLayout(document_dirs={'body': 'docs'}, asset_roots={export.AssetScope.STATEMENT: 'docs/assets'})
    layout = statement_assets.RasterizingLayout(inner)
    assert layout.place_asset(_asset('fig.pdf')) == pathlib.PurePosixPath('docs/assets/fig.png')


def test_layout_leaves_raster_and_vector_assets_alone():
    inner = export.SubtreeLayout(document_dirs={'body': 'docs'}, asset_roots={export.AssetScope.STATEMENT: 'docs/assets'})
    layout = statement_assets.RasterizingLayout(inner)
    assert layout.place_asset(_asset('fig.png')) == pathlib.PurePosixPath('docs/assets/fig.png')
    assert layout.place_asset(_asset('fig.svg')) == pathlib.PurePosixPath('docs/assets/fig.svg')


def test_rasterize_invokes_pdftoppm_and_replaces_the_pdf(tmp_path):
    ...  # assert pdftoppm called with -png -r 300 -singlefile, and the .pdf is gone


def test_rasterize_refuses_when_poppler_is_missing_and_names_the_figures(tmp_path, capsys):
    ...  # typer.Exit, output names fig.pdf


def test_rasterize_is_a_noop_without_pdf_assets(tmp_path):
    """Must not probe for poppler at all -- the overwhelmingly common package has no
    PDF figures, and demanding poppler from it would be a gratuitous new requirement."""
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_statement_assets.py -v`
Expected: FAIL — module does not exist.

**Step 3: Implement**

- `RasterizingLayout`: an `AssetLayout` that wraps another one, delegating `keep_extension` and `document_dir`, and mapping a `.pdf` result from `place_asset` to `.png` via `with_suffix('.png')`. Doing it in the layout — rather than in the packager after the fact — is what makes the *derived remap* already point at the rasterized name; `derive_remap` reads `place_asset`, so any other placement leaves references pointing at a `.pdf`. Extension mangling is already a layout concern (`keep_extension`), so this is in-idiom.
- `rasterize_pdf_assets(bundle, root)`: after `bundle.materialize(root)`, find each `BundledAsset` whose **source** is a `.pdf`, run `tooling.PDFTOPPM.run(['-png', '-r', '300', '-singlefile', str(src), str(dest_without_suffix)])`, and delete the PDF. Return early when there are none, **without** probing for poppler.
- Missing poppler: `tooling.PDFTOPPM.ensure()` raises with the install hint; catch and re-raise/print listing the offending figures so the setter knows which ones to convert. This follows the MOJ packager's existing rule — refuse rather than ship something that breaks on the judge.
- SVG passes through untouched: pandoc embeds it fine.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_statement_assets.py -v`
Expected: all PASS

**Step 5: Lint and commit**

`feat(packaging): rasterize PDF statement assets for MOJ`

---

### Task 5: TeX → Markdown conversion

**Files:**
- Create: `rbx/box/statements/markdown_export.py`
- Test: `tests/rbx/box/statements/test_markdown_export.py`
- Test fixtures: `tests/rbx/box/statements/testdata/markdown_export/*.tex` + `*.md`

**Step 1: Write the failing tests**

Golden-file tests, one `.tex`/`.md` pair per construct in the Polygon subset. Cover at minimum: inline and display math; `\textbf`/`\textit`/`\texttt`/`\emph`/`\underline`/`\sout`/`\textsc`; `{\bf …}`/`{\it …}` font switches; `itemize`; `enumerate`; `center`; `tabular` with `\hline`; `tabular` with `\multicolumn`; `verbatim`/`lstlisting`; `\url`/`\href`; `\includegraphics`; `\epigraph`.

The whole subset was verified to survive `pandoc -f latex -t markdown` and round-trip back to HTML, so these goldens are recording behavior, not aspiration. Generate each golden by running the converter once and **reading the output** before committing it — a golden nobody read is not a test.

Plus the two behavioral tests that are not about pandoc:

```python
def test_image_alt_text_is_cleared():
    """pandoc's LaTeX reader emits ![image](f.png); non-empty alt triggers
    implicit_figures on MOJ's side, captioning EVERY figure 'image'."""
    out = markdown_export.tex_to_markdown('\\includegraphics{fig.png}')
    assert '![](fig.png)' in out
    assert '![image]' not in out


def test_converted_output_has_no_fences():
    """A ``` fence trips validate-problem.sh's hand-written-example warning.
    pandoc emits INDENTED code blocks by default -- this pins that."""
    out = markdown_export.tex_to_markdown('\\begin{lstlisting}\nx = 1\n\\end{lstlisting}')
    assert '```' not in out


@pytest.mark.parametrize('block', ['## Exemplos\n', '```\nx\n```\n'])
def test_gate_guard_rejects_leaked_examples(block):
    with pytest.raises(...):
        markdown_export.check_moj_gate(block, block_name='legend')
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_markdown_export.py -v`
Expected: FAIL — module does not exist.

**Step 3: Implement**

- `tex_to_markdown(tex: str) -> str`: `tooling.PANDOC.ensure()`, then convert LaTeX → **pandoc JSON AST** → clear every `Image` node's alt inlines → JSON → Markdown, using `pypandoc.convert_text`. Going through the AST rather than regexing `![image](` is what makes the alt fix robust against captions, attributes and nested contexts, and it gives later fixes a home.
- `check_moj_gate(markdown: str, *, block_name: str) -> None`: raise with an actionable message when the converted text contains a ``` fence or an `^#{1,3}\s*(exemplos?|examples?|sample)` heading, naming the block. MOJ injects examples from `tests/input/sample*`; a statement carrying its own trips `render_warnings`.
- Pin a pandoc floor in `pyproject.toml` if `pypandoc>=1.15` does not already imply one, and note in the module docstring that the goldens are pandoc-version-sensitive.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/test_markdown_export.py -v`
Expected: all PASS

**Step 5: Lint and commit**

`feat(statements): convert Polygon-TeX blocks to markdown`

---

### Task 6: Assemble the MOJ statement documents

**Files:**
- Create: `rbx/box/packaging/moj/statement.py`
- Test: `tests/rbx/box/packaging/moj/test_statement.py`

**Step 1: Write the failing tests**

```python
def test_body_has_no_title_heading():
    """render-statement.sh injects <h1> from display_title and strips a legacy
    '% Title' line, so a title in the document would be a duplicate."""


def test_mandatory_headings_are_emitted_for_portuguese():
    doc = statement.build_enunciado(blocks, language='pt-br')
    assert '## Entrada' in doc
    assert '## Saída' in doc


def test_headings_follow_the_statement_language():
    """validate-problem.sh accepts entrada|input and saída|saida|output, case
    insensitively, so an English statement gets English headings and still passes."""
    doc = statement.build_enunciado(blocks, language='en')
    assert '## Input' in doc
    assert '## Output' in doc


def test_notes_block_becomes_a_section():
    ...


def test_explanations_are_written_per_sample_by_test_name():
    """mojtools pairs docs/notes/<sample>.md to tests/input/<sample> BY NAME."""
    # index 0 -> docs/notes/sample001.md, matching naming.testcase_name(is_sample=True)


def test_layout_uses_docs_as_the_remap_base_for_both_slots():
    """The note FILE lives in docs/notes/, but gen-problem-json.sh renders it with
    --resource-path=<pkg>/docs, so its images resolve against docs/. A remap base of
    docs/notes/ would derive '../assets/f.png' and break every note image."""
    layout = statement.moj_layout()
    assert layout.document_dir(export.DocumentSlot.body()) == pathlib.PurePosixPath('docs')
    assert layout.document_dir(export.DocumentSlot.sample(1)) == pathlib.PurePosixPath('docs')
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_statement.py -v`
Expected: FAIL — module does not exist.

**Step 3: Implement**

- `moj_layout()` returns the `SubtreeLayout` (wrapped by Task 4's `RasterizingLayout`):
  - `document_dirs = {'body': 'docs', 'sample_explanation': 'docs'}` — **both constant `docs`**, which is exactly why Task 3 was needed. Comment the `sample_explanation` value with the `--resource-path` reason; it looks like a bug otherwise.
  - `asset_roots = {STATEMENT: 'docs/assets', SAMPLE: 'docs/samples/{index:03d}', ...}` — the SAMPLE root keeps `{index}`, which is still required.
- `build_enunciado(blocks, *, language)`: `legend` as the body with **no heading**, then `## Entrada`, `## Saída`, and `## Notas` when a `notes` block exists — heading text selected from the statement language, defaulting to Portuguese. Run `check_moj_gate` over each converted block.
- `build_notes(explanations, testcase_names)`: map each explanation index to its sample's test name via `rbx/box/packaging/moj/naming.py:testcase_name(..., is_sample=True)`, producing `docs/notes/<name>.md`. Do not re-derive the `sample%03d` format by hand — call `naming`, so the two can never drift.
- Warn (do not fail) when an explanation contains `$…$`: `gen-problem-json.sh` renders notes **without** `--mathml`, unlike the body, so math reaches the student as literal `\(x\)`. Nothing in the package can fix it.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_statement.py -v`
Expected: all PASS

**Step 5: Lint and commit**

`feat(packaging): assemble MOJ statement documents`

---

### Task 7: Wire it into the packager and the CLI

**Files:**
- Modify: `rbx/box/packaging/moj/packager.py` — `statement_types()` (~line 86), add `statement_export_params()`, `_write_metadata` (~line 214-221)
- Modify: `rbx/box/packaging/main.py:135-143` — add `--language`
- Test: `tests/rbx/box/packaging/moj/test_packager.py`, `tests/rbx/box/packaging/moj/test_cli.py`

**Step 1: Write the failing tests**

```python
# CORRECTED after implementation: this assertion was wrong and shipped a bug.
# `statement_types()` names the OUTPUT type, and v2 emits only pdf/tex/md, so
# rbxTeX (a SOURCE type) fails the build. Leave the hook at its default [PDF].
def test_builds_pdf_statements_even_though_it_consumes_blocks():
    assert MojPackager(testcase_entries=[]).statement_types() == [StatementType.PDF]


def test_export_params_force_externalize_and_demacro():
    """Without these the overlay has no blocks.sub.yml/macros.json and the export
    pipeline has nothing to read. Mirrors PolygonPackager.statement_export_params."""


def test_package_writes_a_real_enunciado(...):
    # docs/enunciado.md contains the legend text and the two headings, not DUMMY_STATEMENT


def test_package_falls_back_to_the_dummy_without_statements(...):
    """MOJ requires the two headings; a statement-less package must still package."""


def test_language_option_selects_the_statement(...):


def test_display_title_comes_from_the_selected_statement(...):
    """Body and <h1> must never come from different languages."""
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/moj/ -v`
Expected: FAIL — `statement_types()` still returns `[]`.

**Step 3: Implement**

- **Do NOT override `statement_types()`** — leave the inherited `[StatementType.PDF]`, as `PolygonPackager` does. (The plan originally said `[StatementType.rbxTeX]`; that shipped a bug. The hook names the *output* type and v2 emits only pdf/tex/md, so a source type fails the build — and TeX/Markdown output would skip `render.compile_pdf`, where externalization and demacro actually run.)
- Add `statement_export_params()` returning the same forced steps as `PolygonPackager.statement_export_params` (`rbx/box/packaging/polygon/packager.py:73`): `rbxToTeX(externalize=True)` and `TexToPDF(externalize=True, demacro=True)`.
- `MojPackager.__init__` takes `main_language: Optional[str] = None`, mirroring `PolygonPackager`. `_get_main_statement()` honors it, and `_display_title()` resolves from **the same** statement.
- In `_write_metadata`, replace the `DUMMY_STATEMENT` write with: build the bundle via `export.build_statement_bundle(statement, layout=statement_mod.moj_layout())`, `materialize` into `into_path`, `rasterize_pdf_assets`, then write `docs/enunciado.md` and each `docs/notes/<name>.md`. Keep `DUMMY_STATEMENT` for the no-statement case — do not delete the constant.
- `rbx/box/packaging/main.py`: add `language: Optional[str] = typer.Option(None, '--language', help=...)` to the `moj` command and pass it through, mirroring `rbx package polygon --language`. Error clearly when the requested language has no statement.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/packaging/moj/ tests/rbx/box/statements/ -q`
Expected: all PASS, and not fewer than the 419-test baseline plus the new tests.

**Step 5: Lint and commit**

`feat(packaging): build markdown statements for MOJ`

---

### Task 8: End-to-end against the real judge tooling, and docs

This is the check that matters: it runs the same renderer the student sees.

**Files:**
- Test: `tests/rbx/box/packaging/moj/test_statement_e2e.py`
- Modify: `rbx/box/packaging/moj/CLAUDE.md` (the **Out of scope → Statements** section is now wrong), `rbx/box/packaging/CLAUDE.md` (the MOJ bullet saying `statement_types()` is `[]`), `rbx/box/statements/CLAUDE.md` (SubtreeLayout now has a production consumer)

**Step 1: Write the test**

Package a fixture carrying a statement image and a sample explanation, then, when `MOJTOOLS_DIR` is set (skip otherwise, and mark `slow`), run mojtools' real `validate-problem.sh` over the output and assert the JSON it emits has `secao_entrada`, `secao_saida` and `html_builds` all ok **with empty `render_warnings`**. Also run `render-statement.sh` and assert the statement image appears as an embedded `data:` URI — that is the end-to-end proof the remap and the resource-path base are right.

**Step 2: Run it**

Run: `MOJTOOLS_DIR=/path/to/mojtools uv run pytest tests/rbx/box/packaging/moj/test_statement_e2e.py -v`
Expected: PASS. Without `MOJTOOLS_DIR`: SKIPPED.

**Step 3: Update the docs**

- `moj/CLAUDE.md`: statements are no longer out of scope. Document the `--language` flag, the `docs/` remap base for notes and **why**, the poppler requirement for PDF figures, and the no-`--mathml`-in-notes limitation.
- `packaging/CLAUDE.md`: update the MOJ bullet.
- `statements/CLAUDE.md`: `SubtreeLayout` has a consumer now; record that a document dir may be constant and why.

**Step 4: Full verification**

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto
uv run ruff check . && uv run ruff format --check .
```
Compare the failure set against a clean checkout of `main` — this repo has known pre-existing local failures (C++/sandbox/docker). **Zero new failures** is the bar.

**Step 5: Commit and open the PR**

`docs(packaging): document MOJ markdown statements`, then open the PR **against #640's branch**, not `main`, noting it must merge after #640.

---

## Definition of done

- `rbx package moj` emits a real `docs/enunciado.md` with the mandatory headings, no title, no fences and no examples section.
- Statement and sample-note images resolve and embed under mojtools' actual renderer.
- PDF figures are rasterized; a missing poppler refuses the package with an install hint.
- `mojtools/validate-problem.sh` reports empty `render_warnings`.
- Zero new test failures against the `main` baseline; ruff clean.
