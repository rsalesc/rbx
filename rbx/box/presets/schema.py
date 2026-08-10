import pathlib
from typing import Annotated, Callable, Hashable, List, Optional, TypeVar

import typer
from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator

from rbx import console, utils
from rbx.autoenum import AutoEnum, alias
from rbx.box.presets.fetch import PresetFetchInfo, get_preset_fetch_info


def NameField(**kwargs):
    return Field(
        pattern=r'^[a-zA-Z0-9][a-zA-Z0-9\-]*$', min_length=3, max_length=32, **kwargs
    )


def _reject_escaping_path(value: pathlib.Path) -> pathlib.Path:
    """Reject a declared path that does not stay inside the directory it is
    declared relative to.

    Every path a preset declares is interpreted relative to the preset directory
    (or, for a tracked asset, to a template directory inside it). An absolute
    path would silently discard that root when joined, and a `..` component would
    walk out of it -- reaching files rbx never intended the preset to touch, and
    in the case of a library `dest`, writing them into the user's package. This is
    a purely lexical check, so it fires at parse time with the offending field's
    location; `resolve_template` additionally checks real containment, which is
    the only way to catch a symlinked template directory.
    """
    if value.is_absolute() or value.drive or value.root:
        raise ValueError(
            f"'{value}' must be a path relative to the preset directory, "
            'but it is absolute'
        )
    if '..' in value.parts:
        raise ValueError(
            f"'{value}' must stay inside the preset directory, but it has a "
            "'..' component that walks out of it"
        )
    return value


# A path declared by a preset: always relative to the preset directory, and never
# allowed to escape it.
RelativePath = Annotated[pathlib.Path, AfterValidator(_reject_escaping_path)]


class TrackedAsset(BaseModel):
    # Path of the asset relative to the root of the problem/contest that should
    # be tracked. Can also be a glob, when specified in the preset config.
    path: RelativePath

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
    # May be nested (e.g. `include/testlib.h`), but must stay inside the package.
    dest: RelativePath

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


class PackageVariant(BaseModel):
    # Identifier of the variant. Used in `--variant` and recorded in the
    # package's `.preset-lock.yml`.
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]*$', min_length=1, max_length=32)

    # Path of the variant's template directory, relative to the preset directory.
    path: RelativePath

    # Human-readable description, shown in the variant picker.
    description: str = Field(default='')

    # Assets tracked for this variant, merged over the shared tracking list
    # for this package kind (variant entries win, per path).
    tracking: List[TrackedAsset] = []

    # Libraries for this variant, merged over the shared library list for this
    # package kind (variant entries win, per library name).
    libraries: List[Library] = []

    # Variable expansions for this variant, merged over the shared expansion
    # list for this package kind (variant entries win, per needle).
    expansion: List[VariableExpansion] = []

    @field_validator('id')
    @classmethod
    def validate_id_not_reserved(cls, value: str) -> str:
        if value == 'default':
            raise ValueError(
                "'default' is a reserved variant id: it refers to the preset's "
                'canonical template'
            )
        return value


T = TypeVar('T')


def _merge_by(
    overrides: List[T], base: List[T], key: Callable[[T], Hashable]
) -> List[T]:
    """Merge `overrides` over `base`, keyed by `key`. Overrides win; base order
    is preserved and override-only entries are appended. If `base` itself
    repeats a key, only its first entry is overridden and the later ones are
    kept as-is."""
    override_by_key = {key(item): item for item in overrides}
    res = [override_by_key.pop(key(item), item) for item in base]
    res.extend(override_by_key.values())
    return res


class Preset(BaseModel):
    # Name of the preset, or a GitHub repository containing it.
    name: str = NameField()

    # Human-readable description of the preset, shown in the preset registry
    # picker. This is the canonical home of the description; the registry keeps
    # a denormalized copy for display.
    description: str = Field(default='')

    # URI of the preset to be fetched. Uniquely identifies the preset.
    # Should usually be a GitHub repository.
    uri: str

    # Minimum version of rbx.cp required to use this preset.
    min_version: str = '1.0.0'

    # Path to the environment file that will be installed with this preset.
    # When copied to the box environment, the environment will be named `name`.
    env: Optional[RelativePath] = None

    # Path to the contest preset directory, relative to the preset directory.
    problem: Optional[RelativePath] = None

    # Path to the problem preset directory, relative to the preset directory.
    contest: Optional[RelativePath] = None

    # Configures how preset assets should be tracked and updated when the
    # preset has an update. Usually useful when a common library used by the
    # package changes in the preset, or when a latex template is changed.
    tracking: Tracking = Field(default_factory=Tracking)

    # Configures how variables should be expanded in the preset.
    expansion: Expansion = Field(default_factory=Expansion)

    # Configures third-party libraries (testlib, jngen, etc.) that should be
    # fetched, cached, and materialized into the package.
    libraries: Libraries = Field(default_factory=Libraries)

    # Additional problem templates ("variants") offered by this preset, beyond
    # the canonical `problem` template. Selected with `rbx create --variant`.
    problemVariants: List[PackageVariant] = Field(default_factory=list)

    # Additional contest templates, selected with `rbx contest create --variant`.
    contestVariants: List[PackageVariant] = Field(default_factory=list)

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

    @model_validator(mode='after')
    def validate_unique_variant_ids(self) -> 'Preset':
        for kind, variants in (
            ('problemVariants', self.problemVariants),
            ('contestVariants', self.contestVariants),
        ):
            seen = set()
            for variant in variants:
                if variant.id in seen:
                    raise ValueError(f'duplicate variant id {variant.id} in {kind}')
                seen.add(variant.id)
        return self

    def variants(self, is_contest: bool) -> List[PackageVariant]:
        """Variants declared for the given package kind."""
        return self.contestVariants if is_contest else self.problemVariants

    def find_variant(
        self, variant_id: str, is_contest: bool
    ) -> Optional[PackageVariant]:
        """Variant with the given id for this package kind, or None if unknown."""
        for variant in self.variants(is_contest):
            if variant.id == variant_id:
                return variant
        return None

    def merged_tracking(
        self, variant: Optional[PackageVariant], is_contest: bool
    ) -> List[TrackedAsset]:
        """Shared tracking for this package kind, with `variant`'s entries merged
        over it. Pass None for the canonical template."""
        shared = self.tracking.contest if is_contest else self.tracking.problem
        return _merge_by(
            variant.tracking if variant is not None else [], shared, lambda a: a.path
        )

    def merged_libraries(
        self, variant: Optional[PackageVariant], is_contest: bool
    ) -> List[Library]:
        """Shared libraries for this package kind, with `variant`'s entries merged
        over it. Pass None for the canonical template."""
        shared = self.libraries.contest if is_contest else self.libraries.problem
        return _merge_by(
            variant.libraries if variant is not None else [],
            shared,
            lambda lib: lib.name,
        )

    def merged_expansion(
        self, variant: Optional[PackageVariant], is_contest: bool
    ) -> List[VariableExpansion]:
        """Shared expansions for this package kind, with `variant`'s entries merged
        over it. Pass None for the canonical template."""
        shared = self.expansion.contest if is_contest else self.expansion.problem
        return _merge_by(
            variant.expansion if variant is not None else [], shared, lambda e: e.needle
        )

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
