import pathlib
import shutil
import tempfile
from typing import Annotated, Iterable, List, Optional, Sequence, Union

import rich
import rich.prompt
import typer
from iso639.language import functools

from rbx import console, utils
from rbx.box import cd, git_utils
from rbx.box.environment import get_environment_path
from rbx.box.presets.fetch import PresetFetchInfo, get_preset_fetch_info
from rbx.box.presets.lock_schema import LockedAsset, PresetLock
from rbx.box.presets.schema import Preset, TrackedAsset
from rbx.config import get_default_app_path
from rbx.grading.judge.digester import digest_cooperatively, digest_file

app = typer.Typer(no_args_is_help=True)

LOCAL = 'local'


def find_preset_yaml(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    found = root / 'preset.rbx.yml'
    if found.exists():
        return found
    return None


def get_preset_yaml(root: pathlib.Path = pathlib.Path()) -> Preset:
    found = find_preset_yaml(root)
    if not found:
        console.console.print(
            f'[error][item]preset.rbx.yml[/item] not found in [item]{root.absolute()}[/item][/error]'
        )
        raise typer.Exit(1)
    return utils.model_from_yaml(Preset, found.read_text())


def find_preset_lock(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    root = root.resolve()
    problem_yaml_path = root / '.preset-lock.yml'
    if not problem_yaml_path.is_file():
        return None
    return problem_yaml_path


def get_preset_lock(root: pathlib.Path = pathlib.Path()) -> Optional[PresetLock]:
    found = find_preset_lock(root)
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


def get_preset_installation_path(
    name: str, root: pathlib.Path = pathlib.Path()
) -> pathlib.Path:
    if name == LOCAL:
        local_path = _find_local_preset(root)
        if local_path is None:
            console.console.print('[error]Local preset was not found.[/error]')
            raise typer.Exit(1)
        return local_path
    nested_preset_path = _find_nested_preset(root)
    if nested_preset_path is not None:
        nested_preset = utils.model_from_yaml(
            Preset, (nested_preset_path / 'preset.rbx.yml').read_text()
        )
        if nested_preset.name == name:
            return nested_preset_path
    return utils.get_app_path() / 'presets' / name


def _find_installed_presets() -> List[str]:
    folder = utils.get_app_path() / 'presets'

    res = []
    if get_preset_installation_path('local'):
        res.append('local')
    for yml in folder.glob('*/preset.rbx.yml'):
        res.append(yml.parent.name)
    return res


def _is_contest(root: pathlib.Path = pathlib.Path()) -> bool:
    return (root / 'contest.rbx.yml').is_file()


def _is_problem(root: pathlib.Path = pathlib.Path()) -> bool:
    return (root / 'problem.rbx.yml').is_file()


def _check_is_valid_package(root: pathlib.Path = pathlib.Path()):
    if not _is_contest(root) and not _is_problem(root):
        console.console.print('[error]Not a valid rbx package directory.[/error]')
        raise typer.Exit(1)


def _get_preset_package_path(
    name: str, is_contest: bool, root: pathlib.Path = pathlib.Path()
) -> pathlib.Path:
    preset_path = get_preset_installation_path(name, root)
    preset = get_installed_preset(name, root)

    if is_contest:
        assert (
            preset.contest is not None
        ), 'Preset does not have a contest package definition.'
        return preset_path / preset.contest

    assert (
        preset.problem is not None
    ), 'Preset does not have a problem package definition,'
    return preset_path / preset.problem


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


def _get_preset_tracked_assets(name: str, is_contest: bool) -> List[TrackedAsset]:
    preset = get_installed_preset(name)
    preset_path = get_preset_installation_path(name)

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
    preset_name: str,
    preset_lock: PresetLock,
    is_contest: bool,
    root: pathlib.Path = pathlib.Path(),
):
    current_package_snapshot = _build_package_locked_assets(preset_lock.assets)
    non_modified_assets = _find_non_modified_assets(
        preset_lock.assets, current_package_snapshot
    )

    preset_package_path = _get_preset_package_path(preset_name, is_contest=is_contest)
    preset_tracked_assets = _get_preset_tracked_assets(
        preset_name, is_contest=is_contest
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
            f'Updated [item]{asset.path}[/item] from preset [item]{preset_name}[/item].'
        )


def _try_installing_from_resources(name: str) -> bool:
    if name == LOCAL:
        return False
    rsrc_preset_path = get_default_app_path() / 'presets' / name
    if not rsrc_preset_path.exists():
        return False
    yaml_path = rsrc_preset_path / 'preset.rbx.yml'
    if not yaml_path.is_file():
        return False
    console.console.print(f'Installing preset [item]{name}[/item] from resources...')
    _install(rsrc_preset_path, force=True)
    return True


@functools.cache
def _install_from_resources_just_once(name: str) -> bool:
    # Send all output to the void since we don't wanna be verbose here.
    with console.console.capture():
        return _try_installing_from_resources(name)


def get_installed_preset_or_null(
    name: str, root: pathlib.Path = pathlib.Path()
) -> Optional[Preset]:
    installation_path = get_preset_installation_path(name, root) / 'preset.rbx.yml'
    if not installation_path.is_file():
        if not _try_installing_from_resources(name):
            return None
    elif name == 'default':
        _install_from_resources_just_once(name)

    return utils.model_from_yaml(Preset, installation_path.read_text())


def get_installed_preset(name: str, root: pathlib.Path = pathlib.Path()) -> Preset:
    preset = get_installed_preset_or_null(name, root)
    if preset is None:
        console.console.print(
            f'[error]Preset [item]{name}[/item] is not installed.[/error]'
        )
        raise typer.Exit(1)
    return preset


def optionally_install_environment_from_preset(
    preset: Preset, root: pathlib.Path = pathlib.Path()
):
    if preset.env is None:
        return
    env_path = get_environment_path(preset.name)
    preset_env_path = root / preset.env
    if env_path.is_file():
        if digest_file(preset_env_path) == digest_file(env_path):
            return
        import questionary

        overwrite = questionary.confirm(
            'Preset environment file has changed. Overwrite?',
            default=False,
        ).ask()
        if not overwrite:
            return

    console.console.print(
        f'[success]Overwriting the existing environment based on [item]{preset.env}[/item].'
    )
    env_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(preset_env_path), env_path)


def _install(root: pathlib.Path = pathlib.Path(), force: bool = False):
    preset = get_preset_yaml(root)

    if preset.name == LOCAL:
        console.console.print('[error]Naming a preset "local" is prohibited.[/error]')

    console.console.print(f'Installing preset [item]{preset.name}[/item]...')
    installation_path = get_preset_installation_path(preset.name)

    if root.resolve().is_relative_to(installation_path.resolve()):
        console.console.print(
            '[error]Current folder is nested into the preset installation path, cannot install it.[/error]'
        )
        raise typer.Exit(1)

    if preset.env is not None:
        console.console.print(
            f'[item]{preset.name}[/item]: Copying environment file...'
        )
        should_copy_env = True
        if get_environment_path(preset.name).exists():
            res = force or rich.prompt.Confirm.ask(
                f'Environment [item]{preset.name}[/item] already exists. Overwrite?',
                console=console.console,
            )
            if not res:
                should_copy_env = False

        if should_copy_env:
            get_environment_path(preset.name).parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(get_environment_path(preset.name), ignore_errors=True)
            shutil.copyfile(str(root / preset.env), get_environment_path(preset.name))

    console.console.print(f'[item]{preset.name}[/item]: Copying preset folder...')
    installation_path.parent.mkdir(parents=True, exist_ok=True)
    if installation_path.exists():
        res = force or rich.prompt.Confirm.ask(
            f'Preset [item]{preset.name}[/item] is already installed. Overwrite?',
            console=console.console,
        )
        if not res:
            raise typer.Exit(1)
    shutil.rmtree(str(installation_path), ignore_errors=True)
    copy_tree_normalizing_gitdir(root, installation_path)
    shutil.rmtree(str(installation_path / 'build'), ignore_errors=True)
    shutil.rmtree(str(installation_path / '.box'), ignore_errors=True)
    shutil.rmtree(str(installation_path / '.local.rbx'), ignore_errors=True)


def install_from_local_dir(fetch_info: PresetFetchInfo, force: bool = False) -> str:
    pd = pathlib.Path(fetch_info.inner_dir)
    preset = get_preset_yaml(pd)
    _install(pd, force=force)
    return preset.name


def install_from_remote(fetch_info: PresetFetchInfo, force: bool = False) -> str:
    import git

    assert fetch_info.fetch_uri is not None
    with tempfile.TemporaryDirectory() as d:
        console.console.print(
            f'Cloning preset from [item]{fetch_info.fetch_uri}[/item]...'
        )
        git.Repo.clone_from(fetch_info.fetch_uri, d)
        pd = pathlib.Path(d)
        if fetch_info.inner_dir:
            pd = pd / fetch_info.inner_dir
            console.console.print(
                f'Installing preset from [item]{fetch_info.inner_dir}[/item].'
            )
        preset = get_preset_yaml(pd)
        preset.uri = fetch_info.uri

        (pd / 'preset.rbx.yml').write_text(utils.model_to_yaml(preset))
        _install(pd, force=force)
        return preset.name


def generate_lock(
    preset_name: Optional[str] = None, root: pathlib.Path = pathlib.Path()
):
    if preset_name is None:
        preset_lock = get_preset_lock(root)
        if preset_lock is None:
            console.console.print(
                '[error][item].preset-lock.yml[/item] not found. '
                'Specify a preset argument to this function to create a lock from scratch.[/error]'
            )
            raise typer.Exit(1)
        preset_name = preset_lock.preset_name

    preset = get_installed_preset(preset_name, root)

    tracked_assets = _get_preset_tracked_assets(preset_name, is_contest=_is_contest())
    preset_lock = PresetLock(
        name=preset.name if preset_name != LOCAL else LOCAL,
        uri=preset.uri,
        assets=_build_package_locked_assets(tracked_assets, root),
    )

    (root / '.preset-lock.yml').write_text(utils.model_to_yaml(preset_lock))
    console.console.print(
        '[success][item].preset-lock.yml[/item] was created.[/success]'
    )


def _sync(try_update: bool = False):
    preset_lock = get_preset_lock()
    if preset_lock is None:
        console.console.print(
            '[error]Package does not have a [item].preset.lock.yml[/item] file and thus cannot be synced.[/error]'
        )
        console.console.print(
            '[error]Ensure this package was created through a preset, or manually associate one with [item]rbx presets lock [PRESET][/item][/error]'
        )
        raise typer.Exit(1)

    should_update = try_update and preset_lock.uri is not None
    installed_preset = get_installed_preset_or_null(preset_lock.preset_name)
    if installed_preset is None:
        if not try_update or preset_lock.uri is None:
            console.console.print(
                f'[error]Preset [item]{preset_lock.preset_name}[/item] is not installed. Install it before trying to update.'
            )
            raise typer.Exit(1)
        install(preset_lock.uri)
    elif should_update:
        update(preset_lock.name)

    _copy_updated_assets(
        preset_lock.preset_name,
        preset_lock,
        is_contest=_is_contest(),
    )
    generate_lock(preset_lock.preset_name)


def copy_tree_normalizing_gitdir(src_path: pathlib.Path, dst_path: pathlib.Path):
    shutil.copytree(str(src_path), str(dst_path))
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


@app.command(
    'install', help='Install preset from current directory or from the given URI.'
)
def install(
    uri: Optional[str] = typer.Argument(
        None,
        help='URI for the preset to install. Might be a Github repository, or even a local path.',
    ),
):
    if uri is None:
        _install()
        return

    fetch_info = get_preset_fetch_info(uri)
    if fetch_info is None:
        console.console.print(f'[error] Preset with URI {uri} not found.[/error]')
        raise typer.Exit(1)
    if not fetch_info.is_local_dir() and not fetch_info.is_remote():
        console.console.print(f'[error]URI {uri} is invalid.[/error]')
        raise typer.Exit(1)
    if fetch_info.is_remote():
        install_from_remote(fetch_info)
    else:
        install_from_local_dir(fetch_info)


@app.command('update', help='Update installed remote presets')
def update(
    name: Annotated[
        Optional[str], typer.Argument(help='If set, update only this preset.')
    ] = None,
):
    if not name:
        presets = _find_installed_presets()
    else:
        presets = [name]

    for preset_name in presets:
        if preset_name == LOCAL:
            import questionary

            if not questionary.confirm(
                'Updating local preset will remove all custom changes you made to the preset.',
                default=False,
            ).ask():
                continue

        preset = get_installed_preset_or_null(preset_name)
        if preset is None:
            console.console.print(
                f'[error]Preset [item]{preset_name}[/item] is not installed.'
            )
            continue
        if preset.uri is None:
            console.console.print(
                f'Skipping preset [item]{preset_name}[/item], not remote.'
            )
            continue
        install_from_remote(preset.fetch_info, force=True)

        if preset_name == LOCAL:
            # Get global path to the preset.
            preset_path = get_preset_installation_path(preset.name)
            dest_path = '.local.rbx'
            shutil.rmtree(dest_path, ignore_errors=True)
            shutil.copytree(preset_path, dest_path)
            console.console.print(
                '[success]Local preset updated successfully.[/success]'
            )
        else:
            console.console.print(
                f'[success]Preset [item]{preset_name}[/item] updated successfully.[/success]'
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
def lock(
    preset: Annotated[
        Optional[str],
        typer.Argument(
            help='Preset to generate a lock for. If unset, will default to the one in the existing .preset-lock.yml.',
        ),
    ] = None,
):
    _check_is_valid_package()
    generate_lock(preset)


@app.callback()
def callback():
    pass
