# Statement Export Bundle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract the reusable core of the Polygon statement upload — block
processing, asset scope resolution, TikZ collection, reference rewriting — into a
target-independent `StatementBundle` API, and port the Polygon upload onto it
without changing its output.

**Architecture:** A new `rbx/box/statements/export.py` resolves a statement's
assets into scope-tagged `ResolvedAsset`s (scope = the directory their
`\includegraphics` reference is relative to). An `AssetLayout` places each asset
*and* each referencing document as a path; the reference remap is **derived** from
those two placements rather than configured. `FlatLayout` reproduces Polygon
byte-for-byte; `SubtreeLayout` expresses a multi-root tarball judge such as MOJ.
`polygon/upload.py` keeps only the API client, the language selection and the
Polygon-specific `notes` assembly.

**Tech Stack:** Python 3, Pydantic v2, TexSoup, pytest.

**Design doc:** [`docs/plans/2026-08-13-statement-export-bundle-design.md`](2026-08-13-statement-export-bundle-design.md).
Read it before Task 1 — §3/§4 define the asset model and the derived-remap rule
this plan implements.

**Conventions you must follow** (from `CLAUDE.md`):
- Single quotes for strings; absolute imports only (relative imports are banned).
- Commits are Conventional Commits, checked by a pre-commit hook. Use the
  `.claude/skills/commit.md` workflow. If the hook rejects a commit, fix and make
  a **new** commit; never amend.
- Run `uv run ruff format . && uv run ruff check --fix .` before each commit.
- Tests: `uv run pytest <path> -v`.

**Known-bad baseline:** some C++/sandbox/docker tests fail locally on `main` for
unrelated reasons. Only judge the test files this plan touches.

---

### Task 1: Move the `\includegraphics` rewriting into `texsoup_utils`

The rewriting is pure LaTeX manipulation with nothing Polygon about it, and its
only dependency (`parse_latex`) already lives in `texsoup_utils`.

**Files:**
- Modify: `rbx/box/statements/texsoup_utils.py`
- Modify: `rbx/box/packaging/polygon/upload.py:605-678` (delete the moved code)
- Modify: `tests/rbx/box/statements/test_texsoup_utils.py`
- Modify: `tests/rbx/box/packaging/test_polygon_upload_assets.py:55-98` (move the
  rewrite tests out)

**Step 1: Write the failing tests**

Append to `tests/rbx/box/statements/test_texsoup_utils.py` (adjust the import
block at the top of the file to include the new names):

```python
from rbx.box.statements.texsoup_utils import (
    ASSET_EXTS,
    rewrite_includegraphics,
    strip_asset_ext,
)


def test_strip_asset_ext_drops_only_asset_extensions():
    assert strip_asset_ext('img/diagram.png') == 'img/diagram'
    assert strip_asset_ext('img/diagram.PDF') == 'img/diagram'
    assert strip_asset_ext('img/diagram') == 'img/diagram'
    # Not an asset extension: left alone, dots and all.
    assert strip_asset_ext('data.v2') == 'data.v2'


def test_rewrite_includegraphics_subdir_reference():
    out = rewrite_includegraphics(
        r'see \includegraphics{img/diagram}.', {'img/diagram': 'img__diagram.png'}
    )
    assert r'\includegraphics{img__diagram.png}' in out


def test_rewrite_includegraphics_no_double_extension():
    out = rewrite_includegraphics(
        r'\includegraphics{img/diagram.png}', {'img/diagram': 'img__diagram.png'}
    )
    assert r'\includegraphics{img__diagram.png}' in out
    assert '.png.png' not in out


def test_rewrite_includegraphics_preserves_optional_arg():
    out = rewrite_includegraphics(
        r'\includegraphics[width=0.5\textwidth]{pic}', {'pic': 'pic.png'}
    )
    assert r'[width=0.5\textwidth]' in out
    assert r'{pic.png}' in out


def test_rewrite_includegraphics_leaves_unmapped_untouched():
    block = r'\includegraphics{other}'
    assert rewrite_includegraphics(block, {'pic': 'pic.png'}) == block


def test_rewrite_includegraphics_empty_remap_is_identity():
    block = r'\includegraphics{pic}'
    assert rewrite_includegraphics(block, {}) is block


def test_asset_exts_contains_the_expected_set():
    assert ASSET_EXTS == ('.png', '.jpg', '.jpeg', '.pdf')
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/statements/test_texsoup_utils.py -v`
Expected: FAIL — `ImportError: cannot import name 'rewrite_includegraphics'`.

**Step 3: Move the implementation**

Cut `_ASSET_EXTS`, `_strip_asset_ext` and `_rewrite_includegraphics` from
`upload.py` and paste them into `rbx/box/statements/texsoup_utils.py`, renamed
without the leading underscore (they are public API now) and keeping their
docstrings. Add the TexSoup imports the moved code needs:

```python
from TexSoup.data import BraceGroup, BracketGroup

ASSET_EXTS = ('.png', '.jpg', '.jpeg', '.pdf')


def strip_asset_ext(ref: str) -> str:
    """Drop a trailing image/PDF extension from an ``\\includegraphics`` argument
    so it lines up with an (extensionless) reference key."""
    path = pathlib.Path(ref)
    return str(path.with_suffix('')) if path.suffix.lower() in ASSET_EXTS else ref


def rewrite_includegraphics(block: str, remap: Dict[str, str]) -> str:
    ...  # body unchanged from upload.py, calling strip_asset_ext
```

`texsoup_utils.py` already imports `pathlib`? If not, add it, plus `Dict` from
`typing`.

In `upload.py`, import the new names and keep the call sites working:

```python
from rbx.box.statements.texsoup_utils import rewrite_includegraphics
```

Replace the two `_rewrite_includegraphics(...)` call sites with
`rewrite_includegraphics(...)`.

**Step 4: Delete the now-duplicated tests**

Remove `test_rewrite_*` (lines ~55-98) from
`tests/rbx/box/packaging/test_polygon_upload_assets.py`, along with the local
`_rewrite` helper. Leave the `_collect_assets` and flat-naming tests alone — Task
6 handles those.

**Step 5: Run both test files**

Run:
```
uv run pytest tests/rbx/box/statements/test_texsoup_utils.py tests/rbx/box/packaging/test_polygon_upload_assets.py -v
```
Expected: PASS, all.

**Step 6: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/statements/texsoup_utils.py rbx/box/packaging/polygon/upload.py \
        tests/rbx/box/statements/test_texsoup_utils.py \
        tests/rbx/box/packaging/test_polygon_upload_assets.py
git commit -m "$(cat <<'EOF'
refactor(statements): move includegraphics rewriting to texsoup_utils

The rewrite is pure LaTeX manipulation with nothing Polygon-specific in
it, and it belongs next to parse_latex, which it already uses.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `ResolvedAsset` and `resolve_assets`

Scope resolution without naming. This is `upload.py:_collect_assets` with the flat
naming lifted out.

**Files:**
- Create: `rbx/box/statements/export.py`
- Create: `tests/rbx/box/statements/test_export_assets.py`

**Step 1: Write the failing test**

Create `tests/rbx/box/statements/test_export_assets.py`. It mirrors the existing
`test_collect_assets_three_scopes` fixture layout so the two can be compared
during the Task 6 port.

```python
"""Unit tests for scope resolution of statement assets (the target-independent
half of what the Polygon upload used to do inline)."""

import pathlib

from rbx.box.statements import export
from rbx.box.statements.schema import Statement


def _statement() -> Statement:
    return Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['extra/logo.png'],
    )


def _build_tree(tmp_path):
    (tmp_path / 'statement' / 'img').mkdir(parents=True)
    (tmp_path / 'statement' / 'img' / 'd.png').touch()
    (tmp_path / 'statement' / 'pic.png').touch()
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()  # source, dropped
    (tmp_path / 'statement' / 'samples').mkdir()
    (tmp_path / 'statement' / 'samples' / '000.in').touch()  # noise, dropped
    (tmp_path / 'extra').mkdir()
    (tmp_path / 'extra' / 'logo.png').touch()  # out-of-tree, via assets

    overlay = tmp_path / 'build' / 'overlay'
    (overlay / '.samples' / '000').mkdir(parents=True)
    (overlay / '.samples' / '000' / 'diagram.png').touch()
    (overlay / '.samples' / '000' / 'in').touch()  # noise, dropped
    return overlay


def test_resolve_assets_tags_every_scope(tmp_path, monkeypatch):
    overlay = _build_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])

    assets = export.resolve_assets(_statement(), {0})

    got = {(a.scope, str(a.rel), a.sample_index) for a in assets}
    assert got == {
        (export.AssetScope.STATEMENT, 'img/d.png', None),
        (export.AssetScope.STATEMENT, 'pic.png', None),
        (export.AssetScope.EXTERNAL, 'extra/logo.png', None),
        (export.AssetScope.SAMPLE, 'diagram.png', 0),
    }
    # Sample I/O and the statement source never leak in.
    assert not any(str(a.rel).endswith(('.in', '.rbx.tex')) for a in assets)


def test_resolve_assets_is_deterministically_sorted(tmp_path, monkeypatch):
    overlay = _build_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])

    first = export.resolve_assets(_statement(), {0})
    second = export.resolve_assets(_statement(), {0})
    assert [a.source for a in first] == [a.source for a in second]


def test_resolve_assets_includes_tikz_relative_to_overlay(tmp_path, monkeypatch):
    overlay = _build_tree(tmp_path)
    tikz = overlay / 'artifacts' / 'tikz_figures'
    tikz.mkdir(parents=True)
    (tikz / 'i_0.pdf').touch()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(
        export,
        'get_produced_tikz_pdfs',
        lambda statement: [(tikz / 'i_0.pdf', pathlib.Path('artifacts/tikz_figures/i_0.pdf'))],
    )

    assets = export.resolve_assets(_statement(), set())
    tikz_assets = [a for a in assets if a.scope == export.AssetScope.TIKZ]
    assert [str(a.rel) for a in tikz_assets] == ['artifacts/tikz_figures/i_0.pdf']


def test_resolve_assets_explicit_asset_under_statement_dir_any_extension(
    tmp_path, monkeypatch
):
    (tmp_path / 'statement').mkdir()
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()
    (tmp_path / 'statement' / 'figure.svg').touch()
    overlay = tmp_path / 'overlay'
    overlay.mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])

    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['statement/figure.svg'],
    )
    assets = export.resolve_assets(statement, set())
    assert [(a.scope, str(a.rel)) for a in assets] == [
        (export.AssetScope.STATEMENT, 'figure.svg')
    ]
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_export_assets.py -v`
Expected: FAIL — `ModuleNotFoundError: rbx.box.statements.export`.

**Step 3: Write `export.py`**

```python
"""Target-independent statement export: resolve a statement's blocks and assets
once, then let a layout decide where they land.

Extracted from the Polygon upload path, which was the only consumer. See
``docs/plans/2026-08-13-statement-export-bundle-design.md``.
"""

import dataclasses
import enum
import pathlib
from typing import List, Optional, Set

from rbx import utils
from rbx.box.statements import sample_staging
from rbx.box.statements.build_statements import (
    get_produced_tikz_pdfs,
    get_statement_dir,
)
from rbx.box.statements.schema import Statement
from rbx.box.statements.texsoup_utils import ASSET_EXTS


class AssetScope(enum.Enum):
    """The directory an asset's reference is relative to. See design §3."""

    STATEMENT = 'statement'  # the statement `file`'s directory
    TIKZ = 'tikz'  # the overlay root
    SAMPLE = 'sample'  # <overlay>/.samples/<idx>/
    EXTERNAL = 'external'  # the package root


@dataclasses.dataclass(frozen=True)
class ResolvedAsset:
    scope: AssetScope
    source: pathlib.Path  # absolute
    rel: pathlib.PurePosixPath  # relative to the scope's reference base
    sample_index: Optional[int] = None  # set iff scope is SAMPLE

    @property
    def ref_key(self) -> str:
        """The extensionless reference a block uses to cite this asset."""
        return str(self.rel.with_suffix(''))


def _resolve_asset_globs(root: pathlib.Path, globs: List[str]) -> List[pathlib.Path]:
    # Moved verbatim from upload.py.
    seen = set()
    for glob in globs:
        for path in root.glob(glob):
            if path.is_file():
                seen.add(utils.abspath(path))
    return sorted(seen)


def _image_files_under(base: pathlib.Path) -> List[pathlib.Path]:
    # Moved verbatim from upload.py.
    if not base.is_dir():
        return []
    return sorted(
        path
        for path in base.rglob('*')
        if path.is_file() and path.suffix.lower() in ASSET_EXTS
    )


def _rel(path: pathlib.Path, base: pathlib.Path) -> pathlib.PurePosixPath:
    return pathlib.PurePosixPath(path.relative_to(base).as_posix())


def resolve_assets(
    statement: Statement, explanation_indices: Set[int]
) -> List[ResolvedAsset]:
    """Every asset the statement ships, tagged with the scope its references are
    relative to. Naming and placement are a layout's job -- this is the same list
    for every target.

    Deduped on absolute source path (an ``assets`` glob may re-name a file the
    image/PDF default already picked up) and deterministically ordered.
    """
    pkg_root = utils.abspath(pathlib.Path())
    statement_dir = (
        utils.abspath(statement.file).parent if statement.file is not None else pkg_root
    )
    overlay = get_statement_dir(statement)

    out: List[ResolvedAsset] = []
    seen: Set[pathlib.Path] = set()

    def add(asset: ResolvedAsset) -> None:
        if asset.source in seen:
            return
        seen.add(asset.source)
        out.append(asset)

    # 1. Statement-scope image/PDF defaults.
    for abs_path in _image_files_under(statement_dir):
        add(
            ResolvedAsset(
                scope=AssetScope.STATEMENT,
                source=abs_path,
                rel=_rel(abs_path, statement_dir),
            )
        )

    # 2. Explicit `assets`: under the statement dir -> statement scope (any
    #    extension); elsewhere -> external scope, referenced package-root
    #    relative (or by bare name when outside the package entirely).
    for abs_path in _resolve_asset_globs(pkg_root, statement.assets):
        if abs_path.is_relative_to(statement_dir):
            add(
                ResolvedAsset(
                    scope=AssetScope.STATEMENT,
                    source=abs_path,
                    rel=_rel(abs_path, statement_dir),
                )
            )
            continue
        try:
            rel = _rel(abs_path, pkg_root)
        except ValueError:
            rel = pathlib.PurePosixPath(abs_path.name)
        add(ResolvedAsset(scope=AssetScope.EXTERNAL, source=abs_path, rel=rel))

    # 3. Externalized TikZ figure PDFs, referenced overlay-relative.
    for abs_path, overlay_rel in get_produced_tikz_pdfs(statement):
        add(
            ResolvedAsset(
                scope=AssetScope.TIKZ,
                source=abs_path,
                rel=pathlib.PurePosixPath(pathlib.Path(overlay_rel).as_posix()),
            )
        )

    # 4. Per-sample scope: image/PDF under each staged .samples/<idx>/.
    for idx in sorted(explanation_indices):
        base = overlay / sample_staging.SAMPLES_DIRNAME / f'{idx:03d}'
        for abs_path in _image_files_under(base):
            add(
                ResolvedAsset(
                    scope=AssetScope.SAMPLE,
                    source=abs_path,
                    rel=_rel(abs_path, base),
                    sample_index=idx,
                )
            )

    return out
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/test_export_assets.py -v`
Expected: PASS.

**Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/statements/export.py tests/rbx/box/statements/test_export_assets.py
git commit -m "$(cat <<'EOF'
feat(statements): resolve statement assets into reference scopes

Naming an asset's reference base -- statement dir, overlay, sample dir,
package root -- is what makes the same asset list serve an uploader and
a tarball writer.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Layouts and the derived remap

The heart of the design. Read §4 of the design doc, **including the extension
caveat**, before writing this.

**Files:**
- Modify: `rbx/box/statements/export.py`
- Create: `tests/rbx/box/statements/test_export_layout.py`

**Step 1: Write the failing test**

```python
"""Layouts decide where assets and documents land; the reference remap is derived
from those two placements, never configured."""

import pathlib

import pytest

from rbx.box.statements import export
from rbx.box.statements.export import AssetScope, DocumentSlot, ResolvedAsset


def _asset(scope, rel, sample_index=None):
    return ResolvedAsset(
        scope=scope,
        source=pathlib.Path('/nowhere') / rel,
        rel=pathlib.PurePosixPath(rel),
        sample_index=sample_index,
    )


STATEMENT_ASSET = _asset(AssetScope.STATEMENT, 'img/d.png')
ROOT_ASSET = _asset(AssetScope.STATEMENT, 'pic.png')
TIKZ_ASSET = _asset(AssetScope.TIKZ, 'artifacts/tikz_figures/i_0.pdf')
SAMPLE_ASSET = _asset(AssetScope.SAMPLE, 'diagram.png', sample_index=0)
EXTERNAL_ASSET = _asset(AssetScope.EXTERNAL, 'extra/logo.png')

ALL = [STATEMENT_ASSET, ROOT_ASSET, TIKZ_ASSET, SAMPLE_ASSET, EXTERNAL_ASSET]


# --- FlatLayout: one root, no directories (Polygon) -------------------------


def test_flat_layout_places_everything_at_the_root():
    layout = export.FlatLayout()
    assert str(layout.place_asset(STATEMENT_ASSET)) == 'img__d.png'
    assert str(layout.place_asset(ROOT_ASSET)) == 'pic.png'
    assert (
        str(layout.place_asset(TIKZ_ASSET))
        == 'artifacts__tikz_figures__i_0.pdf'
    )
    assert str(layout.place_asset(EXTERNAL_ASSET)) == 'extra__logo.png'


def test_flat_layout_namespaces_sample_assets_by_index():
    layout = export.FlatLayout()
    assert str(layout.place_asset(SAMPLE_ASSET)) == 'sample_0__diagram.png'


def test_flat_layout_puts_every_document_at_the_root():
    layout = export.FlatLayout()
    assert str(layout.document_dir(DocumentSlot.body())) == '.'
    assert str(layout.document_dir(DocumentSlot.sample(0))) == '.'


def test_flat_layout_remap_rewrites_every_reference():
    layout = export.FlatLayout()
    remap = export.derive_remap(ALL, layout, DocumentSlot.body())
    assert remap == {
        'img/d': 'img__d.png',
        'pic': 'pic.png',
        'artifacts/tikz_figures/i_0': 'artifacts__tikz_figures__i_0.pdf',
        'extra/logo': 'extra__logo.png',
    }


def test_flat_layout_sample_slot_sees_statement_and_own_sample_assets():
    layout = export.FlatLayout()
    remap = export.derive_remap(ALL, layout, DocumentSlot.sample(0))
    assert remap['diagram'] == 'sample_0__diagram.png'
    assert remap['img/d'] == 'img__d.png'


def test_sample_slot_ignores_other_samples():
    other = _asset(AssetScope.SAMPLE, 'diagram.png', sample_index=1)
    remap = export.derive_remap(
        [SAMPLE_ASSET, other], export.FlatLayout(), DocumentSlot.sample(0)
    )
    assert remap == {'diagram': 'sample_0__diagram.png'}


def test_body_slot_never_sees_sample_assets():
    remap = export.derive_remap([SAMPLE_ASSET], export.FlatLayout(), DocumentSlot.body())
    assert remap == {}


# --- SubtreeLayout: directories, several roots (MOJ) ------------------------


def _moj_layout(**kwargs):
    return export.SubtreeLayout(
        asset_roots={
            AssetScope.STATEMENT: 'docs',
            AssetScope.TIKZ: 'docs',
            AssetScope.EXTERNAL: 'docs',
            AssetScope.SAMPLE: 'docs/notes/{index:03d}',
        },
        document_dirs={
            'body': 'docs',
            'sample_explanation': 'docs/notes/{index:03d}',
        },
        **kwargs,
    )


def test_subtree_layout_preserves_the_tree_under_its_root():
    layout = _moj_layout()
    assert str(layout.place_asset(STATEMENT_ASSET)) == 'docs/img/d.png'
    assert str(layout.place_asset(SAMPLE_ASSET)) == 'docs/notes/000/diagram.png'


def test_subtree_layout_documents_can_live_in_different_roots():
    layout = _moj_layout()
    assert str(layout.document_dir(DocumentSlot.body())) == 'docs'
    assert str(layout.document_dir(DocumentSlot.sample(0))) == 'docs/notes/000'


def test_subtree_layout_without_extensions_needs_no_rewriting():
    # The identity case: derived reference == authored reference, so the entry
    # drops out of the remap entirely.
    layout = _moj_layout(keep_extension=False)
    assert export.derive_remap(ALL, layout, DocumentSlot.body()) == {}


def test_subtree_layout_keeping_extensions_rewrites_only_the_extension():
    layout = _moj_layout(keep_extension=True)
    remap = export.derive_remap(ALL, layout, DocumentSlot.body())
    assert remap['img/d'] == 'img/d.png'
    assert remap['extra/logo'] == 'extra/logo.png'


def test_subtree_layout_sample_reference_is_relative_to_the_explanation():
    layout = _moj_layout(keep_extension=False)
    # The explanation lives in the same dir as its own images -> identity...
    assert export.derive_remap([SAMPLE_ASSET], layout, DocumentSlot.sample(0)) == {}
    # ...but a statement-dir image cited from an explanation must climb out.
    remap = export.derive_remap([STATEMENT_ASSET], layout, DocumentSlot.sample(0))
    assert remap == {'img/d': '../../img/d'}


def test_sample_scope_root_requires_an_index_placeholder():
    with pytest.raises(ValueError):
        export.SubtreeLayout(
            asset_roots={AssetScope.SAMPLE: 'docs/notes'},
            document_dirs={},
        ).place_asset(SAMPLE_ASSET)
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_export_layout.py -v`
Expected: FAIL — `AttributeError: module 'rbx.box.statements.export' has no attribute 'DocumentSlot'`.

**Step 3: Implement**

Append to `rbx/box/statements/export.py`:

```python
class DocumentSlot(NamedTuple):
    """Where a piece of referencing text will end up. The remap is derived per
    slot, because a reference's meaning depends on where the text sits."""

    kind: Literal['body', 'sample_explanation']
    index: Optional[int] = None

    @classmethod
    def body(cls) -> 'DocumentSlot':
        return cls(kind='body')

    @classmethod
    def sample(cls, index: int) -> 'DocumentSlot':
        return cls(kind='sample_explanation', index=index)


class AssetLayout(Protocol):
    """Decides where assets and documents land. Both answers are *paths*, so a
    layout with several roots needs no extra concept -- see design §4."""

    keep_extension: bool

    def place_asset(self, asset: ResolvedAsset) -> pathlib.PurePosixPath: ...

    def document_dir(self, slot: DocumentSlot) -> pathlib.PurePosixPath: ...


@dataclasses.dataclass(frozen=True)
class FlatLayout:
    """One root, no directories: subdirectory separators collapse to ``sep`` and
    sample assets are namespaced by index. This is Polygon, which has a single
    statement definition (hence one root) and no directory support (hence flat
    names) -- two independent facts that this layout happens to combine.

    ``keep_extension`` is fixed True: the flat name IS the uploaded resource
    name, so a reference without it would not resolve.
    """

    sep: str = '__'
    keep_extension: bool = dataclasses.field(default=True, init=False)

    def place_asset(self, asset: ResolvedAsset) -> pathlib.PurePosixPath:
        flat = str(asset.rel).replace('/', self.sep)
        if asset.scope == AssetScope.SAMPLE:
            flat = f'sample_{asset.sample_index}{self.sep}{flat}'
        return pathlib.PurePosixPath(flat)

    def document_dir(self, slot: DocumentSlot) -> pathlib.PurePosixPath:
        return pathlib.PurePosixPath('.')


@dataclasses.dataclass(frozen=True)
class SubtreeLayout:
    """Directories preserved under a per-scope root, with documents free to live
    in roots of their own -- the shape a tarball judge such as MOJ needs, where
    the statement is ``docs/enunciado.md`` and sample notes ship elsewhere.

    Roots are format strings; ``{index}`` (the sample index) is available to the
    SAMPLE scope and the sample_explanation slot, and is REQUIRED there.

    ``keep_extension=False`` yields references identical to the authored ones, so
    the remap comes out empty and no block is rewritten.
    """

    asset_roots: Dict[AssetScope, str] = dataclasses.field(default_factory=dict)
    document_dirs: Dict[str, str] = dataclasses.field(default_factory=dict)
    keep_extension: bool = True

    def _format(self, template: str, index: Optional[int], what: str) -> str:
        try:
            return template.format(index=index)
        except (KeyError, IndexError) as e:
            raise ValueError(f'Invalid placeholder in {what} root {template!r}.') from e

    def place_asset(self, asset: ResolvedAsset) -> pathlib.PurePosixPath:
        root = self.asset_roots.get(asset.scope, '')
        if asset.scope == AssetScope.SAMPLE and '{index' not in root:
            raise ValueError(
                'The SAMPLE asset root must carry an {index} placeholder, '
                'otherwise assets from different samples collide; '
                f'got {root!r}.'
            )
        root = self._format(root, asset.sample_index, asset.scope.value)
        return pathlib.PurePosixPath(root) / asset.rel if root else asset.rel

    def document_dir(self, slot: DocumentSlot) -> pathlib.PurePosixPath:
        template = self.document_dirs.get(slot.kind, '')
        return pathlib.PurePosixPath(self._format(template, slot.index, slot.kind) or '.')


def _slot_sees(asset: ResolvedAsset, slot: DocumentSlot) -> bool:
    """Body text sees everything but sample assets; an explanation additionally
    sees its OWN sample's assets."""
    if asset.scope != AssetScope.SAMPLE:
        return True
    return slot.kind == 'sample_explanation' and asset.sample_index == slot.index


def derive_remap(
    assets: Iterable[ResolvedAsset], layout: AssetLayout, slot: DocumentSlot
) -> Dict[str, str]:
    """The reference rewrites a document in ``slot`` needs, derived from where the
    layout put things: an asset's new reference is its placement seen from the
    document's directory.

    Entries whose derived reference already equals the authored one are dropped,
    which is what makes rewriting optional: an identity-preserving layout yields
    an empty remap and every block comes back untouched.

    Sample-scope entries are added last so they win a key collision with a
    statement-scope asset of the same name.
    """
    doc_dir = layout.document_dir(slot)
    remap: Dict[str, str] = {}
    ordered = sorted(assets, key=lambda a: a.scope == AssetScope.SAMPLE)
    for asset in ordered:
        if not _slot_sees(asset, slot):
            continue
        dest = layout.place_asset(asset)
        if not layout.keep_extension:
            dest = dest.with_suffix('')
        ref = posixpath.relpath(str(dest), str(doc_dir))
        if ref == asset.ref_key:
            continue
        remap[asset.ref_key] = ref
    return remap
```

Add the imports this needs at the top of the file: `posixpath`, and from
`typing`: `Dict`, `Iterable`, `Literal`, `NamedTuple`, `Protocol`.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/test_export_layout.py -v`
Expected: PASS.

If `test_subtree_layout_sample_reference_is_relative_to_the_explanation` fails on
the expected `'../../img/d'`, work the arithmetic by hand rather than editing the
expectation to match the output: the asset is at `docs/img/d`, the document dir is
`docs/notes/000`, so climbing two levels and descending into `img` is correct.

**Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/statements/export.py tests/rbx/box/statements/test_export_layout.py
git commit -m "$(cat <<'EOF'
feat(statements): derive asset reference remaps from a layout

A layout places assets and documents as paths; the remap follows from
the two placements. An identity-preserving layout therefore yields an
empty remap, which is how remapping becomes optional without a flag.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Move the block pipeline into `export.py`

`get_substituted_statement_blocks` / `get_processed_statement_blocks` reach down
into `statements/` for everything they do; they belong there, with the Polygon-TeX
tail behind a parameter.

**Files:**
- Modify: `rbx/box/statements/export.py`
- Modify: `rbx/box/packaging/polygon/statement_block_utils.py`
- Modify: `tests/rbx/box/statements/test_polygon_export.py` (imports only)

**Step 1: Move the two functions**

Cut both from `statement_block_utils.py` into `export.py`, with one change to
`get_processed_statement_blocks`:

```python
def get_processed_statement_blocks(
    statement: Statement, normalize: bool = True
) -> StatementBlocks:
    """Read the built blocks, expand and filter macros, and (by default) convert
    to Polygon TeX.

    ``normalize`` controls only that last conversion. It defaults on because the
    Polygon subset is the well-behaved one -- it is what pandoc and browser TeX
    renderers handle cleanly -- but a consumer wanting the raw macro-expanded TeX
    can turn it off.
    """
```

Guard the two conversion loops with `if normalize:` and gate the debug dump on
the same. Rename the debug output directory from `polygon` to `export`, since the
blocks are no longer necessarily Polygon's:

```python
    statement_dir = overlay_dir / 'export'
```

In `statement_block_utils.py`, keep thin re-exports so `validate_statements` and
any other caller keep working:

```python
from rbx.box.statements.export import (  # noqa: F401
    get_processed_statement_blocks,
    get_substituted_statement_blocks,
)
```

**Step 2: Fix the test imports**

`tests/rbx/box/statements/test_polygon_export.py` imports these from
`statement_block_utils`. Point it at `rbx.box.statements.export` instead. Do not
change any assertion.

**Step 3: Add a test for the new parameter**

Append to `tests/rbx/box/statements/test_polygon_export.py` a case asserting that
`normalize=False` leaves a construct that `convert_to_polygon_tex` would have
rewritten. Pick one from the existing tests in that file — read them first and
mirror their fixture setup rather than inventing a new one.

**Step 4: Run the statements suite**

Run: `uv run pytest tests/rbx/box/statements/ -v`
Expected: PASS. A failure mentioning the `polygon/` debug directory means
something asserts on that path — update it to `export/`.

**Step 5: Run the packaging suite for regressions**

Run: `uv run pytest tests/rbx/box/packaging/ -v`
Expected: PASS.

**Step 6: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/statements/export.py rbx/box/packaging/polygon/statement_block_utils.py \
        tests/rbx/box/statements/test_polygon_export.py
git commit -m "$(cat <<'EOF'
refactor(statements): move the block pipeline out of the polygon package

Macro expansion and block reading were never Polygon's; only the final
TeX conversion is, and it becomes a parameter that stays on by default.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `StatementBundle` and `build_statement_bundle`

**Files:**
- Modify: `rbx/box/statements/export.py`
- Create: `tests/rbx/box/statements/test_export_bundle.py`

**Step 1: Write the failing test**

```python
"""The bundle: blocks rewritten for a layout, assets placed, materializable."""

import pathlib

from rbx.box.statements import export
from rbx.box.statements.export import AssetScope, DocumentSlot
from rbx.box.statements.render import StatementBlocks
from rbx.box.statements.schema import Statement


def _setup(tmp_path, monkeypatch):
    (tmp_path / 'statement' / 'img').mkdir(parents=True)
    (tmp_path / 'statement' / 'img' / 'd.png').write_bytes(b'PNGDATA')
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()
    overlay = tmp_path / 'overlay'
    (overlay / '.samples' / '000').mkdir(parents=True)
    (overlay / '.samples' / '000' / 'diagram.png').write_bytes(b'SAMPLEDATA')

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])
    monkeypatch.setattr(
        export,
        'get_processed_statement_blocks',
        lambda statement, normalize=True: StatementBlocks(
            blocks={'legend': r'\includegraphics{img/d}'},
            explanations={0: r'\includegraphics{diagram}'},
        ),
    )
    return Statement(
        language='en', file=pathlib.Path('statement/statement.rbx.tex')
    )


def test_bundle_rewrites_blocks_and_explanations_for_a_flat_layout(
    tmp_path, monkeypatch
):
    statement = _setup(tmp_path, monkeypatch)
    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())

    assert bundle.blocks['legend'] == r'\includegraphics{img__d.png}'
    assert bundle.explanations[0] == r'\includegraphics{sample_0__diagram.png}'
    assert {str(a.dest) for a in bundle.assets} == {
        'img__d.png',
        'sample_0__diagram.png',
    }


def test_bundle_leaves_blocks_untouched_under_an_identity_layout(
    tmp_path, monkeypatch
):
    statement = _setup(tmp_path, monkeypatch)
    layout = export.SubtreeLayout(
        asset_roots={
            AssetScope.STATEMENT: 'docs',
            AssetScope.SAMPLE: 'docs/notes/{index:03d}',
        },
        document_dirs={'body': 'docs', 'sample_explanation': 'docs/notes/{index:03d}'},
        keep_extension=False,
    )
    bundle = export.build_statement_bundle(statement, layout=layout)

    assert bundle.blocks['legend'] == r'\includegraphics{img/d}'
    assert bundle.explanations[0] == r'\includegraphics{diagram}'
    assert bundle.remaps[DocumentSlot.body()] == {}


def test_bundle_materializes_into_a_multi_root_tree(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    layout = export.SubtreeLayout(
        asset_roots={
            AssetScope.STATEMENT: 'docs',
            AssetScope.SAMPLE: 'docs/notes/{index:03d}',
        },
        document_dirs={'body': 'docs', 'sample_explanation': 'docs/notes/{index:03d}'},
    )
    bundle = export.build_statement_bundle(statement, layout=layout)

    into = tmp_path / 'out'
    bundle.materialize(into)

    assert (into / 'docs' / 'img' / 'd.png').read_bytes() == b'PNGDATA'
    assert (
        into / 'docs' / 'notes' / '000' / 'diagram.png'
    ).read_bytes() == b'SAMPLEDATA'


def test_bundled_asset_exposes_content_without_materializing(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())
    by_dest = {str(a.dest): a for a in bundle.assets}
    assert by_dest['img__d.png'].content == b'PNGDATA'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_export_bundle.py -v`
Expected: FAIL — no `build_statement_bundle`.

**Step 3: Implement**

```python
@dataclasses.dataclass(frozen=True)
class BundledAsset:
    asset: ResolvedAsset
    dest: pathlib.PurePosixPath

    @property
    def content(self) -> bytes:
        return self.asset.source.read_bytes()


@dataclasses.dataclass
class StatementBundle:
    """A statement's blocks and assets, resolved for one target.

    An uploader reads ``assets[i].content`` and never materializes; a tarball
    packager calls ``materialize`` and never touches ``content``. Both get the
    same rewritten blocks. Deliberately mirrors ``flattening.FlatNamespace``,
    which solves the same problem for source files.
    """

    blocks: Dict[str, str]
    explanations: Dict[int, str]
    assets: List[BundledAsset]
    remaps: Dict[DocumentSlot, Dict[str, str]]

    def materialize(self, root: pathlib.Path) -> None:
        for bundled in self.assets:
            target = root / bundled.dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundled.content)


def build_statement_bundle(
    statement: Statement,
    *,
    layout: AssetLayout,
    normalize: bool = True,
) -> StatementBundle:
    """Resolve ``statement`` into blocks + placed assets for one target."""
    processed = get_processed_statement_blocks(statement, normalize=normalize)
    assets = resolve_assets(statement, set(processed.explanations))

    body_slot = DocumentSlot.body()
    remaps = {body_slot: derive_remap(assets, layout, body_slot)}
    for idx in processed.explanations:
        slot = DocumentSlot.sample(idx)
        remaps[slot] = derive_remap(assets, layout, slot)

    return StatementBundle(
        blocks={
            name: rewrite_includegraphics(content, remaps[body_slot])
            for name, content in processed.blocks.items()
        },
        explanations={
            idx: rewrite_includegraphics(text, remaps[DocumentSlot.sample(idx)])
            for idx, text in processed.explanations.items()
        },
        assets=[
            BundledAsset(asset=asset, dest=layout.place_asset(asset))
            for asset in assets
        ],
        remaps=remaps,
    )
```

Import `rewrite_includegraphics` from `texsoup_utils` at the top of `export.py`.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/test_export_bundle.py -v`
Expected: PASS.

**Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/statements/export.py tests/rbx/box/statements/test_export_bundle.py
git commit -m "$(cat <<'EOF'
feat(statements): add StatementBundle for target-independent export

Mirrors flattening.FlatNamespace: an uploader reads bytes, a tarball
packager materializes, and both get the same rewritten blocks.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Port `upload.py` onto the bundle

The behavior-preservation task. `_collect_assets`, `_flat_name`, `_remap_key`,
`_resolve_asset_globs`, `_image_files_under`, `_ASSET_EXTS` and `_AssetRemaps` all
disappear from `upload.py`.

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py:598-845`
- Modify: `tests/rbx/box/packaging/test_polygon_upload_assets.py`

**Step 1: Rewrite the resource upload against the bundle**

```python
def _upload_statement_resources(
    problem: api.Problem, bundle: export.StatementBundle
) -> None:
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for bundled in sorted(bundle.assets, key=lambda a: str(a.dest)):
            flat_name = str(bundled.dest)
            console.console.print(
                f'Uploading statement resource [item]{flat_name}[/item]...'
            )
            resource_bytes = bundled.content
            if len(resource_bytes) >= 1024 * 1024:  # >= 1mb
                console.console.print(
                    f'[error]Statement resource [item]{flat_name}[/item] is too large to upload (more than 1MB).[/error]'
                )
                raise typer.Exit(1)
            futures.append(
                executor.submit(
                    problem.save_statement_resource,
                    name=flat_name,
                    file=resource_bytes,
                )
            )
        for future in futures:
            future.result()
```

`process_statement` in `_upload_statement` becomes:

```python
    def process_statement(statement: Statement, language: str, uploaded_language: str):
        console.console.print(
            f'Uploading statement for language [item]{language}[/item] (uploaded language: [item]{uploaded_language}[/item])...'
        )
        bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())
        _upload_statement_resources(problem, bundle)

        def _get_block(block_name: str) -> str:
            return bundle.blocks.get(block_name) or ''

        def _get_notes_with_explanations() -> Optional[str]:
            notes = _get_block('notes')
            if not notes and not bundle.explanations:
                return None
            res = _get_explanations(bundle.explanations)
            if notes:
                res = notes + '\n\n' + res
            return res

        ...  # api.Statement construction unchanged
```

The blocks arrive already rewritten, so `_rewrite_includegraphics`, the closure
default-argument bindings and the explanation remap merge all go away — the merge
is now `derive_remap`'s sample-wins-on-collision ordering.

Delete the dead helpers and their now-unused imports (`sample_staging`,
`get_produced_tikz_pdfs`, `get_statement_dir`, `BraceGroup`, `BracketGroup`,
`parse_latex`, `dataclasses` if unused, `Tuple` if unused). Add:

```python
from rbx.box.statements import export
```

Keep `get_processed_statement_blocks` imported only if something else in the file
still uses it; the bundle calls it internally now.

**Step 2: Rewrite the assets test onto the bundle**

`tests/rbx/box/packaging/test_polygon_upload_assets.py` currently asserts on
deleted private helpers. Replace its remaining tests with two that assert the
Polygon *outcome* through the public API — this is the port guard:

```python
"""The Polygon upload's statement resources, asserted through the bundle it now
uses. Guards that the extraction did not change what reaches Polygon."""

import pathlib

from rbx.box.statements import export
from rbx.box.statements.render import StatementBlocks
from rbx.box.statements.schema import Statement


def test_polygon_bundle_reproduces_the_expected_flat_resource_set(
    tmp_path, monkeypatch
):
    (tmp_path / 'statement' / 'img').mkdir(parents=True)
    (tmp_path / 'statement' / 'img' / 'd.png').touch()
    (tmp_path / 'statement' / 'pic.png').touch()
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()
    (tmp_path / 'statement' / 'samples').mkdir()
    (tmp_path / 'statement' / 'samples' / '000.in').touch()
    (tmp_path / 'extra').mkdir()
    (tmp_path / 'extra' / 'logo.png').touch()

    overlay = tmp_path / 'build' / 'overlay'
    (overlay / '.samples' / '000').mkdir(parents=True)
    (overlay / '.samples' / '000' / 'diagram.png').touch()
    (overlay / '.samples' / '000' / 'in').touch()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])
    monkeypatch.setattr(
        export,
        'get_processed_statement_blocks',
        lambda statement, normalize=True: StatementBlocks(
            blocks={}, explanations={0: ''}
        ),
    )

    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['extra/logo.png'],
    )
    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())

    assert {str(a.dest) for a in bundle.assets} == {
        'img__d.png',
        'pic.png',
        'extra__logo.png',
        'sample_0__diagram.png',
    }
    # No sample I/O or statement source leaks in (finding #5).
    assert not any(str(a.dest).endswith(('.in', '.rbx.tex')) for a in bundle.assets)
```

**Note the deliberate behavior change (design §7):** the old test asserted
out-of-tree assets are **not** remapped. They now are — `extra/logo` →
`extra__logo.png`. Uploaded bytes are unchanged; the only reference whose meaning
changes is one that is broken today. Add a test pinning the new behavior:

```python
def test_out_of_tree_assets_are_now_remapped(tmp_path, monkeypatch):
    # Design §7: previously the author had to spell the flat name by hand.
    ...  # same fixture as above
    assert bundle.remaps[export.DocumentSlot.body()]['extra/logo'] == 'extra__logo.png'
```

**Step 3: Run the packaging and statements suites**

Run: `uv run pytest tests/rbx/box/packaging/ tests/rbx/box/statements/ -v`
Expected: PASS.

**Step 4: Verify nothing still references the deleted helpers**

Run: `grep -rn '_collect_assets\|_AssetRemaps\|_flat_name\|_remap_key\|_image_files_under\|_rewrite_includegraphics' rbx/ tests/`
Expected: no output.

**Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/packaging/polygon/upload.py tests/rbx/box/packaging/test_polygon_upload_assets.py
git commit -m "$(cat <<'EOF'
refactor(polygon): upload statements through the export bundle

upload.py keeps the API client, the language selection and the Polygon
notes assembly; everything else is now shared. Out-of-tree assets gain a
reference remap they lacked, which can only fix a reference that was
already broken.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Document the seam

**Files:**
- Modify: `rbx/box/packaging/packager.py:86-90`
- Modify: `rbx/box/packaging/CLAUDE.md:59-66`
- Modify: `rbx/box/statements/CLAUDE.md` (the "Polygon export" section)

**Step 1: Promote `statement_export_params` to a contract**

Rewrite the docstring so a future packager knows opting in is how it gets blocks:

```python
    def statement_export_params(self) -> List[ConversionStep]:
        """Packager-forced statement conversion toggles applied at export time
        (design §2 decision 6: externalize/demacro are not user schema).

        Returning the externalize+demacro steps is how a packager declares "I
        consume statement *blocks*, not a PDF": the forced build is what writes
        the ``blocks.sub.yml`` / ``macros.json`` / externalized TikZ PDFs that
        ``rbx.box.statements.export.build_statement_bundle`` reads. A packager
        that ships a PDF wants the default, which is none.
        """
        return []
```

**Step 2: Update `packaging/CLAUDE.md`**

Rewrite the Polygon "Statement upload" bullet to point at the shared module, and
add a short subsection under **Base Abstractions** describing the export bundle —
including that `SubtreeLayout` exists for tarball judges but has no consumer yet.
Keep the issue references (#568, #583, #595, #590) intact.

**Step 3: Update `statements/CLAUDE.md`**

In the "Polygon export (S12, #568)" section, note that the block pipeline and
asset resolution now live in `export.py`, that `statement_block_utils` keeps thin
re-exports, and that the debug dump moved from `<overlay>/polygon/` to
`<overlay>/export/`.

**Step 4: Verify the docs build**

Run: `uv run mkdocs build 2>&1 | tail -20`
Expected: the ~9 pre-existing unrelated warnings, no new ones. (`--strict` fails
on `main` for unrelated reasons — do not use it.)

**Step 5: Commit**

```bash
git add rbx/box/packaging/packager.py rbx/box/packaging/CLAUDE.md rbx/box/statements/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(packaging): document the statement export seam

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Full verification

**Step 1: Run the affected suites**

Run: `uv run pytest tests/rbx/box/statements/ tests/rbx/box/packaging/ -n auto`
Expected: PASS.

**Step 2: Run the wider suite**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: only the known-bad C++/sandbox/docker failures. Compare against `main`
if anything looks new — do not assume a failure is pre-existing without checking.

**Step 3: Lint clean**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no findings.

**Step 4: Real-package smoke test**

Build and upload-validate a package that actually has statement images, to
exercise the path end to end rather than through monkeypatched fixtures:

```bash
uv run rbx package polygon --help
```

then, inside a test package with images (see `tests/e2e/` fixtures), run the
statement validation path. If `POLYGON_API_KEY`/`POLYGON_API_SECRET` are set, a
statements-only upload (`--upload --upload-only statements`) against a scratch
Polygon problem is the strongest available check that resource names and rewritten
references still line up.

---

## Notes for the implementer

- **Do not "fix" a failing expectation by copying the actual output into the
  test.** Every expected value in this plan was derived from the design; if the
  code disagrees, one of them is wrong and it is worth ten seconds to find out
  which.
- **`resolve_assets` dedupes on absolute source path.** An `assets` glob naming a
  file the image/PDF default already picked up must not ship twice.
- **Sample assets must win reference collisions** with statement-scope assets of
  the same name, matching today's `{**statement, **sample}` merge.
- **The `{index}` placeholder in `SubtreeLayout`'s SAMPLE root is required**, not
  optional — without it, two samples with an `img.png` each collide silently.
