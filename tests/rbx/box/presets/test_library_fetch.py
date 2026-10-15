import pytest
import typer

from rbx.box.presets import library_fetch
from rbx.box.presets.schema import Library


def test_fetch_library_local_source_caches(tmp_path, monkeypatch):
    # Point the app cache at a temp dir.
    app = tmp_path / 'app'
    monkeypatch.setattr(library_fetch, 'get_app_path', lambda: app)

    src_repo = tmp_path / 'src'
    src_repo.mkdir()
    (src_repo / 'lib.h').write_text('#pragma once\n// lib')

    lib = Library(
        name='lib',
        source=str(src_repo),
        path='lib.h',
        version='latest',
        dest='lib.h',
    )

    cached = library_fetch.fetch_library(lib)
    assert cached.is_file()
    assert cached.read_text() == '#pragma once\n// lib'
    assert app in cached.parents  # cached under the app libs dir


def test_fetch_library_local_file_source(tmp_path, monkeypatch):
    # A local source that points directly at a file (path omitted).
    app = tmp_path / 'app'
    monkeypatch.setattr(library_fetch, 'get_app_path', lambda: app)

    src_file = tmp_path / 'foo.h'
    src_file.write_text('// foo')

    lib = Library(name='foo', source=str(src_file), dest='foo.h')
    cached = library_fetch.fetch_library(lib)
    assert cached.read_text() == '// foo'


def test_fetch_library_github_strips_git_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(library_fetch, 'get_app_path', lambda: tmp_path / 'app')
    captured = {}

    def fake_download(url, dst):
        captured['url'] = url
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text('// header')

    monkeypatch.setattr(library_fetch, '_download_url', fake_download)

    lib = Library(
        name='testlib',
        source='https://github.com/MikeMirzayanov/testlib.git',
        path='testlib.h',
        version='v0.9.40',  # pinned ref => no network HEAD resolve
        dest='testlib.h',
    )
    cached = library_fetch.fetch_library(lib)
    assert cached.read_text() == '// header'
    assert captured['url'] == (
        'https://raw.githubusercontent.com/MikeMirzayanov/testlib/v0.9.40/testlib.h'
    )


def test_fetch_library_github_directory_path_rejected(tmp_path, monkeypatch):
    import typer

    monkeypatch.setattr(library_fetch, 'get_app_path', lambda: tmp_path / 'app')
    lib = Library(
        name='somelib',
        source='https://github.com/owner/repo',
        path='single_include',  # a directory (no suffix) — unsupported via raw fetch
        version='v1',
        dest='lib.h',
    )
    with pytest.raises(typer.Exit):
        library_fetch.fetch_library(lib)


def test_fetch_library_github_requires_path(tmp_path, monkeypatch):
    monkeypatch.setattr(library_fetch, 'get_app_path', lambda: tmp_path / 'app')
    lib = Library(
        name='testlib',
        source='https://github.com/MikeMirzayanov/testlib',
        version='v0.9.40',
        dest='testlib.h',
    )
    with pytest.raises(typer.Exit):
        library_fetch.fetch_library(lib)


def test_materialize_copy(tmp_path):
    cache = tmp_path / 'cache.h'
    cache.write_text('content')
    lib = Library(name='lib', source='x', path='lib.h', dest='sub/lib.h')
    pkg = tmp_path / 'pkg'
    pkg.mkdir()

    library_fetch.materialize_library(lib, cache, pkg)

    out = pkg / 'sub' / 'lib.h'
    assert out.is_file() and not out.is_symlink()
    assert out.read_text() == 'content'


def test_materialize_symlink(tmp_path):
    cache = tmp_path / 'cache.h'
    cache.write_text('content')
    lib = Library(name='lib', source='x', path='lib.h', dest='sub/lib.h', symlink=True)
    pkg = tmp_path / 'pkg'
    pkg.mkdir()

    library_fetch.materialize_library(lib, cache, pkg)

    out = pkg / 'sub' / 'lib.h'
    stored = pkg / '.local.rbx' / 'libs' / 'lib' / 'lib.h'
    assert stored.is_file()
    assert out.is_symlink()
    assert out.resolve() == stored.resolve()
    assert out.read_text() == 'content'


def test_materialize_overwrites_existing(tmp_path):
    # Re-materializing replaces a prior file/symlink at dest cleanly.
    cache = tmp_path / 'cache.h'
    cache.write_text('v2')
    lib = Library(name='lib', source='x', path='lib.h', dest='lib.h')
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / 'lib.h').write_text('v1')

    library_fetch.materialize_library(lib, cache, pkg)
    assert (pkg / 'lib.h').read_text() == 'v2'


def test_materialize_symlink_clears_stale_backing_file(tmp_path):
    # Re-materializing a symlink library whose filename changed must not leave
    # the old backing file behind under .local.rbx/libs/<name>/.
    cache = tmp_path / 'cache.h'
    cache.write_text('content')
    pkg = tmp_path / 'pkg'
    pkg.mkdir()

    old = Library(name='lib', source='x', path='old.h', dest='old.h', symlink=True)
    library_fetch.materialize_library(old, cache, pkg)
    assert (pkg / '.local.rbx' / 'libs' / 'lib' / 'old.h').is_file()

    new = Library(name='lib', source='x', path='new.h', dest='new.h', symlink=True)
    library_fetch.materialize_library(new, cache, pkg)

    libs_dir = pkg / '.local.rbx' / 'libs' / 'lib'
    assert (libs_dir / 'new.h').is_file()
    assert not (libs_dir / 'old.h').exists()  # stale orphan removed


def _contest_with_problem(tmp_path):
    contest = tmp_path / 'contest'
    (contest / '.local.rbx').mkdir(parents=True)
    (contest / '.local.rbx' / 'preset.rbx.yml').write_text('name: p\n')
    problem = contest / 'problems' / 'a'
    problem.mkdir(parents=True)
    return contest, problem


def test_materialize_symlink_in_contest_problem_uses_contest_preset(tmp_path):
    # A problem inside a contest has no preset of its own: the symlink content
    # belongs next to the contest's installed preset, not in a per-problem
    # .local.rbx that would duplicate it in every problem.
    cache = tmp_path / 'cache.h'
    cache.write_text('content')
    contest, problem = _contest_with_problem(tmp_path)
    lib = Library(name='lib', source='x', path='lib.h', dest='sub/lib.h', symlink=True)

    library_fetch.materialize_library(lib, cache, problem)

    out = problem / 'sub' / 'lib.h'
    stored = contest / '.local.rbx' / 'libs' / 'lib' / 'lib.h'
    assert stored.is_file()
    assert not (problem / '.local.rbx').exists()
    assert out.is_symlink()
    assert out.readlink().as_posix() == '../../../.local.rbx/libs/lib/lib.h'
    assert out.read_text() == 'content'


def test_materialize_symlink_shared_store_keeps_sibling_files(tmp_path):
    # In a shared store, re-materializing one problem's library must not delete
    # a file another problem's symlink still points to.
    cache = tmp_path / 'cache.h'
    cache.write_text('content')
    contest, problem = _contest_with_problem(tmp_path)
    other = contest / 'problems' / 'b'
    other.mkdir()

    old = Library(name='lib', source='x', path='old.h', dest='old.h', symlink=True)
    library_fetch.materialize_library(old, cache, other)
    new = Library(name='lib', source='x', path='new.h', dest='new.h', symlink=True)
    library_fetch.materialize_library(new, cache, problem)

    assert (other / 'old.h').read_text() == 'content'
    assert (problem / 'new.h').read_text() == 'content'


def test_materialize_symlink_problem_with_own_preset(tmp_path):
    # A problem carrying its own installed preset keeps using its own store.
    cache = tmp_path / 'cache.h'
    cache.write_text('content')
    contest, problem = _contest_with_problem(tmp_path)
    (problem / '.local.rbx').mkdir()
    (problem / '.local.rbx' / 'preset.rbx.yml').write_text('name: q\n')
    lib = Library(name='lib', source='x', path='lib.h', dest='lib.h', symlink=True)

    library_fetch.materialize_library(lib, cache, problem)

    assert (problem / '.local.rbx' / 'libs' / 'lib' / 'lib.h').is_file()
    assert not (contest / '.local.rbx' / 'libs').exists()


def test_resolve_remote_head_parses_sha(monkeypatch):
    from rbx.box import git_utils

    monkeypatch.setattr(git_utils.utils, 'command_exists', lambda *a, **k: True)
    monkeypatch.setattr(
        git_utils.subprocess,
        'check_output',
        lambda *a, **k: 'abc123\tHEAD\n',
    )
    assert git_utils.resolve_remote_head('https://x/y') == 'abc123'


def test_resolve_remote_head_empty_raises(monkeypatch):
    from rbx.box import git_utils

    monkeypatch.setattr(git_utils.utils, 'command_exists', lambda *a, **k: True)
    monkeypatch.setattr(git_utils.subprocess, 'check_output', lambda *a, **k: '')
    with pytest.raises(ValueError):
        git_utils.resolve_remote_head('https://x/y')
