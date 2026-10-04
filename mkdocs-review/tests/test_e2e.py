"""Build a real two-commit mkdocs project and review it end to end."""

import json
import shutil
import sys
import urllib.request

import pytest

from mkdocs_review.cli import _parser, create_session
from mkdocs_review.server import serve
from tests.test_gitops import _commit, _git

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='needs git')

CONFIG = 'site_name: Demo\nnav:\n  - index.md\n  - guide.md\n'


@pytest.fixture
def project(tmp_path):
    repo = tmp_path / 'proj'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    _git(repo, 'config', 'user.email', 't@example.com')
    _git(repo, 'config', 'user.name', 't')
    _git(repo, 'config', 'commit.gpgsign', 'false')
    _commit(
        repo,
        {
            'mkdocs.yml': CONFIG,
            'docs/index.md': '# Home\n\nWelcome to the demo.\n',
            'docs/guide.md': '# Guide\n\nRun the old command to build.\n\nKeep this.\n',
        },
        'base',
    )
    _commit(
        repo,
        {
            'docs/guide.md': '# Guide\n\nRun the new command to build.\n\nKeep this.\n',
            'docs/extra.md': '# Extra\n\nA brand new page.\n',
        },
        'head',
    )
    return repo


def test_review_range_end_to_end(project, tmp_path):
    mkdocs = f'{sys.executable} -m mkdocs build -q'
    args = _parser().parse_args(
        [
            'HEAD~1..HEAD',
            '--repo-dir',
            str(project),
            '--build-cmd',
            mkdocs,
            '--cache-dir',
            str(tmp_path / 'cache'),
        ]
    )
    session = create_session(args, log=lambda message: None)
    statuses = {p['path']: p['status'] for p in session.state()['pages']}
    assert statuses == {
        'index.html': 'unchanged',
        'guide/index.html': 'modified',
        'extra/index.html': 'added',
    }

    server = serve(session)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/state') as resp:
            state = json.loads(resp.read())
        guide = next(p for p in state['pages'] if p['path'] == 'guide/index.html')
        assert guide['counts'] == {'added': 0, 'removed': 0, 'changed': 1}
        assert guide['source'] == 'docs/guide.md'

        drafts = [
            {
                'id': 'd',
                'page': 'guide/index.html',
                'side': 'head',
                'block': 1,
                'body': '?',
            }
        ]
        req = urllib.request.Request(
            f'http://127.0.0.1:{port}/api/anchors',
            data=json.dumps(drafts).encode(),
            method='POST',
        )
        with urllib.request.urlopen(req) as resp:
            anchors = json.loads(resp.read())
        assert anchors == [
            {'id': 'd', 'anchor': {'path': 'docs/guide.md', 'line': 3, 'side': 'RIGHT'}}
        ]
    finally:
        server.shutdown()

    # Building again reuses the cache instead of re-running mkdocs.
    logs = []
    create_session(args, log=logs.append)
    assert sum('Using cached build' in m for m in logs) == 2
    # The temporary worktrees are gone; only the project itself remains.
    assert len(_git(project, 'worktree', 'list').splitlines()) == 1


def test_earlier_commits_are_built_in_the_background_and_usable_as_base(
    project, tmp_path
):
    third = _commit(
        project,
        {
            'docs/guide.md': '# Guide\n\nRun the newest command to build.\n\nKeep this.\n'
        },
        'third',
    )
    args = _parser().parse_args(
        [
            'HEAD~2..HEAD',
            '--repo-dir',
            str(project),
            '--build-cmd',
            f'{sys.executable} -m mkdocs build -q',
            '--cache-dir',
            str(tmp_path / 'cache'),
        ]
    )
    session = create_session(args, log=lambda message: None)
    assert [s.kind for s in session.snapshots] == ['base', 'commit', 'head']
    assert session.snapshots[-1].sha == third
    middle = session.snapshots[1].sha

    # The middle commit was queued for a background build at startup.
    assert session.builder.wait(middle, timeout=60) == 'ready'
    statuses = {p['path']: p['status'] for p in session.state(middle)['pages']}
    # Against the middle commit only the guide changed; extra.md already existed.
    assert statuses == {
        'index.html': 'unchanged',
        'guide/index.html': 'modified',
        'extra/index.html': 'unchanged',
    }
