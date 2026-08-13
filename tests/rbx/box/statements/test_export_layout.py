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
    assert str(layout.place_asset(TIKZ_ASSET)) == 'artifacts__tikz_figures__i_0.pdf'
    assert str(layout.place_asset(EXTERNAL_ASSET)) == 'extra__logo.png'


def test_flat_layout_namespaces_sample_assets_by_index():
    layout = export.FlatLayout()
    assert str(layout.place_asset(SAMPLE_ASSET)) == 'sample_0__diagram.png'


def test_flat_layout_puts_every_document_at_the_root():
    layout = export.FlatLayout()
    assert str(layout.document_dir(DocumentSlot.body())) == '.'
    assert str(layout.document_dir(DocumentSlot.sample(0))) == '.'


def test_flat_layout_keeps_extensions_and_cannot_be_told_otherwise():
    # The flat name IS the uploaded resource name, so a reference without the
    # extension would not resolve.
    assert export.FlatLayout().keep_extension is True
    with pytest.raises(TypeError):
        export.FlatLayout(keep_extension=False)  # type: ignore[call-arg]


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
    remap = export.derive_remap(
        [SAMPLE_ASSET], export.FlatLayout(), DocumentSlot.body()
    )
    assert remap == {}


def test_sample_scope_asset_wins_a_key_collision_with_a_statement_asset():
    statement_named_like_the_sample = _asset(AssetScope.STATEMENT, 'diagram.png')
    remap = export.derive_remap(
        [SAMPLE_ASSET, statement_named_like_the_sample],
        export.FlatLayout(),
        DocumentSlot.sample(0),
    )
    assert remap == {'diagram': 'sample_0__diagram.png'}


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


def test_subtree_layout_without_roots_places_at_the_top():
    layout = export.SubtreeLayout()
    assert str(layout.place_asset(STATEMENT_ASSET)) == 'img/d.png'
    assert str(layout.document_dir(DocumentSlot.body())) == '.'


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


def test_unknown_placeholder_in_a_root_is_reported():
    with pytest.raises(ValueError, match='placeholder'):
        export.SubtreeLayout(
            asset_roots={AssetScope.STATEMENT: 'docs/{bogus}'},
            document_dirs={},
        ).place_asset(STATEMENT_ASSET)
