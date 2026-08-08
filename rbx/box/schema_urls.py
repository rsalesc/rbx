import functools
import pathlib
from typing import Optional, Tuple, Type

import yaml
from pydantic import BaseModel

from rbx import utils

# Base URL of the versioned schema site. Kept in one place so adopting a
# custom domain later is a one-line change (github.io then redirects, so pins
# already written into users' files keep resolving).
VERSIONED_BASE_URL = 'https://rsalesc.github.io/rbx-schemas'

# First minor whose schemas are published. Older floors -- including the
# historical `min_version` default of 0.14.0 -- fall back to the unversioned
# URL, because pointing at a nonexistent file makes editors show a hard
# "unable to load schema" error.
#
# This is deliberately the minor that the bundled preset already declares, so
# pinning goes live with the first release that publishes schemas and needs no
# compatibility-breaking bump to `min_version`. A floor above the installed
# version would be unreachable: a preset whose `min_version` exceeds the
# installed version is rejected outright, so no preset could both install and
# pin.
SCHEMA_PIN_FLOOR: Tuple[int, int] = (1, 0)


@functools.cache
def preset_min_version(root: pathlib.Path) -> Optional[str]:
    """`min_version` of the preset governing `root`, or None.

    Deliberately tolerant: never raises, never prints. Unlike
    `presets.get_preset_yaml`, this does not run compatibility checks -- writing
    a schema comment must never abort a command. Cached because
    `model_to_yaml` is called once per test evaluation.
    """
    from rbx.box.presets import find_local_preset

    try:
        preset_path = find_local_preset(root)
        if preset_path is None:
            return None
        loaded = yaml.safe_load((preset_path / 'preset.rbx.yml').read_text())
        if not isinstance(loaded, dict):
            return None
        version = loaded.get('min_version')
        if not isinstance(version, str) or not utils.is_valid_semver(version):
            return None
        return version
    except Exception:
        return None


def _minor(version: str) -> Tuple[int, int]:
    semver = utils.get_semver(version)
    return (semver.major, semver.minor)


def schema_url(model_cls: Type[BaseModel], root: pathlib.Path = pathlib.Path()) -> str:
    """URL of the schema for `model_cls`, pinned to the compatibility floor of
    the preset governing `root` (or to the installed version if there is
    none)."""
    version = preset_min_version(utils.abspath(root)) or utils.get_version()
    try:
        major, minor = _minor(version)
    except Exception:
        return utils.uploaded_schema_path(model_cls)
    if (major, minor) < SCHEMA_PIN_FLOOR:
        return utils.uploaded_schema_path(model_cls)
    return f'{VERSIONED_BASE_URL}/{major}.{minor}/{model_cls.__name__}.json'
