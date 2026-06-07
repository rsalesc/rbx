import hashlib
import pathlib
import shutil
import tempfile
from typing import Optional

import typer

from rbx import console
from rbx.box import git_utils
from rbx.box.presets.fetch import get_library_fetch_info
from rbx.box.presets.schema import Library
from rbx.utils import get_app_path


def _cache_root() -> pathlib.Path:
    return get_app_path() / 'libs'


def _source_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def _cache_path(library: Library, ref: str) -> pathlib.Path:
    path_part = str(library.path) if library.path is not None else 'file'
    return _cache_root() / _source_hash(library.source) / ref / path_part


def fetch_library(library: Library) -> pathlib.Path:
    """Fetch the library into the global cache and return the cached file path.

    First fetch requires network for remote sources; afterwards the cache is
    reused. Raises typer.Exit on failure (no offline fallback, by design).
    """
    info = get_library_fetch_info(library.source)
    if info is None:
        console.console.print(
            f'[error]Library [item]{library.name}[/item] has an invalid source '
            f'[item]{library.source}[/item].[/error]'
        )
        raise typer.Exit(1)

    if info.is_local():
        src = pathlib.Path(info.fetch_uri)
        if library.path is not None and src.is_dir():
            src = src / library.path
        dst = _cache_path(library, 'local')
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        return dst

    if info.is_raw_url():
        dst = _cache_path(library, 'url')
        if not dst.exists():
            _download_url(info.fetch_uri, dst)
        return dst

    if info.is_github():
        ref = _resolve_ref(info.fetch_uri, library.version)
        dst = _cache_path(library, ref)
        if not dst.exists():
            owner_repo = info.fetch_uri.removeprefix('https://github.com/')
            raw = f'https://raw.githubusercontent.com/{owner_repo}/{ref}/{library.path}'
            _download_url(raw, dst)
        return dst

    # Arbitrary git: clone + checkout + copy path.
    ref = library.version if library.version != 'latest' else None
    dst = _cache_path(library, ref or 'latest')
    if not dst.exists():
        _clone_and_copy(info.fetch_uri, ref, library.path, dst)
    return dst


def _resolve_ref(github_uri: str, version: str) -> str:
    if version != 'latest':
        return version
    return git_utils.resolve_remote_head(github_uri)


def _download_url(url: str, dst: pathlib.Path) -> None:
    import requests

    console.console.print(f'Downloading [item]{url}[/item]...')
    r = requests.get(url)
    if not r.ok:
        console.console.print(f'[error]Failed to download [item]{url}[/item].[/error]')
        raise typer.Exit(1)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.content)


def _clone_and_copy(
    uri: str, ref: Optional[str], path: Optional[pathlib.Path], dst: pathlib.Path
) -> None:
    import git

    with tempfile.TemporaryDirectory() as td:
        repo = git.Repo.clone_from(uri, td)
        if ref is not None:
            repo.git.checkout(ref)
        src = pathlib.Path(td) / (path or '')
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copyfile(src, dst)
