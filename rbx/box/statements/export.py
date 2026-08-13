"""Target-independent statement export: resolve a statement's assets once, then
let a layout decide where they land.

Extracted from the Polygon upload path, which was the only consumer. See
``docs/plans/2026-08-13-statement-export-bundle-design.md``.
"""

import dataclasses
import enum
import pathlib
import posixpath
from typing import Dict, Iterable, List, Literal, NamedTuple, Optional, Protocol, Set

from rbx import utils
from rbx.box.statements import sample_staging
from rbx.box.statements.build_statements import (
    get_produced_tikz_pdfs,
    get_statement_dir,
)
from rbx.box.statements.schema import Statement
from rbx.box.statements.texsoup_utils import ASSET_EXTS


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

    def place_asset(self, asset: 'ResolvedAsset') -> pathlib.PurePosixPath: ...

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
        return pathlib.PurePosixPath(
            self._format(template, slot.index, slot.kind) or '.'
        )


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
