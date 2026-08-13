"""The bundle: blocks rewritten for a layout, assets placed, materializable."""

import pathlib

import pytest

from rbx.box.statements import export
from rbx.box.statements.export import AssetScope, DocumentSlot
from rbx.box.statements.render import StatementBlocks
from rbx.box.statements.schema import Statement


def _setup(tmp_path, monkeypatch, blocks=None):
    (tmp_path / 'statement' / 'img').mkdir(parents=True)
    (tmp_path / 'statement' / 'img' / 'd.png').write_bytes(b'PNGDATA')
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()
    overlay = tmp_path / 'overlay'
    (overlay / '.samples' / '000').mkdir(parents=True)
    (overlay / '.samples' / '000' / 'diagram.png').write_bytes(b'SAMPLEDATA')

    if blocks is None:
        blocks = StatementBlocks(
            blocks={'legend': r'\includegraphics{img/d}'},
            explanations={0: r'\includegraphics{diagram}'},
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])
    monkeypatch.setattr(
        export,
        'get_processed_statement_blocks',
        lambda statement, normalize=True: blocks.model_copy(deep=True),
    )
    return Statement(language='en', file=pathlib.Path('statement/statement.rbx.tex'))


def _subtree_layout(**kwargs) -> export.SubtreeLayout:
    return export.SubtreeLayout(
        asset_roots={
            AssetScope.STATEMENT: 'docs',
            AssetScope.SAMPLE: 'docs/notes/{index:03d}',
        },
        document_dirs={
            'body': 'docs',
            'sample_explanation': 'docs/notes/{index:03d}',
        },
        **kwargs,
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


def test_bundle_leaves_blocks_untouched_under_an_identity_layout(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    bundle = export.build_statement_bundle(
        statement, layout=_subtree_layout(keep_extension=False)
    )

    assert bundle.blocks['legend'] == r'\includegraphics{img/d}'
    assert bundle.explanations[0] == r'\includegraphics{diagram}'
    assert bundle.remaps[DocumentSlot.body()] == {}


def test_bundle_materializes_into_a_multi_root_tree(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    bundle = export.build_statement_bundle(statement, layout=_subtree_layout())

    into = tmp_path / 'out'
    bundle.materialize(into)

    assert (into / 'docs' / 'img' / 'd.png').read_bytes() == b'PNGDATA'
    assert (
        into / 'docs' / 'notes' / '000' / 'diagram.png'
    ).read_bytes() == b'SAMPLEDATA'


def test_bundle_materialize_is_idempotent(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    bundle = export.build_statement_bundle(statement, layout=_subtree_layout())

    into = tmp_path / 'out'
    bundle.materialize(into)
    bundle.materialize(into)

    assert (into / 'docs' / 'img' / 'd.png').read_bytes() == b'PNGDATA'


def test_bundled_asset_exposes_content_without_materializing(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())
    by_dest = {str(a.dest): a for a in bundle.assets}
    assert by_dest['img__d.png'].content == b'PNGDATA'


def test_bundle_without_explanations_ships_no_sample_assets(tmp_path, monkeypatch):
    statement = _setup(
        tmp_path,
        monkeypatch,
        blocks=StatementBlocks(blocks={'legend': r'\includegraphics{img/d}'}),
    )
    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())

    assert bundle.explanations == {}
    assert list(bundle.remaps) == [DocumentSlot.body()]
    assert {str(a.dest) for a in bundle.assets} == {'img__d.png'}
    assert bundle.blocks['legend'] == r'\includegraphics{img__d.png}'


def test_bundle_rejects_two_sources_landing_on_one_destination(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    # A package-root `img/d.png` reached by an `assets` glob is EXTERNAL-scope,
    # and its package-root-relative path matches the statement-dir asset's. The
    # two collide the moment a layout maps both scopes onto one root -- which is
    # not something FlatLayout alone can be blamed for.
    (tmp_path / 'img').mkdir()
    (tmp_path / 'img' / 'd.png').write_bytes(b'OTHERDATA')
    statement.assets = ['img/*.png']

    layout = export.SubtreeLayout(
        asset_roots={
            AssetScope.STATEMENT: 'docs',
            AssetScope.EXTERNAL: 'docs',
            AssetScope.SAMPLE: 'docs/notes/{index:03d}',
        },
        document_dirs={
            'body': 'docs',
            'sample_explanation': 'docs/notes/{index:03d}',
        },
    )
    with pytest.raises(ValueError) as exc:
        export.build_statement_bundle(statement, layout=layout)

    message = str(exc.value)
    assert str(tmp_path / 'statement' / 'img' / 'd.png') in message
    assert str(tmp_path / 'img' / 'd.png') in message
    assert 'docs/img/d.png' in message


def test_bundle_accepts_a_png_pdf_pair_that_shares_a_reference(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    # `img/d.png` next to its vector export: one reference key, two destinations.
    # graphicx precedence decides the reference; both files still ship.
    (tmp_path / 'statement' / 'img' / 'd.pdf').write_bytes(b'PDFDATA')

    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())

    assert {str(a.dest) for a in bundle.assets} == {
        'img__d.png',
        'img__d.pdf',
        'sample_0__diagram.png',
    }
    assert bundle.blocks['legend'] == r'\includegraphics{img__d.pdf}'


def test_bundle_accepts_one_source_reached_twice(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    # The same file picked up by the statement-dir image sweep AND by an explicit
    # `assets` glob is one asset, not a collision.
    statement.assets = ['statement/img/*.png']

    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())

    assert {str(a.dest) for a in bundle.assets} == {
        'img__d.png',
        'sample_0__diagram.png',
    }
