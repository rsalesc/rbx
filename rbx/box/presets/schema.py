import pathlib
from typing import List, Optional

import semver
import typer
from pydantic import BaseModel, Field, field_validator

from rbx import console
from rbx.box.presets.fetch import PresetFetchInfo, get_preset_fetch_info


def NameField(**kwargs):
    return Field(
        pattern=r'^[a-zA-Z0-9][a-zA-Z0-9\-]*$', min_length=3, max_length=32, **kwargs
    )


class TrackedAsset(BaseModel):
    # Path of the asset relative to the root of the problem/contest that should
    # be tracked. Can also be a glob, when specified in the preset config.
    path: pathlib.Path

    # Whether the asset should be symlinked to the local preset directory,
    # instead of being copied.
    symlink: bool = False


class Tracking(BaseModel):
    # Problem assets that should be tracked and updated by rbx
    # when the preset has an update.
    problem: List[TrackedAsset] = []

    # Contest assets that should be tracked and updated by rbx
    # when the preset has an update.
    contest: List[TrackedAsset] = []


class Preset(BaseModel):
    # Name of the preset, or a GitHub repository containing it.
    name: str = NameField()

    # URI of the preset to be fetched. Uniquely identifies the preset.
    # Should usually be a GitHub repository.
    uri: str

    # Minimum version of rbx.cp required to use this preset.
    min_version: str = '0.14.0'

    # Path to the environment file that will be installed with this preset.
    # When copied to the box environment, the environment will be named `name`.
    env: Optional[pathlib.Path] = None

    # Path to the contest preset directory, relative to the preset directory.
    problem: Optional[pathlib.Path] = None

    # Path to the problem preset directory, relative to the preset directory.
    contest: Optional[pathlib.Path] = None

    # Configures how preset assets should be tracked and updated when the
    # preset has an update. Usually useful when a common library used by the
    # package changes in the preset, or when a latex template is changed.
    tracking: Tracking = Field(default_factory=Tracking)

    @field_validator('min_version')
    @classmethod
    def validate_min_version(cls, value: str) -> str:
        try:
            semver.Version.parse(value)
        except ValueError as err:
            raise ValueError(
                "min_version must be a valid SemVer string (e.g., '1.2.3' or '1.2.3-rc.1')"
            ) from err
        return value

    @property
    def fetch_info(self) -> PresetFetchInfo:
        res = get_preset_fetch_info(self.uri)
        if res is None:
            console.console.print(
                f'[error]Preset URI [item]{self.uri}[/item] is not valid.[/error]'
            )
            console.console.print(
                '[error]Please check that the URI is correct and that the directory/asset really exists.[/error]'
            )
            raise typer.Exit(1)
        return res
