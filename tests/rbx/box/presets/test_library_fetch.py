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
