import json
import urllib.error
import urllib.request

import pytest

from mkdocs_review.anchor import parse_unified_diff
from mkdocs_review.server import serve
from mkdocs_review.session import DraftStore, Session
from mkdocs_review.site import Page


def _page(body):
    return f'<html><head></head><body><article>{body}</article></body></html>'


DIFF = """\
diff --git a/docs/guide.md b/docs/guide.md
--- a/docs/guide.md
+++ b/docs/guide.md
@@ -1,3 +1,3 @@
 # Guide

-Run the old command.
+Run the new command.
"""


@pytest.fixture
def server(tmp_path):
    base, head = tmp_path / 'base', tmp_path / 'head'
    (base / 'guide').mkdir(parents=True)
    (head / 'guide').mkdir(parents=True)
    (base / 'guide/index.html').write_text(
        _page('<h1>Guide</h1><p>Run the old command.</p>')
    )
    (head / 'guide/index.html').write_text(
        _page('<h1>Guide</h1><p>Run the new command.</p>')
    )
    (head / 'style.css').write_text('p{}')
    (tmp_path / 'secret.txt').write_text('nope')

    posted = []

    def poster(payload):
        posted.append(payload)
        return {'html_url': 'https://github.com/o/r/pull/1#review-1'}

    session = Session(
        label='#1 docs',
        base_sha='b' * 40,
        head_sha='h' * 40,
        sites={'base': base, 'head': head},
        pages=[Page('guide/index.html', 'docs/guide.md', 'docs/guide.md', True, True)],
        diff_files=parse_unified_diff(DIFF),
        drafts=DraftStore(tmp_path / 'repo/.mkdocs-review/pr-1.json'),
        pr={'number': 1, 'url': 'https://github.com/o/r/pull/1'},
        poster=poster,
    )
    srv = serve(session)
    srv.posted = posted
    srv.tmp = tmp_path
    yield srv
    srv.shutdown()


def _url(srv, path):
    return f'http://127.0.0.1:{srv.server_address[1]}{path}'


def _get(srv, path):
    with urllib.request.urlopen(_url(srv, path)) as resp:
        return resp.status, resp.read().decode()


def _call(srv, method, path, data):
    req = urllib.request.Request(
        _url(srv, path),
        data=json.dumps(data).encode(),
        method=method,
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_state_lists_modified_page(server):
    status, body = _get(server, '/api/state')
    state = json.loads(body)
    assert status == 200
    assert state['can_submit'] is True
    [page] = state['pages']
    assert page['status'] == 'modified'
    assert page['title'] == 'Guide'
    assert page['counts'] == {'added': 0, 'removed': 0, 'changed': 1}


def test_serves_annotated_pages_assets_and_ui(server):
    _, html = _get(server, '/site/head/guide/')
    assert 'mr-w-add' in html and 'data-side="head"' in html
    assert _get(server, '/site/head/style.css')[1] == 'p{}'
    assert 'mkdocs-review' in _get(server, '/')[1]
    assert _get(server, '/_mr/inject.js')[0] == 200


def test_rejects_path_traversal(server):
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(server, '/site/head/../secret.txt')
    assert err.value.code == 404
    with pytest.raises(urllib.error.HTTPError):
        _get(server, '/site/head/%2e%2e/secret.txt')


def test_drafts_round_trip_and_gitignore(server):
    drafts = [
        {
            'id': 'd1',
            'page': 'guide/index.html',
            'side': 'head',
            'block': 1,
            'body': 'Why new?',
        }
    ]
    assert _call(server, 'PUT', '/api/drafts', drafts)[0] == 200
    assert json.loads(_get(server, '/api/drafts')[1]) == drafts
    assert (server.tmp / 'repo/.mkdocs-review/.gitignore').read_text() == '*\n'


def test_anchors_and_submit(server):
    drafts = [
        {
            'id': 'd1',
            'page': 'guide/index.html',
            'side': 'head',
            'block': 1,
            'body': 'Why new?',
        }
    ]
    _call(server, 'PUT', '/api/drafts', drafts)
    status, anchors = _call(server, 'POST', '/api/anchors', drafts)
    assert anchors == [
        {'id': 'd1', 'anchor': {'path': 'docs/guide.md', 'line': 3, 'side': 'RIGHT'}}
    ]

    status, result = _call(server, 'POST', '/api/submit', {'summary': 'LGTM'})
    assert status == 200
    assert result['url'].endswith('#review-1')
    assert server.posted == [
        {
            'commit_id': 'h' * 40,
            'event': 'COMMENT',
            'body': 'LGTM',
            'comments': [
                {
                    'path': 'docs/guide.md',
                    'line': 3,
                    'side': 'RIGHT',
                    'body': 'Why new?',
                }
            ],
        }
    ]
    assert json.loads(_get(server, '/api/drafts')[1]) == []
    assert list((server.tmp / 'repo/.mkdocs-review').glob('pr-1.submitted-*.json'))


def test_submit_with_nothing_is_an_error(server):
    status, result = _call(server, 'POST', '/api/submit', {'summary': ''})
    assert status == 400
    assert result == {'error': 'nothing to submit'}
