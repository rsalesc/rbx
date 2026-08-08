import dataclasses
import fnmatch
import functools
import os
import pathlib
import shutil
import sys
import tempfile
from typing import (
    TYPE_CHECKING,
    Annotated,
    Iterable,
    List,
    NoReturn,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

import pydantic
import questionary
import ruyaml
import typer
import yaml

from rbx import console, utils
from rbx.box import cd, git_utils
from rbx.box.git_utils import latest_remote_tag
from rbx.box.presets import registry as preset_registry
from rbx.box.presets.fetch import (
    PresetFetchInfo,
    get_preset_fetch_info,
    get_remote_uri_from_tool_preset,
)
from rbx.box.presets.lock_schema import LockedAsset, PresetLock, SymlinkInfo
from rbx.box.presets.schema import (
    Library,
    PackageVariant,
    Preset,
    ReplacementMode,
    TrackedAsset,
    VariableExpansion,
)
from rbx.box.yaml_validation import load_yaml_model
from rbx.config import CACHE_DIR_NAME, LEGACY_CACHE_DIR_NAME, get_default_app_path
from rbx.grading.judge.digester import digest_cooperatively

if TYPE_CHECKING:
    from rbx.box.presets.registry_schema import RegistryPreset

app = typer.Typer(no_args_is_help=True)

_MAX_EXPAND_SIZE = 1024 * 1024  # 1024 KB

LOCK_FILE_NAME = '.preset-lock.yml'

# Cache/build artefacts ignored when globbing a package's source files. The
# legacy cache dir is kept so stale caches don't leak into globbed output.
_DEFAULT_GLOB_GITIGNORE = (
    f'{CACHE_DIR_NAME}\n{LEGACY_CACHE_DIR_NAME}\nbuild\n.limits/local.yml\n'
)


@dataclasses.dataclass(frozen=True)
class ResolvedTemplate:
    """A preset template directory plus the config that applies to it.

    `variant_id` is None for the preset's canonical template, and the variant's
    id otherwise. `inner` is the template path as declared in `preset.rbx.yml`
    (relative to the preset root); `path` is where it actually lives on disk.

    Built by `resolve_template`, which is the only place that maps a variant id
    to a template directory.
    """

    preset: Preset
    preset_path: pathlib.Path
    inner: pathlib.Path
    variant_id: Optional[str]
    tracking: List[TrackedAsset]
    libraries: List[Library]
    expansion: List[VariableExpansion]

    @property
    def path(self) -> pathlib.Path:
        return self.preset_path / self.inner


def _expand_content(
    content: bytes,
    expansions: List[Tuple[str, str, List[str]]],
    src_relative: pathlib.PurePosixPath,
) -> bytes:
    """Apply variable expansions to file content."""
    for needle, value, globs in expansions:
        if globs and not any(fnmatch.fnmatch(str(src_relative), g) for g in globs):
            continue
        content = content.replace(needle.encode(), value.encode())
    return content


def _collect_expansions(
    expansions: List[VariableExpansion],
) -> List[Tuple[str, str, List[str]]]:
    """Prompt the user for expansion values and return (needle, value, globs) tuples."""
    result: List[Tuple[str, str, List[str]]] = []
    for exp in expansions:
        if exp.replacement == ReplacementMode.PROMPT:
            assert exp.prompt is not None
            value = questionary.text(exp.prompt).ask()
            if value is None:
                raise typer.Exit(1)
            result.append((exp.needle, value, exp.glob))
    return result


def _should_expand_file(src: pathlib.Path, content: bytes) -> bool:
    """Check whether a preset file should undergo variable expansion."""
    if src.is_symlink():
        return False
    if len(content) > _MAX_EXPAND_SIZE:
        return False
    if b'\x00' in content:
        return False
    return True


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
        console.console.print(
            '[error]If you want to bypass the preset constraint, you can change the [item]min_version[/item] field in the preset file ([item].local.rbx/preset.rbx.yml)[/item] to the current version.[/error]'
        )
    elif compatibility == utils.SemVerCompatibility.BREAKING_CHANGE:
        console.console.print(
            f'[error]Preset [item]{preset_name}[/item] requires rbx at version [item]{preset_version}[/item], but the current version is [item]{utils.get_version()}[/item].[/error]'
        )
        console.console.print(
            '[error]rbx version is newer, but is in a later major version, which might have introduced breaking changes.[/error]'
        )
        console.console.print(
            '[error]If you are sure that the preset is compatible with the current rbx version, you can change the [item]min_version[/item] field in the preset file ([item].local.rbx/preset.rbx.yml)[/item] to the current version.[/error]'
        )
    if compatibility != utils.SemVerCompatibility.COMPATIBLE:
        raise typer.Exit(1)


def get_preset_yaml(root: pathlib.Path = pathlib.Path()) -> Preset:
    found = find_preset_yaml(root)
    if not found:
        console.console.print(
            f'[error][item]preset.rbx.yml[/item] not found in [item]{root.absolute()}[/item][/error]'
        )
        raise typer.Exit(1)
    preset = load_yaml_model(found, Preset)
    _check_preset_compatibility(preset.name, preset.min_version)
    return preset


# Return name and version.
def get_preset_yaml_metadata(root: pathlib.Path = pathlib.Path()) -> Tuple[str, str]:
    found = find_preset_yaml(root)
    if not found:
        console.console.print(
            f'[error][item]preset.rbx.yml[/item] not found in [item]{root.absolute()}[/item][/error]'
        )
        raise typer.Exit(1)
    loaded_yaml = yaml.safe_load(found.read_text())
    if 'name' not in loaded_yaml:
        console.console.print(
            f'[error][item]preset.rbx.yml[/item] does not have a [item]name[/item] field in [item]{root.absolute()}[/item][/error]'
        )
        raise typer.Exit(1)
    if 'min_version' not in loaded_yaml:
        console.console.print(
            f'[error][item]preset.rbx.yml[/item] does not have a [item]min_version[/item] field in [item]{root.absolute()}[/item][/error]'
        )
        raise typer.Exit(1)
    return loaded_yaml['name'], loaded_yaml['min_version']


def _find_preset_lock(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    root = utils.abspath(root)
    problem_yaml_path = root / LOCK_FILE_NAME
    if not problem_yaml_path.is_file():
        return None
    return problem_yaml_path


def get_preset_lock(root: pathlib.Path = pathlib.Path()) -> Optional[PresetLock]:
    found = _find_preset_lock(root)
    if not found:
        return None
    return load_yaml_model(found, PresetLock)


def _read_locked_variant(root: pathlib.Path = pathlib.Path()) -> Optional[str]:
    """The `variant` recorded in the lock, read without validating the rest.

    `rbx presets lock` is the command you reach for when `.preset-lock.yml` is
    broken, so it must not choke on a malformed one: anything unreadable here
    degrades to None (the canonical template) with a warning.
    """
    found = _find_preset_lock(root)
    if found is None:
        return None
    try:
        data = yaml.safe_load(found.read_text())
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        data = None

    variant = data.get('variant') if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(variant, (str, type(None))):
        console.console.print(
            f'[warning]Could not read the [item]variant[/item] field of '
            f'[item]{LOCK_FILE_NAME}[/item]; assuming this package came from the '
            "preset's canonical template.[/warning]"
        )
        return None
    return variant


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
    extra_gitignore: Optional[str] = _DEFAULT_GLOB_GITIGNORE,
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


def _get_template_tracked_assets(
    template: ResolvedTemplate, *, add_symlinks: bool = False
) -> List[TrackedAsset]:
    preset_pkg_path = template.path
    res = process_globbing(template.tracking, preset_pkg_path)

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
    expansions: Optional[List[Tuple[str, str, List[str]]]] = None,
):
    if dst.is_file() or dst.is_symlink():
        dst.unlink(missing_ok=True)
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_symlink() and not force_symlink:
        content = src.read_bytes()
        if expansions and _should_expand_file(src, content):
            relative = pathlib.PurePosixPath(src.relative_to(preset_package_path))
            content = _expand_content(content, expansions, relative)
        dst.write_bytes(content)
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
    template: ResolvedTemplate,
    root: pathlib.Path = pathlib.Path(),
    *,
    force: bool = False,
    symlinks: bool = False,
):
    # Build preset package snapshot.
    preset = template.preset
    preset_path = template.preset_path
    preset_package_path = template.path

    preset_tracked_assets = _get_template_tracked_assets(
        template, add_symlinks=symlinks
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


def get_active_preset_path_or_null(
    root: pathlib.Path = pathlib.Path(),
) -> Optional[pathlib.Path]:
    return find_local_preset(root)


def get_active_preset_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    preset_path = get_active_preset_path_or_null(root)
    if preset_path is None:
        console.console.print('[error]No preset is active.[/error]')
        raise typer.Exit(1)
    return preset_path


def check_active_preset_compatibility():
    preset_path = get_active_preset_path_or_null()
    if preset_path is None:
        return
    name, min_version = get_preset_yaml_metadata(preset_path)
    _check_preset_compatibility(name, min_version)


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


def _canonical_template(preset: Preset, is_contest: bool) -> Optional[pathlib.Path]:
    return preset.contest if is_contest else preset.problem


def _print_available_templates(
    preset: Preset, *, is_contest: bool, requested_by: Optional[str] = None
) -> None:
    kind = 'contest' if is_contest else 'problem'
    # `-v` only exists on the commands that create a package. When the template
    # was requested by a file, that flag is not the user's lever, so don't
    # advertise it.
    how = '' if requested_by is not None else ' (select with [item]-v <id>[/item])'
    console.console.print(f'Available {kind} templates{how}:')
    if _canonical_template(preset, is_contest) is not None:
        console.console.print("  [item]default[/item] — the preset's main template")
    for variant in preset.variants(is_contest):
        suffix = f' — {variant.description}' if variant.description else ''
        console.console.print(f'  [item]{variant.id}[/item]{suffix}')


def _print_requested_by_remediation(requested_by: str) -> None:
    """Explain that the missing template was asked for by a file, not by a flag,
    and how to get out of it."""
    console.console.print(
        f'[error]This template was requested by [item]{requested_by}[/item], and rbx '
        'will not silently fall back to another one -- doing so could overwrite this '
        "package's assets.[/error]"
    )
    console.console.print(
        'Either restore the template in the installed preset copy at '
        '[item].local.rbx/preset.rbx.yml[/item] (re-fetching the preset with '
        '[item]rbx presets sync -u[/item] overwrites that copy from the remote), '
        f'or set the [item]variant[/item] field of [item]{requested_by}[/item] to a '
        "template that does exist ([item]default[/item] means the preset's canonical "
        'template).'
    )


def _fail_no_template(
    preset: Preset,
    *,
    is_contest: bool,
    message: str,
    requested_by: Optional[str] = None,
) -> NoReturn:
    """Report that a requested template could not be resolved, and exit.

    When the preset declares no templates of this kind at all, `message` is
    dropped in favor of saying just that -- listing an empty set of alternatives
    would only muddy the error.
    """
    kind = 'contest' if is_contest else 'problem'
    if _canonical_template(preset, is_contest) is None and not preset.variants(
        is_contest
    ):
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] declares no {kind} templates at all.[/error]'
        )
    else:
        console.console.print(message)
        _print_available_templates(
            preset, is_contest=is_contest, requested_by=requested_by
        )
    if requested_by is not None:
        _print_requested_by_remediation(requested_by)
    raise typer.Exit(1)


def _print_missing_template_dir(
    preset: Preset,
    *,
    kind: str,
    inner: pathlib.Path,
    path: pathlib.Path,
    severity: str,
    consequence: str = '',
) -> None:
    """Report a template whose declared directory does not exist.

    Shared by the fatal path (`resolve_template`, severity 'error') and the
    sweep (`all_templates`, severity 'warning'), so both name the declaration
    and the location it resolved to identically.
    """
    console.console.print(
        f'[{severity}]Preset [item]{preset.name}[/item] declares a {kind} template at '
        f'[item]{inner}[/item], but that directory does not exist '
        f'([item]{path}[/item]).{consequence}[/{severity}]'
    )


def resolve_template(
    preset: Preset,
    preset_path: pathlib.Path,
    *,
    is_contest: bool,
    variant: Optional[str],
    requested_by: Optional[str] = None,
) -> ResolvedTemplate:
    """Resolve a variant id into the template directory it names.

    This is the only place that maps an id to a template directory, and the only
    place that errors on an unknown or removed one. `variant` is None (or the
    reserved id 'default') for the preset's canonical template.

    `requested_by` names the file that asked for this template (e.g.
    `.preset-lock.yml`) when it was not a command-line flag. It only shapes the
    error messages -- provenance lives here, next to the code that knows which
    template is missing, so every failure branch reports it consistently.
    """
    kind = 'contest' if is_contest else 'problem'
    if variant == 'default':
        variant = None

    found: Optional[PackageVariant] = None
    if variant is None:
        canonical = _canonical_template(preset, is_contest)
        if canonical is None:
            _fail_no_template(
                preset,
                is_contest=is_contest,
                message=(
                    f'[error]Preset [item]{preset.name}[/item] does not have a '
                    f'canonical {kind} template.[/error]'
                ),
                requested_by=requested_by,
            )
        inner = canonical
    else:
        found = preset.find_variant(variant, is_contest)
        if found is None:
            _fail_no_template(
                preset,
                is_contest=is_contest,
                message=(
                    f'[error]Preset [item]{preset.name}[/item] has no {kind} variant '
                    f'[item]{variant}[/item].[/error]'
                ),
                requested_by=requested_by,
            )
        inner = found.path

    path = preset_path / inner
    if not path.is_dir():
        _print_missing_template_dir(
            preset, kind=kind, inner=inner, path=path, severity='error'
        )
        if requested_by is not None:
            _print_requested_by_remediation(requested_by)
        raise typer.Exit(1)

    return ResolvedTemplate(
        preset=preset,
        preset_path=preset_path,
        inner=inner,
        variant_id=variant,
        tracking=preset.merged_tracking(found, is_contest),
        libraries=preset.merged_libraries(found, is_contest),
        expansion=preset.merged_expansion(found, is_contest),
    )


def get_active_template(
    root: pathlib.Path = pathlib.Path(),
    *,
    is_contest: bool = False,
    variant: Optional[str] = None,
    requested_by: Optional[str] = None,
) -> ResolvedTemplate:
    """Resolve a template of the preset that is active for the package at `root`."""
    return resolve_template(
        get_active_preset(root),
        get_active_preset_path(root),
        is_contest=is_contest,
        variant=variant,
        requested_by=requested_by,
    )


def declared_templates(
    preset: Preset,
    *,
    is_contest: bool,
) -> List[Tuple[Optional[PackageVariant], pathlib.Path]]:
    """Every template of this kind as *declared*, without touching the disk.

    Yields `(variant, inner)` pairs -- `variant` is None for the canonical
    template and the `PackageVariant` itself otherwise, `inner` is the declared
    path relative to the preset root. Ordering is stable: canonical first (a
    variants-only preset simply has none), then variants in declaration order.

    The `PackageVariant` is carried rather than just its id because the variant
    picker and `rbx presets ls` need its `description`. They also need the
    declarations whose directories are missing, which `all_templates` drops --
    which is why this is the shared layer rather than the other way around.
    """
    declared: List[Tuple[Optional[PackageVariant], pathlib.Path]] = []
    canonical = _canonical_template(preset, is_contest)
    if canonical is not None:
        declared.append((None, canonical))
    for variant in preset.variants(is_contest):
        declared.append((variant, variant.path))
    return declared


def pick_variant(
    preset: Preset, *, is_contest: bool, variant: Optional[str]
) -> Optional[str]:
    """Resolve the variant to use, prompting when the preset offers a choice.

    Returns None for the canonical template. Never prompts when the preset
    declares no variants, or when stdin is not a TTY.
    """
    if variant is not None:
        # An explicit flag always wins: never second-guess it with a prompt,
        # and let `resolve_template` be the one to reject a bad id.
        return variant

    declared = declared_templates(preset, is_contest=is_contest)
    has_canonical = any(v is None for v, _ in declared)
    variants = [v for v, _ in declared if v is not None]
    if not variants:
        # The overwhelmingly common case: a preset with a single template. Stay
        # exactly as silent as rbx was before variants existed.
        return None

    kind = 'contest' if is_contest else 'problem'
    if not sys.stdin.isatty():
        if not has_canonical:
            console.console.print(
                f'[error]Preset [item]{preset.name}[/item] does not have a canonical '
                f'{kind} template, so one of its variants must be chosen '
                'explicitly.[/error]'
            )
            console.console.print(
                '[error]Re-run with [item]-v <id>[/item] -- there is no terminal to '
                'prompt on.[/error]'
            )
            _print_available_templates(preset, is_contest=is_contest)
            raise typer.Exit(1)
        return None

    choices = []
    if has_canonical:
        choices.append(
            questionary.Choice(
                title="default — the preset's main template", value='default'
            )
        )
    for v in variants:
        choices.append(
            questionary.Choice(
                title=f'{v.id} — {v.description}' if v.description else v.id,
                value=v.id,
            )
        )

    answer = questionary.select(
        f'Which {kind} template do you want to use?',
        choices=choices,
        default=choices[0].value,
    ).ask()
    if answer is None:
        raise typer.Exit(1)
    return None if answer == 'default' else answer


def all_templates(
    preset: Preset,
    preset_path: pathlib.Path,
    *,
    is_contest: bool,
) -> List[ResolvedTemplate]:
    """Every template of this kind that actually resolves: the canonical one
    (when declared) plus each variant, in `declared_templates` order.

    A template that fails to resolve -- today, one whose declared directory does
    not exist -- is reported and skipped, rather than raising like
    `resolve_template` does. Callers of this function sweep over every template
    (linting them, cleaning build artifacts out of them) instead of acting on the
    one template the user asked for, so a bad declaration is a recoverable
    authoring mistake that must not stop the remaining templates from being
    processed. `resolve_template` still exits, since there the bad template *is*
    what was asked for.
    """
    kind = 'contest' if is_contest else 'problem'

    resolved: List[ResolvedTemplate] = []
    for variant, inner in declared_templates(preset, is_contest=is_contest):
        if not (preset_path / inner).is_dir():
            _print_missing_template_dir(
                preset,
                kind=kind,
                inner=inner,
                path=preset_path / inner,
                severity='warning',
                consequence=(
                    ' Skipping it: this template will not be formatted, cleaned '
                    'or otherwise processed. Fix or remove its entry in '
                    '[item]preset.rbx.yml[/item].'
                ),
            )
            continue
        try:
            resolved.append(
                resolve_template(
                    preset,
                    preset_path,
                    is_contest=is_contest,
                    variant=variant.id if variant is not None else None,
                )
            )
        except typer.Exit:
            # The existence check above already covers `resolve_template`'s only
            # current failure mode for a declared template, so this is dead code
            # today. It is here because validations queued for `resolve_template`
            # (e.g. rejecting declared paths that escape the preset root) would
            # otherwise turn a sweep into a hard exit halfway through. Every exit
            # branch there prints its own message first, so skipping stays loud.
            continue
    return resolved


def variant_for_path(
    preset: Preset,
    preset_path: pathlib.Path,
    target: pathlib.Path,
    *,
    is_contest: bool,
) -> Optional[str]:
    """Which template directory contains `target`?

    Returns the owning variant's id, the string 'default' when `target` lives in
    the preset's canonical template, or None when it is inside no template at
    all. The result is directly usable as `resolve_template`'s `variant`. When
    templates nest, the deepest declared one wins.
    """
    # Lexical, like `find_local_preset`: a template dir reached through a
    # symlink will not match.
    target = utils.abspath(target)
    candidates: List[Tuple[pathlib.Path, str]] = [
        (variant.path, variant.id) for variant in preset.variants(is_contest)
    ]
    canonical = _canonical_template(preset, is_contest)
    if canonical is not None:
        candidates.append((canonical, 'default'))

    best: Optional[Tuple[int, str]] = None
    for inner, variant_id in candidates:
        candidate = utils.abspath(preset_path / inner)
        if target.is_relative_to(candidate):
            depth = len(candidate.parts)
            if best is None or depth > best[0]:
                best = (depth, variant_id)
    return best[1] if best is not None else None


def get_preset_fetch_info_with_fallback(
    uri: Optional[str],
    local: bool = False,
) -> Optional[PresetFetchInfo]:
    if uri is not None:
        return get_preset_fetch_info(uri, local=local)

    # No explicit preset: prefer the active preset in the cwd.
    if get_active_preset_or_null() is not None:
        return None

    # No active preset: choose from the registry.
    if not utils.is_interactive_tty():
        console.console.print(
            '[error]No preset selected and no active preset found.[/error]'
        )
        console.console.print(
            'Pass [item]--preset <name-or-uri>[/item] (e.g. [item]--preset default[/item]) '
            'or run interactively to pick from the registry.'
        )
        raise typer.Exit(1)

    chosen = preset_registry.pick_preset()
    return get_preset_fetch_info(chosen.uri, local=local)


def clean_copied_package_dir(dest: pathlib.Path):
    # Strip the current cache dir as well as the legacy one, so a stale cache
    # left over from before #306 never leaks into a generated preset/package.
    for cache_name in (CACHE_DIR_NAME, LEGACY_CACHE_DIR_NAME):
        for cache_dir in dest.rglob(cache_name):
            shutil.rmtree(str(cache_dir), ignore_errors=True)
    for lock in dest.rglob('.preset-lock.yml'):
        lock.unlink(missing_ok=True)


def get_preset_build_dir(env_path: Optional[pathlib.Path]) -> pathlib.Path:
    """Resolve the buildDir configured by a preset's env.rbx.yml.

    Used when stripping build artifacts from a copied preset/package so a
    custom buildDir is removed and never leaks into the generated tree. Only the
    buildDir field is read, so a stub or partially-specified env still resolves;
    a missing/unset value falls back to the env schema's default buildDir.
    """
    # Lazy import: rbx.box.environment imports this module.
    from rbx.box.environment import Environment

    default = Environment.model_fields['buildDir'].default
    if env_path is None or not env_path.is_file():
        return default
    data = yaml.safe_load(env_path.read_text())
    build_dir = data.get('buildDir') if isinstance(data, dict) else None
    return pathlib.Path(build_dir) if build_dir else default


def clean_copied_contest_dir(
    dest: pathlib.Path,
    delete_local_rbx: bool = True,
    build_dir: pathlib.Path = pathlib.Path('build'),
):
    shutil.rmtree(str(dest / build_dir), ignore_errors=True)
    if delete_local_rbx:
        shutil.rmtree(str(dest / '.local.rbx'), ignore_errors=True)
    clean_copied_package_dir(dest)


def clean_copied_problem_dir(
    dest: pathlib.Path, build_dir: pathlib.Path = pathlib.Path('build')
):
    shutil.rmtree(str(dest / build_dir), ignore_errors=True)
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

    # A preset only needs *some* template of the requested kind -- a
    # variants-only preset (no canonical `problem:`/`contest:`, only
    # `problemVariants`/`contestVariants`) is legal, and `-v <id>` picks from it
    # just fine. Only a preset that declares nothing at all is unusable here.
    if ensure_contest and not declared_templates(preset, is_contest=True):
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] does not declare any contest template.[/error]'
        )
        raise typer.Exit(1)
    if ensure_problem and not declared_templates(preset, is_contest=False):
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] does not declare any problem template.[/error]'
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
    # to avoid conflicts. Resolve the build dir from the preset's own env so a
    # custom buildDir is stripped instead of the default 'build'.
    build_dir = get_preset_build_dir(
        dest / preset.env if preset.env is not None else None
    )
    shutil.rmtree(str(dest / build_dir), ignore_errors=True)
    shutil.rmtree(str(dest / '.local.rbx'), ignore_errors=True)

    # Every declared template, not just the canonical one: build artifacts left
    # in a variant's directory would otherwise leak into the installed preset.
    for template in all_templates(preset, dest, is_contest=True):
        clean_copied_contest_dir(template.path, build_dir=build_dir)
    for template in all_templates(preset, dest, is_contest=False):
        clean_copied_problem_dir(template.path, build_dir=build_dir)

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
            if (
                utils.is_valid_semver(fetch_info.tool_tag)
                and utils.get_semver(fetch_info.tool_tag).is_prerelease
            ):
                console.console.print(
                    f'[warning]Tool tag [item]{fetch_info.tool_tag}[/item] is a prerelease tag. This may not be what you want.[/warning]'
                )
                console.console.print(
                    f'[warning]You are in [item]rbx.cp[/item] prerelease version {utils.get_semver()}, which means projects '
                    'will be created from prerelease presets. Consider installing a stable release for better compatibility with other users.[/warning]'
                )
                if not questionary.confirm(
                    'If you want to proceed anyway, press [y]', default=False
                ).ask():
                    raise typer.Exit(1)
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
    if not questionary.confirm(
        'Do you really want to install this preset from its local copy? This is usually unsafe for mature projects, and means that youre not online.'
    ).ask():
        raise typer.Exit(1)
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
    try:
        latest_tag = latest_remote_tag(remote_fetch_info.fetch_uri)
        latest_version = utils.get_semver(latest_tag)
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
    except ValueError as e:
        console.console.print(f'[error]{e}[/error]')
        pass

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


def _install_package_from_preset(
    template: ResolvedTemplate,
    dest_pkg: pathlib.Path,
    expansions: Optional[List[Tuple[str, str, List[str]]]] = None,
):
    # `resolve_template` already guaranteed the template directory exists.
    preset_path = template.preset_path
    preset_package_path = template.path

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
            expansions=expansions,
        )

    for asset in template.tracking:
        if not asset.symlink:
            continue
        copy_preset_file(
            preset_package_path / asset.path,
            dest_pkg / asset.path,
            preset_package_path,
            preset_path,
            force_symlink=True,
        )


def materialize_libraries(libraries: List[Library], pkg_root: pathlib.Path):
    # Libraries are tool-managed: every create/sync re-fetches per the version
    # spec and overwrites the materialized file. Reproducibility comes from the
    # committed files (the pin), not from a lock — so local hand-edits to a
    # materialized library are intentionally NOT preserved. Vendor a custom copy
    # under a different path/source if you need to diverge.
    from rbx.box.presets import library_fetch

    for library in libraries:
        cached = library_fetch.fetch_library(library)
        library_fetch.materialize_library(library, cached, pkg_root)
        console.console.print(
            f'Materialized library [item]{library.name}[/item] at '
            f'[item]{library.dest}[/item].'
        )


def install_contest(
    dest_pkg: pathlib.Path,
    fetch_info: Optional[PresetFetchInfo] = None,
    materialize: bool = True,
    variant: Optional[str] = None,
) -> ResolvedTemplate:
    """Install a contest package from the preset, returning the template used.

    Callers MUST pass the returned template to `generate_lock`, so the lock can
    never claim a different template than the one that was installed.
    """
    if fetch_info is not None:
        _install_preset_from_fetch_info(
            fetch_info,
            dest_pkg / '.local.rbx',
            ensure_contest=True,
        )
    variant = pick_variant(
        get_active_preset(dest_pkg), is_contest=True, variant=variant
    )
    template = get_active_template(dest_pkg, is_contest=True, variant=variant)

    expansions = _collect_expansions(template.expansion)
    console.console.print(
        f'Installing contest from [item]{template.path}[/item] to [item]{dest_pkg}[/item]...'
    )
    _install_package_from_preset(
        template,
        dest_pkg,
        expansions=expansions,
    )
    clean_copied_contest_dir(
        dest_pkg,
        delete_local_rbx=False,
        build_dir=get_preset_build_dir(get_preset_environment_path(dest_pkg)),
    )
    if materialize:
        materialize_libraries(template.libraries, dest_pkg)
    return template


def install_problem(
    dest_pkg: pathlib.Path,
    fetch_info: Optional[PresetFetchInfo] = None,
    materialize: bool = True,
    variant: Optional[str] = None,
) -> ResolvedTemplate:
    """Install a problem package from the preset, returning the template used.

    Callers MUST pass the returned template to `generate_lock`, so the lock can
    never claim a different template than the one that was installed.
    """
    if fetch_info is not None:
        _install_preset_from_fetch_info(
            fetch_info,
            dest_pkg / '.local.rbx',
            ensure_problem=True,
        )
    variant = pick_variant(
        get_active_preset(dest_pkg), is_contest=False, variant=variant
    )
    template = get_active_template(dest_pkg, is_contest=False, variant=variant)

    expansions = _collect_expansions(template.expansion)
    console.console.print(
        f'Installing problem from [item]{template.path}[/item] to [item]{dest_pkg}[/item]...'
    )
    _install_package_from_preset(
        template,
        dest_pkg,
        expansions=expansions,
    )
    clean_copied_problem_dir(
        dest_pkg,
        build_dir=get_preset_build_dir(get_preset_environment_path(dest_pkg)),
    )
    if materialize:
        materialize_libraries(template.libraries, dest_pkg)
    return template


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


def _read_preset_for_peek(uri: str, local: bool = False) -> Preset:
    """Lightweight read of a preset's metadata for the registry.

    Reads only the preset's ``preset.rbx.yml`` (for its name + description)
    without installing it or running any install-time prompts: a direct read
    for local-path and bundled presets, and a shallow clone for remotes.
    """
    # Local directory passed directly.
    try:
        local_path = pathlib.Path(uri)
        if (local_path / 'preset.rbx.yml').is_file():
            return get_preset_yaml(local_path)
    except OSError:
        pass

    # Bundled preset shipped with rbx (e.g. `default`). Read it directly so a
    # `registry add default` needs no network and no install-time prompts.
    bundled = get_default_app_path() / 'presets' / uri
    if (bundled / 'preset.rbx.yml').is_file():
        return get_preset_yaml(bundled)

    if local:
        console.console.print(
            f'[error]Local preset [item]{uri}[/item] not found in rbx resources.[/error]'
        )
        raise typer.Exit(1)

    # Remote preset: resolve and shallow-clone just to read preset.rbx.yml.
    fetch_info = get_preset_fetch_info(uri, local=local)
    if fetch_info is None or fetch_info.fetch_uri is None:
        console.console.print(
            f'[error]Could not resolve preset URI [item]{uri}[/item].[/error]'
        )
        raise typer.Exit(1)

    import git

    with tempfile.TemporaryDirectory() as tmp:
        console.console.print(
            f'Fetching preset metadata from [item]{fetch_info.fetch_uri}[/item]...'
        )
        try:
            git.Repo.clone_from(fetch_info.fetch_uri, tmp, depth=1)
        except Exception as e:
            console.console.print(
                f'[error]Could not fetch preset from [item]{fetch_info.fetch_uri}[/item].[/error]'
            )
            raise typer.Exit(1) from e
        pd = pathlib.Path(tmp)
        if fetch_info.inner_dir:
            pd = pd / fetch_info.inner_dir
        return get_preset_yaml(pd)


def _peek_preset_metadata(uri: str, local: bool = False) -> 'RegistryPreset':
    from rbx.box.presets.registry_schema import RegistryPreset

    preset = _read_preset_for_peek(uri, local=local)
    return RegistryPreset(name=preset.name, uri=uri, description=preset.description)


def maybe_offer_to_register(
    fetch_info: Optional[PresetFetchInfo], package_dir: pathlib.Path
) -> None:
    """After a user creates a package with an explicit ``--preset`` URI, offer
    to add it to the user registry. Interactive-only, and only when the preset
    is not already known to the registry."""
    from rbx.box.presets.registry_schema import RegistryPreset

    if fetch_info is None or not getattr(fetch_info, 'uri', None):
        return
    if not utils.is_interactive_tty():
        return
    if preset_registry.find_in_registry(fetch_info.uri) is not None:
        return
    if not questionary.confirm(
        f'Register preset "{fetch_info.uri}" so it shows up in the picker next time?',
        default=False,
    ).ask():
        return
    # Read the just-installed preset from its .local.rbx copy instead of
    # re-fetching it from the network.
    preset_path = find_local_preset(package_dir)
    if preset_path is not None:
        preset = get_preset_yaml(preset_path)
        entry = RegistryPreset(
            name=preset.name, uri=fetch_info.uri, description=preset.description
        )
    else:
        entry = _peek_preset_metadata(fetch_info.uri)
    preset_registry.add_to_user_registry(entry)
    console.console.print(
        f'[success]Registered preset [item]{entry.name}[/item].[/success]'
    )


def get_ruyaml(root: pathlib.Path = pathlib.Path()) -> Tuple[ruyaml.YAML, ruyaml.Any]:
    if not (root / 'preset.rbx.yml').is_file():
        console.console.print(
            f'[error]Preset at [item]{root}[/item] does not have a [item]preset.rbx.yml[/item] file.[/error]'
        )
        raise typer.Exit(1)
    res = ruyaml.YAML()
    return res, res.load(root / 'preset.rbx.yml')


def generate_lock(
    root: pathlib.Path = pathlib.Path(),
    template: Optional[ResolvedTemplate] = None,
):
    """Write `.preset-lock.yml` for the package at `root`.

    `template` is the template the package was installed from / synced against.
    Callers that already resolved one MUST pass it, so the lock can never end up
    describing a different template than the one that was just applied; it is
    resolved here only for callers that have none.
    """
    if template is None:
        template = get_active_template(root, is_contest=is_contest(root))

    tracked_assets = _get_template_tracked_assets(template)
    preset_lock = PresetLock(
        name=template.preset.name,
        variant=template.variant_id,
        assets=build_package_locked_assets(tracked_assets, root),
    )

    (root / LOCK_FILE_NAME).write_text(utils.model_to_yaml(preset_lock))
    console.console.print(
        f'[success][item]{LOCK_FILE_NAME}[/item] was created.[/success]'
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

    # Sync against the template the package was actually created from. Falling
    # back to the canonical one would overwrite a variant package's tracked
    # assets with the wrong template's, so a template that no longer exists in
    # the (possibly just-updated) preset is a hard error -- reported by
    # `resolve_template`, which is told the request came from the lock.
    template = get_active_template(
        is_contest=is_contest(),
        variant=preset_lock.variant,
        requested_by=LOCK_FILE_NAME if preset_lock.variant is not None else None,
    )

    _copy_updated_assets(
        preset_lock,
        template,
        force=force,
        symlinks=symlinks,
    )
    materialize_libraries(template.libraries, pathlib.Path())
    generate_lock(template=template)


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
            help='The name of the preset to create. This will also be the name of the folder. '
            'A relative path may be given, in which case the preset name is its basename.',
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
    local: Annotated[
        bool,
        typer.Option(
            '--local',
            help='Whether to fetch the init preset from the local version of rbx, instead of the remote one (not recommended).',
        ),
    ] = False,
):
    dest_path = pathlib.Path(name)

    # The preset name is the basename of the destination folder, even when a
    # relative path is given (e.g. `presets/my-preset` -> `my-preset`).
    preset_name = dest_path.stem
    try:
        utils.validate_field(Preset, 'name', preset_name)
    except pydantic.ValidationError:
        console.console.print(
            f'[error]Invalid preset name [item]{preset_name}[/item], '
            f'derived from [item]{name}[/item].[/error]'
        )
        console.console.print(
            '[error]A preset name must be 3-32 characters long and contain only '
            'letters, digits, dashes and underscores.[/error]'
        )
        raise typer.Exit(1) from None

    console.console.print(f'Creating new preset [item]{preset_name}[/item]...')

    fetch_info = get_preset_fetch_info_with_fallback(from_preset, local=local)
    if dest_path.exists():
        console.console.print(
            f'[error]Directory [item]{dest_path}[/item] already exists.[/error]'
        )
        raise typer.Exit(1)

    install_preset(dest_path, fetch_info)

    ru, preset = get_ruyaml(dest_path)
    preset['name'] = preset_name
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
    contest = is_contest()
    # Re-locking must keep the template the package is already locked to;
    # silently re-pointing a variant package at the canonical template would
    # make the next sync overwrite its assets.
    existing_lock = _find_preset_lock()
    variant = _read_locked_variant() if existing_lock is not None else None
    template = get_active_template(is_contest=contest, variant=variant)

    if existing_lock is None and template.preset.variants(contest):
        # Nothing recorded the template this package came from, so canonical is
        # only a guess -- and a wrong guess makes the next sync overwrite the
        # package's assets. Say so instead of guessing silently.
        console.console.print(
            f'[warning]This package had no [item]{LOCK_FILE_NAME}[/item], so it was '
            "locked to the preset's [item]default[/item] template.[/warning]"
        )
        console.console.print(
            'If it was created from another template, set the [item]variant[/item] '
            f'field in [item]{LOCK_FILE_NAME}[/item] to its id before syncing:'
        )
        _print_available_templates(
            template.preset, is_contest=contest, requested_by=LOCK_FILE_NAME
        )

    generate_lock(template=template)


@app.command('ls', help='List details about the active preset.')
@cd.within_closest_package
def ls():
    preset = get_active_preset()
    preset_path = find_local_preset(pathlib.Path.cwd())
    console.console.print(f'Preset: [item]{preset.name}[/item]')
    console.console.print(f'Path: {preset_path}')
    console.console.print(f'URI: {preset.uri}')


registry_app = typer.Typer(no_args_is_help=True)
app.add_typer(registry_app, name='registry', help='Manage the preset registry.')


@registry_app.command('ls', help='List presets available in the registry.')
def registry_ls():
    merged = preset_registry.get_merged_registry()
    user_names = {p.name for p in preset_registry.get_user_registry().presets}
    if not merged.presets:
        console.console.print('No presets in the registry.')
        return
    from rich.table import Table

    table = Table('Name', 'Description', 'URI', 'Source')
    for p in merged.presets:
        source = 'user' if p.name in user_names else 'built-in'
        table.add_row(p.name, p.description, p.uri, source)
    console.console.print(table)


@registry_app.command('add', help='Add a preset to the user registry.')
def registry_add(
    uri: Annotated[
        str,
        typer.Argument(
            help='URI of the preset to register (owner/repo, URL, or path).'
        ),
    ],
    local: Annotated[
        bool,
        typer.Option('--local', help='Resolve the preset from the local rbx version.'),
    ] = False,
):
    entry = _peek_preset_metadata(uri, local=local)
    preset_registry.add_to_user_registry(entry)
    console.console.print(
        f'[success]Registered preset [item]{entry.name}[/item] '
        f'([item]{entry.uri}[/item]).[/success]'
    )


@registry_app.command('rm', help='Remove a preset from the user registry.')
def registry_rm(
    name: Annotated[str, typer.Argument(help='Name of the preset to remove.')],
):
    if preset_registry.remove_from_user_registry(name):
        console.console.print(
            f'[success]Removed preset [item]{name}[/item] from the registry.[/success]'
        )
        return
    # Not in the user registry: tailor the message for a built-in vs an unknown.
    builtin_names = {p.name for p in preset_registry.get_builtin_registry().presets}
    if name in builtin_names:
        console.console.print(
            f'[error]Preset [item]{name}[/item] is a built-in preset and cannot be removed.[/error]'
        )
    else:
        console.console.print(
            f'[error]Preset [item]{name}[/item] is not in the user registry.[/error]'
        )
    raise typer.Exit(1)


@app.callback()
def callback():
    pass
