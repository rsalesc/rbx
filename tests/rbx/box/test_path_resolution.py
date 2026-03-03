import pathlib
from typing import List, Optional

import typer
from typing_extensions import Annotated

from rbx.annotations import PackagePath
from rbx.box.path_resolution import resolve_package_paths


def test_resolve_single_str():
    """Single str param annotated with PackagePath is resolved."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': 'sol.cpp'}, original_cwd, package_dir
    )
    assert resolved['path'] == 'subdir/sol.cpp'


def test_resolve_optional_str_with_value():
    """Optional[str] param with a value is resolved."""

    def cmd(
        path: Annotated[Optional[str], PackagePath, typer.Argument()] = None,
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': 'sol.cpp'}, original_cwd, package_dir
    )
    assert resolved['path'] == 'subdir/sol.cpp'


def test_resolve_optional_str_none():
    """Optional[str] param with None value is left as None."""

    def cmd(
        path: Annotated[Optional[str], PackagePath, typer.Argument()] = None,
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(cmd, (), {'path': None}, original_cwd, package_dir)
    assert resolved['path'] is None


def test_resolve_list_str():
    """Optional[List[str]] param is resolved element-wise."""

    def cmd(
        paths: Annotated[Optional[List[str]], PackagePath, typer.Argument()] = None,
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'paths': ['a.cpp', 'b.cpp']}, original_cwd, package_dir
    )
    assert resolved['paths'] == ['subdir/a.cpp', 'subdir/b.cpp']


def test_resolve_list_none():
    """Optional[List[str]] param with None is left as None."""

    def cmd(
        paths: Annotated[Optional[List[str]], PackagePath, typer.Argument()] = None,
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'paths': None}, original_cwd, package_dir
    )
    assert resolved['paths'] is None


def test_resolve_absolute_path():
    """Absolute path is made relative to package dir."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': '/project/other/sol.cpp'}, original_cwd, package_dir
    )
    assert resolved['path'] == 'other/sol.cpp'


def test_resolve_absolute_path_outside_package():
    """Absolute path outside package dir stays absolute."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': '/elsewhere/sol.cpp'}, original_cwd, package_dir
    )
    assert resolved['path'] == '/elsewhere/sol.cpp'


def test_no_annotation_untouched():
    """Params without PackagePath annotation are not modified."""

    def cmd(
        name: str = '',
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'name': 'foo', 'path': 'sol.cpp'}, original_cwd, package_dir
    )
    assert resolved['name'] == 'foo'
    assert resolved['path'] == 'subdir/sol.cpp'


def test_resolve_pathlib_path():
    """pathlib.Path values are resolved and returned as pathlib.Path."""

    def cmd(
        path: Annotated[pathlib.Path, PackagePath, typer.Argument()] = pathlib.Path(),
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': pathlib.Path('sol.cpp')}, original_cwd, package_dir
    )
    assert resolved['path'] == pathlib.Path('subdir/sol.cpp')
    assert isinstance(resolved['path'], pathlib.Path)


def test_resolve_same_dir():
    """When original cwd IS the package dir, paths pass through unchanged."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': 'sol.cpp'}, package_dir, package_dir
    )
    assert resolved['path'] == 'sol.cpp'


def test_resolve_with_positional_args():
    """Parameters passed as positional args are also resolved."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()],
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(cmd, ('sol.cpp',), {}, original_cwd, package_dir)
    assert resolved['path'] == 'subdir/sol.cpp'
