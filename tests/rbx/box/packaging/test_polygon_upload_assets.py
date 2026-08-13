"""The Polygon upload's statement resources, asserted through the bundle it now
consumes (#595, audit findings #5/#6).

These are port guards: `upload.py` used to resolve, name and rewrite its own
assets, and the extraction into `rbx.box.statements.export` must not change a
single uploaded resource name -- a live Polygon problem references them by name.
The one intended difference is pinned in
`test_out_of_tree_assets_are_now_remapped` (design §7).
"""

import pathlib
from typing import List, Tuple

import pytest
import typer

from rbx.box.packaging.polygon import upload
from rbx.box.statements import export
from rbx.box.statements.render import StatementBlocks
from rbx.box.statements.schema import Statement


def _stub_blocks(monkeypatch, blocks=None, explanations=None):
    monkeypatch.setattr(
        export,
        'get_processed_statement_blocks',
        lambda statement, normalize=True: StatementBlocks(
            blocks=dict(blocks or {}),
            explanations=dict(explanations or {}),
        ),
    )


def _simple_tree(tmp_path, monkeypatch, *, explanations=None, blocks=None):
    """The fixture the pre-extraction test used, verbatim."""
    (tmp_path / 'statement' / 'img').mkdir(parents=True)
    (tmp_path / 'statement' / 'img' / 'd.png').touch()
    (tmp_path / 'statement' / 'pic.png').touch()
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()  # source, dropped
    (tmp_path / 'statement' / 'samples').mkdir()
    (tmp_path / 'statement' / 'samples' / '000.in').touch()  # noise, dropped
    (tmp_path / 'extra').mkdir()
    (tmp_path / 'extra' / 'logo.png').touch()  # out-of-tree, declared via assets

    overlay = tmp_path / 'build' / 'overlay'
    (overlay / '.samples' / '000').mkdir(parents=True)
    (overlay / '.samples' / '000' / 'diagram.png').touch()
    (overlay / '.samples' / '000' / 'in').touch()  # noise, dropped

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])
    _stub_blocks(monkeypatch, blocks=blocks, explanations=explanations or {0: ''})

    return Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['extra/logo.png'],
    )


def _bundle(statement) -> export.StatementBundle:
    return export.build_statement_bundle(statement, layout=export.FlatLayout())


def test_polygon_bundle_reproduces_the_expected_flat_resource_set(
    tmp_path, monkeypatch
):
    bundle = _bundle(_simple_tree(tmp_path, monkeypatch))

    assert {str(a.dest) for a in bundle.assets} == {
        'img__d.png',
        'pic.png',
        'extra__logo.png',
        'sample_0__diagram.png',
    }
    # No sample I/O or statement source leaks in (finding #5).
    assert not any(str(a.dest).endswith(('.in', '.rbx.tex')) for a in bundle.assets)


def test_out_of_tree_assets_are_now_remapped(tmp_path, monkeypatch):
    # Design §7: previously the author had to spell the uploaded flat name by
    # hand, because out-of-tree `assets` got no remap at all. They now get one,
    # keyed on their package-root-relative path.
    bundle = _bundle(_simple_tree(tmp_path, monkeypatch))

    assert bundle.remaps[export.DocumentSlot.body()] == {
        'img/d': 'img__d.png',
        'pic': 'pic.png',
        'extra/logo': 'extra__logo.png',
    }


# ---------------------------------------------------------------------------
# Name preservation on a realistic tree
# ---------------------------------------------------------------------------


def _realistic_tree(tmp_path, monkeypatch, *, blocks=None, explanations=None):
    """Every scope at once: statement images in a subdir, a non-image asset
    declared explicitly, a recursive out-of-tree glob, externalized TikZ, and a
    sample with a nested image."""
    (tmp_path / 'statement' / 'img').mkdir(parents=True)
    (tmp_path / 'statement' / 'img' / 'd.png').write_bytes(b'd')
    (tmp_path / 'statement' / 'pic.png').write_bytes(b'pic')
    (tmp_path / 'statement' / 'figure.svg').write_bytes(b'svg')
    (tmp_path / 'statement' / 'statement.rbx.tex').touch()
    (tmp_path / 'statement' / 'samples').mkdir()
    (tmp_path / 'statement' / 'samples' / '000.in').touch()
    (tmp_path / 'extra' / 'deep').mkdir(parents=True)
    (tmp_path / 'extra' / 'deep' / 'logo.png').write_bytes(b'logo')

    overlay = tmp_path / 'build' / 'overlay'
    (overlay / '.samples' / '000' / 'sub').mkdir(parents=True)
    (overlay / '.samples' / '000' / 'diagram.png').write_bytes(b'diagram')
    (overlay / '.samples' / '000' / 'sub' / 'e.pdf').write_bytes(b'e')
    (overlay / '.samples' / '000' / 'in').touch()
    tikz = overlay / 'artifacts' / 'tikz_figures'
    tikz.mkdir(parents=True)
    (tikz / 'i_0.pdf').write_bytes(b'tikz')

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(
        export,
        'get_produced_tikz_pdfs',
        lambda statement: [
            (tikz / 'i_0.pdf', pathlib.Path('artifacts/tikz_figures/i_0.pdf'))
        ],
    )
    _stub_blocks(monkeypatch, blocks=blocks, explanations=explanations or {0: ''})

    return Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        # A recursive glob, a non-image extension, and a duplicate of a file the
        # image/PDF default already picks up.
        assets=['extra/**/*.png', 'statement/figure.svg', 'statement/img/d.png'],
    )


#: What `upload.py:_collect_assets` produced for `_realistic_tree` before the
#: extraction. Frozen on purpose: these strings are the resource names a live
#: Polygon problem's statement references.
_EXPECTED_UPLOADED_NAMES = [
    'artifacts__tikz_figures__i_0.pdf',
    'extra__deep__logo.png',
    'figure.svg',
    'img__d.png',
    'pic.png',
    'sample_0__diagram.png',
    'sample_0__sub__e.pdf',
]


def test_uploaded_resource_names_are_unchanged_on_a_realistic_tree(
    tmp_path, monkeypatch
):
    bundle = _bundle(_realistic_tree(tmp_path, monkeypatch))

    assert sorted(str(a.dest) for a in bundle.assets) == _EXPECTED_UPLOADED_NAMES


def test_realistic_tree_remaps_preserve_the_old_rewrites(tmp_path, monkeypatch):
    bundle = _bundle(_realistic_tree(tmp_path, monkeypatch))

    # The old `_AssetRemaps.statement` (statement + TikZ scopes), plus the
    # out-of-tree entry it lacked (design §7).
    assert bundle.remaps[export.DocumentSlot.body()] == {
        'img/d': 'img__d.png',
        'pic': 'pic.png',
        'figure': 'figure.svg',
        'artifacts/tikz_figures/i_0': 'artifacts__tikz_figures__i_0.pdf',
        'extra/deep/logo': 'extra__deep__logo.png',
    }
    # The old per-explanation merge (statement remap updated with the sample's)
    # is now what `derive_remap` yields for the sample slot.
    assert bundle.remaps[export.DocumentSlot.sample(0)] == {
        'img/d': 'img__d.png',
        'pic': 'pic.png',
        'figure': 'figure.svg',
        'artifacts/tikz_figures/i_0': 'artifacts__tikz_figures__i_0.pdf',
        'extra/deep/logo': 'extra__deep__logo.png',
        'diagram': 'sample_0__diagram.png',
        'sub/e': 'sample_0__sub__e.pdf',
    }


def test_blocks_and_explanations_arrive_rewritten(tmp_path, monkeypatch):
    statement = _realistic_tree(
        tmp_path,
        monkeypatch,
        blocks={'legend': r'A \includegraphics[width=1cm]{img/d} B'},
        explanations={0: r'See \includegraphics{diagram}.'},
    )
    bundle = _bundle(statement)

    assert bundle.blocks['legend'] == r'A \includegraphics[width=1cm]{img__d.png} B'
    assert bundle.explanations[0] == r'See \includegraphics{sample_0__diagram.png}.'


# ---------------------------------------------------------------------------
# The upload itself (`_upload_statement_resources`)
# ---------------------------------------------------------------------------


class _FakeProblem:
    def __init__(self):
        self.saved: List[Tuple[str, bytes]] = []

    def save_statement_resource(self, name, file):
        self.saved.append((name, file))


def test_resources_are_uploaded_by_flat_name_in_sorted_order(tmp_path, monkeypatch):
    bundle = _bundle(_realistic_tree(tmp_path, monkeypatch))
    problem = _FakeProblem()

    upload._upload_statement_resources(problem, bundle)  # pyright: ignore # noqa: SLF001

    assert [name for name, _ in problem.saved] == _EXPECTED_UPLOADED_NAMES
    assert dict(problem.saved)['sample_0__diagram.png'] == b'diagram'
    assert dict(problem.saved)['extra__deep__logo.png'] == b'logo'


def test_oversized_resource_aborts_the_upload(tmp_path, monkeypatch):
    statement = _simple_tree(tmp_path, monkeypatch)
    (tmp_path / 'statement' / 'pic.png').write_bytes(b'x' * (1024 * 1024))
    bundle = _bundle(statement)
    problem = _FakeProblem()

    with pytest.raises(typer.Exit):
        upload._upload_statement_resources(problem, bundle)  # pyright: ignore # noqa: SLF001

    # Aborted before the offending resource was handed to the API.
    assert 'pic.png' not in [name for name, _ in problem.saved]


# ---------------------------------------------------------------------------
# Error surface at the CLI boundary
# ---------------------------------------------------------------------------


def test_ambiguous_assets_exit_instead_of_raising(tmp_path, monkeypatch):
    _simple_tree(tmp_path, monkeypatch)
    # `extra/logo.png` and a root-level `extra__logo.png` flatten to the same
    # uploaded name, which `export` rejects. A setter must see an error message,
    # not a `ValueError` traceback.
    (tmp_path / 'extra__logo.png').write_bytes(b'other')
    statement = Statement(
        language='en',
        file=pathlib.Path('statement/statement.rbx.tex'),
        assets=['extra/logo.png', 'extra__logo.png'],
    )

    with pytest.raises(typer.Exit):
        upload._build_bundle(statement)  # noqa: SLF001
