import json
import urllib.error
import urllib.request

import pytest

from mkdocs_review.anchor import parse_unified_diff
from mkdocs_review.builds import READY, Builder, BuiltSite
from mkdocs_review.server import serve
from mkdocs_review.session import DraftStore, Session
from mkdocs_review.snapshots import Snapshot


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


BASE, MID, HEAD = 'b' * 40, 'm' * 40, 'h' * 40
SOURCES = {'guide/index.html': 'docs/guide.md'}


def _built(root, text):
    (root / 'guide').mkdir(parents=True)
    (root / 'guide/index.html').write_text(_page(f'<h1>Guide</h1><p>{text}</p>'))
    return BuiltSite(root, {'guide/index.html'}, SOURCES)


@pytest.fixture
def server(tmp_path):
    base = _built(tmp_path / 'base', 'Run the old command.')
    head = _built(tmp_path / 'head', 'Run the new command.')
    (tmp_path / 'head/style.css').write_text('p{}')
    (tmp_path / 'secret.txt').write_text('nope')

    posted = []

    def poster(payload):
        posted.append(payload)
        return {'html_url': 'https://github.com/o/r/pull/1#review-1'}

    # The middle snapshot is only built on request, like a prebuild would.
    builder = Builder(lambda sha: _built(tmp_path / 'mid', 'Run the newer command.'))
    builder.add(BASE, base)
    builder.add(HEAD, head)
    snapshots = [
        Snapshot(BASE, 'base', 'main', 1, 'a day ago'),
        Snapshot(MID, 'commit', 'first try', 2, 'an hour ago', ['reviewed by me']),
        Snapshot(HEAD, 'head', 'second try', 3, 'now'),
    ]
    session = Session(
        label='#1 docs',
        head_sha=HEAD,
        default_base=BASE,
        snapshots=snapshots,
        builder=builder,
        diff_files=parse_unified_diff(DIFF),
        drafts=DraftStore(tmp_path / 'repo/.mkdocs-review/pr-1.json'),
        pr={'number': 1, 'url': 'https://github.com/o/r/pull/1'},
        poster=poster,
    )
    srv = serve(session)
    srv.builder = builder
    srv.posted = posted
    srv.tmp = tmp_path
    yield srv
    srv.shutdown()


def _url(srv, path):
    return f'http://127.0.0.1:{srv.server_address[1]}{path}'


def _get(srv, path):
    with urllib.request.urlopen(_url(srv, path)) as resp:
        return resp.status, resp.read().decode()


def _call_get(srv, path):
    try:
        with urllib.request.urlopen(_url(srv, path)) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


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


def test_state_lists_snapshots_with_build_status(server):
    state = json.loads(_get(server, '/api/state')[1])
    assert state['base'] == state['default_base'] == BASE
    assert [
        (s['sha'], s['kind'], s['status'], s['notes']) for s in state['snapshots']
    ] == [
        (BASE, 'base', 'ready', []),
        (MID, 'commit', 'unbuilt', ['reviewed by me']),
        (HEAD, 'head', 'ready', []),
    ]


def test_switching_base_builds_it_then_diffs_against_it(server):
    # Asking for an unbuilt base queues it and reports no pages yet.
    state = json.loads(_get(server, f'/api/state?base={MID[:12]}')[1])
    assert state['base'] == MID
    assert state['pages'] is None
    assert server.builder.wait(MID, timeout=5) == READY

    state = json.loads(_get(server, f'/api/state?base={MID[:12]}')[1])
    [page] = state['pages']
    assert page['counts'] == {'added': 0, 'removed': 0, 'changed': 1}
    _, html = _get(server, f'/r/{MID}/base/guide/')
    assert 'newer' in html and 'mr-w-del' in html


def test_unknown_or_head_base_is_rejected(server):
    assert _call_get(server, '/api/state?base=zzz')[0] == 404
    assert _call_get(server, f'/api/state?base={HEAD}')[0] == 404


def test_build_endpoint_prioritizes(server):
    assert _call(server, 'POST', '/api/build', {'base': MID})[0] == 200
    assert server.builder.wait(MID, timeout=5) == READY


def test_serves_annotated_pages_assets_and_ui(server):
    _, html = _get(server, f'/r/{BASE}/head/guide/')
    assert 'mr-w-add' in html and 'data-side="head"' in html
    assert _get(server, f'/r/{BASE}/head/style.css')[1] == 'p{}'
    assert 'mkdocs-review' in _get(server, '/')[1]
    assert _get(server, '/_mr/inject.js')[0] == 200


def test_root_absolute_assets_come_from_the_requesting_pane(server):
    req = urllib.request.Request(
        _url(server, '/style.css'),
        headers={'Referer': _url(server, f'/r/{BASE}/head/guide/')},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.read().decode() == 'p{}'
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(server, '/style.css')
    assert err.value.code == 404


def test_unbuilt_base_pages_say_so(server):
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(server, f'/r/{MID}/head/guide/')
    assert err.value.code == 503
    assert 'still being built' in err.value.read().decode()


def test_rejects_path_traversal(server):
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(server, f'/r/{BASE}/head/../secret.txt')
    assert err.value.code == 404
    with pytest.raises(urllib.error.HTTPError):
        _get(server, f'/r/{BASE}/head/%2e%2e/secret.txt')


def test_base_side_drafts_use_the_base_they_were_made_on(server):
    server.builder.prioritize(MID)
    assert server.builder.wait(MID, timeout=5) == READY
    drafts = [
        {
            'id': 'd1',
            'page': 'guide/index.html',
            'side': 'base',
            'block': 1,
            'base': MID,
            'body': 'Was newer better?',
        },
    ]
    payload = _call(server, 'POST', '/api/preview', {'drafts': drafts})[1]
    # It lands on the merge base's version of the sentence, so it quotes the
    # text the reviewer actually saw on that snapshot.
    assert payload['comments'] == [
        {
            'path': 'docs/guide.md',
            'line': 3,
            'side': 'LEFT',
            'body': 'On `guide/index.html`:\n> Run the newer command.\n\nWas newer better?',
        }
    ]


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
            'commit_id': HEAD,
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
