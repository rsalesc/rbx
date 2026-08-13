# Statement export bundle — design

**Date:** 2026-08-13
**Status:** approved, pending implementation
**Issue:** extract the reusable core of the Polygon statement upload so other
judges — including ones with no upload API, that merely produce a tarball — can
consume statement blocks and their assets.

## 1. The problem

`rbx/box/packaging/polygon/upload.py` grew a complete statement-export pipeline:
it reads the v2 overlay's `blocks.sub.yml` + `macros.json`, expands and filters
macros, converts to Polygon TeX, resolves the statement's asset set across four
different scopes, assigns each asset an uploaded name, and rewrites every
`\includegraphics` reference to match.

Only three things in that pipeline are actually Polygon's:

1. the **naming policy** (flat names, because Polygon has no directories),
2. the **single root** (Polygon has one statement definition and resolves every
   resource from one place),
3. the **sink** (a signed HTTP call, rather than files on disk).

Everything else — scope resolution, macro expansion, TikZ figure collection,
reference rewriting — is target-independent and currently unreachable from any
other packager. The MOJ packager writes a dummy `docs/enunciado.md` today; a real
MOJ statement needs exactly this machinery, arranged differently.

> **Note.** This design was written while that packager lived as `moj_next`
> beside a legacy `moj`. #641 replaced the legacy one outright, so it is now
> `rbx/box/packaging/moj/` (`rbx package moj`). Nothing about the design changes —
> the dummy `enunciado.md` and the mandatory `## Entrada` / `## Saída` shape are
> unaffected by the rename.

### The correction that shapes the design

Flat naming and single-root are **orthogonal**, and conflating them is why the
current code cannot be reused. Polygon flattens because it has no directories;
it uses one root because it has one statement definition. MOJ has directories
*and* more than one root: `docs/enunciado.{md,org,tex}` is the statement, and
sample notes ship in a different directory. A design that offers only
"flat or not" cannot express MOJ.

## 2. Scope of this effort

**In scope:** extract the API, port the Polygon upload onto it with unchanged
output, land it.

**Out of scope, deliberately:**

- **The real MOJ statement.** It becomes a follow-up that *consumes* this
  API. Keeping the refactor and the feature separate keeps both reviewable, and
  the feature has its own open questions (heading mapping to the mandatory
  `## Entrada` / `## Saída`, MOJ's injection of samples from `tests/input/sample*`,
  the `render_warnings` fenced-code heuristic).
- **TeX → markdown conversion.** The bundle stops at TeX. Polygon TeX is a good
  pandoc input, but adding pandoc is a hard external dependency on the packaging
  path and belongs to whichever consumer first needs markdown.
- **Offline Polygon `problem.zip` statement embedding (#583).** It becomes a
  natural second consumer of `materialize()`, but is not part of this change.

## 3. The asset model: a scope is a reference base

Every statement asset is resolved against some directory, and that directory is
precisely what its `\includegraphics` reference is relative to. Naming the
directory names the scope:

| Scope | Reference base | Source | Example reference |
|---|---|---|---|
| `STATEMENT` | the statement `file`'s directory | image/PDF under that dir, plus `assets` globs falling under it (any extension) | `img/fig` |
| `TIKZ` | the overlay root (`get_statement_dir`) | `artifacts/tikz_figures/**/*.pdf` from the forced-externalize build | `artifacts/tikz_figures/i_0` |
| `SAMPLE(idx)` | `<overlay>/.samples/<idx>/` | image/PDF under that staged folder | `diagram` |
| `EXTERNAL` | the package root | `assets` globs outside the statement dir | — (see §7) |

```python
@dataclasses.dataclass(frozen=True)
class ResolvedAsset:
    scope: AssetScope          # STATEMENT | TIKZ | SAMPLE | EXTERNAL
    sample_index: Optional[int]  # set iff scope is SAMPLE
    source: pathlib.Path       # absolute path on disk
    rel: pathlib.PurePosixPath # relative to the scope's reference base
```

`resolve_assets(statement, explanation_indices) -> List[ResolvedAsset]` is
`upload.py:_collect_assets` with the naming step removed. It is pure with
respect to any target: the same list serves an uploader and a tarball writer.

The **reference key** for an asset is `rel` with its extension dropped —
`\includegraphics` is conventionally extensionless, which is why
`_remap_key`/`_strip_asset_ext` exist today. That stays, unchanged, in the
shared layer.

## 4. `AssetLayout` answers two questions

A layout decides where an asset lands **and** where the text that references it
lands. Without the second question, multiple roots are inexpressible.

```python
class DocumentSlot(NamedTuple):
    kind: Literal['body', 'sample_explanation']
    index: Optional[int]        # set for sample_explanation

class AssetLayout(Protocol):
    def place_asset(self, asset: ResolvedAsset) -> pathlib.PurePosixPath: ...
    def document_dir(self, slot: DocumentSlot) -> pathlib.PurePosixPath: ...
```

Both return **paths**, not names. `materialize(root)` writes `root / dest`, so a
layout that returns `docs/img/fig.png` and `docs/notes/003/diagram.png` produces
two roots through one mechanism, with no extra concept.

### The remap is derived, never configured

An asset's new reference is:

```
relpath(place_asset(asset), document_dir(slot))
```

for each slot whose text may cite it. That single rule reproduces both targets:

- **Polygon** — `FlatLayout`: every scope collapses to the root with `/` → `__`,
  `SAMPLE(idx)` assets prefixed `sample_<idx>__`; every document sits at the
  root. The derived reference is the flat name, so every reference is rewritten
  — byte-identical to today's behavior.
- **MOJ** — `SubtreeLayout` binding `STATEMENT` → `docs/`, `SAMPLE(idx)` →
  `docs/notes/<idx>/`, with `body` → `docs/` and `sample_explanation(idx)` →
  `docs/notes/<idx>/`. `docs/img/fig.png` referenced from a document in `docs/`
  derives back to `img/fig` — **identical to the authored reference**, so the
  remap for that asset is empty and nothing is rewritten.

This is what makes remapping optional without a flag: an identity-preserving
layout simply produces nothing to remap. `_rewrite_includegraphics` already
returns its input untouched on an empty remap, so the TexSoup pass costs nothing
in that case. No `rewrite=False` knob is added — it could only ever mean "place
the assets somewhere the references do not point," which is a bug, not an
option.

#### The extension caveat

Reference *keys* are extensionless (`\includegraphics` is conventionally spelled
without one, which is why the lookup strips extensions today), but a derived
reference is a real path and carries its extension. So `relpath` alone does not
reach identity: `docs/img/d.png` seen from `docs/` derives to `img/d.png`, which
differs from the key `img/d` and would be rewritten.

A layout therefore also declares whether the derived reference keeps its
extension:

- `FlatLayout` **must** keep it — the flat name *is* the uploaded Polygon
  resource name (`img__d.png`), and dropping it would break the reference.
- `SubtreeLayout(keep_extension=...)` chooses. `False` yields `img/d`, equal to
  the key, so the entry drops out of the remap and nothing is rewritten — the
  true identity case. `True` yields `img/d.png`, which is harmless in TeX and
  *required* by markdown, at the cost of a rewrite pass.

The default is `True`, since an explicit extension is valid in every target;
`False` is the opt-in for consumers that want the blocks returned untouched.

`keep_extension=False` is necessary but **not sufficient** for identity. The
derived reference is `relpath(asset_dest, document_dir)`, so it equals the
authored one only when the asset's root and its document's root are the same
directory — formally, when `asset_roots[scope] == document_dirs[slot.kind]` for
that pair. The MOJ binding reaches identity because it maps STATEMENT, TIKZ and
EXTERNAL all onto `docs/`; give TIKZ a root of its own and its references become
`../figs/artifacts/tikz_figures/i_0`. Identity is a property of the *binding*,
not of the flag.

That has a consequence worth stating: mapping several scopes onto one root
collapses reference bases that are genuinely unrelated — the statement dir, the
overlay root and the package root — so any relative path they share collides.
The realistic case is a statement-dir `img/fig.png` meeting an `assets` glob on a
package-root `img/fig.png`. This is why the collision guard in §5 is keyed on the
placed destination across *all* scopes rather than per scope.

#### Ambiguous references

Two assets can reduce to one reference key with different destinations —
`img/d.png` and `img/d.pdf` under the statement dir both key on `img/d`. A
destination-keyed guard cannot see this, since the destinations differ.

`derive_remap` resolves it the way LaTeX already does. `graphicx` fills in an
extensionless `\includegraphics{img/d}` by extension precedence, preferring PDF
under pdflatex, so the statement the setter proofread locally rendered `img/d.pdf`.
Following the same order (`.pdf` > `.png` > `.jpg` > `.jpeg`, unknown extensions
last) therefore ships exactly what the local build showed — strictly better than
the old path's silent last-wins, which could publish the `.png` while the PDF
displayed the `.pdf`.

Only a clash precedence cannot decide — same shadow tier, same extension,
different destinations — raises. Rejecting the `.png`/`.pdf` pair outright was
considered and dropped: statement assets are collected automatically by
extension, so a raster source sitting next to its vector export is routine and
cites nothing, and failing the export over it breaks packages that worked.

The losing asset is still shipped under its own destination. Precedence decides
only which file an extensionless reference resolves to, never what the package
contains.

### Which slots see which assets

- `body` (legend/input/output/interaction/notes) sees `STATEMENT`, `TIKZ` and
  `EXTERNAL` assets.
- `sample_explanation(idx)` sees those **plus** `SAMPLE(idx)`, with the
  sample-scope entry winning on a key collision. This generalizes the merge
  `upload.py:_rewritten_explanations` already performs.

## 5. `StatementBundle`

Deliberately mirrors `flattening.FlatNamespace`, which solves the structurally
identical problem for source files and is already understood in this codebase.

```python
@dataclasses.dataclass
class BundledAsset:
    asset: ResolvedAsset
    dest: pathlib.PurePosixPath
    @property
    def content(self) -> bytes: ...

@dataclasses.dataclass
class StatementBundle:
    blocks: Dict[str, str]         # rewritten
    explanations: Dict[int, str]   # rewritten
    assets: List[BundledAsset]
    def materialize(self, root: pathlib.Path) -> None: ...

def build_statement_bundle(
    statement: Statement,
    *,
    layout: AssetLayout,
    normalize: bool = True,
) -> StatementBundle: ...
```

`normalize=True` applies the Polygon-TeX conversion. It defaults on because that
subset is the well-behaved one — it is what pandoc and browser TeX renderers
handle cleanly — but it is a parameter, so a consumer wanting the raw
macro-expanded TeX can have it.

An uploader reads `.content` and never calls `materialize`; a tarball packager
calls `materialize` and never touches `.content`. Both get the same rewritten
blocks.

## 6. What moves where

**New — `rbx/box/statements/export.py`:**

- `AssetScope`, `ResolvedAsset`, `resolve_assets` — from `upload.py:_collect_assets`,
  minus naming.
- `DocumentSlot`, `AssetLayout`, `FlatLayout`, `SubtreeLayout`.
- `BundledAsset`, `StatementBundle`, `build_statement_bundle`.
- The block stage: `get_substituted_statement_blocks` and
  `get_processed_statement_blocks` move here from
  `packaging/polygon/statement_block_utils.py`. This is a layering *improvement*,
  not a violation: `demacro_utils` and `polygon_utils` already live under
  `statements/`, so the block pipeline was reaching down from `packaging/` into
  `statements/` for everything it did.

**Moves to `rbx/box/statements/texsoup_utils.py`** (next to `parse_latex`, which
it already uses): `_rewrite_includegraphics`, `_strip_asset_ext`, `_ASSET_EXTS`.

**Stays in `packaging/polygon/`:**

- the API client, `upload_as_english` and the language-selection twist,
- the 1 MiB per-resource cap (a Polygon server limit),
- `_get_explanations` — concatenating explanations under
  `\textbf{Explanation for example N}` is a workaround for Polygon having a single
  `notes` field, not a general statement concern,
- `validate_statements` (Polygon-construct validation).

**`BasePackager.statement_export_params`** is promoted from "the Polygon
packager overrides this" to a documented "this packager consumes blocks"
contract, so a future block-consuming packager opts in by returning the
externalize+demacro steps rather than copying them.

`get_processed_statement_blocks` writes its debug output to `<overlay>/polygon/`
today; it becomes `<overlay>/export/`, since the blocks are no longer necessarily
Polygon's.

## 7. Deliberate behavior changes

Three, all verified against the pre-port code by running both paths over the
same trees and diffing the resulting `{uploaded_name: source}` maps and remaps.
**Uploaded names and bytes are identical in every case** — only reference
resolution and error behavior differ.

**1. `EXTERNAL` assets gain a remap.** They are uploaded under a flat name and
the author previously had to spell that flat name in `\includegraphics` by hand.
Under the derived rule they gain a remap keyed on their package-root-relative
path. The only reference whose meaning changes is one that is broken today.

**2. A `.pdf`/`.png` pair now resolves by precedence rather than by iteration
order.** Old: `img/d` → `img__d.png`, because the last write in path-sorted order
won. New: `img__d.pdf`, per §4's graphicx rule. Both files ship either way; this
changes which one an extensionless reference resolves to, and it now matches what
the setter's local pdflatex build rendered.

**3. Two distinct sources landing on one uploaded name now fail loudly.** Old:
`uploads[flat] = abs_path` silently overwrote, so one file was never uploaded and
the surviving name pointed at the wrong image. New: `_check_destination_collisions`
raises. This replaces a silent wrong upload with an actionable error.

Changes 2 and 3 both replace order-dependent or silently-lossy behavior; neither
can turn a correct package into a broken one, and both are pinned by tests.

**Error surface.** `export.py` raises `StatementExportError(ValueError)`, which
`upload.py` catches at its boundary and re-renders as a console error plus
`typer.Exit(1)`. The subclass exists because the library must stay usable from
non-CLI callers — a packager, not just a Typer command — while a bare `ValueError`
catch at the boundary would also swallow pydantic's `ValidationError` (itself a
`ValueError`) and render a validation dump as a setter-facing asset error.

## 8. Testing

- **Pure units.** `resolve_assets` and both layouts are pure functions over paths.
  Layout tests need no package at all: assert `place_asset`/`document_dir` and the
  derived remap for the Polygon and MOJ bindings, including the
  identity-preserving case producing an empty remap.
- **Port guard.** On the existing Polygon statement fixtures, assert that the
  `(dest -> source)` map and every rewritten block/explanation match what the
  current code produces, so the refactor is provably output-preserving.
- **Reference rewriting.** The existing `_rewrite_includegraphics` cases (optional
  arguments preserved, no double extension, root-level references) move with the
  function and must keep passing.

## 9. Known gaps

- **No second consumer at merge time.** The MOJ layout is designed against MOJ's
  documented package shape and exercised by unit tests, but no packager emits it
  until the follow-up. The abstraction is validated by construction, not by a
  second shipped call site.
- **Blocks stop at TeX.** A markdown target still needs a converter that does not
  exist yet.
- **Sample-note directory.** `docs/notes/<idx>/` is this document's placeholder for
  MOJ's required layout; the follow-up must confirm it against
  `PACOTE.html`/`mojtools` before shipping. Nothing in the API depends on the
  choice — it is a `SubtreeLayout` binding.
