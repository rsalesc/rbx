import json

import pytest

from rbx.box.packaging.polygon import polygon_api as api
from tests.e2e import polygon_capture
from tests.e2e.assertions import AssertionContext, check_polygon_upload
from tests.e2e.spec import PolygonUploadMatcher


def test_recording_problem_serializes_statement_and_resources(tmp_path):
    capture_dir = tmp_path / 'cap'
    polygon_capture.set_capture_dir(capture_dir)
    try:
        client = polygon_capture.make_recording_polygon()
        assert client.problems_list(name='x') == []
        problem = client.problem_create('x')
        problem.save_statement_resource(name='img__d.png', file=b'PNG')
        problem.save_statement(
            lang='english',
            problem_statement=api.Statement(
                encoding='utf-8',
                name='Title',
                legend=r'\includegraphics{img__d.png}',
                input='in',
                output='out',
                notes='',
            ),
        )
        problem.commit_changes()
    finally:
        polygon_capture.reset_capture_dir()

    data = json.loads((capture_dir / 'statements' / 'english.json').read_text())
    assert data['name'] == 'Title'
    assert r'\includegraphics{img__d.png}' in data['legend']
    assert (capture_dir / 'resources' / 'img__d.png').read_bytes() == b'PNG'
    assert 'img__d.png' in json.loads((capture_dir / 'resources.json').read_text())


def _ctx(pkg_root):
    return AssertionContext(package_root=pkg_root, stdout='', stderr='')


def _write_capture(pkg_root, *, legend, resources):
    cap = pkg_root / '.rbx' / 'polygon_capture'
    (cap / 'statements').mkdir(parents=True, exist_ok=True)
    (cap / 'resources').mkdir(parents=True, exist_ok=True)
    (cap / 'statements' / 'english.json').write_text(
        json.dumps(
            {
                'name': 'Title',
                'legend': legend,
                'input': 'in',
                'output': 'out',
                'interaction': None,
                'notes': '',
            }
        )
    )
    for r in resources:
        (cap / 'resources' / r).write_bytes(b'x')
    (cap / 'resources.json').write_text(json.dumps(sorted(resources)))


def test_polygon_upload_matcher_passes(tmp_path):
    _write_capture(tmp_path, legend=r'\includegraphics{foo.pdf}', resources=['foo.pdf'])
    m = PolygonUploadMatcher(
        statements={
            'english': {'legend_contains': 'includegraphics', 'name_contains': 'Title'}
        },
        resources_present=['foo.pdf'],
        resources_referenced_consistent=True,
    )
    check_polygon_upload(_ctx(tmp_path), m)  # no raise


def test_polygon_upload_matcher_extensionless_reference_matches_stem(tmp_path):
    # \includegraphics{img__d} should match an uploaded ``img__d.png``.
    _write_capture(
        tmp_path, legend=r'\includegraphics{img__d}', resources=['img__d.png']
    )
    m = PolygonUploadMatcher(resources_referenced_consistent=True)
    check_polygon_upload(_ctx(tmp_path), m)  # no raise


def test_polygon_upload_matcher_detects_orphan_reference(tmp_path):
    _write_capture(
        tmp_path, legend=r'\includegraphics{missing.pdf}', resources=['foo.pdf']
    )
    m = PolygonUploadMatcher(resources_referenced_consistent=True)
    with pytest.raises(AssertionError, match='missing.pdf'):
        check_polygon_upload(_ctx(tmp_path), m)


def test_polygon_upload_matcher_missing_resource_present(tmp_path):
    _write_capture(tmp_path, legend='no images', resources=['foo.pdf'])
    m = PolygonUploadMatcher(resources_present=['bar.pdf'])
    with pytest.raises(AssertionError, match='bar.pdf'):
        check_polygon_upload(_ctx(tmp_path), m)
