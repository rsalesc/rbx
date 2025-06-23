import pathlib
import shutil
import tempfile
from typing import Annotated, Iterable, List, Optional, Sequence, Union

import typer

from rbx import console, utils
from rbx.box import cd
from rbx.box.presets.fetch import PresetFetchInfo, get_preset_fetch_info
from rbx.box.presets.lock_schema import LockedAsset, PresetLock
from rbx.box.presets.schema import Preset, TrackedAsset
from rbx.config import get_default_app_path
from rbx.grading.judge.digester import digest_cooperatively

app = typer.Typer(no_args_is_help=True)


def _find_preset_yaml(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    found = root / 'preset.rbx.yml'
    if found.exists():
        return found
    return None


def _get_preset_yaml(root: pathlib.Path = pathlib.Path()) -> Preset:
    found = _find_preset_yaml(root)
    if not found:
        console.console.print(
            f'[error][item]preset.rbx.yml[/item] not found in [item]{root.absolute()}[/item][/error]'
        )
        raise typer.Exit(1)
    return utils.model_from_yaml(Preset, found.read_text())


def _find_preset_lock(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    root = root.resolve()
    problem_yaml_path = root / '.preset-lock.yml'
    if not problem_yaml_path.is_file():
        return None
    return problem_yaml_path


def _get_preset_lock(root: pathlib.Path = pathlib.Path()) -> Optional[PresetLock]:
    found = _find_preset_lock(root)
    if not found:
        return None
    return utils.model_from_yaml(PresetLock, found.read_text())


def _find_nested_preset(root: pathlib.Path) -> Optional[pathlib.Path]:
    root = root.resolve()
    problem_yaml_path = root / 'preset.rbx.yml'
    while root != pathlib.PosixPath('/') and not problem_yaml_path.is_file():
        root = root.parent
        problem_yaml_path = root / 'preset.rbx.yml'
    if not problem_yaml_path.is_file():
        return None
    return problem_yaml_path.parent


def _find_local_preset(root: pathlib.Path) -> Optional[pathlib.Path]:
    original_root = root
    root = root.resolve()
    problem_yaml_path = root / '.local.rbx' / 'preset.rbx.yml'
    while root != pathlib.PosixPath('/') and not problem_yaml_path.is_file():
        root = root.parent
        problem_yaml_path = root / '.local.rbx' / 'preset.rbx.yml'
    if not problem_yaml_path.is_file():
        return _find_nested_preset(original_root)
    return problem_yaml_path.parent


def _is_installed_preset(root: pathlib.Path = pathlib.Path()) -> bool:
    preset_path = _find_local_preset(root)
    if preset_path is None:
        return False
    resolved_path = preset_path.resolve()
    return resolved_path.name == '.local.rbx'


def _is_active_preset_nested(root: pathlib.Path = pathlib.Path()) -> bool:
    preset_path = _find_local_preset(root)
    if preset_path is None:
        return False
    nested_preset_path = _find_nested_preset(root)
    if nested_preset_path is None:
        return False
    return nested_preset_path == preset_path


def _is_contest(root: pathlib.Path = pathlib.Path()) -> bool:
    return (root / 'contest.rbx.yml').is_file()


def _is_problem(root: pathlib.Path = pathlib.Path()) -> bool:
    return (root / 'problem.rbx.yml').is_file()


def _check_is_valid_package(root: pathlib.Path = pathlib.Path()):
    if not _is_contest(root) and not _is_problem(root):
        console.console.print('[error]Not a valid rbx package directory.[/error]')
        raise typer.Exit(1)


def _process_globbing(
    assets: Iterable[TrackedAsset], preset_dir: pathlib.Path
) -> List[TrackedAsset]:
    res = []
    for asset in assets:
        if '*' in str(asset.path):
            glb = str(asset.path)
            files = preset_dir.glob(glb)
            relative_files = [file.relative_to(preset_dir) for file in files]
            res.extend([TrackedAsset(path=path) for path in relative_files])
            continue
        res.append(asset)
    return res


def _get_preset_tracked_assets(
    root: pathlib.Path, is_contest: bool
) -> List[TrackedAsset]:
    preset = get_active_preset(root)
    preset_path = _find_local_preset(root)
    assert preset_path is not None

    if is_contest:
        assert (
            preset.contest is not None
        ), 'Preset does not have a contest package definition.'
        return _process_globbing(preset.tracking.contest, preset_path)

    assert (
        preset.problem is not None
    ), 'Preset does not have a problem package definition,'
    return _process_globbing(preset.tracking.problem, preset_path)


def _build_package_locked_assets(
    tracked_assets: Sequence[Union[TrackedAsset, LockedAsset]],
    root: pathlib.Path = pathlib.Path(),
) -> List[LockedAsset]:
    res = []
    for tracked_asset in tracked_assets:
        asset_path = root / tracked_asset.path
        if not asset_path.is_file():
            continue
        with asset_path.open('rb') as f:
            res.append(
                LockedAsset(path=tracked_asset.path, hash=digest_cooperatively(f))
            )
    return res


def _find_non_modified_assets(
    reference: List[LockedAsset], current: List[LockedAsset]
) -> List[LockedAsset]:
    current_by_path = {asset.path: asset for asset in current}

    res = []
    for asset in reference:
        if (
            asset.path in current_by_path
            and current_by_path[asset.path].hash != asset.hash
        ):
            # This is a file that was modified.
            continue
        res.append(asset)
    return res


def _find_modified_assets(
    reference: List[LockedAsset],
    current: List[LockedAsset],
):
    reference_by_path = {asset.path: asset for asset in reference}

    res = []
    for asset in current:
        if (
            asset.path in reference_by_path
            and reference_by_path[asset.path].hash == asset.hash
        ):
            # This is a file that was not modified.
            continue
        res.append(asset)
    return res


def _copy_updated_assets(
    preset_lock: PresetLock,
    is_contest: bool,
    root: pathlib.Path = pathlib.Path(),
):
    current_package_snapshot = _build_package_locked_assets(preset_lock.assets)
    non_modified_assets = _find_non_modified_assets(
        preset_lock.assets, current_package_snapshot
    )

    preset = get_active_preset(root)
    preset_package_path = _get_active_preset_package_path(root, is_contest)

    preset_tracked_assets = _get_preset_tracked_assets(
        preset_package_path, is_contest=is_contest
    )
    current_preset_snapshot = _build_package_locked_assets(
        preset_tracked_assets, preset_package_path
    )
    assets_to_copy = _find_modified_assets(non_modified_assets, current_preset_snapshot)

    for asset in assets_to_copy:
        src_path = preset_package_path / asset.path
        dst_path = root / asset.path
        shutil.copyfile(str(src_path), str(dst_path))
        console.console.print(
            f'Updated [item]{asset.path}[/item] from preset [item]{preset.name}[/item].'
        )


def get_active_preset_or_null(root: pathlib.Path = pathlib.Path()) -> Optional[Preset]:
    local_preset = _find_local_preset(root)
    if local_preset is not None:
        return _get_preset_yaml(local_preset)
    return None


def get_active_preset(root: pathlib.Path = pathlib.Path()) -> Preset:
    preset = get_active_preset_or_null(root)
    if preset is None:
        console.console.print('[error]No preset is active.[/error]')
        raise typer.Exit(1)
    return preset


def get_active_preset_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    preset_path = _find_local_preset(root)
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
    preset_path = _find_local_preset(root)
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
        default_preset = get_preset_fetch_info('default')
        if default_preset is None:
            console.console.print(
                '[error]Internal error: could not find [item]default[/item] preset.[/error]'
            )
            raise typer.Exit(1)
        return default_preset
    return get_preset_fetch_info(uri)


def _clean_copied_package_dir(dest: pathlib.Path):
    for box_dir in dest.rglob('.box'):
        shutil.rmtree(str(box_dir), ignore_errors=True)
    for lock in dest.rglob('.preset-lock.yml'):
        lock.unlink(missing_ok=True)


def _clean_copied_contest_dir(dest: pathlib.Path, delete_local_rbx: bool = True):
    shutil.rmtree(str(dest / 'build'), ignore_errors=True)
    if delete_local_rbx:
        shutil.rmtree(str(dest / '.local.rbx'), ignore_errors=True)
    _clean_copied_package_dir(dest)


def _clean_copied_problem_dir(dest: pathlib.Path):
    shutil.rmtree(str(dest / 'build'), ignore_errors=True)
    _clean_copied_package_dir(dest)


def _install_preset_from_dir(
    src: pathlib.Path,
    dest: pathlib.Path,
    ensure_contest: bool = False,
    ensure_problem: bool = False,
    update: bool = False,
    override_uri: Optional[str] = None,
):
    preset = _get_preset_yaml(src)

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
        _clean_copied_contest_dir(dest / preset.contest)
    if preset.problem is not None:
        _clean_copied_problem_dir(dest / preset.problem)

    _clean_copied_package_dir(dest)


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
        git.Repo.clone_from(fetch_info.fetch_uri, d)
        pd = pathlib.Path(d)
        if fetch_info.inner_dir:
            console.console.print(
                f'Installing preset from [item]{fetch_info.inner_dir}[/item].'
            )
            pd = pd / fetch_info.inner_dir
        _install_preset_from_dir(
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
    preset = _get_preset_yaml(pd)
    console.console.print(
        f'Installing local preset [item]{preset.name}[/item] into [item]{dest}[/item]...'
    )
    _install_preset_from_dir(
        pd,
        dest,
        ensure_contest,
        ensure_problem,
        override_uri=str(pd.resolve()),
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
    console.console.print(
        f'Installing preset [item]{fetch_info.name}[/item] from resources...'
    )
    _install_preset_from_dir(
        rsrc_preset_path,
        dest,
        ensure_contest,
        ensure_problem,
        override_uri=str(rsrc_preset_path.resolve()),
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
    if _install_preset_from_resources(
        fetch_info,
        dest,
        ensure_contest=ensure_contest,
        ensure_problem=ensure_problem,
        update=update,
    ):
        return
    console.console.print(
        f'[error]Preset [item]{fetch_info.name}[/item] not found.[/error]'
    )
    raise typer.Exit(1)


def install_preset_at_package(fetch_info: PresetFetchInfo, dest_pkg: pathlib.Path):
    _install_preset_from_fetch_info(fetch_info, dest_pkg / '.local.rbx')


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
    preset_path = _find_local_preset(dest_pkg)
    assert preset_path is not None
    if preset.contest is None:
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] does not have a contest package definition.[/error]'
        )
        raise typer.Exit(1)

    console.console.print(
        f'Installing contest from [item]{preset_path / preset.contest}[/item] to [item]{dest_pkg}[/item]...'
    )
    shutil.copytree(
        str(preset_path / preset.contest),
        str(dest_pkg),
        dirs_exist_ok=True,
    )
    _clean_copied_contest_dir(dest_pkg, delete_local_rbx=False)


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
    preset_path = _find_local_preset(dest_pkg)
    assert preset_path is not None
    if preset.problem is None:
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] does not have a problem package definition.[/error]'
        )
        raise typer.Exit(1)

    console.console.print(
        f'Installing problem from [item]{preset_path / preset.problem}[/item] to [item]{dest_pkg}[/item]...'
    )
    shutil.copytree(
        str(preset_path / preset.problem),
        str(dest_pkg),
        dirs_exist_ok=True,
    )
    _clean_copied_problem_dir(dest_pkg)


def generate_lock(root: pathlib.Path = pathlib.Path()):
    preset = get_active_preset(root)

    tracked_assets = _get_preset_tracked_assets(root, is_contest=_is_contest(root))
    preset_lock = PresetLock(
        name=preset.name,
        assets=_build_package_locked_assets(tracked_assets, root),
    )

    (root / '.preset-lock.yml').write_text(utils.model_to_yaml(preset_lock))
    console.console.print(
        '[success][item].preset-lock.yml[/item] was created.[/success]'
    )


def _sync(try_update: bool = False):
    preset_lock = _get_preset_lock()
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
        is_contest=_is_contest(),
    )
    generate_lock()


def copy_tree_normalizing_gitdir(
    src_path: pathlib.Path, dst_path: pathlib.Path, update: bool = False
):
    from rbx.box import git_utils

    shutil.copytree(str(src_path), str(dst_path), dirs_exist_ok=update)
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

    from rbx.box import git_utils

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

    dest_path_rel = dest_path.resolve().relative_to(pathlib.Path.cwd().resolve())
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

    preset_path = _find_local_preset(pathlib.Path.cwd())
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
):
    _check_is_valid_package()
    _sync(try_update=update)


@app.command(
    'lock', help='Generate a lock for this package, based on a existing preset.'
)
@cd.within_closest_package
def lock():
    _check_is_valid_package()
    generate_lock()


@app.command('ls', help='List details about the active preset.')
@cd.within_closest_package
def ls():
    preset = get_active_preset()
    preset_path = _find_local_preset(pathlib.Path.cwd())
    console.console.print(f'Preset: [item]{preset.name}[/item]')
    console.console.print(f'Path: {preset_path}')
    console.console.print(f'URI: {preset.uri}')


@app.callback()
def callback():
    pass
