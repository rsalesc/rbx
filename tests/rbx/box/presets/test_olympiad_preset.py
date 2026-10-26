"""Tests for rbx's bundled `olympiad` preset.

These load `rbx/resources/presets/olympiad` directly (no mocks and no fixture
preset), so they fail if the shipped template drifts from what the schema
accepts.
"""

import pathlib
from typing import Optional

import pytest

from rbx.box.presets import get_preset_yaml, registry
from rbx.box.presets.schema import Preset, ReplacementMode
from rbx.box.schema import ExpectedOutcome, Package, TaskType
from rbx.box.yaml_validation import load_yaml_model
from rbx.config import get_default_app_path

# Every problem template the preset offers: None is the canonical one.
TEMPLATES = [None, 'grader', 'interactive', 'interactive-grader']


@pytest.fixture
def preset_path() -> pathlib.Path:
    return get_default_app_path() / 'presets' / 'olympiad'


@pytest.fixture
def preset(preset_path: pathlib.Path) -> Preset:
    return get_preset_yaml(preset_path)


def _template_path(
    preset: Preset, preset_path: pathlib.Path, variant_id: Optional[str]
) -> pathlib.Path:
    if variant_id is None:
        assert preset.problem is not None
        return preset_path / preset.problem
    variant = preset.find_variant(variant_id, is_contest=False)
    assert variant is not None, f'olympiad preset must declare {variant_id}'
    return preset_path / variant.path


@pytest.fixture(params=TEMPLATES, ids=lambda v: v or 'canonical')
def template_path(
    request: pytest.FixtureRequest, preset: Preset, preset_path: pathlib.Path
) -> pathlib.Path:
    return _template_path(preset, preset_path, request.param)


@pytest.fixture
def package(template_path: pathlib.Path) -> Package:
    return load_yaml_model(template_path / 'problem.rbx.yml', Package)


class TestRegistration:
    def test_registry_lists_olympiad(self):
        entry = next(
            p for p in registry.get_builtin_registry().presets if p.name == 'olympiad'
        )
        assert entry.uri == 'olympiad'
        assert entry.description.strip() != ''

    def test_preset_is_named_olympiad(self, preset: Preset):
        assert preset.name == 'olympiad'

    def test_declares_exactly_the_four_templates(self, preset: Preset):
        assert preset.problem == pathlib.Path('problem')
        assert [v.id for v in preset.problemVariants] == [
            'grader',
            'interactive',
            'interactive-grader',
        ]
        for variant in preset.problemVariants:
            assert variant.description.strip() != ''


class TestEveryTemplate:
    def test_is_scored_by_points(self, package: Package):
        assert package.points_scoring is not None

    def test_has_samples_and_one_100_point_subtask(self, package: Package):
        groups = [(g.name, g.score) for g in package.testcases]
        assert groups == [('samples', 0), ('subtask1', 100)]

    def test_subtasks_share_the_problem_level_testplan(
        self, package: Package, template_path: pathlib.Path
    ):
        assert package.generatorScript is not None
        assert package.generatorScript.path == pathlib.Path('tests/testplan.txt')
        subtask = next(g for g in package.testcases if g.name == 'subtask1')
        # No test parameters of its own, so it inherits the problem-level one.
        assert subtask.generatorScript is None
        assert subtask.testcaseGlob is None
        assert not subtask.generators and not subtask.testcases
        testplan = (template_path / 'tests' / 'testplan.txt').read_text()
        assert '@testgroup subtask1 {' in testplan

    def test_declares_a_single_tagged_solution_with_its_score(
        self, package: Package, template_path: pathlib.Path
    ):
        [solution] = package.solutions
        assert solution.path == pathlib.Path('sols/main.cpp')
        assert solution.outcome == ExpectedOutcome.ACCEPTED
        assert solution.score == 100
        assert solution.tags == ['model']
        assert (template_path / solution.path).is_file()

    def test_explains_how_to_declare_solutions(self, template_path: pathlib.Path):
        text = (template_path / 'problem.rbx.yml').read_text()
        assert 'setters/reference/package/#solutions' in text

    def test_every_referenced_source_exists(
        self, package: Package, template_path: pathlib.Path
    ):
        items = [package.checker, package.interactor, package.validator]
        items.append(package.grader)
        for item in items:
            if item is not None:
                assert (template_path / item.path).is_file(), item.path
        for attachment in package.attachments:
            path = getattr(attachment, 'path', None)  # samples carry none
            if path is not None:
                assert (template_path / path).is_file(), path

    def test_statement_has_a_scoring_block(self, template_path: pathlib.Path):
        statement = template_path / 'statement' / 'statement-en.rbx.tex'
        assert '%- block scoring' in statement.read_text()

    def test_statement_shows_examples_by_default(self, package: Package):
        [statement] = package.statements
        assert statement.params['show_examples'] is True

    def test_testplan_has_live_generator_calls(self, template_path: pathlib.Path):
        testplan = (template_path / 'tests' / 'testplan.txt').read_text()
        calls = [
            line.strip()
            for line in testplan.splitlines()
            if line.strip() and not line.strip().startswith('#')
        ]
        assert calls, 'the 100-point subtask must have tests'

    @pytest.mark.parametrize('filename', ['rbx.h', '.gitignore'])
    def test_shared_file_is_byte_identical_to_canonical(
        self, filename: str, preset_path: pathlib.Path, template_path: pathlib.Path
    ):
        canonical = preset_path / 'problem' / filename
        assert (template_path / filename).read_bytes() == canonical.read_bytes()


class TestTemplateKinds:
    def _package(
        self, preset: Preset, preset_path: pathlib.Path, variant_id: Optional[str]
    ) -> Package:
        path = _template_path(preset, preset_path, variant_id)
        return load_yaml_model(path / 'problem.rbx.yml', Package)

    def test_canonical_is_a_plain_batch_problem(
        self, preset: Preset, preset_path: pathlib.Path
    ):
        pkg = self._package(preset, preset_path, None)
        assert pkg.type == TaskType.BATCH
        assert pkg.grader is None
        assert pkg.interactor is None
        assert pkg.checker is not None

    def test_grader_variant_is_a_batch_problem_with_a_grader(
        self, preset: Preset, preset_path: pathlib.Path
    ):
        pkg = self._package(preset, preset_path, 'grader')
        assert pkg.type == TaskType.BATCH
        assert pkg.grader is not None
        assert pkg.interactor is None
        assert pkg.checker is not None

    def test_interactive_variant_has_an_interactor_and_no_grader(
        self, preset: Preset, preset_path: pathlib.Path
    ):
        pkg = self._package(preset, preset_path, 'interactive')
        assert pkg.type == TaskType.COMMUNICATION
        assert pkg.grader is None
        assert pkg.interactor is not None
        assert pkg.checker is None

    def test_interactive_grader_variant_has_an_interactor_and_a_grader_stub(
        self, preset: Preset, preset_path: pathlib.Path
    ):
        pkg = self._package(preset, preset_path, 'interactive-grader')
        assert pkg.type == TaskType.COMMUNICATION
        assert pkg.grader is not None
        assert pkg.interactor is not None
        assert pkg.checker is None


class TestGraderSecret:
    NEEDLE = '__GRADER_SECRET__'

    @pytest.mark.parametrize('variant_id', ['grader', 'interactive-grader'])
    def test_grader_templates_use_the_placeholder(
        self, variant_id: str, preset: Preset, preset_path: pathlib.Path
    ):
        path = _template_path(preset, preset_path, variant_id)
        pkg = load_yaml_model(path / 'problem.rbx.yml', Package)
        assert pkg.grader is not None
        assert pkg.grader.secret == self.NEEDLE

    @pytest.mark.parametrize('variant_id', TEMPLATES, ids=lambda v: v or 'canonical')
    def test_placeholder_is_replaced_by_random_hex(
        self, variant_id: Optional[str], preset: Preset
    ):
        variant = (
            preset.find_variant(variant_id, is_contest=False) if variant_id else None
        )
        [expansion] = [
            e
            for e in preset.merged_expansion(variant, is_contest=False)
            if e.needle == self.NEEDLE
        ]
        assert expansion.replacement == ReplacementMode.RANDOM_HEX
        assert expansion.glob == ['problem.rbx.yml']


class TestContestChrome:
    def test_problem_body_renders_the_scoring_block(self, preset_path: pathlib.Path):
        body = preset_path / 'contest' / 'statements' / '_problem-body.rbx.tex'
        text = body.read_text()
        assert 'problem.blocks.scoring is defined' in text
        assert r'\scoringdesc{\VAR{problem.blocks.scoring}}' in text

    def test_problem_body_lets_an_examples_block_replace_the_samples(
        self, preset_path: pathlib.Path
    ):
        body = preset_path / 'contest' / 'statements' / '_problem-body.rbx.tex'
        lines = [line.strip() for line in body.read_text().splitlines()]
        switch = lines.index(
            '%- if params.show_examples is null or params.show_examples is truthy'
        )
        override = lines.index('%- if problem.blocks.examples is defined')
        generated = lines.index('%- elif problem.samples')
        assert switch < override < generated
        assert r'\VAR{problem.blocks.examples}' in lines[override:generated]

    def test_style_defines_the_scoring_section(self, preset_path: pathlib.Path):
        style = (preset_path / 'contest' / 'statements' / 'icpc.sty').read_text()
        assert r'\newcommand{\scoringdesc}' in style
        assert style.count(r'\def\strScoring{') == 2  # pt and en
