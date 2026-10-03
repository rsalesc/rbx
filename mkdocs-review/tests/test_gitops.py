import pathlib
import subprocess

import pytest

from mkdocs_review.gitops import build_command, ls_files, resolve_range, show_file


def _git(repo, *args):
    return subprocess.run(
        ['git', *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: pathlib.Path, files: dict, message: str) -> str:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', message)
    return _git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _git(tmp_path, 'config', 'user.email', 't@example.com')
    _git(tmp_path, 'config', 'user.name', 't')
    _git(tmp_path, 'config', 'commit.gpgsign', 'false')
    return tmp_path


def test_resolve_range_forms(repo):
    root = _commit(repo, {'docs/index.md': 'a'}, 'root')
    main2 = _commit(repo, {'docs/index.md': 'b'}, 'main moves on')
    _git(repo, 'checkout', '-q', '-b', 'feature', root)
    feature = _commit(repo, {'docs/new.md': 'c'}, 'feature')

    two_dot = resolve_range(repo, 'main..feature')
    assert (two_dot.base_sha, two_dot.head_sha) == (main2, feature)

    three_dot = resolve_range(repo, 'main...feature')
    assert (three_dot.base_sha, three_dot.head_sha) == (root, feature)

    bare = resolve_range(repo, 'main')
    assert (bare.base_sha, bare.head_sha) == (root, feature)
    assert bare.key == f'range-{root[:10]}-{feature[:10]}'


def test_show_and_ls_files(repo):
    sha = _commit(repo, {'docs/a.md': 'x', 'docs/b/c.md': 'y', 'other.md': 'z'}, 'c')
    assert ls_files(repo, sha, 'docs') == ['docs/a.md', 'docs/b/c.md']
    assert show_file(repo, sha, 'docs/a.md') == 'x'
    assert show_file(repo, sha, 'missing.yml') is None


def test_build_command():
    site = pathlib.Path('/tmp/out site')
    assert build_command('mkdocs build', 'mkdocs.yml', site) == (
        "mkdocs build --site-dir '/tmp/out site'"
    )
    assert build_command('uv run mkdocs build', 'cfg.yml', site) == (
        "uv run mkdocs build -f cfg.yml --site-dir '/tmp/out site'"
    )
    assert build_command('make docs OUT={site_dir}', 'x.yml', site) == (
        "make docs OUT='/tmp/out site'"
    )
