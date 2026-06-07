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
