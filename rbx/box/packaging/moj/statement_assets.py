"""PDF statement figures, rasterized for MOJ.

MOJ renders the statement to HTML and base64-embeds every image, so an
``<img src="fig.pdf">`` is broken in every browser -- and rbx's TikZ
externalization produces exactly that. rbx has no rasterizer of its own
(PyMuPDF is AGPL, incompatible with rbx's Apache-2.0), so this shells out to
poppler's ``pdftoppm`` through the external tool registry.

The conversion is split in two, and the split is load-bearing:

- ``RasterizingLayout`` changes the *placement* extension, which is what makes
  the derived remap point at the rasterized name. ``derive_remap`` reads
  ``place_asset``, so renaming the file after ``materialize`` would leave every
  ``\\includegraphics`` reference citing a ``.pdf`` that is no longer there.
- ``rasterize_pdf_assets`` does the actual conversion, after materialization.
"""

import base64
import dataclasses
import pathlib
import subprocess
from typing import Callable, List

import typer

from rbx import console, tooling
from rbx.box.statements import export


@dataclasses.dataclass(frozen=True)
class RasterizingLayout:
    """An ``AssetLayout`` that places PDF assets under a ``.png`` name.

    Wraps another layout rather than subclassing one: every other decision --
    the roots, the document dirs, whether references keep their extension --
    belongs to the wrapped layout, and this one has an opinion about exactly one
    thing. Extension mangling is already a layout concern (``keep_extension``),
    so this is in-idiom rather than a special case bolted onto the packager.
    """

    inner: export.AssetLayout

    @property
    def keep_extension(self) -> bool:
        return self.inner.keep_extension

    def place_asset(self, asset: export.ResolvedAsset) -> pathlib.PurePosixPath:
        dest = self.inner.place_asset(asset)
        if dest.suffix.lower() == '.pdf':
            return dest.with_suffix('.png')
        return dest

    def document_dir(self, slot: export.DocumentSlot) -> pathlib.PurePosixPath:
        return self.inner.document_dir(slot)


# 300 DPI: high enough that a vector figure stays crisp at print size, low enough
# that the base64 payload MOJ embeds into the HTML stays reasonable.
_RASTER_DPI = '300'


def _pdf_assets(bundle: export.StatementBundle) -> List[export.BundledAsset]:
    """The bundled assets whose SOURCE is a PDF.

    Keyed on the source, not the destination: ``RasterizingLayout`` has already
    renamed the destination to ``.png``, so the destination no longer says what
    the file actually is.
    """
    return [
        bundled
        for bundled in bundle.assets
        if bundled.asset.source.suffix.lower() == '.pdf'
    ]


def rasterize_pdf_assets(bundle: export.StatementBundle, root: pathlib.Path) -> None:
    """Convert every materialized PDF asset under ``root`` to PNG.

    Call after ``bundle.materialize(root)``: the PDF has already been copied to
    the ``.png`` destination the layout chose, and this replaces those bytes with
    a real raster.

    Returns immediately -- **without probing for poppler** -- when the statement
    ships no PDF figure. The overwhelmingly common package has none, and turning
    poppler into a requirement for those would be gratuitous.
    """
    pdfs = _pdf_assets(bundle)
    if not pdfs:
        return

    if not tooling.PDFTOPPM.is_available():
        figures = '[/item], [item]'.join(
            str(bundled.asset.rel) for bundled in sorted(pdfs, key=lambda b: b.dest)
        )
        console.console.print(
            f'[error]This statement ships PDF figures ([item]{figures}[/item]), '
            'which MOJ cannot display: it renders to HTML and base64-embeds every '
            'image, and no browser draws a PDF in an [item]<img>[/item].[/error]\n'
            '[error]rbx converts them with poppler, which is not installed. Install '
            'it, or replace those figures with PNG or SVG.[/error]'
        )
        # Raises with the platform's install command.
        tooling.PDFTOPPM.ensure()

    for bundled in pdfs:
        dest = root / bundled.dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        # `-singlefile` suppresses pdftoppm's `-<page>` suffix and appends `.png`
        # to the prefix, so the prefix is the destination without its extension.
        prefix = dest.with_suffix('')
        result = tooling.PDFTOPPM.run(
            [
                '-png',
                '-r',
                _RASTER_DPI,
                '-singlefile',
                str(bundled.asset.source),
                str(prefix),
            ],
            capture_output=True,
        )
        produced = prefix.with_suffix('.png')
        if result.returncode != 0 or not produced.is_file():
            _fail(bundled, result)

        # The materialized copy of the PDF, when the layout did not rename it.
        # Shipping it would mean a broken <img> in the rendered statement.
        if dest != produced and dest.is_file():
            dest.unlink()


# --- Base64 inlining -------------------------------------------------------
#
# The alternative to shipping the image files beside the documents: the
# statement carries every figure inside itself, as a `data:` URI, and
# `docs/assets` (and friends) are not written at all. Which one a package gets
# is `statement.INLINE_IMAGES_AS_BASE64`; the argument for each is there.


# The suffixes a statement figure can reach MOJ with, mapped to the MIME type the
# data URI must declare. Spelled out rather than read off `mimetypes`, whose table
# is platform- and registry-dependent (`.svg` in particular is routinely missing
# on a bare container) -- the set is small and closed anyway, since PDFs have
# already been rasterized by the time inlining runs.
_MIME_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
    '.tif': 'image/tiff',
    '.tiff': 'image/tiff',
}

_DEFAULT_MIME_TYPE = 'application/octet-stream'


def data_uri(path: pathlib.Path) -> str:
    """The ``data:`` URI carrying ``path``'s bytes."""
    mime = _MIME_TYPES.get(path.suffix.lower(), _DEFAULT_MIME_TYPE)
    payload = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{payload}'


def base64_inliner(base: pathlib.Path) -> Callable[[str], str]:
    """A ``rewrite_image_url`` that replaces a reference with the file's own bytes.

    ``base`` is the directory the document's references resolve against -- for
    every MOJ document the materialized ``docs/``, since that is what
    ``gen-problem-json.sh`` hands pandoc as ``--resource-path``. So this must run
    AFTER ``materialize`` and ``rasterize_pdf_assets``: what it reads is the
    placed file, which for a TikZ figure is the rasterized PNG rather than the
    PDF the statement was authored against.

    A reference that does not name a file under ``base`` is left exactly as it
    is -- an absolute URL, an already-inlined ``data:`` URI, a path that escapes
    ``base`` -- rather than being reported: none of them is this function's to
    rewrite, and a broken local reference is already MOJ's renderer's to
    complain about, in the same words it would have used without inlining.
    """

    def rewrite(url: str) -> str:
        if not url or '://' in url or url.startswith('data:'):
            return url
        target = base / url
        if not target.is_file():
            return url
        return data_uri(target)

    return rewrite


def discard_assets(bundle: export.StatementBundle, root: pathlib.Path) -> None:
    """Remove every materialized asset under ``root``, and the dirs left empty.

    The other half of inlining: the bytes now live inside the documents, so the
    files beside them are dead weight in the tarball. Only the destinations the
    bundle itself chose are removed, and a directory goes only if it comes out
    empty, so nothing else the packager wrote is in the blast radius.
    """
    directories = set()
    for bundled in bundle.assets:
        dest = root / bundled.dest
        if dest.is_file():
            dest.unlink()
        directories.add(dest.parent)

    # Deepest first, so a parent emptied by its own children also goes.
    for directory in sorted(directories, key=lambda d: len(d.parts), reverse=True):
        while directory != root and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            directory = directory.parent


def _fail(bundled: export.BundledAsset, result: subprocess.CompletedProcess) -> None:
    stderr = (result.stderr or b'').decode(errors='replace').strip()
    console.console.print(
        f'[error]Could not rasterize [item]{bundled.asset.source}[/item] for '
        'MOJ.[/error]'
    )
    if stderr:
        console.console.print(f'[error]{stderr}[/error]')
    raise typer.Exit(1)
