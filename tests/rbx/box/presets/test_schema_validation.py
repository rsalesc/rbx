import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.presets.schema import (
    Library,
    PackageVariant,
    Preset,
    ReplacementMode,
    TrackedAsset,
    VariableExpansion,
)
from rbx.box.yaml_validation import load_yaml_model
from rbx.config import get_default_app_path
from rbx.testing_utils import get_testdata_path


class TestVariableExpansionValidation:
    def test_prompt_mode_requires_prompt_field(self):
        with pytest.raises(ValidationError):
            VariableExpansion(
                needle='__NAME__',
                replacement=ReplacementMode.PROMPT,
                prompt=None,
            )

    def test_prompt_mode_accepts_prompt_field(self):
        ve = VariableExpansion(
            needle='__NAME__',
            replacement=ReplacementMode.PROMPT,
            prompt='Enter the problem name:',
        )
        assert ve.prompt == 'Enter the problem name:'

    def test_prompt_mode_is_default(self):
        ve = VariableExpansion(
            needle='__NAME__',
            prompt='Enter name:',
        )
        assert ve.replacement == ReplacementMode.PROMPT


# (builder, field name) for every preset field that declares a path relative to
# the preset directory. Each builder takes the raw value for that one field.
PATH_FIELDS = [
    pytest.param(
        lambda value: Preset(name='my-preset', uri='owner/repo', problem=value),
        id='Preset.problem',
    ),
    pytest.param(
        lambda value: Preset(name='my-preset', uri='owner/repo', contest=value),
        id='Preset.contest',
    ),
    pytest.param(
        lambda value: Preset(name='my-preset', uri='owner/repo', env=value),
        id='Preset.env',
    ),
    pytest.param(
        lambda value: PackageVariant(id='interactive', path=value),
        id='PackageVariant.path',
    ),
    pytest.param(
        lambda value: Library(name='testlib', source='a/b', dest=value),
        id='Library.dest',
    ),
    pytest.param(
        lambda value: TrackedAsset(path=value),
        id='TrackedAsset.path',
    ),
]


class TestDeclaredPathsStayInsidePreset:
    """Every path a preset declares is joined onto the preset directory, so an
    absolute one silently discards that root and a `..` one walks out of it."""

    @pytest.mark.parametrize('build', PATH_FIELDS)
    @pytest.mark.parametrize('bad', ['/etc', '/etc/passwd', '/'])
    def test_rejects_absolute_path(self, build, bad):
        with pytest.raises(ValidationError, match='absolute') as exc:
            build(bad)
        assert bad in str(exc.value)

    @pytest.mark.parametrize('build', PATH_FIELDS)
    @pytest.mark.parametrize(
        'bad', ['..', '../sibling', '../../../somewhere', 'problem/../../escape']
    )
    def test_rejects_escaping_path(self, build, bad):
        with pytest.raises(ValidationError, match=r'walks out of it') as exc:
            build(bad)
        assert bad in str(exc.value)

    @pytest.mark.parametrize('build', PATH_FIELDS)
    @pytest.mark.parametrize(
        'ok',
        [
            'problem',
            'testlib.h',
            'env.rbx.yml',
            '.gitignore',
            'include/testlib.h',
            'bits/stdc++.h',
            'statements/icpc.sty',
            './problem',
            'a..b/c',
        ],
    )
    def test_accepts_contained_paths(self, build, ok):
        build(ok)

    @pytest.mark.parametrize(
        'glob',
        [
            'src/*',
            'src/**/*.cpp',
            'src/**/*.hpp',
            '*',
            '**/*.tex',
        ],
    )
    def test_accepts_globs_in_tracked_assets(self, glob):
        # `TrackedAsset.path` doubles as a glob in preset config (see
        # `process_globbing`), and none of the legitimate glob forms are absolute
        # or contain `..`.
        assert TrackedAsset(path=glob).path == pathlib.Path(glob)


def _shipped_presets() -> list:
    """Every `preset.rbx.yml` that rbx itself ships: the bundled `default` preset
    plus the test fixture presets."""
    paths = [get_default_app_path() / 'presets' / 'default' / 'preset.rbx.yml']
    paths.extend(sorted((get_testdata_path() / 'presets').glob('*/preset.rbx.yml')))
    return [pytest.param(p, id=p.parent.name) for p in paths]


class TestShippedPresetsStillParse:
    """The regression guard for the path validators above: a validator that is
    too strict breaks every preset, so assert the ones rbx ships all still load."""

    def test_found_the_shipped_presets(self):
        # Guards against the glob silently going empty and vacuously passing.
        assert len(_shipped_presets()) >= 5

    @pytest.mark.parametrize('path', _shipped_presets())
    def test_parses(self, path: pathlib.Path):
        assert path.is_file(), path
        load_yaml_model(path, Preset)
