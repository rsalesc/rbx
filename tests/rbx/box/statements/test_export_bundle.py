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


def test_bundle_materializes_the_root_when_there_are_no_assets(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    # A statement with no images at all: whoever tars the root still needs it.
    (tmp_path / 'statement' / 'img' / 'd.png').unlink()
    (tmp_path / 'overlay' / '.samples' / '000' / 'diagram.png').unlink()
    bundle = export.build_statement_bundle(statement, layout=_subtree_layout())

    into = tmp_path / 'out'
    bundle.materialize(into)

    assert bundle.assets == []
    assert into.is_dir()


def test_materialized_bytes_match_the_content_property(tmp_path, monkeypatch):
    # `.content` reads the source and `materialize` copies it: two deliberately
    # separate read paths that "do not double-buffer each other". They must still
    # agree, and only FlatLayout exercises the naming side of materialize.
    statement = _setup(tmp_path, monkeypatch)
    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())

    into = tmp_path / 'out'
    bundle.materialize(into)

    assert bundle.assets
    for bundled in bundle.assets:
        assert (into / bundled.dest).read_bytes() == bundled.content


def test_a_layout_missing_the_sample_explanation_dir_fails_on_any_explanation(
    tmp_path, monkeypatch
):
    # `build_statement_bundle` derives a remap per explanation index, so this
    # explodes on a statement that merely HAS an explanation -- images or not.
    statement = _setup(
        tmp_path,
        monkeypatch,
        blocks=StatementBlocks(blocks={'legend': ''}, explanations={0: 'no images'}),
    )
    layout = export.SubtreeLayout(
        asset_roots={
            AssetScope.STATEMENT: 'docs',
            AssetScope.SAMPLE: 'docs/notes/{index:03d}',
        },
        document_dirs={'body': 'docs'},
    )
    with pytest.raises(export.StatementExportError) as excinfo:
        export.build_statement_bundle(statement, layout=layout)
    assert "document_dirs['sample_explanation']" in str(excinfo.value)


def test_bundled_asset_exposes_content_without_materializing(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())
    by_dest = {str(a.dest): a for a in bundle.assets}
    assert by_dest['img__d.png'].content == b'PNGDATA'


def test_bundled_asset_reports_its_size_without_reading_it(tmp_path, monkeypatch):
    statement = _setup(tmp_path, monkeypatch)
    bundle = export.build_statement_bundle(statement, layout=export.FlatLayout())
    by_dest = {str(a.dest): a for a in bundle.assets}
    assert by_dest['img__d.png'].size == len(b'PNGDATA')
    assert by_dest['sample_0__diagram.png'].size == len(b'SAMPLEDATA')


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
    with pytest.raises(export.StatementExportError) as exc:
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

    # Counted, not just set-compared: a set of destinations would hide a duplicate
    # entry, and a duplicate is exactly what the guard must keep tolerating.
    assert len(bundle.assets) == 2
    assert {str(a.dest) for a in bundle.assets} == {
        'img__d.png',
        'sample_0__diagram.png',
    }
