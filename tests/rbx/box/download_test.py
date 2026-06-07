import pathlib

import pytest
import typer

from rbx.box import download
from rbx.box import libraries as box_libraries
from rbx.box.presets.schema import Libraries, Library
from rbx.box.testing import testing_package


def _declare_local_library(
    pkg: testing_package.TestingPackage,
    name: str,
    *,
    content: bytes = b'// extra library\n',
    dest: str = 'extra.h',
) -> Library:
    """Declare an extra preset library whose source is a real local file.

    Keeps everything offline: the source resolves to a file already inside the
    package, so `library_fetch.fetch_library` just copies it into the cache.
    """
    source_path = (pkg.root / f'{name}.src.h').resolve()
    source_path.write_bytes(content)
    library = Library(
        name=name,
        source=str(source_path),
        path=pathlib.Path(f'{name}.src.h'),
        dest=pathlib.Path(dest),
    )
    preset = pkg.preset
    current = preset.yml.libraries
    preset.yml.libraries = Libraries(
        problem=current.problem + [library], contest=current.contest
    )
    preset.save()
    box_libraries.get_declared_libraries.cache_clear()
    return library


class TestDownloadLibrary:
    def test_named_library_materializes_at_dest(
        self, testing_pkg: testing_package.TestingPackage
    ):
        library = _declare_local_library(
            testing_pkg, 'mylib', content=b'// mylib body\n', dest='libs/mylib.h'
        )

        download.lib(name='mylib', into=None)

        target = pathlib.Path.cwd() / library.dest
        assert target.is_file()
        assert target.read_bytes() == b'// mylib body\n'

    def test_all_libraries_are_refetched(
        self, testing_pkg: testing_package.TestingPackage
    ):
        _declare_local_library(
            testing_pkg, 'mylib', content=b'// mylib body\n', dest='libs/mylib.h'
        )

        download.lib(name=None, into=None)

        # The standard libraries declared by the TestingPackage plus the extra
        # one should all be materialized at their declared dests.
        for library in box_libraries.get_declared_libraries():
            target = pathlib.Path.cwd() / library.dest
            assert target.is_file(), (
                f'{library.name} not materialized at {library.dest}'
            )

    def test_unknown_library_raises_exit(
        self, testing_pkg: testing_package.TestingPackage
    ):
        with pytest.raises(typer.Exit):
            download.lib(name='nonexistent', into=None)

    def test_into_override_copies_to_given_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        _declare_local_library(
            testing_pkg, 'mylib', content=b'// mylib body\n', dest='libs/mylib.h'
        )

        download.lib(name='mylib', into='headers/here.h')

        target = pathlib.Path.cwd() / 'headers' / 'here.h'
        assert target.is_file()
        assert target.read_bytes() == b'// mylib body\n'


class TestDownloadTestlibAlias:
    def test_testlib_alias_materializes_testlib(
        self, testing_pkg: testing_package.TestingPackage
    ):
        # The TestingPackage chokepoint declares testlib with a real local
        # source, so the alias resolves and materializes it offline.
        box_libraries.get_declared_libraries.cache_clear()
        testlib = next(
            lib
            for lib in box_libraries.get_declared_libraries()
            if lib.name == 'testlib'
        )

        download.testlib(into=None)

        target = pathlib.Path.cwd() / testlib.dest
        assert target.is_file()
        assert target.read_bytes()
