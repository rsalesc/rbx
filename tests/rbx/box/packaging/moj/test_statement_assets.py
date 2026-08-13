"""MOJ base64-embeds every image into HTML, so a PDF figure -- which rbx's TikZ
externalization produces -- must be rasterized before it ships."""

import pathlib
import subprocess
from unittest import mock

import pytest
import typer

from rbx.box.packaging.moj import statement_assets
from rbx.box.statements import export


def _inner_layout() -> export.SubtreeLayout:
    return export.SubtreeLayout(
        document_dirs={'body': 'docs'},
        asset_roots={export.AssetScope.STATEMENT: 'docs/assets'},
    )


def _asset(rel: str, source: pathlib.Path | None = None) -> export.ResolvedAsset:
    return export.ResolvedAsset(
        scope=export.AssetScope.STATEMENT,
        source=source if source is not None else pathlib.Path('/nowhere') / rel,
        rel=pathlib.PurePosixPath(rel),
    )


def _bundle(assets) -> export.StatementBundle:
    return export.StatementBundle(
        blocks={}, explanations={}, assets=list(assets), remaps={}
    )


def _bundled(layout, asset) -> export.BundledAsset:
    return export.BundledAsset(asset=asset, dest=layout.place_asset(asset))


def test_layout_places_a_pdf_asset_as_png():
    """The remap is derived from place_asset, so the extension must change HERE --
    rasterizing after materialize would leave every reference pointing at a .pdf."""
    layout = statement_assets.RasterizingLayout(_inner_layout())
    assert layout.place_asset(_asset('fig.pdf')) == pathlib.PurePosixPath(
        'docs/assets/fig.png'
    )


def test_layout_leaves_raster_and_vector_assets_alone():
    layout = statement_assets.RasterizingLayout(_inner_layout())
    assert layout.place_asset(_asset('fig.png')) == pathlib.PurePosixPath(
        'docs/assets/fig.png'
    )
    # SVG passes through untouched: pandoc embeds it fine.
    assert layout.place_asset(_asset('fig.svg')) == pathlib.PurePosixPath(
        'docs/assets/fig.svg'
    )


def test_layout_delegates_document_dir_and_keep_extension():
    inner = _inner_layout()
    layout = statement_assets.RasterizingLayout(inner)
    assert layout.document_dir(export.DocumentSlot.body()) == inner.document_dir(
        export.DocumentSlot.body()
    )
    assert layout.keep_extension == inner.keep_extension


def test_rasterize_invokes_pdftoppm_and_replaces_the_pdf(tmp_path):
    source = tmp_path / 'fig.pdf'
    source.write_bytes(b'%PDF-1.4 fake')
    layout = statement_assets.RasterizingLayout(_inner_layout())
    bundle = _bundle([_bundled(layout, _asset('fig.pdf', source))])

    root = tmp_path / 'package'
    bundle.materialize(root)

    def _fake_run(args, **kwargs):
        # `-singlefile` makes pdftoppm append `.png` to the output prefix.
        pathlib.Path(args[-1] + '.png').write_bytes(b'\x89PNG fake')
        return subprocess.CompletedProcess(args, 0)

    with (
        mock.patch('rbx.tooling.command_exists', return_value=True),
        mock.patch('rbx.tooling.subprocess.run', side_effect=_fake_run) as run,
    ):
        statement_assets.rasterize_pdf_assets(bundle, root)

    args = run.call_args.args[0]
    assert args[:5] == ['pdftoppm', '-png', '-r', '300', '-singlefile']
    assert args[5] == str(source)
    assert (root / 'docs' / 'assets' / 'fig.png').read_bytes() == b'\x89PNG fake'
    assert list(root.rglob('*.pdf')) == []


def test_rasterize_refuses_when_poppler_is_missing_and_names_the_figures(
    tmp_path, capsys
):
    source = tmp_path / 'fig.pdf'
    source.write_bytes(b'%PDF-1.4 fake')
    layout = statement_assets.RasterizingLayout(_inner_layout())
    bundle = _bundle([_bundled(layout, _asset('fig.pdf', source))])
    root = tmp_path / 'package'
    bundle.materialize(root)

    with (
        mock.patch('rbx.tooling.command_exists', return_value=False),
        pytest.raises(typer.Exit),
    ):
        statement_assets.rasterize_pdf_assets(bundle, root)

    out = capsys.readouterr().out
    assert 'fig.pdf' in out
    assert 'pdftoppm' in out


def test_rasterize_is_a_noop_without_pdf_assets(tmp_path):
    """Must not probe for poppler at all -- the overwhelmingly common package has
    no PDF figures, and demanding poppler from it would be a gratuitous new
    requirement."""
    source = tmp_path / 'fig.png'
    source.write_bytes(b'\x89PNG')
    layout = statement_assets.RasterizingLayout(_inner_layout())
    bundle = _bundle([_bundled(layout, _asset('fig.png', source))])
    root = tmp_path / 'package'
    bundle.materialize(root)

    with mock.patch('rbx.tooling.command_exists') as command_exists:
        statement_assets.rasterize_pdf_assets(bundle, root)

    command_exists.assert_not_called()
    assert (root / 'docs' / 'assets' / 'fig.png').exists()
