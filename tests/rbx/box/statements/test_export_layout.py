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


# --- Two assets at the same shadow tier claiming one reference --------------


@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
def test_pdf_wins_the_reference_over_a_raster_of_the_same_name(order):
    # graphicx resolves an extensionless \includegraphics{img/d} to the PDF
    # under pdflatex, so that is the file the author's own build rendered.
    png = _asset(AssetScope.STATEMENT, 'img/d.png')
    pdf = _asset(AssetScope.STATEMENT, 'img/d.pdf')
    both = [png, pdf]
    remap = export.derive_remap(
        [both[i] for i in order], export.FlatLayout(), DocumentSlot.body()
    )
    assert remap == {'img/d': 'img__d.pdf'}


def test_losing_the_reference_does_not_remove_an_asset_from_the_list():
    # The loser is still shipped, under its own distinct destination.
    png = _asset(AssetScope.STATEMENT, 'img/d.png')
    pdf = _asset(AssetScope.STATEMENT, 'img/d.pdf')
    assets = [png, pdf]
    export.derive_remap(assets, export.FlatLayout(), DocumentSlot.body())
    assert assets == [png, pdf]
    layout = export.FlatLayout()
    assert layout.place_asset(png) != layout.place_asset(pdf)


def test_raster_precedence_follows_the_graphicx_order():
    png = _asset(AssetScope.STATEMENT, 'd.png')
    jpg = _asset(AssetScope.STATEMENT, 'd.jpg')
    jpeg = _asset(AssetScope.STATEMENT, 'd.jpeg')
    remap = export.derive_remap(
        [jpeg, jpg, png], export.FlatLayout(), DocumentSlot.body()
    )
    assert remap == {'d': 'd.png'}


def test_an_unknown_extension_loses_to_a_known_one():
    # A .svg only reaches the asset list through an explicit `assets` glob, and
    # graphicx would not have picked it under pdflatex.
    svg = _asset(AssetScope.STATEMENT, 'figure.svg')
    png = _asset(AssetScope.STATEMENT, 'figure.png')
    remap = export.derive_remap([svg, png], export.FlatLayout(), DocumentSlot.body())
    assert remap == {'figure': 'figure.png'}


def test_same_extension_different_destinations_is_undecidable():
    statement = export.ResolvedAsset(
        scope=AssetScope.STATEMENT,
        source=pathlib.Path('/pkg/statement/logo.png'),
        rel=pathlib.PurePosixPath('logo.png'),
    )
    external = export.ResolvedAsset(
        scope=AssetScope.EXTERNAL,
        source=pathlib.Path('/pkg/vendor/logo.png'),
        rel=pathlib.PurePosixPath('logo.png'),
    )
    layout = export.SubtreeLayout(
        asset_roots={AssetScope.STATEMENT: 'docs', AssetScope.EXTERNAL: 'vendor'}
    )
    with pytest.raises(ValueError) as excinfo:
        export.derive_remap([statement, external], layout, DocumentSlot.body())
    message = str(excinfo.value)
    assert 'logo' in message
    assert str(statement.source) in message
    assert str(external.source) in message


def test_two_assets_landing_on_the_same_destination_are_not_ambiguous():
    # Same key AND same dest: the reference is unambiguous. Whether shipping two
    # files to one path is legal is the bundle's dest guard's problem, not this
    # function's.
    a = export.ResolvedAsset(
        scope=AssetScope.EXTERNAL,
        source=pathlib.Path('/one/logo.png'),
        rel=pathlib.PurePosixPath('logo.png'),
    )
    b = export.ResolvedAsset(
        scope=AssetScope.EXTERNAL,
        source=pathlib.Path('/two/logo.png'),
        rel=pathlib.PurePosixPath('logo.png'),
    )
    remap = export.derive_remap([a, b], export.FlatLayout(), DocumentSlot.body())
    assert remap == {'logo': 'logo.png'}


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


def test_shadowing_survives_a_layout_that_reaches_identity():
    # The sample asset shadows the statement one AND derives an identity. If the
    # identity were dropped before the shadowing were resolved, the statement
    # asset would survive and point the explanation at the wrong image.
    layout = _moj_layout(keep_extension=False)
    statement_named_like_the_sample = _asset(AssetScope.STATEMENT, 'diagram.png')
    remap = export.derive_remap(
        [SAMPLE_ASSET, statement_named_like_the_sample],
        layout,
        DocumentSlot.sample(0),
    )
    assert remap == {}


def test_sample_scope_root_requires_an_index_placeholder():
    with pytest.raises(ValueError):
        export.SubtreeLayout(
            asset_roots={AssetScope.SAMPLE: 'docs/notes'},
            document_dirs={},
        ).place_asset(SAMPLE_ASSET)


def test_sample_explanation_document_dir_requires_an_index_placeholder():
    # Without it every sample's notes collapse into one directory.
    with pytest.raises(ValueError, match='index'):
        export.SubtreeLayout(
            document_dirs={'sample_explanation': 'docs/notes'}
        ).document_dir(DocumentSlot.sample(0))


@pytest.mark.parametrize('template', ['docs/{index}', 'docs/{index:03d}'])
def test_a_root_with_no_index_to_interpolate_rejects_the_placeholder(template):
    # The mirror image of the two tests above: without this, a body dir spelled
    # 'docs/{index}' silently becomes 'docs/None' and '{index:03d}' raises a raw
    # TypeError out of str.format.
    with pytest.raises(ValueError, match='index'):
        export.SubtreeLayout(document_dirs={'body': template}).document_dir(
            DocumentSlot.body()
        )
    with pytest.raises(ValueError, match='index'):
        export.SubtreeLayout(asset_roots={AssetScope.STATEMENT: template}).place_asset(
            STATEMENT_ASSET
        )


def test_unknown_placeholder_in_a_root_is_reported():
    with pytest.raises(ValueError, match='placeholder'):
        export.SubtreeLayout(
            asset_roots={AssetScope.STATEMENT: 'docs/{bogus}'},
            document_dirs={},
        ).place_asset(STATEMENT_ASSET)


# --- DocumentSlot invariant -------------------------------------------------


def test_document_slot_index_is_set_iff_the_slot_is_a_sample_explanation():
    with pytest.raises(ValueError, match='sample_explanation'):
        export.DocumentSlot(kind='sample_explanation')
    with pytest.raises(ValueError, match='sample_explanation'):
        export.DocumentSlot(kind='body', index=5)


def test_document_slot_narrows_its_index_for_sample_slots():
    assert DocumentSlot.sample(3).sample_index == 3


def test_document_slot_is_hashable_so_a_bundle_can_key_on_it():
    assert {DocumentSlot.body(): 'a', DocumentSlot.sample(0): 'b'} == {
        DocumentSlot.body(): 'a',
        DocumentSlot.sample(0): 'b',
    }
