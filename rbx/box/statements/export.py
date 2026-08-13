"""One statement export pipeline, shared by every target, in four stages:

1. **Blocks** (``get_substituted_statement_blocks`` /
   ``get_processed_statement_blocks``) -- read what the build left in the overlay,
   expand and filter macros, and optionally normalize the TeX.
2. **Assets** (``resolve_assets``) -- every file the statement ships, tagged with
   the scope its ``\\includegraphics`` references are relative to.
3. **Layout** (``AssetLayout`` and friends) -- where those assets and the
   documents citing them land, for this target.
4. **Remap** (``derive_remap``) -- the reference rewrites the layout implies.

Stages 2--4 are genuinely target-independent: they know only paths, and a target
is expressed entirely as a layout. Stage 1 is not quite -- its final,
*optional* step converts to the Polygon TeX subset (see
``get_processed_statement_blocks``), which is why ``polygon_utils`` is imported
here. That subset is the conservative one, so it is the default rather than a
Polygon special case, and it is a parameter for consumers that want the raw TeX.

Extracted from the Polygon upload path, which was the only consumer. See
``docs/plans/2026-08-13-statement-export-bundle-design.md``.
"""

import dataclasses
import enum
import pathlib
import posixpath
import shutil
import tempfile
from typing import Dict, Iterable, List, Literal, Optional, Protocol, Set

import typer

from rbx import console, utils
from rbx.box.statements import demacro_utils, polygon_utils, sample_staging
from rbx.box.statements.build_statements import (
    get_produced_tikz_pdfs,
    get_statement_dir,
)
from rbx.box.statements.demacro_utils import MacroDefinitions
from rbx.box.statements.render import StatementBlocks
from rbx.box.statements.schema import Statement, StatementType
from rbx.box.statements.texsoup_utils import ASSET_EXTS


def get_substituted_statement_blocks(statement: Statement) -> StatementBlocks:
    assert statement.type == StatementType.rbxTeX
    # The v2 overlay root is the single export source dir; the substituted blocks
    # (TikZ -> \includegraphics) live in blocks.sub.yml, written by the forced
    # externalize build.
    statement_dir = get_statement_dir(statement)
    substituted_blocks_path = statement_dir / 'blocks.sub.yml'
    if not substituted_blocks_path.is_file():
        console.console.print(
            f'Substituted blocks file [item]{substituted_blocks_path}[/item] does not exist. '
            'Please run the command to build the statement again.',
        )
        raise typer.Exit(1)

    statement_blocks = utils.model_from_yaml(
        StatementBlocks, substituted_blocks_path.read_text()
    )
    return statement_blocks


def get_processed_statement_blocks(
    statement: Statement, normalize: bool = True
) -> StatementBlocks:
    """Read the built blocks, expand and filter macros, and (by default) convert
    to Polygon TeX.

    ``normalize`` controls only that last conversion. It defaults on because the
    Polygon subset is the well-behaved one -- it is what pandoc and browser TeX
    renderers handle cleanly -- but a consumer wanting the raw macro-expanded TeX
    can turn it off.

    The macro *filter* runs either way, even though its allowlist comes from
    ``PolygonTeXConfig``: it decides which macros stay unexpanded, and every name
    on that list is a plain LaTeX command any TeX consumer already understands.
    Dropping it under ``normalize=False`` would change the blocks' macro
    semantics, not their TeX dialect, and the two modes would no longer be
    comparable.
    """
    statement_blocks = get_substituted_statement_blocks(statement)
    overlay_dir = get_statement_dir(statement)
    macros_file = overlay_dir / 'macros.json'
    statement_dir = overlay_dir / 'export'

    if not macros_file.is_file():
        # NOTE: this returns BEFORE the conversion, so an explicit
        # ``normalize=True`` silently does nothing when the build did not run the
        # demacro pass. Polygon masks the quirk -- ``validate_statements`` re-checks
        # the constructs and errors loudly -- but a future block-consuming packager
        # would get un-normalized TeX with no signal at all.
        return statement_blocks

    # Get macros and additional macros from defs block.
    macros = MacroDefinitions.from_json_file(macros_file)
    if 'defs' in statement_blocks.blocks:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file = pathlib.Path(temp_dir) / 'defs.tex'
            temp_file.write_text(statement_blocks.blocks['defs'])
            defs_macros = demacro_utils.collect_macro_definitions(temp_file)
            macros.merge(defs_macros)

    # Filter out commands that are accepted by Polygon.
    macros = macros.filter(polygon_utils.PolygonTeXConfig.default().allowed_commands)

    # Expand macros in statement blocks and explanations.
    statement_blocks.blocks = {
        block_name: demacro_utils.expand_macros(block_content, macros)
        for block_name, block_content in statement_blocks.blocks.items()
    }
    statement_blocks.explanations = {
        explanation_index: demacro_utils.expand_macros(explanation, macros)
        for explanation_index, explanation in statement_blocks.explanations.items()
    }

    if normalize:
        # For last, try to convert to Polygon TeX.
        statement_blocks.blocks = {
            block_name: polygon_utils.convert_to_polygon_tex(
                block_content, ignore_macros=True
            )
            for block_name, block_content in statement_blocks.blocks.items()
        }
        statement_blocks.explanations = {
            explanation_index: polygon_utils.convert_to_polygon_tex(
                explanation, ignore_macros=True
            )
            for explanation_index, explanation in statement_blocks.explanations.items()
        }

        # Save normalized blocks for debugging. The wipe belongs to this branch,
        # not the top of the function: a later non-normalizing call writes nothing,
        # so an unconditional wipe would erase the dump a reader came looking for.
        shutil.rmtree(statement_dir, ignore_errors=True)
        statement_dir.mkdir(parents=True, exist_ok=True)
        for block_name, block_content in statement_blocks.blocks.items():
            (statement_dir / f'{block_name}.tex').write_text(block_content)
        for explanation_index, explanation in statement_blocks.explanations.items():
            (statement_dir / f'explanation_{explanation_index}.tex').write_text(
                explanation
            )

    return statement_blocks


class AssetScope(enum.Enum):
    """The directory an asset's reference is relative to.

    Every asset is resolved against some directory, and that directory is
    precisely what its ``\\includegraphics`` reference is relative to -- naming
    the directory names the scope:

    ==============  ==========================================  =======================
    Scope           Reference base                              Example reference
    ==============  ==========================================  =======================
    ``STATEMENT``   the statement ``file``'s directory          ``img/fig``
    ``TIKZ``        the overlay root (``get_statement_dir``)    ``artifacts/tikz_figures/i_0``
    ``SAMPLE``      ``<overlay>/.samples/<idx>/``               ``diagram``
    ``EXTERNAL``    the package root                            n/a (no auto-rewrite)
    ==============  ==========================================  =======================

    Sources, respectively: image/PDF under the statement dir plus ``assets``
    globs falling under it (any extension); the ``artifacts/tikz_figures/**.pdf``
    of the forced-externalize build; image/PDF under the staged sample folder;
    ``assets`` globs outside the statement dir.
    """

    STATEMENT = 'statement'
    TIKZ = 'tikz'
    SAMPLE = 'sample'
    EXTERNAL = 'external'


@dataclasses.dataclass(frozen=True)
class ResolvedAsset:
    """An asset the statement ships, tagged with the base its references are
    relative to. Carries no naming: that is a layout's job."""

    scope: AssetScope
    source: pathlib.Path  # absolute
    rel: pathlib.PurePosixPath  # relative to the scope's reference base
    sample_index: Optional[int] = None  # set iff scope is SAMPLE

    def __post_init__(self) -> None:
        if (self.scope is AssetScope.SAMPLE) != (self.sample_index is not None):
            raise ValueError('sample_index must be set iff scope is SAMPLE')

    @property
    def sample(self) -> int:
        """The sample index, for SAMPLE-scope assets only."""
        assert self.sample_index is not None
        return self.sample_index

    @property
    def ref_key(self) -> str:
        """The extensionless reference a block uses to cite this asset.

        Beware the asymmetry with the lookup side: this strips *any* suffix,
        while ``strip_asset_ext`` strips only ``ASSET_EXTS``. So a ``figure.svg``
        asset keys as ``figure``, and a reference spelled
        ``\\includegraphics{figure.svg}`` -- which strips to itself -- never
        matches it. Pre-existing and intended; non-image extensions only reach
        here through an explicit ``assets`` glob.
        """
        return str(self.rel.with_suffix(''))


def _resolve_asset_globs(root: pathlib.Path, globs: List[str]) -> List[pathlib.Path]:
    """Absolute paths of files matching ``globs`` under ``root`` (``Path.glob``,
    so ``**`` recurses). Files only; deduped; deterministically sorted."""
    seen: Set[pathlib.Path] = set()
    for glob in globs:
        for path in root.glob(glob):
            if path.is_file():
                seen.add(utils.abspath(path))
    return sorted(seen)


def _image_files_under(base: pathlib.Path) -> List[pathlib.Path]:
    """Image/PDF files anywhere under ``base`` (recursive), deterministically
    sorted. Empty when ``base`` is not a directory."""
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

    **``rel`` and ``ref_key`` are NOT unique across the list.** Only ``source``
    is. Two out-of-package ``assets`` hits sharing a basename both fall back to
    the bare name, and ``img/d.png`` + ``img/d.pdf`` under the statement dir have
    distinct ``rel`` but the same ``ref_key``. Detecting and rejecting such
    collisions belongs to whoever assigns names -- the layout/bundle -- since
    only there is it known whether two entries actually land on top of each
    other.

    Not filesystem-pure, despite reading like a query: ``get_statement_dir``
    creates the overlay directory (``mkdir(parents=True, exist_ok=True)``) as a
    side effect.
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


DocumentKind = Literal['body', 'sample_explanation']


@dataclasses.dataclass(frozen=True)
class DocumentSlot:
    """Where a piece of referencing text will end up. The remap is derived per
    slot, because a reference's meaning depends on where the text sits.

    Frozen (and therefore hashable) so a bundle can key its documents on a slot.
    """

    kind: DocumentKind
    index: Optional[int] = None

    def __post_init__(self) -> None:
        if (self.kind == 'sample_explanation') != (self.index is not None):
            raise ValueError(
                'index must be set iff kind is sample_explanation; '
                f'got kind={self.kind!r}, index={self.index!r}'
            )

    @classmethod
    def body(cls) -> 'DocumentSlot':
        return cls(kind='body')

    @classmethod
    def sample(cls, index: int) -> 'DocumentSlot':
        return cls(kind='sample_explanation', index=index)

    @property
    def sample_index(self) -> int:
        """The sample index, for sample_explanation slots only."""
        assert self.index is not None
        return self.index


class AssetLayout(Protocol):
    """Decides where assets and documents land. Both answers are *paths*, so a
    layout with several roots needs no extra concept -- see design §4."""

    @property
    def keep_extension(self) -> bool:
        """Whether a derived reference carries the asset's extension."""
        ...

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

    ``sep`` is Polygon's uploaded-name convention; changing it changes the name
    of every uploaded resource, so there is no reason to touch it for Polygon.
    """

    sep: str = '__'
    keep_extension: bool = dataclasses.field(default=True, init=False)

    def place_asset(self, asset: ResolvedAsset) -> pathlib.PurePosixPath:
        flat = str(asset.rel).replace('/', self.sep)
        if asset.scope == AssetScope.SAMPLE:
            flat = f'sample_{asset.sample}{self.sep}{flat}'
        return pathlib.PurePosixPath(flat)

    def document_dir(self, slot: DocumentSlot) -> pathlib.PurePosixPath:
        return pathlib.PurePosixPath('.')


@dataclasses.dataclass(frozen=True)
class SubtreeLayout:
    """Directories preserved under a per-scope root, with documents free to live
    in roots of their own -- the shape a tarball judge such as MOJ needs, where
    the statement is ``docs/enunciado.md`` and sample notes ship elsewhere.

    Roots are format strings; ``{index}`` (the sample index) is available to the
    SAMPLE scope and the sample_explanation slot, where it is REQUIRED, and is
    rejected anywhere else, where there is no index to interpolate.

    ``keep_extension=False`` yields a reference identical to the authored one --
    so that the entry drops out of the remap and no block is rewritten -- but
    only for an asset whose scope root equals the citing document's dir
    (``asset_roots[scope] == document_dirs[slot.kind]``). Identity is a property
    of the *binding*, which ``keep_extension=False`` merely permits: an asset
    placed in a root the document does not sit in still derives a ``../`` path
    and is still rewritten.
    """

    asset_roots: Dict[AssetScope, str] = dataclasses.field(default_factory=dict)
    document_dirs: Dict[DocumentKind, str] = dataclasses.field(default_factory=dict)
    keep_extension: bool = True

    def _format(self, template: str, index: Optional[int], what: str) -> str:
        try:
            return template.format(index=index)
        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(f'Invalid placeholder in {what} root {template!r}.') from e

    def _check_index_placeholder(self, template: str, what: str, needed: bool) -> None:
        """``{index}`` is meaningful exactly where an index exists: required
        there (or entries from different samples collide into one path) and
        rejected everywhere else (where it could only interpolate ``None``)."""
        if needed and '{index' not in template:
            raise ValueError(
                f'The {what} root must carry an {{index}} placeholder, otherwise '
                f'entries from different samples collide; got {template!r}.'
            )
        if not needed and '{index' in template:
            raise ValueError(
                f'The {what} root has no sample index to interpolate, so it must '
                f'not carry an {{index}} placeholder; got {template!r}.'
            )

    def place_asset(self, asset: ResolvedAsset) -> pathlib.PurePosixPath:
        root = self.asset_roots.get(asset.scope, '')
        self._check_index_placeholder(
            root, f'{asset.scope.value} asset', asset.scope == AssetScope.SAMPLE
        )
        root = self._format(root, asset.sample_index, f'{asset.scope.value} asset')
        return pathlib.PurePosixPath(root) / asset.rel if root else asset.rel

    def document_dir(self, slot: DocumentSlot) -> pathlib.PurePosixPath:
        template = self.document_dirs.get(slot.kind, '')
        self._check_index_placeholder(
            template,
            f'{slot.kind} document',
            slot.kind == 'sample_explanation',
        )
        return pathlib.PurePosixPath(
            self._format(template, slot.index, f'{slot.kind} document') or '.'
        )


def _slot_sees(asset: ResolvedAsset, slot: DocumentSlot) -> bool:
    """Body text sees everything but sample assets; an explanation additionally
    sees its OWN sample's assets."""
    if asset.scope != AssetScope.SAMPLE:
        return True
    return slot.kind == 'sample_explanation' and asset.sample_index == slot.index


def _shadow_tier(asset: ResolvedAsset) -> bool:
    """The tier a reference key is resolved in: a sample-scope asset shadows a
    non-sample one of the same key, and only a same-tier clash is ambiguous."""
    return asset.scope == AssetScope.SAMPLE


#: Extension precedence for an extensionless reference, mirroring pdflatex's
#: default ``\DeclareGraphicsExtensions``: PDF beats the raster formats. An
#: extension outside this list ranks last. Matching is case-insensitive, which
#: is where this stops mirroring graphicx exactly: ``pdftex.def`` lists every
#: lowercase spelling ahead of any uppercase one, so for a ``fig.PNG``/``fig.jpg``
#: pair graphicx picks the JPG where this picks the PNG.
_EXTENSION_PRECEDENCE = ('.pdf', '.png', '.jpg', '.jpeg')


def _extension_rank(asset: ResolvedAsset) -> int:
    """Lower ranks win the reference. See ``_EXTENSION_PRECEDENCE``."""
    suffix = asset.rel.suffix.lower()
    if suffix not in _EXTENSION_PRECEDENCE:
        return len(_EXTENSION_PRECEDENCE)
    return _EXTENSION_PRECEDENCE.index(suffix)


def _resolve_references(
    assets: Iterable[ResolvedAsset], layout: AssetLayout, slot: DocumentSlot
) -> Dict[str, ResolvedAsset]:
    """The single asset each reference key names, for a document in ``slot``.

    References are extensionless, so several assets can claim one key -- and
    routinely do, since ``resolve_assets`` sweeps up every image under the
    statement dir whether or not a block cites it. Resolution mirrors what the
    author's own build did:

    1. A sample-scope asset shadows a non-sample one of the same key.
    2. Within a tier, extension precedence decides (``_EXTENSION_PRECEDENCE``),
       exactly as ``graphicx`` resolves ``\\includegraphics{fig}``. Shipping the
       PDF of a ``fig.pdf``/``fig.png`` pair is therefore not a coin flip: it is
       the file the locally rendered statement used.
    3. Only a same-tier, same-extension, different-destination pair is left
       undecidable, and that raises.

    Each key is decided from its whole candidate set rather than folded over the
    running winner, so the answer -- including whether it raises -- does not
    depend on the order the assets arrive in. Candidates that lose on tier or
    rank are out of the running entirely and cannot make a decided key
    undecidable.
    """
    candidates: Dict[str, List[ResolvedAsset]] = {}
    for asset in assets:
        if _slot_sees(asset, slot):
            candidates.setdefault(asset.ref_key, []).append(asset)

    winner: Dict[str, ResolvedAsset] = {}
    for key, group in candidates.items():
        tier = max(_shadow_tier(asset) for asset in group)
        in_tier = [asset for asset in group if _shadow_tier(asset) == tier]
        rank = min(_extension_rank(asset) for asset in in_tier)
        finalists = [asset for asset in in_tier if _extension_rank(asset) == rank]

        best = finalists[0]
        best_dest = layout.place_asset(best)
        for other in finalists[1:]:
            # Same tier and same extension: precedence has nothing left to
            # decide with. A shared destination is still fine -- the reference
            # is unambiguous whichever asset is recorded, and whether shipping
            # two sources to one path is legal is the bundle's problem.
            if layout.place_asset(other) != best_dest:
                raise ValueError(
                    f'Cannot decide which asset the reference {key!r} names: '
                    f'{best.source} and {other.source} both reduce to it and '
                    'share an extension, so extension precedence cannot choose '
                    'between them. Rename one, move one out of the statement '
                    'directory, or drop one.'
                )
        winner[key] = best
    return winner


def derive_remap(
    assets: Iterable[ResolvedAsset], layout: AssetLayout, slot: DocumentSlot
) -> Dict[str, str]:
    """The reference rewrites a document in ``slot`` needs, derived from where the
    layout put things: an asset's new reference is its placement seen from the
    document's directory.

    Entries whose derived reference already equals the authored one are dropped,
    which is what makes rewriting optional: an identity-preserving layout yields
    an empty remap and every block comes back untouched.

    Which asset a key names is settled BEFORE identities are dropped. The other
    order silently inverts the shadowing rule: a sample asset that lands on its
    own explanation's dir derives an identity and would drop out, leaving the
    statement-scope asset it shadows to rewrite the reference to the wrong image.
    """
    doc_dir = layout.document_dir(slot)
    remap: Dict[str, str] = {}
    for key, asset in _resolve_references(assets, layout, slot).items():
        dest = layout.place_asset(asset)
        if not layout.keep_extension:
            dest = dest.with_suffix('')
        ref = posixpath.relpath(str(dest), str(doc_dir))
        if ref != key:
            remap[key] = ref
    return remap
