import os
import pathlib
import subprocess

from mkdocs_review.snapshots import list_snapshots
from tests.test_gitops import _git


def _commit_at(repo: pathlib.Path, text: str, message: str, timestamp: int) -> str:
    (repo / 'docs').mkdir(exist_ok=True)
    (repo / 'docs/index.md').write_text(text)
    _git(repo, 'add', '-A')
    env = {**os.environ, 'GIT_COMMITTER_DATE': f'{timestamp} +0000'}
    subprocess.run(
        ['git', 'commit', '-q', '-m', message], cwd=repo, env=env, check=True
    )
    return _git(repo, 'rev-parse', 'HEAD')


def test_lists_base_commits_force_pushes_and_head_in_order(repo):
    base = _commit_at(repo, 'a', 'base', 1_700_000_000)
    _git(repo, 'checkout', '-q', '-b', 'old', base)
    lost = _commit_at(repo, 'old try', 'old try', 1_700_001_000)
    _git(repo, 'checkout', '-q', '-b', 'pr', base)
    first = _commit_at(repo, 'b', 'first', 1_700_002_000)
    head = _commit_at(repo, 'c', 'second', 1_700_003_000)

    snapshots = list_snapshots(
        repo, base, head, force_pushed=[lost, head], reviews={lost: ['alice']}
    )
    assert [(s.sha, s.kind, s.subject, s.notes) for s in snapshots] == [
        (base, 'base', 'base', []),
        (lost, 'force-push', 'old try', ['reviewed by alice']),
        (first, 'commit', 'first', []),
        (head, 'head', 'second', []),
    ]
