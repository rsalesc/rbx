"""Unit tests for the scoped statement-resource collection + reference rewriting
that backs the explicit `assets` field (#595, audit findings #5/#6)."""

import pathlib

from rbx import utils
from rbx.box.packaging.polygon import upload
from rbx.box.statements.schema import Statement

# ---------------------------------------------------------------------------
# Pure helpers: glob resolution + flat naming (Task 3)
# ---------------------------------------------------------------------------


def test_resolve_asset_globs_dedup_sorted_files_only(tmp_path):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'a' / 'x.png').touch()
    (tmp_path / 'a' / 'y.png').touch()
    (tmp_path / 'b.png').touch()
    (tmp_path / 'a' / 'sub').mkdir()  # a directory matched by ** but skipped

    out = upload._resolve_asset_globs(tmp_path, ['**/*.png', 'a/*.png'])  # noqa: SLF001

    assert out == [
        utils.abspath(tmp_path / 'a' / 'x.png'),
        utils.abspath(tmp_path / 'a' / 'y.png'),
        utils.abspath(tmp_path / 'b.png'),
    ]


def test_flat_name_and_remap_key():
    assert upload._flat_name(pathlib.Path('img/diagram.png')) == 'img__diagram.png'  # noqa: SLF001
    assert upload._flat_name(pathlib.Path('pic.png')) == 'pic.png'  # noqa: SLF001
    assert upload._remap_key(pathlib.Path('img/diagram.png')) == 'img/diagram'  # noqa: SLF001
    assert upload._remap_key(pathlib.Path('pic.png')) == 'pic'  # noqa: SLF001


def test_image_files_under_filters_non_images(tmp_path):
    (tmp_path / 'p.png').touch()
    (tmp_path / 'doc.PDF').touch()  # case-insensitive extension
    (tmp_path / 's.in').touch()
    (tmp_path / 'e.rbx.tex').touch()

    assert upload._image_files_under(tmp_path) == [  # noqa: SLF001
        tmp_path / 'doc.PDF',
        tmp_path / 'p.png',
    ]


def test_image_files_under_missing_dir_returns_empty(tmp_path):
    assert upload._image_files_under(tmp_path / 'nope') == []  # noqa: SLF001


# ---------------------------------------------------------------------------
# TexSoup-based \includegraphics rewrite (Task 4, fixes audit finding #6)
# ---------------------------------------------------------------------------


def _rewrite(block, remap):
    return upload._rewrite_includegraphics(block, remap)  # noqa: SLF001


def test_rewrite_subdir_reference():
    out = _rewrite(
        r'see \includegraphics{img/diagram}.', {'img/diagram': 'img__diagram.png'}
    )
    assert r'\includegraphics{img__diagram.png}' in out


def test_rewrite_root_level_reference():
    # Finding #6 uniformity: a root-level reference is rewritten to the flat name
    # instead of relying on Polygon resolving the bare stem.
    out = _rewrite(r'\includegraphics{pic}', {'pic': 'pic.png'})
    assert out.strip() == r'\includegraphics{pic.png}'


def test_rewrite_with_extension_no_double_ext():
    # Finding #6: a sub-dir asset referenced WITH its extension must not become
    # `imgs__fig.png.png`.
    out = _rewrite(r'\includegraphics{imgs/fig.png}', {'imgs/fig': 'imgs__fig.png'})
    assert 'imgs__fig.png.png' not in out
    assert r'\includegraphics{imgs__fig.png}' in out


def test_rewrite_preserves_optional_arg():
    out = _rewrite(r'\includegraphics[width=1cm]{pic}', {'pic': 'pic.png'})
    assert r'\includegraphics[width=1cm]{pic.png}' in out


def test_rewrite_leaves_unmapped_untouched():
    src = r'\includegraphics{artifacts/tikz_figures/0_0}'
    assert _rewrite(src, {'pic': 'pic.png'}).strip() == src


def test_rewrite_empty_remap_is_identity():
    src = r'text \includegraphics{pic} more'
    assert _rewrite(src, {}) == src


# ---------------------------------------------------------------------------
# Scoped collection: statement / sample / out-of-tree (Task 5, findings #5/#6)
# ---------------------------------------------------------------------------


def test_collect_assets_three_scopes(tmp_path, monkeypatch):
    # Package root layout.
    (tmp_path / 'statement' / 'img').mkdir(parents=True)
    (tmp_path / 'statement' / 'img' / 'd.png').touch()
    (tmp_path / 'statement' / 'pic.png').touch()
    (tmp_path / 'statement' / 'samples').mkdir()
    (tmp_path / 'statement' / 'samples' / '000.in').touch()  # noise, must be dropped
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()  # source, must be dropped
    (tmp_path / 'extra').mkdir()
    (tmp_path / 'extra' / 'logo.png').touch()  # out-of-tree, declared via assets

    # Fake built overlay with a staged external sample image.
    overlay = tmp_path / 'build' / 'overlay'
    (overlay / '.samples' / '000').mkdir(parents=True)
    (overlay / '.samples' / '000' / 'diagram.png').touch()
    (overlay / '.samples' / '000' / 'in').touch()  # noise, must be dropped

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upload, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(upload, 'get_produced_tikz_pdfs', lambda statement: [])

    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['extra/logo.png'],
    )

    uploads, remaps = upload._collect_assets(statement, {0})  # noqa: SLF001

    assert set(uploads) == {
        'img__d.png',
        'pic.png',
        'extra__logo.png',
        'sample_0__diagram.png',
    }
    # No sample I/O or statement source leaks in (finding #5).
    assert not any(name.endswith(('.in', '.rbx.tex')) for name in uploads)
    # Statement-scope remap is statement-dir-relative; out-of-tree is NOT remapped.
    assert remaps.statement == {'img/d': 'img__d.png', 'pic': 'pic.png'}
    # Sample-scope remap is per-index, sample-dir-relative, namespaced.
    assert remaps.samples == {0: {'diagram': 'sample_0__diagram.png'}}


def test_collect_assets_explicit_asset_under_statement_dir(tmp_path, monkeypatch):
    # A non-default extension under the statement dir is shipped only because it
    # is declared via `assets` (defaults cover image/PDF only).
    (tmp_path / 'statement').mkdir()
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()
    (tmp_path / 'statement' / 'figure.svg').touch()

    overlay = tmp_path / 'overlay'
    overlay.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upload, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(upload, 'get_produced_tikz_pdfs', lambda statement: [])

    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['statement/figure.svg'],
    )
    uploads, remaps = upload._collect_assets(statement, set())  # noqa: SLF001

    assert set(uploads) == {'figure.svg'}
    assert remaps.statement == {'figure': 'figure.svg'}
