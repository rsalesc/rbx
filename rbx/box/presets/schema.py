import pathlib
from typing import List, Optional

import typer
from pydantic import BaseModel, Field, field_validator, model_validator

from rbx import console, utils
from rbx.autoenum import AutoEnum, alias
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


class Library(BaseModel):
    # Logical name of the library. Used as the cache key and as the argument to
    # `rbx download <name>`.
    name: str = NameField()

    # Source of the library, using the same URI grammar as preset `uri`
    # (owner/repo, @gh/owner/repo, a full GitHub/git URL, a raw download URL, or
    # a local path). Resolved by `get_library_fetch_info`.
    source: str

    # Path of the file or directory to take from the source repo. Omit for a
    # raw-URL source (the URL already points at the file).
    path: Optional[pathlib.Path] = None

    # Version to fetch: a commit prefix, a tag/release/branch, or 'latest'.
    version: str = 'latest'

    # Where the library is materialized inside the problem/contest package.
    dest: pathlib.Path

    # When true, the materialized file lives in .local.rbx/libs/<name>/ and
    # `dest` is a relative symlink into it; otherwise `dest` is a real copy.
    symlink: bool = False

    # When true, the library is also injected into the reserved __internal__/
    # dir at compile time (exposed via -I__internal__), so any source can
    # include it without it resolving relative to the includer.
    always_include: bool = False

    # How the library is spelled in an #include when always_include is set.
    # Defaults to the basename of `path` (or `dest`). Use for nested names like
    # `bits/stdc++.h`.
    include_as: Optional[pathlib.Path] = None


class Libraries(BaseModel):
    # Problem libraries, materialized into every problem package.
    problem: List[Library] = []

    # Contest libraries, materialized into every contest package.
    contest: List[Library] = []


class ReplacementMode(AutoEnum):
    PROMPT = alias('prompt')  # type: ignore
    """Replace the needle with an user provided string."""


class VariableExpansion(BaseModel):
    # The needle to be replaced.
    needle: str

    # The mode to use for the replacement.
    replacement: ReplacementMode = Field(default=ReplacementMode.PROMPT)

    # The prompt to use for the replacement.
    # Only used when the replacement mode is PROMPT.
    prompt: Optional[str] = Field(default=None)

    # A glob pattern for the files to be expanded. If left empty, expand all files.
    glob: List[str] = Field(default=[])

    @model_validator(mode='after')
    def validate_prompt_required(self) -> 'VariableExpansion':
        if self.replacement == ReplacementMode.PROMPT and self.prompt is None:
            raise ValueError('prompt is required when replacement mode is PROMPT')
        return self


class Expansion(BaseModel):
    # Problem variables that should be expanded.
    problem: List[VariableExpansion] = []

    # Contest variables that should be expanded.
    contest: List[VariableExpansion] = []


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

    # Configures how variables should be expanded in the preset.
    expansion: Expansion = Field(default_factory=Expansion)

    # Configures third-party libraries (testlib, jngen, etc.) that should be
    # fetched, cached, and materialized into the package.
    libraries: Libraries = Field(default_factory=Libraries)

    @field_validator('min_version')
    @classmethod
    def validate_min_version(cls, value: str) -> str:
        try:
            utils.get_semver(value)
        except ValueError as err:
            raise ValueError(
                "min_version must be a valid PEP440 SemVer string (e.g., '1.2.3' or '1.2.3-rc.1')"
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
