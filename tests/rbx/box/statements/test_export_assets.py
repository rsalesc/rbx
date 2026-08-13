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
        lambda statement: [
            (tikz / 'i_0.pdf', pathlib.Path('artifacts/tikz_figures/i_0.pdf'))
        ],
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


def test_resolve_assets_dedupes_explicit_asset_already_picked_up(tmp_path, monkeypatch):
    overlay = _build_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])

    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['statement/img/d.png'],
    )
    assets = export.resolve_assets(statement, set())
    assert [(a.scope, str(a.rel)) for a in assets] == [
        (export.AssetScope.STATEMENT, 'img/d.png'),
        (export.AssetScope.STATEMENT, 'pic.png'),
    ]


def test_resolved_asset_ref_key_drops_the_extension():
    asset = export.ResolvedAsset(
        scope=export.AssetScope.STATEMENT,
        source=pathlib.Path('/abs/statement/img/d.png'),
        rel=pathlib.PurePosixPath('img/d.png'),
    )
    assert asset.ref_key == 'img/d'
