import json

from rbx.box.packaging.polygon import polygon_api as api
from tests.e2e import polygon_capture


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
