"""Tests for the variants shipped by rbx's bundled `default` preset.

These load `rbx/resources/presets/default` directly (no mocks and no fixture
preset), so they fail if the shipped template drifts from what the schema
accepts.
"""

import pathlib

import pytest

from rbx.box.presets import get_preset_yaml
from rbx.box.presets.schema import PackageVariant, Preset
from rbx.box.schema import Package, TaskType
from rbx.box.yaml_validation import load_yaml_model
from rbx.config import get_default_app_path


@pytest.fixture
def default_preset_path() -> pathlib.Path:
    return get_default_app_path() / 'presets' / 'default'


@pytest.fixture
def default_preset(default_preset_path: pathlib.Path) -> Preset:
    return get_preset_yaml(default_preset_path)


@pytest.fixture
def interactive_variant(default_preset: Preset) -> PackageVariant:
    variant = default_preset.find_variant('interactive', is_contest=False)
    assert variant is not None, 'default preset must declare an interactive variant'
    return variant


@pytest.fixture
def interactive_path(
    default_preset_path: pathlib.Path, interactive_variant: PackageVariant
) -> pathlib.Path:
    return default_preset_path / interactive_variant.path


class TestInteractiveVariantDeclaration:
    def test_variant_is_declared_with_a_description(
        self, interactive_variant: PackageVariant
    ):
        assert interactive_variant.description.strip() != ''

    def test_variant_path_is_a_real_directory(self, interactive_path: pathlib.Path):
        assert interactive_path.is_dir()

    def test_canonical_template_is_untouched(
        self, default_preset: Preset, default_preset_path: pathlib.Path
    ):
        assert default_preset.problem == pathlib.Path('problem')
        assert (default_preset_path / 'problem' / 'problem.rbx.yml').is_file()


class TestInteractiveVariantPackage:
    @pytest.fixture
    def package(self, interactive_path: pathlib.Path) -> Package:
        return load_yaml_model(interactive_path / 'problem.rbx.yml', Package)

    def test_task_type_is_communication(self, package: Package):
        assert package.type == TaskType.COMMUNICATION

    def test_declares_an_interactor_that_exists(
        self, package: Package, interactive_path: pathlib.Path
    ):
        assert package.interactor is not None
        assert (interactive_path / package.interactor.path).is_file()

    def test_declares_no_checker(self, package: Package):
        # A non-legacy communication task must not have a checker: the
        # interactor judges the solution by itself.
        assert package.checker is None

    def test_declares_a_validator_that_exists(
        self, package: Package, interactive_path: pathlib.Path
    ):
        assert package.validator is not None
        assert (interactive_path / package.validator.path).is_file()

    def test_ships_a_main_solution(self, interactive_path: pathlib.Path):
        assert (interactive_path / 'sols' / 'main.cpp').is_file()

    def test_ships_no_checker_source(self, interactive_path: pathlib.Path):
        # Any leftover checker source would mislead a setter into thinking
        # interactive problems need one.
        sources = [path.name for path in interactive_path.rglob('*.cpp')]
        assert not [
            name for name in sources if 'checker' in name or name == 'wcmp.cpp'
        ], sources

    def test_testplan_has_live_generator_calls(self, interactive_path: pathlib.Path):
        testplan = (interactive_path / 'tests' / 'testplan.txt').read_text()
        calls = [
            line.strip()
            for line in testplan.splitlines()
            if line.strip() and not line.strip().startswith('#')
        ]
        assert calls, 'the interactive variant must produce a real testset'


class TestSharedFilesDoNotDrift:
    # These files are plain copies of the canonical template's. This guards
    # against them drifting apart silently.
    @pytest.mark.parametrize('filename', ['rbx.h', '.gitignore'])
    def test_file_is_byte_identical_to_canonical(
        self,
        filename: str,
        default_preset_path: pathlib.Path,
        interactive_path: pathlib.Path,
    ):
        canonical = default_preset_path / 'problem' / filename
        variant = interactive_path / filename
        assert variant.read_bytes() == canonical.read_bytes()
