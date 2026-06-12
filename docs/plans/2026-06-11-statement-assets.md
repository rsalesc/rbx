# Statement `assets` field + scoped Polygon resources — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the implicit "ship everything under the statement dir" Polygon
resource rule with an explicit, inheritable `assets` field plus image/PDF runtime
defaults, fixing dangling `\includegraphics` for sample-explanation images that
live outside the statement directory (#595, closing audit findings #5/#6).

**Architecture:** All resolution + rewriting happens **upload-side** in
`rbx/box/packaging/polygon/upload.py`. The build already stages everything: the
statement subtree is mirrored to the overlay root, and each sample's source dir
(incl. external images) is overlaid into `.samples/<idx>/` — the exact dir
`build_statements.get_statement_dir()` hands the upload. We collect assets in
three scopes (statement / per-sample / out-of-tree), upload each under a
deterministic flat name, and rewrite `\includegraphics` references with a
TexSoup-based, channel-anchored rewriter (statement remap for
legend/input/output/notes-block; statement∪sample[i] remap for explanation i).

**Tech Stack:** Python 3, Pydantic v2, TexSoup (already a dep), pytest, the e2e
YAML DSL (`tests/e2e/`).

---

## Background facts (verified during design)

- `BaseStatement` is at `rbx/box/statements/schema.py:182`; it already imports
  `List` and `Field`.
- `expander.py:34` has `_PROBLEM_ALLOWLIST = ('type', 'file')` and
  `_CONTEST_ALLOWLIST`. `_merge` inherits any allowlisted field the child didn't
  set → **child replaces parent**.
- Upload runs inside the problem dir (`within_problem`), so the **package root**
  is `utils.abspath(pathlib.Path())`.
- `_statement_asset_files` / `_upload_statement_resources` /
  `_get_explanations` / `_upload_statement` live at
  `upload.py:599 / 621 / 591 / 667`.
- `get_processed_statement_blocks(statement)` returns `StatementBlocks` with
  `.blocks: Dict[str,str]` and `.explanations: Dict[int,str]` (keyed by sample
  index). `get_produced_tikz_pdfs(statement)` yields `(abs, overlay_rel)` for the
  externalized TikZ PDFs (referenced as `artifacts/tikz_figures/<label>`).
- The codebase already round-trips these blocks through TexSoup via
  `str(parse_latex(block))` (`render.substitute_externalized_blocks`), so a
  TexSoup-based rewriter is the established, safe pattern.
- Flat-name scheme (uniform): `flat(rel) = str(rel).replace('/', '__')`, keeping
  the extension. Remap key is the ref **without** extension:
  `key(rel) = str(rel.with_suffix(''))`. Sample-scope flat names are prefixed
  `sample_<idx>__`.
- e2e `polygon_upload` matcher: `resources_present`/`resources_absent` (by flat
  name), `resources_referenced_consistent` (every `\includegraphics` resolves to
  an uploaded name or its stem), `statements.<lang>.<field>_contains`. Capture
  dir defaults to `.rbx/polygon_capture` under the **package (contest) root**.
- **Behavior change to encode:** uniform remap now rewrites a root-level asset
  reference (`\includegraphics{pic}` → `\includegraphics{pic.png}`). The existing
  `polygon-tikz-assets` fixture asserts `\includegraphics{pic}`; it must be
  updated to `\includegraphics{pic.png}`.

Run a single test: `uv run pytest <path>::<test> -v`. Lint after edits:
`uv run ruff check --fix . && uv run ruff format .`. Commit with the `commit`
skill workflow (`.claude/skills/commit.md`) — conventional commits, co-author
trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task 1: `assets` schema field

**Files:**
- Modify: `rbx/box/statements/schema.py` (BaseStatement, ~line 220 after `samples`)
- Test: `tests/rbx/box/statements/test_schema_assets.py` (create)

**Step 1 — failing test:**

```python
import pathlib
from rbx.box.statements.schema import Statement

def test_assets_defaults_to_empty_list():
    st = Statement(language='en', file=pathlib.Path('statement/statement.rbx.tex'))
    assert st.assets == []

def test_assets_accepts_globs():
    st = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['statement/**/*.png', 'extra/logo.svg'],
    )
    assert st.assets == ['statement/**/*.png', 'extra/logo.svg']
```

**Step 2:** `uv run pytest tests/rbx/box/statements/test_schema_assets.py -v` → FAIL
(`assets` unknown field; `extra='forbid'`).

**Step 3 — implement** (in `BaseStatement`, after the `samples` field):

```python
assets: List[str] = Field(
    default_factory=list,
    description='Globs (relative to the package root) selecting files to ship as '
    'statement resources (e.g. images/PDFs). Inherited via `extends`. At build '
    'time the default image/PDF globs over the statement subtree and each sample '
    'subtree are concatenated to this list.',
)
```

**Step 4:** rerun → PASS. **Step 5:** lint, commit
`feat(statements): add assets field to BaseStatement (#595)`.

---

## Task 2: inherit `assets` through `extends`

**Files:**
- Modify: `rbx/box/statements/expander.py:34-40`
- Test: `tests/rbx/box/statements/test_expander.py` (add; reuse existing if present)

**Step 1 — failing test:**

```python
import pathlib
from rbx.box.statements.expander import expand_problem_statements
from rbx.box.statements.schema import Statement

def _st(**kw):
    return Statement(file=pathlib.Path('statement/statement.rbx.tex'), **kw)

def test_assets_inherited_when_child_unset():
    parent = _st(language='en', assets=['a/**/*.png'])
    child = _st(language='pt', extends='en')
    out = {s.language: s for s in expand_problem_statements([parent, child])}
    assert out['pt'].assets == ['a/**/*.png']

def test_child_assets_replace_parent():
    parent = _st(language='en', assets=['a/**/*.png'])
    child = _st(language='pt', extends='en', assets=['b/*.pdf'])
    out = {s.language: s for s in expand_problem_statements([parent, child])}
    assert out['pt'].assets == ['b/*.pdf']
```

**Step 2:** run → FAIL (child inherits nothing; `assets` not in allowlist).

**Step 3 — implement:** add `'assets'` to both tuples:

```python
_PROBLEM_ALLOWLIST = ('type', 'file', 'assets')
_CONTEST_ALLOWLIST = (
    'type',
    'file',
    'assets',
    'standaloneProblemTemplate',
    'contestProblemTemplate',
)
```

**Step 4:** run → PASS. **Step 5:** commit
`feat(statements): inherit assets through extends (#595)`.

---

## Task 3: pure asset-collection + flat-name helpers in `upload.py`

Build small, unit-testable helpers before wiring them in. No upload calls here.

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py` (replace `_statement_asset_files`
  region ~599-618; add helpers)
- Test: `tests/rbx/box/packaging/polygon/test_upload_assets.py` (create)

**Helpers to add:**

```python
_ASSET_EXTS = ('.png', '.jpg', '.jpeg', '.pdf')

def _flat_name(rel: pathlib.Path) -> str:
    return str(rel).replace('/', '__')

def _remap_key(rel: pathlib.Path) -> str:
    return str(rel.with_suffix(''))

def _resolve_asset_globs(root: pathlib.Path, globs: List[str]) -> List[pathlib.Path]:
    """Files matching `globs` under `root` (Path.glob, so ** works); files-only,
    deduped, deterministically sorted (by path)."""
    seen: Set[pathlib.Path] = set()
    for g in globs:
        for p in root.glob(g):
            if p.is_file():
                seen.add(utils.abspath(p))
    return sorted(seen)

def _image_files_under(base: pathlib.Path) -> List[pathlib.Path]:
    if not base.is_dir():
        return []
    return sorted(
        p for p in base.rglob('*')
        if p.is_file() and p.suffix.lower() in _ASSET_EXTS
    )
```

**Step 1 — failing tests** (use `tmp_path`, touch files):

```python
def test_resolve_asset_globs_dedup_sorted_files_only(tmp_path):
    (tmp_path / 'a').mkdir(); (tmp_path / 'a/x.png').touch()
    (tmp_path / 'a/y.png').touch(); (tmp_path / 'b.png').touch()
    out = _resolve_asset_globs(tmp_path, ['**/*.png', 'a/*.png'])
    assert out == [tmp_path/'a'/'x.png', tmp_path/'a'/'y.png', tmp_path/'b.png']

def test_flat_name_and_key():
    assert _flat_name(pathlib.Path('img/diagram.png')) == 'img__diagram.png'
    assert _flat_name(pathlib.Path('pic.png')) == 'pic.png'
    assert _remap_key(pathlib.Path('img/diagram.png')) == 'img/diagram'

def test_image_files_under_filters_non_images(tmp_path):
    (tmp_path / 'p.png').touch(); (tmp_path / 's.in').touch()
    (tmp_path / 'e.rbx.tex').touch()
    assert _image_files_under(tmp_path) == [tmp_path / 'p.png']
```

**Step 2:** run → FAIL (helpers undefined). **Step 3:** implement.
**Step 4:** run → PASS. **Step 5:** commit
`refactor(polygon): add scoped asset-collection helpers (#595)`.

---

## Task 4: TexSoup-based `\includegraphics` rewriter (fixes #6)

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py` (add `_rewrite_includegraphics`)
- Test: `tests/rbx/box/packaging/polygon/test_upload_assets.py` (add)

**Implementation** (reuse `parse_latex`, mirror the established
`replace_labeled_tikz_nodes` node-replacement pattern):

```python
from TexSoup.data import BraceGroup, BracketGroup
from rbx.box.statements.texsoup_utils import parse_latex

def _strip_asset_ext(ref: str) -> str:
    p = pathlib.Path(ref)
    return str(p.with_suffix('')) if p.suffix.lower() in _ASSET_EXTS else ref

def _rewrite_includegraphics(block: str, remap: Dict[str, str]) -> str:
    """Rewrite every `\\includegraphics[..]{ref}` whose `ref` (extension-stripped)
    is in `remap` to the mapped flat name, preserving optional args and all
    surrounding text. Parser-based (TexSoup) — not substring replace — so it is
    order-independent and never produces a double extension."""
    if not remap:
        return block
    soup = parse_latex(block)
    for node in list(soup.find_all('includegraphics')):
        brace = next((a for a in node.args if isinstance(a, BraceGroup)), None)
        if brace is None:
            continue
        target = remap.get(_strip_asset_ext(brace.string))
        if target is None:
            continue
        opt = ''.join(f'[{a.string}]' for a in node.args if isinstance(a, BracketGroup))
        node.replace_with(*parse_latex(f'\\includegraphics{opt}{{{target}}}').contents)
    return str(soup)
```

**Step 1 — failing tests:**

```python
def test_rewrite_subdir_reference():
    out = _rewrite_includegraphics(
        r'see \includegraphics{img/diagram}.', {'img/diagram': 'img__diagram.png'})
    assert r'\includegraphics{img__diagram.png}' in out

def test_rewrite_root_level_reference():  # finding #6 uniformity
    out = _rewrite_includegraphics(
        r'\includegraphics{pic}', {'pic': 'pic.png'})
    assert out.strip() == r'\includegraphics{pic.png}'

def test_rewrite_with_extension_no_double_ext():  # finding #6 double-ext
    out = _rewrite_includegraphics(
        r'\includegraphics{imgs/fig.png}', {'imgs/fig': 'imgs__fig.png'})
    assert r'imgs__fig.png.png' not in out
    assert r'\includegraphics{imgs__fig.png}' in out

def test_rewrite_preserves_optional_arg():
    out = _rewrite_includegraphics(
        r'\includegraphics[width=1cm]{pic}', {'pic': 'pic.png'})
    assert r'\includegraphics[width=1cm]{pic.png}' in out

def test_rewrite_leaves_unmapped_untouched():
    src = r'\includegraphics{artifacts/tikz_figures/0_0}'
    assert _rewrite_includegraphics(src, {'pic': 'pic.png'}).strip() == src
```

**Step 2:** run → FAIL. **Step 3:** implement. **Step 4:** run → PASS (adjust
helper if TexSoup round-trip differs — tests pin exact behavior). **Step 5:**
commit `fix(polygon): parser-based includegraphics rewrite (#589 #6, #595)`.

---

## Task 5: scoped resource upload + per-channel rewrite wiring

Rewrite `_upload_statement_resources` to upload all three scopes and return a
structured remap, then update the `_upload_statement` closures to rewrite per
channel.

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py`
  (`_upload_statement_resources` 621-664; `_get_explanations` 591-596;
  `_upload_statement` 667-715; add `get_statement_dir` import from
  `build_statements`)
- Test: `tests/rbx/box/packaging/polygon/test_upload_assets.py` (add a
  collection-level test with a fake `.samples/` tree + monkeypatched
  `get_statement_dir`)

**Design:**

```python
@dataclasses.dataclass
class _AssetRemaps:
    statement: Dict[str, str]                 # key->flat for legend/input/output/notes-block
    samples: Dict[int, Dict[str, str]]        # per explanation index: key->flat

def _collect_assets(statement, explanation_indices):
    """Return (uploads, remaps) where uploads is a list of (abs_path, flat_name)
    and remaps is _AssetRemaps. Pure-ish: reads the filesystem only."""
    pkg_root = utils.abspath(pathlib.Path())
    statement_dir = utils.abspath(statement.file).parent
    overlay = get_statement_dir(statement)

    uploads: Dict[str, pathlib.Path] = {}          # flat_name -> abs (dedup)
    stmt_remap: Dict[str, str] = {}

    # 1. statement-scope: image/PDF under the statement dir, referenced
    #    statement-dir-relative.
    for abs_path in _image_files_under(statement_dir):
        rel = abs_path.relative_to(statement_dir)
        flat = _flat_name(rel)
        uploads[flat] = abs_path
        stmt_remap[_remap_key(rel)] = flat

    # 1b. explicit assets under the statement dir (any extension beyond defaults).
    for abs_path in _resolve_asset_globs(pkg_root, statement.assets):
        try:
            rel = abs_path.relative_to(statement_dir)
        except ValueError:
            continue  # handled as out-of-tree below
        flat = _flat_name(rel)
        uploads[flat] = abs_path
        stmt_remap[_remap_key(rel)] = flat

    # 2. externalized TikZ PDFs (overlay-relative), referenced as
    #    artifacts/tikz_figures/<label>.
    for abs_path, overlay_rel in get_produced_tikz_pdfs(statement):
        flat = _flat_name(overlay_rel)
        uploads[flat] = abs_path
        stmt_remap[_remap_key(overlay_rel)] = flat

    # 3. per-sample scope: image/PDF under .samples/<idx>/ for each explanation,
    #    referenced sample-dir-relative, namespaced sample_<idx>__.
    sample_remaps: Dict[int, Dict[str, str]] = {}
    for idx in sorted(explanation_indices):
        base = overlay / sample_staging.SAMPLES_DIRNAME / f'{idx:03d}'
        rmap: Dict[str, str] = {}
        for abs_path in _image_files_under(base):
            rel = abs_path.relative_to(base)
            flat = f'sample_{idx}__{_flat_name(rel)}'
            uploads[flat] = abs_path
            rmap[_remap_key(rel)] = flat
        if rmap:
            sample_remaps[idx] = rmap

    # 4. out-of-tree explicit assets: upload by flat name, no auto-rewrite.
    for abs_path in _resolve_asset_globs(pkg_root, statement.assets):
        try:
            abs_path.relative_to(statement_dir)
            continue  # already statement-scope
        except ValueError:
            pass
        try:
            rel = abs_path.relative_to(pkg_root)
        except ValueError:
            rel = pathlib.Path(abs_path.name)
        uploads[_flat_name(rel)] = abs_path

    return uploads, _AssetRemaps(statement=stmt_remap, samples=sample_remaps)
```

`_upload_statement_resources(problem, statement, explanation_indices)` then:
calls `_collect_assets`, uploads each `(flat_name, abs_path)` (keep the 1MB cap +
the "Uploading statement resource ..." prints; iterate the deduped `uploads`
dict), and returns the `_AssetRemaps`.

`_upload_statement.process_statement` updates:

```python
blocks = get_processed_statement_blocks(statement)
remaps = _upload_statement_resources(problem, statement, set(blocks.explanations))

def _get_block(name):
    return _rewrite_includegraphics(blocks.blocks.get(name) or '', remaps.statement)

def _rewritten_explanations():
    out = {}
    for idx, text in blocks.explanations.items():
        merged = {**remaps.statement, **remaps.samples.get(idx, {})}  # sample wins
        out[idx] = _rewrite_includegraphics(text, merged)
    return out

def _get_notes_with_explanations():
    notes = _get_block('notes')
    expl = _rewritten_explanations()
    if not notes and not expl:
        return None
    res = _get_explanations(expl)        # builds "Explanation for example N" text
    return notes + '\n\n' + res if notes else res
```

`_get_explanations(explanations: Dict[int, str])` is unchanged (already takes the
dict). `legend`/`input`/`output`/`interaction` go through `_get_block` (statement
remap). Delete the old `_replace_resources`/`_statement_asset_files`.

**Tests (collection level):** build a `tmp_path` with `statement/img/d.png`,
`statement/pic.png`, an out-of-tree `extra/logo.png`, a fake overlay
`.samples/000/diagram.png`; set `statement.assets=['extra/logo.png']`; monkeypatch
`get_statement_dir`→overlay and `get_produced_tikz_pdfs`→[] ; `cd` into pkg root.
Assert:
- `uploads` flat names == `{img__diagram.png, pic.png, extra__logo.png, sample_0__diagram.png}`.
- `remaps.statement == {'img/diagram':'img__diagram.png', 'pic':'pic.png'}`.
- `remaps.samples == {0: {'diagram':'sample_0__diagram.png'}}`.
- no `*.in`/`*.rbx.tex` in uploads (finding #5).

**Step 5:** commit `fix(polygon): scope statement resources to assets + defaults (#595)`.

---

## Task 6: e2e fixture — external sample-explanation assets

**Files (create under `tests/e2e/testdata/polygon-explanation-external-assets/`):**
mirror `polygon-tikz-assets` layout (contest + problem A + recording fake).
- `contest.rbx.yml`, `statements/contest.rbx.tex`,
  `statements/problem-standalone.rbx.tex`, `statements/problem-in-contest.rbx.tex`
  (copy from `polygon-tikz-assets`).
- `A/problem.rbx.yml`: samples come from a **manual** testcase whose inputs live
  **outside** `statement/` (e.g. `tests/samples/*.in`), and `statements[0].assets`
  declares an out-of-tree asset (e.g. `extra/logo.png`).
- `A/statement/statement.rbx.tex`: minimal legend/input/output; **no** in-statement
  images required for the core assertion (keep it about the external case), but
  reference the out-of-tree `\includegraphics{extra__logo.png}` in the legend to
  exercise the `assets` field end-to-end (referenced by flat name).
- `A/tests/samples/000.in`, `A/tests/samples/000.tex` (explanation:
  `\includegraphics{diagram.png}`), `A/tests/samples/diagram.png`,
  `A/extra/logo.png`, `A/sols/main.cpp`, `A/wcmp.cpp`.
- `.gitignore` (copy), `e2e.rbx.yml`.

**`e2e.rbx.yml`** (single passing scenario — the fix lands in this PR, so no
xfail):

```yaml
scenarios:
  - name: polygon-explanation-external-assets
    markers: [pdflatex]
    description: >
      A manual sample, its explanation, and the explanation image all live
      OUTSIDE the statement dir (tests/samples/). #595: the explanation image is
      uploaded under a per-sample flat name and the notes reference resolves.
      Also exercises the assets field with an out-of-tree resource referenced by
      flat name. Asserts sample I/O / explanation sources are not uploaded (#5).
    steps:
      - cmd: build
        cwd: A
      - cmd: st b
        cwd: A
        expect:
          files_exist: [A/build/statement-en.pdf]
      - cmd: package polygon -u --upload-as-english --upload-only statements
        cwd: A
        expect:
          stdout_contains: "uploaded successfully"
          polygon_upload:
            statements:
              english:
                notes_contains:
                  - "Explanation for example 1"
                  - "\\includegraphics{sample_0__diagram.png}"
                legend_contains:
                  - "\\includegraphics{extra__logo.png}"
            resources_present:
              - "sample_0__diagram.png"
              - "extra__logo.png"
            resources_absent:
              - "diagram.png"          # not under statement dir, never bare-uploaded
              - "000.in"
            resources_referenced_consistent: true
```

**Step — run:** `uv run pytest "tests/e2e/test_e2e.py" -k polygon-explanation-external-assets -m pdflatex -v`
(exact node id per `tests/e2e/README.md`). Expected PASS. If pdflatex is missing
locally it is skipped — verify the non-pdflatex parts (collection, capture) at
least import. **Step — commit** `test(e2e): external sample-explanation assets (#595)`.

---

## Task 7: update the existing `polygon-tikz-assets` fixture for uniform remap

**Files:** `tests/e2e/testdata/polygon-tikz-assets/e2e.rbx.yml`

**Change** (finding #6 uniform remap now rewrites the root-level reference):
in scenario `polygon-upload-assets`, `legend_contains`, replace
`"\\includegraphics{pic}"` with `"\\includegraphics{pic.png}"`. Optionally add
`resources_absent: ["samples__000.in"]` to lock in finding #5.

Leave `polygon-upload-assets-referential-integrity` as-is (still xfail in
`tests/e2e/conftest.py` — that is #590's TikZ case, out of scope here).

**Step — run** the `polygon-upload-assets` scenario → PASS. **Commit**
`test(e2e): root-level reference now rewritten to flat name (#595)`.

---

## Task 8: full verification + docs

1. `uv run pytest tests/rbx/box/statements tests/rbx/box/packaging/polygon -v`
   → all green.
2. `uv run pytest --ignore=tests/rbx/box/cli -n auto` (project default suite) →
   green except the known pre-existing failures (C++/sandbox/docker/walltime/
   completion-drift — see memory). Note any in the PR.
3. `mise run test-e2e-pdflatex` if pdflatex is available; otherwise document that
   the two pdflatex scenarios were validated by reasoning + the unit-level capture
   tests.
4. `uv run ruff check . && uv run ruff format --check .`.
5. Update `rbx/box/statements/CLAUDE.md` (schema bullet) and
   `rbx/box/packaging/CLAUDE.md` (Polygon upload bullet) to mention the `assets`
   field + scoped resource upload, if they describe this area.
6. **Commit** `docs: note assets field + scoped polygon resources (#595)`.

---

## Acceptance mapping

- Referential integrity incl. external sample images — Tasks 4-6.
- Resources restricted to assets + image/PDF defaults; no `.in`/`.out`/`.rbx.tex`
  — Task 5 (supersedes finding #5); asserted in Tasks 6-7.
- `assets` honored through `extends` — Tasks 1-2.
- Worked in-statement/out-of-tree `assets` example — Task 6 e2e (deviation from
  AC4: in an e2e package, not the preset, per the user's instruction).
