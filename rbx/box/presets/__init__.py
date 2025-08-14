import functools
import os
import pathlib
import shutil
import tempfile
from typing import Annotated, Iterable, List, Optional, Sequence, Set, Tuple, Union

import questionary
import ruyaml
import semver
import typer

from rbx import console, utils
from rbx.box import cd, git_utils
from rbx.box.git_utils import latest_remote_tag
from rbx.box.presets.fetch import (
    PresetFetchInfo,
    get_preset_fetch_info,
    get_remote_uri_from_tool_preset,
)
from rbx.box.presets.lock_schema import LockedAsset, PresetLock, SymlinkInfo
from rbx.box.presets.schema import Preset, TrackedAsset
from rbx.config import get_default_app_path
from rbx.grading.judge.digester import digest_cooperatively

app = typer.Typer(no_args_is_help=True)

_FALLBACK_PRESET_NAME = 'default'


def find_preset_yaml(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    found = root / 'preset.rbx.yml'
    if found.exists():
        return found
    return None


@functools.cache
def _check_preset_compatibility(preset_name: str, preset_version: str) -> None:
    compatibility = utils.check_version_compatibility(preset_version)
    if compatibility == utils.SemVerCompatibility.OUTDATED:
        console.console.print(
            f'[error]Preset [item]{preset_name}[/item] requires rbx at version [item]{preset_version}[/item], but the current version is [item]{utils.get_version()}[/item].[/error]'
        )
        console.console.print(
            f'[error]Please update rbx.cp to the latest compatible version using [item]{utils.get_upgrade_command(preset_version)}[/item].[/error]'
        )
        raise typer.Exit(1)
    if compatibility == utils.SemVerCompatibility.BREAKING_CHANGE:
        console.console.print(
            f'[error]Preset [item]{preset_name}[/item] requires rbx at version [item]{preset_version}[/item], but the current version is [item]{utils.get_version()}[/item].[/error]'
        )
        console.console.print(
            '[error]rbx version is newer, but is in a later major version, which might have introduced breaking changes.[/error]'
        )
        console.console.print(
            '[error]If you are sure that the preset is compatible with the current rbx version, you can change the [item]min_version[/item] field in the preset file ([item].local.rbx/preset.rbx.yml)[/item] to the current version.[/error]'
        )
        raise typer.Exit(1)


def get_preset_yaml(root: pathlib.Path = pathlib.Path()) -> Preset:
    found = find_preset_yaml(root)
    if not found:
        console.console.print(
            f'[error][item]preset.rbx.yml[/item] not found in [item]{root.absolute()}[/item][/error]'
        )
        raise typer.Exit(1)
    preset = utils.model_from_yaml(Preset, found.read_text())
    _check_preset_compatibility(preset.name, preset.min_version)
    return preset


def _find_preset_lock(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    root = utils.abspath(root)
    problem_yaml_path = root / '.preset-lock.yml'
    if not problem_yaml_path.is_file():
        return None
    return problem_yaml_path


def get_preset_lock(root: pathlib.Path = pathlib.Path()) -> Optional[PresetLock]:
    found = _find_preset_lock(root)
    if not found:
        return None
    return utils.model_from_yaml(PresetLock, found.read_text())


def find_nested_preset(root: pathlib.Path) -> Optional[pathlib.Path]:
    root = utils.abspath(root)
    problem_yaml_path = root / 'preset.rbx.yml'
    while root != pathlib.PosixPath('/') and not problem_yaml_path.is_file():
        root = root.parent
        problem_yaml_path = root / 'preset.rbx.yml'
    if not problem_yaml_path.is_file():
        return None
    return problem_yaml_path.parent


def find_local_preset(root: pathlib.Path) -> Optional[pathlib.Path]:
    original_root = root
    root = utils.abspath(root)
    problem_yaml_path = root / '.local.rbx' / 'preset.rbx.yml'
    while root != pathlib.PosixPath('/') and not problem_yaml_path.is_file():
        root = root.parent
        problem_yaml_path = root / '.local.rbx' / 'preset.rbx.yml'
    if not problem_yaml_path.is_file():
        return find_nested_preset(original_root)
    return problem_yaml_path.parent


def _is_installed_preset(root: pathlib.Path = pathlib.Path()) -> bool:
    preset_path = find_local_preset(root)
    if preset_path is None:
        return False
    resolved_path = utils.abspath(preset_path)
    return resolved_path.name == '.local.rbx'


def _is_active_preset_nested(root: pathlib.Path = pathlib.Path()) -> bool:
    preset_path = find_local_preset(root)
    if preset_path is None:
        return False
    nested_preset_path = find_nested_preset(root)
    if nested_preset_path is None:
        return False
    return nested_preset_path == preset_path


def is_contest(root: pathlib.Path = pathlib.Path()) -> bool:
    return (root / 'contest.rbx.yml').is_file()


def is_problem(root: pathlib.Path = pathlib.Path()) -> bool:
    return (root / 'problem.rbx.yml').is_file()


def check_is_valid_package(root: pathlib.Path = pathlib.Path()):
    if not is_contest(root) and not is_problem(root):
        console.console.print('[error]Not a valid rbx package directory.[/error]')
        raise typer.Exit(1)


def _glob_while_ignoring(
    dir: pathlib.Path,
    glb: str,
    extra_gitignore: Optional[str] = '.box\nbuild\n.limits/local.yml\n',
    recursive: bool = False,
) -> Iterable[pathlib.Path]:
    from gitignore_parser import parse_gitignore, parse_gitignore_str

    ignore_matchers = []

    if extra_gitignore is not None:
        ignore_matchers.append(parse_gitignore_str(extra_gitignore, base_dir=dir))

    for file in dir.rglob('.gitignore'):
        if file.is_file():
            ignore_matchers.append(parse_gitignore(file))

    def should_ignore(path: pathlib.Path) -> bool:
        return any(m(str(path)) for m in ignore_matchers)

    for file in dir.rglob(glb) if recursive else dir.glob(glb):
        if should_ignore(file):
            continue
        yield file


def process_globbing(
    assets: Iterable[TrackedAsset], preset_pkg_dir: pathlib.Path
) -> List[TrackedAsset]:
    res = []
    for asset in assets:
        if '*' in str(asset.path):
            glb = str(asset.path)
            files = _glob_while_ignoring(
                preset_pkg_dir,
                glb,
            )
            relative_files = [file.relative_to(preset_pkg_dir) for file in files]
            res.extend(
                [
                    TrackedAsset(path=path, symlink=asset.symlink)
                    for path in relative_files
                ]
            )
            continue
        res.append(asset)
    return res


def dedup_tracked_assets(assets: List[TrackedAsset]) -> List[TrackedAsset]:
    seen_paths = set()
    res = []
    for asset in assets:
        if asset.path in seen_paths:
            continue
        seen_paths.add(asset.path)
        res.append(asset)
    return res


def get_preset_tracked_assets(
    root: pathlib.Path, is_contest: bool, add_symlinks: bool = False
) -> List[TrackedAsset]:
    preset = get_active_preset(root)
    preset_path = find_local_preset(root)
    assert preset_path is not None

    if is_contest:
        assert (
            preset.contest is not None
        ), 'Preset does not have a contest package definition.'
        preset_pkg_path = preset_path / preset.contest
        res = process_globbing(preset.tracking.contest, preset_pkg_path)
    else:
        assert (
            preset.problem is not None
        ), 'Preset does not have a problem package definition,'
        preset_pkg_path = preset_path / preset.problem
        res = process_globbing(preset.tracking.problem, preset_pkg_path)

    if add_symlinks:
        for file in _glob_while_ignoring(
            preset_pkg_path,
            '*',
            recursive=True,
        ):
            if not file.is_symlink() or not file.is_file():
                continue
            res.append(
                TrackedAsset(path=file.relative_to(preset_pkg_path), symlink=True)
            )

    return dedup_tracked_assets(res)


def _get_tracked_assets_symlinks(
    tracked_assets: List[TrackedAsset],
) -> Set[pathlib.Path]:
    res = set()
    for asset in tracked_assets:
        if asset.symlink:
            res.add(asset.path)
    return res


def get_symlink_info(
    tracked_asset: Union[TrackedAsset, LockedAsset], root: pathlib.Path
) -> Optional[SymlinkInfo]:
    asset_path = root / tracked_asset.path
    if not asset_path.is_symlink():
        return None
    target = pathlib.Path(os.readlink(str(asset_path)))
    absolute_target = utils.abspath(asset_path.parent / target)
    is_broken = not absolute_target.exists()
    is_outside = not absolute_target.is_relative_to(utils.abspath(root))
    return SymlinkInfo(target=target, is_broken=is_broken, is_outside=is_outside)


def build_package_locked_assets(
    tracked_assets: Sequence[Union[TrackedAsset, LockedAsset]],
    root: pathlib.Path = pathlib.Path(),
) -> List[LockedAsset]:
    res = []
    for tracked_asset in tracked_assets:
        asset_path = root / tracked_asset.path
        if not asset_path.is_file():
            res.append(
                LockedAsset(
                    path=tracked_asset.path,
                    hash=None,
                    symlink_info=get_symlink_info(tracked_asset, root),
                )
            )
            continue
        with asset_path.open('rb') as f:
            res.append(
                LockedAsset(
                    path=tracked_asset.path,
                    hash=digest_cooperatively(f),
                    symlink_info=get_symlink_info(tracked_asset, root),
                )
            )
    return res


def find_non_modified_assets(
    reference: List[LockedAsset], current: List[LockedAsset]
) -> List[LockedAsset]:
    reference_by_path = {asset.path: asset for asset in reference}

    res = []
    for asset in current:
        # File does not exist in the reference.
        reference_asset = LockedAsset(path=asset.path, hash=None)

        # File already exists.
        if asset.path in reference_by_path:
            reference_asset = reference_by_path[asset.path]

        if asset.was_modified(reference_asset) and not asset.is_broken_symlink():
            # This is a file that was modified.
            continue
        res.append(asset)
    return res


def find_modified_assets(
    reference: List[LockedAsset],
    current: List[LockedAsset],
    seen_symlinks: Set[pathlib.Path],
):
    current_by_path = {asset.path: asset for asset in current}

    res = []
    for asset in reference:
        current_asset = LockedAsset(path=asset.path, hash=None)
        if asset.path in current_by_path:
            current_asset = current_by_path[asset.path]
        if current_asset.path in seen_symlinks and not asset.is_symlink():
            # TODO: improve this condition, it's almost always triggering
            # Preset asset should be forced to be a symlink,
            # but in the current package it is not.
            res.append(asset)
            continue
        if current_asset.was_modified(asset, follow_symlinks=True):
            # This is a file that was modified.
            res.append(asset)
    return res


def copy_preset_file(
    src: pathlib.Path,
    dst: pathlib.Path,
    preset_package_path: pathlib.Path,
    preset_path: pathlib.Path,
    force_symlink: bool = False,
):
    if dst.is_file() or dst.is_symlink():
        dst.unlink(missing_ok=True)
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_symlink() and not force_symlink:
        shutil.copyfile(str(src), str(dst))
        return

    # Ensure preset package path is inside the preset path.
    absolute_preset_package_path = utils.abspath(preset_package_path)
    absolute_preset_path = utils.abspath(preset_path)
    assert absolute_preset_package_path.is_relative_to(absolute_preset_path)

    # Get the symlink absolute path.
    if src.is_symlink():
        target_relative_path = pathlib.Path(os.readlink(str(src)))
        target_absolute_path = utils.abspath(src.parent / target_relative_path)

        if target_absolute_path.is_relative_to(absolute_preset_package_path):
            # The symlink points inside the preset package path.
            # Copy the symlink as is.
            dst.symlink_to(target_relative_path)
            return
    else:
        target_absolute_path = utils.abspath(src)

    if not target_absolute_path.is_relative_to(absolute_preset_path):
        console.console.print(
            f'[error]Preset [item]{preset_path.name}[/item] has a symlink to [item]{target_absolute_path}[/item] which is outside the preset folder.[/error]'
        )
        raise typer.Exit(1)

    # The symlink points somewhere inside the preset folder, fix the symlink.
    dst_absolute_path = utils.abspath(dst)
    fixed_target_relative_path = utils.relpath(
        target_absolute_path,
        dst_absolute_path.parent,
    )
    dst.symlink_to(fixed_target_relative_path)


def _copy_updated_assets(
    preset_lock: PresetLock,
    is_contest: bool,
    root: pathlib.Path = pathlib.Path(),
    force: bool = False,
    symlinks: bool = False,
):
    # Build preset package snapshot.
    preset = get_active_preset(root)
    preset_path = get_active_preset_path(root)
    preset_package_path = _get_active_preset_package_path(root, is_contest)

    preset_tracked_assets = get_preset_tracked_assets(
        preset_package_path, is_contest=is_contest, add_symlinks=symlinks
    )
    current_preset_snapshot = build_package_locked_assets(
        preset_tracked_assets, preset_package_path
    )

    # Build current package snapshot based on the current preset snapshot.
    current_package_snapshot = build_package_locked_assets(current_preset_snapshot)

    non_modified_assets = current_package_snapshot
    if not force:
        non_modified_assets = find_non_modified_assets(
            preset_lock.assets, current_package_snapshot
        )

    console.console.print('Tracking the following assets from preset:')
    for asset in current_preset_snapshot:
        console.console.print(f'  - [item]{asset}[/item]')
    console.console.print()

    console.console.print('Current package snapshot:')
    for asset in current_package_snapshot:
        console.console.print(f'  - [item]{asset}[/item]')
    console.console.print()

    seen_symlinks = _get_tracked_assets_symlinks(preset_tracked_assets)

    assets_to_copy = find_modified_assets(
        non_modified_assets, current_preset_snapshot, seen_symlinks
    )

    # console.console.log(current_package_snapshot)
    # console.console.log(current_preset_snapshot)

    if not assets_to_copy:
        console.console.print('[warning]No assets to update.[/warning]')
        return

    # console.console.log(assets_to_copy)

    for asset in assets_to_copy:
        src_path = preset_package_path / asset.path
        dst_path = root / asset.path
        copy_preset_file(
            src_path,
            dst_path,
            preset_package_path,
            preset_path,
            force_symlink=asset.path in seen_symlinks,
        )
        console.console.print(
            f'Updated [item]{asset.path}[/item] from preset [item]{preset.name}[/item].'
        )


def get_active_preset_or_null(root: pathlib.Path = pathlib.Path()) -> Optional[Preset]:
    local_preset = find_local_preset(root)
    if local_preset is not None:
        return get_preset_yaml(local_preset)
    return None


def get_active_preset(root: pathlib.Path = pathlib.Path()) -> Preset:
    preset = get_active_preset_or_null(root)
    if preset is None:
        console.console.print('[error]No preset is active.[/error]')
        raise typer.Exit(1)
    return preset


def get_active_preset_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    preset_path = find_local_preset(root)
    if preset_path is None:
        console.console.print('[error]No preset is active.[/error]')
        raise typer.Exit(1)
    return preset_path


def get_preset_environment_path(
    root: pathlib.Path = pathlib.Path(),
) -> Optional[pathlib.Path]:
    preset = get_active_preset_or_null(root)
    if preset is None or preset.env is None:
        return None
    preset_path = get_active_preset_path(root)
    env_path = preset_path / preset.env
    if not env_path.is_file():
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] environment file [item]{preset.env}[/item] does not exist.[/error]'
        )
        raise typer.Exit(1)
    return env_path


def _get_active_preset_package_path(
    root: pathlib.Path = pathlib.Path(),
    is_contest: bool = False,
) -> pathlib.Path:
    preset = get_active_preset(root)
    preset_path = find_local_preset(root)
    assert preset_path is not None
    if is_contest:
        assert (
            preset.contest is not None
        ), 'Preset does not have a contest package definition.'
        return preset_path / preset.contest
    assert (
        preset.problem is not None
    ), 'Preset does not have a problem package definition.'
    return preset_path / preset.problem


def get_preset_fetch_info_with_fallback(
    uri: Optional[str],
) -> Optional[PresetFetchInfo]:
    if uri is None:
        # Use active preset if any, otherwise use the default preset.
        if get_active_preset_or_null() is not None:
            return None
        default_preset = get_preset_fetch_info(_FALLBACK_PRESET_NAME)
        if default_preset is None:
            console.console.print(
                '[error]Internal error: could not find [item]default[/item] preset.[/error]'
            )
            raise typer.Exit(1)
        return default_preset
    return get_preset_fetch_info(uri)


def clean_copied_package_dir(dest: pathlib.Path):
    for box_dir in dest.rglob('.box'):
        shutil.rmtree(str(box_dir), ignore_errors=True)
    for lock in dest.rglob('.preset-lock.yml'):
        lock.unlink(missing_ok=True)


def clean_copied_contest_dir(dest: pathlib.Path, delete_local_rbx: bool = True):
    shutil.rmtree(str(dest / 'build'), ignore_errors=True)
    if delete_local_rbx:
        shutil.rmtree(str(dest / '.local.rbx'), ignore_errors=True)
    clean_copied_package_dir(dest)


def clean_copied_problem_dir(dest: pathlib.Path):
    shutil.rmtree(str(dest / 'build'), ignore_errors=True)
    clean_copied_package_dir(dest)


def install_preset_from_dir(
    src: pathlib.Path,
    dest: pathlib.Path,
    ensure_contest: bool = False,
    ensure_problem: bool = False,
    update: bool = False,
    override_uri: Optional[str] = None,
):
    preset = get_preset_yaml(src)

    if ensure_contest and preset.contest is None:
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] does not have a contest package definition.[/error]'
        )
        raise typer.Exit(1)
    if ensure_problem and preset.problem is None:
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] does not have a problem package definition.[/error]'
        )
        raise typer.Exit(1)

    try:
        _check_preset_compatibility(preset.name, preset.min_version)
    except Exception:
        console.console.print(
            f'[error]Error updating preset [item]{preset.name}[/item] to its latest version.[/error]'
        )
        raise

    dest.parent.mkdir(parents=True, exist_ok=True)
    copy_tree_normalizing_gitdir(src, dest, update=update)

    # Override the uri of the preset.
    if override_uri is not None:
        preset.uri = override_uri
        (dest / 'preset.rbx.yml').write_text(utils.model_to_yaml(preset))

    # Clean up all cache and left over directories before copying
    # to avoid conflicts.
    shutil.rmtree(str(dest / 'build'), ignore_errors=True)
    shutil.rmtree(str(dest / '.local.rbx'), ignore_errors=True)

    if preset.contest is not None:
        clean_copied_contest_dir(dest / preset.contest)
    if preset.problem is not None:
        clean_copied_problem_dir(dest / preset.problem)

    clean_copied_package_dir(dest)


def _install_preset_from_remote(
    fetch_info: PresetFetchInfo,
    dest: pathlib.Path,
    ensure_contest: bool = False,
    ensure_problem: bool = False,
    update: bool = False,
):
    import git

    assert fetch_info.fetch_uri is not None
    with tempfile.TemporaryDirectory() as d:
        console.console.print(
            f'Cloning preset from [item]{fetch_info.fetch_uri}[/item]...'
        )
        repo = git.Repo.clone_from(fetch_info.fetch_uri, d)
        if fetch_info.tool_tag is not None:
            console.console.print(
                f'Checking out tool tag [item]{fetch_info.tool_tag}[/item]...'
            )
            try:
                repo.git.checkout(fetch_info.tool_tag)
            except Exception as e:
                console.console.print(
                    f'[error]Could not checkout tool tag [item]{fetch_info.tool_tag}[/item] for preset [item]{fetch_info.name}[/item].[/error]'
                )
                raise typer.Exit(1) from e
        pd = pathlib.Path(d)
        if fetch_info.inner_dir:
            console.console.print(
                f'Installing preset from [item]{fetch_info.inner_dir}[/item].'
            )
            pd = pd / fetch_info.inner_dir
        install_preset_from_dir(
            pd,
            dest,
            ensure_contest,
            ensure_problem,
            override_uri=fetch_info.fetch_uri,
            update=update,
        )


def _install_preset_from_local_dir(
    fetch_info: PresetFetchInfo,
    dest: pathlib.Path,
    ensure_contest: bool = False,
    ensure_problem: bool = False,
    update: bool = False,
):
    pd = pathlib.Path(fetch_info.inner_dir)
    preset = get_preset_yaml(pd)
    console.console.print(
        f'Installing local preset [item]{preset.name}[/item] into [item]{dest}[/item]...'
    )
    install_preset_from_dir(
        pd,
        dest,
        ensure_contest,
        ensure_problem,
        override_uri=str(utils.abspath(pd)),
        update=update,
    )


def _install_preset_from_resources(
    fetch_info: PresetFetchInfo,
    dest: pathlib.Path,
    ensure_contest: bool = False,
    ensure_problem: bool = False,
    update: bool = False,
):
    rsrc_preset_path = get_default_app_path() / 'presets' / fetch_info.name
    if not rsrc_preset_path.exists():
        return False
    yaml_path = rsrc_preset_path / 'preset.rbx.yml'
    if not yaml_path.is_file():
        return False
    preset_uri = get_remote_uri_from_tool_preset(fetch_info.name)
    remote_fetch_info = get_preset_fetch_info(preset_uri)
    if remote_fetch_info is None or remote_fetch_info.fetch_uri is None:
        console.console.print(
            f'[error]Preset [item]{fetch_info.name}[/item] not found.[/error]'
        )
        raise typer.Exit(1)

    # Check if the latest release has breaking changes.
    latest_tag = latest_remote_tag(remote_fetch_info.fetch_uri)
    latest_version = semver.VersionInfo.parse(latest_tag)
    if latest_version.major > utils.get_semver().major:
        console.console.print(
            f'[error]You are not in rbx.cp latest major version ({latest_version.major}), but are installing a built-in preset from rbx.cp.[/error]'
        )
        console.console.print(
            f'[error]To allow for a better experience for users that clone your repository, please update rbx.cp to the latest major version using [item]{utils.get_upgrade_command(latest_version)}[/item].[/error]'
        )
        if not questionary.confirm(
            'If you want to proceed anyway, press [y]', default=False
        ).ask():
            raise typer.Exit(1)

    console.console.print(
        f'Installing preset [item]{fetch_info.name}[/item] from resources...'
    )
    install_preset_from_dir(
        rsrc_preset_path,
        dest,
        ensure_contest,
        ensure_problem,
        override_uri=preset_uri,
        update=update,
    )
    return True


def _install_preset_from_fetch_info(
    fetch_info: PresetFetchInfo,
    dest: pathlib.Path,
    ensure_contest: bool = False,
    ensure_problem: bool = False,
    update: bool = False,
):
    if fetch_info.is_remote():
        _install_preset_from_remote(
            fetch_info,
            dest,
            ensure_contest=ensure_contest,
            ensure_problem=ensure_problem,
            update=update,
        )
        return
    if fetch_info.is_local_dir():
        _install_preset_from_local_dir(
            fetch_info,
            dest,
            ensure_contest=ensure_contest,
            ensure_problem=ensure_problem,
            update=update,
        )
        return
    if fetch_info.is_tool():
        # Fallback to the remote tool tag if it exists.
        assert fetch_info.tool_tag is not None
        remote_fetch_info = get_preset_fetch_info(
            get_remote_uri_from_tool_preset(fetch_info.name)
        )
        assert remote_fetch_info is not None
        remote_fetch_info.tool_tag = fetch_info.tool_tag

        _install_preset_from_remote(
            remote_fetch_info,
            dest,
            ensure_contest=ensure_contest,
            ensure_problem=ensure_problem,
            update=update,
        )
        return

    # if _install_preset_from_resources(
    #     fetch_info,
    #     dest,
    #     ensure_contest=ensure_contest,
    #     ensure_problem=ensure_problem,
    #     update=update,
    # ):
    #     return
    console.console.print(
        f'[error]Preset [item]{fetch_info.name}[/item] not found.[/error]'
    )
    raise typer.Exit(1)


def install_preset_at_package(fetch_info: PresetFetchInfo, dest_pkg: pathlib.Path):
    _install_preset_from_fetch_info(fetch_info, dest_pkg / '.local.rbx')


def _install_package_from_preset(
    preset_path: pathlib.Path,
    preset_package_inner_path: pathlib.Path,
    dest_pkg: pathlib.Path,
    tracked_assets: List[TrackedAsset],
):
    preset_package_path = preset_path / preset_package_inner_path
    if not preset_package_path.is_dir():
        console.console.print(
            f'[error]Preset [item]{preset_path.name}[/item] does not have a [item]{preset_package_inner_path}[/item] package definition.[/error]'
        )
        raise typer.Exit(1)

    for file in _glob_while_ignoring(
        preset_package_path,
        '*',
        recursive=True,
    ):
        if not file.is_file():
            continue
        copy_preset_file(
            file,
            dest_pkg / file.relative_to(preset_package_path),
            preset_package_path,
            preset_path,
        )

    for asset in tracked_assets:
        if not asset.symlink:
            continue
        copy_preset_file(
            preset_package_path / asset.path,
            dest_pkg / asset.path,
            preset_package_path,
            preset_path,
            force_symlink=True,
        )


def install_contest(
    dest_pkg: pathlib.Path, fetch_info: Optional[PresetFetchInfo] = None
):
    if fetch_info is not None:
        _install_preset_from_fetch_info(
            fetch_info,
            dest_pkg / '.local.rbx',
            ensure_contest=True,
        )
    preset = get_active_preset(dest_pkg)
    preset_path = find_local_preset(dest_pkg)
    assert preset_path is not None
    if preset.contest is None:
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] does not have a contest package definition.[/error]'
        )
        raise typer.Exit(1)

    console.console.print(
        f'Installing contest from [item]{preset_path / preset.contest}[/item] to [item]{dest_pkg}[/item]...'
    )
    _install_package_from_preset(
        preset_path, preset.contest, dest_pkg, preset.tracking.contest
    )
    clean_copied_contest_dir(dest_pkg, delete_local_rbx=False)


def install_problem(
    dest_pkg: pathlib.Path, fetch_info: Optional[PresetFetchInfo] = None
):
    if fetch_info is not None:
        _install_preset_from_fetch_info(
            fetch_info,
            dest_pkg / '.local.rbx',
            ensure_problem=True,
        )
    preset = get_active_preset(dest_pkg)
    preset_path = find_local_preset(dest_pkg)
    assert preset_path is not None
    if preset.problem is None:
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] does not have a problem package definition.[/error]'
        )
        raise typer.Exit(1)

    console.console.print(
        f'Installing problem from [item]{preset_path / preset.problem}[/item] to [item]{dest_pkg}[/item]...'
    )
    _install_package_from_preset(
        preset_path, preset.problem, dest_pkg, preset.tracking.problem
    )
    clean_copied_problem_dir(dest_pkg)


def install_preset(
    dest_pkg: pathlib.Path, fetch_info: Optional[PresetFetchInfo] = None
):
    if fetch_info is None and get_active_preset_or_null() is None:
        console.console.print(
            '[error]No preset found to initialize the new preset from.[/error]'
        )
        raise typer.Exit(1)
    if fetch_info is None:
        install_preset_from_dir(get_active_preset_path(), dest_pkg)
    else:
        _install_preset_from_fetch_info(fetch_info, dest_pkg)


def get_ruyaml(root: pathlib.Path = pathlib.Path()) -> Tuple[ruyaml.YAML, ruyaml.Any]:
    if not (root / 'preset.rbx.yml').is_file():
        console.console.print(
            f'[error]Preset at [item]{root}[/item] does not have a [item]preset.rbx.yml[/item] file.[/error]'
        )
        raise typer.Exit(1)
    res = ruyaml.YAML()
    return res, res.load(root / 'preset.rbx.yml')


def generate_lock(root: pathlib.Path = pathlib.Path()):
    preset = get_active_preset(root)

    tracked_assets = get_preset_tracked_assets(root, is_contest=is_contest(root))
    preset_lock = PresetLock(
        name=preset.name,
        assets=build_package_locked_assets(tracked_assets, root),
    )

    (root / '.preset-lock.yml').write_text(utils.model_to_yaml(preset_lock))
    console.console.print(
        '[success][item].preset-lock.yml[/item] was created.[/success]'
    )


def _sync(try_update: bool = False, force: bool = False, symlinks: bool = False):
    preset_lock = get_preset_lock()
    if preset_lock is None:
        console.console.print(
            '[error]Package does not have a [item].preset.lock.yml[/item] file and thus cannot be synced.[/error]'
        )
        console.console.print(
            '[error]Ensure this package was created through a preset, or manually associate one with [item]rbx presets lock [PRESET][/item][/error]'
        )
        raise typer.Exit(1)

    if try_update:
        update()

    _copy_updated_assets(
        preset_lock,
        is_contest=is_contest(),
        force=force,
        symlinks=symlinks,
    )
    generate_lock()


def copy_tree_normalizing_gitdir(
    src_path: pathlib.Path, dst_path: pathlib.Path, update: bool = False
):
    shutil.copytree(str(src_path), str(dst_path), dirs_exist_ok=update, symlinks=True)

    if not (src_path / '.git').is_file():
        return

    src_repo = git_utils.get_repo_or_nil(src_path)
    if src_repo is None:
        return

    gitdir_dst = dst_path / '.git'
    shutil.rmtree(str(gitdir_dst), ignore_errors=True)
    gitdir_dst.unlink(missing_ok=True)

    shutil.copytree(str(src_repo.git_dir), str(gitdir_dst))


def copy_local_preset(
    preset_path: pathlib.Path, dest_path: pathlib.Path, remote_uri: Optional[str] = None
):
    copy_tree_normalizing_gitdir(preset_path, dest_path / '.local.rbx')

    preset_repo = git_utils.get_repo_or_nil(preset_path)
    current_repo = git_utils.get_repo_or_nil(
        pathlib.Path.cwd(), search_parent_directories=True
    )

    if preset_repo is None or current_repo is None:
        return

    fetch_info = get_preset_fetch_info(remote_uri)
    remote_uri = fetch_info.fetch_uri if fetch_info is not None else None

    preset_remote = git_utils.get_any_remote(preset_repo)
    preset_remote_uri = preset_remote.url if preset_remote is not None else remote_uri
    if preset_remote_uri is None:
        return

    import questionary

    add_submodule = questionary.confirm(
        'The preset is installed from a remote Git repository. Do you want to add it as a submodule of your project?',
        default=False,
    ).ask()
    if not add_submodule:
        return

    dest_path_rel = utils.abspath(dest_path).relative_to(
        utils.abspath(pathlib.Path.cwd())
    )
    path_str = str(dest_path_rel / '.local.rbx')
    try:
        current_repo.git.submodule('add', preset_remote_uri, path_str)
    except Exception as e:
        console.console.print('[error]Failed to add preset as a submodule.[/error]')
        console.console.print(f'[error]Error:[/error] {e}')
        console.console.print(
            '[error]You might want to do this manually with the [item]git submodule add[/item] command.[/error]'
        )
        raise typer.Exit(1) from None
    console.console.print(
        f'[success]Preset [item]{preset_remote_uri}[/item] was added as a submodule to your project at [item]{path_str}[/item].[/success]'
    )


@app.command('create', help='Create a new preset.')
def create(
    name: Annotated[
        str,
        typer.Option(
            help='The name of the preset to create. This will also be the name of the folder.',
            prompt='What is the name of your new preset?',
        ),
    ],
    uri: Annotated[
        str,
        typer.Option(
            help='The URI of the new preset.',
            prompt='What is the URI of your new preset? (ex: rsalesc/rbx-preset for a GitHub repository)',
        ),
    ],
    from_preset: Annotated[
        Optional[str],
        typer.Option(
            '--preset', '-p', help='The URI of the preset to init the new preset from.'
        ),
    ] = None,
):
    console.console.print(f'Creating new preset [item]{name}[/item]...')

    fetch_info = get_preset_fetch_info_with_fallback(from_preset)
    dest_path = pathlib.Path(name)
    if dest_path.exists():
        console.console.print(
            f'[error]Directory [item]{dest_path}[/item] already exists.[/error]'
        )
        raise typer.Exit(1)

    install_preset(dest_path, fetch_info)

    ru, preset = get_ruyaml(dest_path)
    preset['name'] = name
    preset['uri'] = uri
    utils.save_ruyaml(dest_path / 'preset.rbx.yml', ru, preset)


@app.command('update', help='Update preset of current package')
def update():
    preset = get_active_preset()
    if _is_active_preset_nested():
        console.console.print(
            '[error]Your package is nested inside the active preset. Updating such a preset is not supported.[/error]'
        )
        return
    if not _is_installed_preset():
        console.console.print(
            '[error]Your active preset is not installed in a [item].local.rbx[/item] directory. Updating such a preset is not supported.[/error]'
        )
        return
    if preset.uri is None:
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] is not updateable because it does not have a remote URI.'
        )
        return

    import questionary

    console.console.print(
        f'Updating preset [item]{preset.name}[/item] from [item]{preset.uri}[/item]...'
    )
    if not questionary.confirm(
        'Updating local preset from remote will remove all custom changes you made to the preset.',
        default=False,
    ).ask():
        return

    preset_path = find_local_preset(pathlib.Path.cwd())
    assert preset_path is not None
    _install_preset_from_fetch_info(preset.fetch_info, dest=preset_path, update=True)
    console.console.print(
        f'[success]Preset [item]{preset.name}[/item] updated successfully.[/success]'
    )


@app.command(
    'sync',
    help='Sync current package assets with those provided by the installed preset.',
)
@cd.within_closest_package
def sync(
    update: Annotated[
        bool,
        typer.Option(
            '--update',
            '-u',
            help='Whether to fetch an up-to-date version of the installed preset from remote, if available.',
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            '--force',
            '-f',
            help='Whether to forcefully overwrite the local assets with the preset assets, even if they have been modified.',
        ),
    ] = False,
    symlinks: Annotated[
        bool,
        typer.Option(
            '--symlinks',
            '-s',
            help='Whether to update all symlinks in the preset to point to their right targets.',
        ),
    ] = False,
):
    check_is_valid_package()
    _sync(try_update=update, force=force, symlinks=symlinks)


@app.command(
    'lock',
    help='Generate a lock for this package, based on a existing preset.',
    hidden=True,
)
@cd.within_closest_package
def lock():
    check_is_valid_package()
    generate_lock()


@app.command('ls', help='List details about the active preset.')
@cd.within_closest_package
def ls():
    preset = get_active_preset()
    preset_path = find_local_preset(pathlib.Path.cwd())
    console.console.print(f'Preset: [item]{preset.name}[/item]')
    console.console.print(f'Path: {preset_path}')
    console.console.print(f'URI: {preset.uri}')


@app.callback()
def callback():
    pass
