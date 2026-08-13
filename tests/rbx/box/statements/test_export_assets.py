"""Unit tests for scope resolution of statement assets (the target-independent
half of what the Polygon upload used to do inline)."""

import pathlib

import pytest

from rbx.box.packaging.polygon import upload
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


@pytest.fixture
def overlay(tmp_path, monkeypatch) -> pathlib.Path:
    """The staged tree of `_build_tree`, with the two filesystem seams
    (`get_statement_dir` / `get_produced_tikz_pdfs`) stubbed out."""
    built = _build_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: built)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])
    return built


def test_resolve_assets_tags_every_scope(tmp_path, overlay):
    assert export.resolve_assets(_statement(), {0}) == [
        export.ResolvedAsset(
            scope=export.AssetScope.STATEMENT,
            source=tmp_path / 'statement' / 'img' / 'd.png',
            rel=pathlib.PurePosixPath('img/d.png'),
        ),
        export.ResolvedAsset(
            scope=export.AssetScope.STATEMENT,
            source=tmp_path / 'statement' / 'pic.png',
            rel=pathlib.PurePosixPath('pic.png'),
        ),
        export.ResolvedAsset(
            scope=export.AssetScope.EXTERNAL,
            source=tmp_path / 'extra' / 'logo.png',
            rel=pathlib.PurePosixPath('extra/logo.png'),
        ),
        export.ResolvedAsset(
            scope=export.AssetScope.SAMPLE,
            source=overlay / '.samples' / '000' / 'diagram.png',
            rel=pathlib.PurePosixPath('diagram.png'),
            sample_index=0,
        ),
    ]


def test_resolve_assets_includes_tikz_relative_to_overlay(
    tmp_path, monkeypatch, overlay
):
    tikz = overlay / 'artifacts' / 'tikz_figures'
    tikz.mkdir(parents=True)
    (tikz / 'i_0.pdf').touch()
    monkeypatch.setattr(
        export,
        'get_produced_tikz_pdfs',
        lambda statement: [
            (tikz / 'i_0.pdf', pathlib.Path('artifacts/tikz_figures/i_0.pdf'))
        ],
    )

    assets = export.resolve_assets(_statement(), set())
    assert [a for a in assets if a.scope == export.AssetScope.TIKZ] == [
        export.ResolvedAsset(
            scope=export.AssetScope.TIKZ,
            source=tikz / 'i_0.pdf',
            rel=pathlib.PurePosixPath('artifacts/tikz_figures/i_0.pdf'),
        )
    ]


def test_resolve_assets_explicit_asset_under_statement_dir_any_extension(
    tmp_path, monkeypatch
):
    (tmp_path / 'statement').mkdir()
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()
    (tmp_path / 'statement' / 'figure.svg').touch()
    built = tmp_path / 'overlay'
    built.mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: built)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])

    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['statement/figure.svg'],
    )
    assert export.resolve_assets(statement, set()) == [
        export.ResolvedAsset(
            scope=export.AssetScope.STATEMENT,
            source=tmp_path / 'statement' / 'figure.svg',
            rel=pathlib.PurePosixPath('figure.svg'),
        )
    ]


def test_resolve_assets_dedupes_explicit_asset_already_picked_up(tmp_path, overlay):
    # `img/d.png` is both an image/PDF default and an explicit asset; it must be
    # resolved once, and the dedupe must key on the source, not on `rel`.
    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['statement/img/d.png'],
    )
    assert [a.source for a in export.resolve_assets(statement, set())] == [
        tmp_path / 'statement' / 'img' / 'd.png',
        tmp_path / 'statement' / 'pic.png',
    ]


def test_resolve_assets_scopes_each_sample_separately(tmp_path, overlay):
    # A two-digit index exercises the `{idx:03d}` staged-folder padding.
    (overlay / '.samples' / '012').mkdir()
    (overlay / '.samples' / '012' / 'diagram.png').touch()

    samples = [
        a
        for a in export.resolve_assets(_statement(), {0, 12})
        if a.scope == export.AssetScope.SAMPLE
    ]
    assert [(a.sample, str(a.rel)) for a in samples] == [
        (0, 'diagram.png'),
        (12, 'diagram.png'),
    ]
    assert [a.source for a in samples] == [
        overlay / '.samples' / '000' / 'diagram.png',
        overlay / '.samples' / '012' / 'diagram.png',
    ]


def test_resolve_assets_falls_back_to_the_bare_name_outside_the_package(
    tmp_path, monkeypatch
):
    pkg = tmp_path / 'pkg'
    (pkg / 'statement').mkdir(parents=True)
    (pkg / 'statement' / 'statement.rbx.tex').touch()
    (tmp_path / 'sibling').mkdir()
    (tmp_path / 'sibling' / 'logo.png').touch()
    built = pkg / 'overlay'
    built.mkdir()

    monkeypatch.chdir(pkg)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: built)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])

    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['../sibling/logo.png'],
    )
    assert export.resolve_assets(statement, set()) == [
        export.ResolvedAsset(
            scope=export.AssetScope.EXTERNAL,
            source=tmp_path / 'sibling' / 'logo.png',
            rel=pathlib.PurePosixPath('logo.png'),
        )
    ]


def test_resolve_assets_without_a_statement_file_scopes_the_whole_package(
    tmp_path, overlay
):
    # Pins surprising-but-current behavior: with no `file`, the statement dir
    # collapses to the package root, so the image/PDF default walks the entire
    # package (build outputs included) and nothing can ever be EXTERNAL.
    statement = Statement(
        language='en',
        extends='pt',  # a `file` is only required without `extends`
        assets=['extra/logo.png'],
    )
    assets = export.resolve_assets(statement, set())
    assert {a.scope for a in assets} == {export.AssetScope.STATEMENT}
    assert [str(a.rel) for a in assets] == [
        'build/overlay/.samples/000/diagram.png',
        'extra/logo.png',
        'statement/img/d.png',
        'statement/pic.png',
    ]


@pytest.mark.parametrize(
    'scope,sample_index',
    [
        (export.AssetScope.SAMPLE, None),
        (export.AssetScope.EXTERNAL, 3),
        (export.AssetScope.STATEMENT, 0),
    ],
)
def test_resolved_asset_rejects_a_mismatched_sample_index(scope, sample_index):
    with pytest.raises(ValueError, match='sample_index must be set iff'):
        export.ResolvedAsset(
            scope=scope,
            source=pathlib.Path('/abs/d.png'),
            rel=pathlib.PurePosixPath('d.png'),
            sample_index=sample_index,
        )


def test_resolved_asset_ref_key_drops_the_extension():
    asset = export.ResolvedAsset(
        scope=export.AssetScope.STATEMENT,
        source=pathlib.Path('/abs/statement/img/d.png'),
        rel=pathlib.PurePosixPath('img/d.png'),
    )
    assert asset.ref_key == 'img/d'


def _flat_name(asset: export.ResolvedAsset) -> str:
    """The Polygon uploaded name for an asset, i.e. what `_collect_assets` bakes
    in and `resolve_assets` deliberately leaves to a layout."""
    flat = str(asset.rel).replace('/', '__')
    if asset.scope == export.AssetScope.SAMPLE:
        return f'sample_{asset.sample}__{flat}'
    return flat


def test_resolve_assets_matches_collect_assets_under_the_flat_naming(
    tmp_path, monkeypatch
):
    """Port guard (design §8): `resolve_assets` is `_collect_assets` minus the
    naming, so projecting the flat name back onto it must reproduce the uploads
    and remaps byte for byte.

    DELETE THIS TEST IN TASK 6, together with `_collect_assets`. It reaches into
    a private Polygon helper on purpose and only to keep the two implementations
    honest while they coexist.
    """
    (tmp_path / 'statement' / 'img').mkdir(parents=True)
    (tmp_path / 'statement' / 'img' / 'd.png').touch()
    (tmp_path / 'statement' / 'pic.png').touch()
    (tmp_path / 'statement' / 'figure.svg').touch()
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()
    (tmp_path / 'statement' / 'samples').mkdir()
    (tmp_path / 'statement' / 'samples' / '000.in').touch()
    (tmp_path / 'extra' / 'deep').mkdir(parents=True)
    (tmp_path / 'extra' / 'deep' / 'logo.png').touch()

    built = tmp_path / 'build' / 'overlay'
    (built / '.samples' / '000' / 'sub').mkdir(parents=True)
    (built / '.samples' / '000' / 'diagram.png').touch()
    (built / '.samples' / '000' / 'sub' / 'e.pdf').touch()
    (built / '.samples' / '000' / 'in').touch()
    tikz = built / 'artifacts' / 'tikz_figures'
    tikz.mkdir(parents=True)
    (tikz / 'i_0.pdf').touch()

    monkeypatch.chdir(tmp_path)
    for module in (upload, export):
        monkeypatch.setattr(module, 'get_statement_dir', lambda statement: built)
        monkeypatch.setattr(
            module,
            'get_produced_tikz_pdfs',
            lambda statement: [
                (tikz / 'i_0.pdf', pathlib.Path('artifacts/tikz_figures/i_0.pdf'))
            ],
        )

    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        # A recursive glob, a non-image extension, and a duplicate of a file the
        # image/PDF default already picks up.
        assets=['extra/**/*.png', 'statement/figure.svg', 'statement/img/d.png'],
    )

    uploads, remaps = upload._collect_assets(statement, {0})  # noqa: SLF001
    assets = export.resolve_assets(statement, {0})

    assert {_flat_name(a): a.source for a in assets} == uploads
    # TikZ is its own scope here, but Polygon folds it into the statement remap.
    assert {
        a.ref_key: _flat_name(a)
        for a in assets
        if a.scope in (export.AssetScope.STATEMENT, export.AssetScope.TIKZ)
    } == remaps.statement
    assert {
        0: {
            a.ref_key: _flat_name(a)
            for a in assets
            if a.scope == export.AssetScope.SAMPLE
        }
    } == remaps.samples
