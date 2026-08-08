import pathlib
import re
from typing import Any

import pytest
import typer
from pydantic import ValidationError

from rbx.box import presets
from rbx.box.presets.schema import (
    Expansion,
    Libraries,
    Library,
    PackageVariant,
    Preset,
    ReplacementMode,
    TrackedAsset,
    Tracking,
    VariableExpansion,
)


def _preset(**kwargs: Any) -> Preset:
    # NOTE: `Preset` does not forbid extra fields, so a misspelled keyword here
    # is silently ignored and the assertion below would run against a default.
    base: dict = dict(name='my-preset', uri='owner/repo')
    base.update(kwargs)
    return Preset(**base)


class TestPackageVariant:
    def test_minimal_variant(self):
        variant = PackageVariant(
            id='interactive', path=pathlib.Path('problem-interactive')
        )
        assert variant.id == 'interactive'
        assert variant.description == ''
        assert variant.tracking == []
        assert variant.libraries == []
        assert variant.expansion == []

    @pytest.mark.parametrize('bad_id', ['1abc', 'has space', 'has.dot', '', 'a/b'])
    def test_rejects_malformed_id(self, bad_id):
        with pytest.raises(ValidationError):
            PackageVariant(id=bad_id, path=pathlib.Path('p'))

    def test_rejects_reserved_default_id(self):
        with pytest.raises(ValidationError, match='reserved'):
            PackageVariant(id='default', path=pathlib.Path('p'))

    @pytest.mark.parametrize('ok_id', ['default2', 'my-default', 'defaults'])
    def test_accepts_ids_merely_containing_default(self, ok_id):
        assert PackageVariant(id=ok_id, path=pathlib.Path('p')).id == ok_id

    def test_accepts_dashes_and_underscores(self):
        variant = PackageVariant(id='interactive-points_2', path=pathlib.Path('p'))
        assert variant.id == 'interactive-points_2'

    def test_constructs_nested_payload_from_dict(self):
        variant = PackageVariant(
            **{
                'id': 'interactive',
                'path': 'problem-interactive',
                'tracking': [{'path': 'interactor.cpp', 'symlink': True}],
                'libraries': [
                    {'name': 'testlib', 'source': 'a/b', 'dest': 'testlib.h'}
                ],
                'expansion': [{'needle': 'AUTHOR', 'prompt': 'Author?'}],
            }
        )

        assert variant.path == pathlib.Path('problem-interactive')

        assert variant.tracking == [
            TrackedAsset(path=pathlib.Path('interactor.cpp'), symlink=True)
        ]
        assert isinstance(variant.tracking[0], TrackedAsset)

        assert variant.libraries == [
            Library(name='testlib', source='a/b', dest=pathlib.Path('testlib.h'))
        ]
        assert isinstance(variant.libraries[0], Library)

        assert variant.expansion == [
            VariableExpansion(needle='AUTHOR', prompt='Author?')
        ]
        assert isinstance(variant.expansion[0], VariableExpansion)
        assert variant.expansion[0].replacement == ReplacementMode.PROMPT


class TestPresetVariants:
    def test_defaults_to_no_variants(self):
        preset = _preset(problem=pathlib.Path('problem'))
        assert preset.problemVariants == []
        assert preset.contestVariants == []

    def test_rejects_duplicate_variant_ids(self):
        with pytest.raises(
            ValidationError, match='duplicate variant id interactive in problemVariants'
        ):
            _preset(
                problem=pathlib.Path('problem'),
                problemVariants=[
                    PackageVariant(id='interactive', path=pathlib.Path('a')),
                    PackageVariant(id='interactive', path=pathlib.Path('b')),
                ],
            )

    def test_rejects_duplicate_contest_variant_ids(self):
        with pytest.raises(
            ValidationError, match='duplicate variant id div1 in contestVariants'
        ):
            _preset(
                contest=pathlib.Path('contest'),
                contestVariants=[
                    PackageVariant(id='div1', path=pathlib.Path('a')),
                    PackageVariant(id='div1', path=pathlib.Path('b')),
                ],
            )

    def test_same_id_allowed_across_kinds(self):
        preset = _preset(
            problem=pathlib.Path('problem'),
            contest=pathlib.Path('contest'),
            problemVariants=[PackageVariant(id='div1', path=pathlib.Path('a'))],
            contestVariants=[PackageVariant(id='div1', path=pathlib.Path('b'))],
        )
        assert preset.problemVariants[0].path != preset.contestVariants[0].path

    def test_find_variant_returns_none_for_unknown(self):
        preset = _preset(problem=pathlib.Path('problem'))
        assert preset.find_variant('nope', is_contest=False) is None

    def test_find_variant_is_scoped_by_kind(self):
        variant = PackageVariant(id='div1', path=pathlib.Path('a'))
        preset = _preset(
            problem=pathlib.Path('problem'),
            problemVariants=[variant],
        )
        assert preset.find_variant('div1', is_contest=False) == variant
        assert preset.find_variant('div1', is_contest=True) is None


class TestVariantMerging:
    def test_tracking_variant_entry_wins_over_shared(self):
        variant = PackageVariant(
            id='interactive',
            path=pathlib.Path('problem-interactive'),
            tracking=[
                TrackedAsset(path=pathlib.Path('shared.h'), symlink=True),
                TrackedAsset(path=pathlib.Path('interactor.cpp')),
            ],
        )
        preset = _preset(
            problem=pathlib.Path('problem'),
            tracking=Tracking(
                problem=[
                    TrackedAsset(path=pathlib.Path('.gitignore')),
                    TrackedAsset(path=pathlib.Path('shared.h'), symlink=False),
                ]
            ),
            problemVariants=[variant],
        )
        merged = preset.merged_tracking(variant, is_contest=False)
        # Shared order is preserved and variant-only entries are appended.
        assert [str(a.path) for a in merged] == [
            '.gitignore',
            'shared.h',
            'interactor.cpp',
        ]
        by_path = {str(a.path): a for a in merged}
        assert by_path['shared.h'].symlink is True

    def test_tracking_canonical_returns_shared_only(self):
        preset = _preset(
            problem=pathlib.Path('problem'),
            tracking=Tracking(problem=[TrackedAsset(path=pathlib.Path('.gitignore'))]),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('pi'),
                    tracking=[TrackedAsset(path=pathlib.Path('only-variant'))],
                )
            ],
        )
        merged = preset.merged_tracking(None, is_contest=False)
        assert [str(a.path) for a in merged] == ['.gitignore']

    def test_tracking_merges_contest_side_independently(self):
        variant = PackageVariant(
            id='div1',
            path=pathlib.Path('contest-div1'),
            tracking=[TrackedAsset(path=pathlib.Path('div1.tex'))],
        )
        preset = _preset(
            contest=pathlib.Path('contest'),
            tracking=Tracking(
                problem=[TrackedAsset(path=pathlib.Path('problem-only'))],
                contest=[TrackedAsset(path=pathlib.Path('contest-only'))],
            ),
            contestVariants=[variant],
        )
        merged = preset.merged_tracking(variant, is_contest=True)
        assert [str(a.path) for a in merged] == ['contest-only', 'div1.tex']

    def test_libraries_merge_by_name_variant_wins(self):
        shared = Library(name='testlib', source='a/b', dest=pathlib.Path('testlib.h'))
        other_shared = Library(name='jngen', source='e/f', dest=pathlib.Path('jngen.h'))
        override = Library(
            name='testlib', source='a/b', dest=pathlib.Path('testlib.h'), version='1.0'
        )
        extra = Library(name='interlib', source='c/d', dest=pathlib.Path('inter.h'))
        variant = PackageVariant(
            id='interactive',
            path=pathlib.Path('pi'),
            libraries=[override, extra],
        )
        preset = _preset(
            problem=pathlib.Path('problem'),
            libraries=Libraries(problem=[shared, other_shared]),
            problemVariants=[variant],
        )
        merged = preset.merged_libraries(variant, is_contest=False)
        assert [lib.name for lib in merged] == ['testlib', 'jngen', 'interlib']
        by_name = {lib.name: lib for lib in merged}
        assert by_name['testlib'].version == '1.0'
        assert by_name['jngen'] == other_shared

    def test_libraries_merge_contest_side_independently(self):
        problem_lib = Library(
            name='testlib', source='a/b', dest=pathlib.Path('testlib.h')
        )
        contest_lib = Library(name='jngen', source='e/f', dest=pathlib.Path('jngen.h'))
        variant_lib = Library(name='interlib', source='c/d', dest=pathlib.Path('i.h'))
        variant = PackageVariant(
            id='div1', path=pathlib.Path('contest-div1'), libraries=[variant_lib]
        )
        preset = _preset(
            contest=pathlib.Path('contest'),
            libraries=Libraries(problem=[problem_lib], contest=[contest_lib]),
            contestVariants=[variant],
        )
        merged = preset.merged_libraries(variant, is_contest=True)
        assert [lib.name for lib in merged] == ['jngen', 'interlib']

    def test_libraries_canonical_returns_shared_only(self):
        shared = Library(name='testlib', source='a/b', dest=pathlib.Path('testlib.h'))
        preset = _preset(
            problem=pathlib.Path('problem'),
            libraries=Libraries(problem=[shared]),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('pi'),
                    libraries=[
                        Library(
                            name='interlib', source='c/d', dest=pathlib.Path('inter.h')
                        )
                    ],
                )
            ],
        )
        assert preset.merged_libraries(None, is_contest=False) == [shared]

    def test_expansion_merges_by_needle(self):
        variant = PackageVariant(
            id='interactive',
            path=pathlib.Path('pi'),
            expansion=[
                VariableExpansion(needle='AUTHOR', prompt='Who wrote it?'),
                VariableExpansion(needle='JUDGE', prompt='Judge?'),
            ],
        )
        preset = _preset(
            problem=pathlib.Path('problem'),
            expansion=Expansion(
                problem=[
                    VariableExpansion(needle='AUTHOR', prompt='Author?'),
                    VariableExpansion(needle='TITLE', prompt='Title?'),
                ]
            ),
            problemVariants=[variant],
        )
        merged = preset.merged_expansion(variant, is_contest=False)
        assert [e.needle for e in merged] == ['AUTHOR', 'TITLE', 'JUDGE']
        assert merged[0].prompt == 'Who wrote it?'

    def test_expansion_merges_contest_side_independently(self):
        variant = PackageVariant(
            id='div1',
            path=pathlib.Path('contest-div1'),
            expansion=[VariableExpansion(needle='DIVISION', prompt='Division?')],
        )
        preset = _preset(
            contest=pathlib.Path('contest'),
            expansion=Expansion(
                problem=[VariableExpansion(needle='TITLE', prompt='Title?')],
                contest=[VariableExpansion(needle='AUTHOR', prompt='Author?')],
            ),
            contestVariants=[variant],
        )
        merged = preset.merged_expansion(variant, is_contest=True)
        assert [e.needle for e in merged] == ['AUTHOR', 'DIVISION']

    def test_expansion_canonical_returns_shared_only(self):
        shared = VariableExpansion(needle='AUTHOR', prompt='Author?')
        preset = _preset(
            problem=pathlib.Path('problem'),
            expansion=Expansion(problem=[shared]),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('pi'),
                    expansion=[VariableExpansion(needle='JUDGE', prompt='Judge?')],
                )
            ],
        )
        assert preset.merged_expansion(None, is_contest=False) == [shared]


PRESET_WITH_VARIANT = """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    description: "Interactive"
"""


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _plain(captured: str) -> str:
    """Console output without rich's styling, so assertions can match spans of
    text that the highlighter breaks up with escape codes."""
    return _ANSI.sub('', captured)


def _write_preset(root: pathlib.Path, body: str) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'preset.rbx.yml').write_text(body)
    (root / 'problem').mkdir(exist_ok=True)
    (root / 'problem-interactive').mkdir(exist_ok=True)
    return root


class TestResolveTemplate:
    def test_canonical_when_no_variant_requested(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant=None
        )
        assert resolved.variant_id is None
        assert resolved.path == root / 'problem'

    def test_named_variant(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='interactive'
        )
        assert resolved.variant_id == 'interactive'
        assert resolved.path == root / 'problem-interactive'

    def test_default_keyword_means_canonical(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='default'
        )
        assert resolved.variant_id is None
        assert resolved.path == root / 'problem'

    def test_unknown_variant_exits_and_lists_available(self, tmp_path, capsys):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=False, variant='nope')
        out = _plain(capsys.readouterr().out)
        assert 'nope' in out
        assert 'interactive' in out
        assert 'default' in out

    def test_missing_canonical_without_variant_exits(self, tmp_path, capsys):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "variant-only"
uri: "test/variant-only"
min_version: "1.0.0"
problemVariants:
  - id: interactive
    path: "problem-interactive"
""",
        )
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=False, variant=None)
        out = _plain(capsys.readouterr().out)
        assert 'interactive' in out

    def test_declared_but_missing_directory_exits(self, tmp_path, capsys):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: interactive
    path: "problem-gone"
""",
        )
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(
                preset, root, is_contest=False, variant='interactive'
            )
        out = _plain(capsys.readouterr().out)
        assert 'problem-gone' in out
        # The resolved location is shown too, so the user can tell which copy of
        # the preset is stale.
        assert str(root / 'problem-gone') in out

    def test_carries_merged_config(self, tmp_path):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
tracking:
  problem:
    - path: ".gitignore"
expansion:
  problem:
    - needle: "AUTHOR"
      prompt: "Author?"
libraries:
  problem:
    - name: "testlib"
      source: "owner/testlib"
      dest: "testlib.h"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    tracking:
      - path: "interactor.cpp"
    expansion:
      - needle: "JUDGE"
        prompt: "Judge?"
    libraries:
      - name: "jngen"
        source: "owner/jngen"
        dest: "jngen.h"
""",
        )
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='interactive'
        )
        assert [str(a.path) for a in resolved.tracking] == [
            '.gitignore',
            'interactor.cpp',
        ]
        assert [e.needle for e in resolved.expansion] == ['AUTHOR', 'JUDGE']
        assert [lib.name for lib in resolved.libraries] == ['testlib', 'jngen']

    def test_canonical_carries_shared_config_only(self, tmp_path):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
tracking:
  problem:
    - path: ".gitignore"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    tracking:
      - path: "interactor.cpp"
""",
        )
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant=None
        )
        assert [str(a.path) for a in resolved.tracking] == ['.gitignore']

    def test_contest_variant_is_not_a_problem_variant(self, tmp_path, capsys):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        (root / 'contest').mkdir(exist_ok=True)
        (root / 'preset.rbx.yml').write_text(
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
contest: "contest"
problemVariants:
  - id: interactive
    path: "problem-interactive"
"""
        )
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(
                preset, root, is_contest=True, variant='interactive'
            )
        out = _plain(capsys.readouterr().out)
        assert 'no contest variant' in out
        # Only the canonical contest template is offered; the problem variant is
        # not a valid choice here.
        assert 'interactive' not in out.split('Available contest templates')[1]

    def test_carries_preset_root_and_declared_inner_path(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='interactive'
        )
        assert resolved.preset is preset
        assert resolved.preset_path == root
        assert resolved.inner == pathlib.Path('problem-interactive')
        assert resolved.path == resolved.preset_path / resolved.inner

    def test_lists_the_flag_to_use(self, tmp_path, capsys):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=False, variant='nope')
        assert 'select with -v <id>' in _plain(capsys.readouterr().out)

    def test_no_templates_at_all_reports_only_that(self, tmp_path, capsys):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "no-templates"
uri: "test/no-templates"
min_version: "1.0.0"
problem: "problem"
""",
        )
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=True, variant=None)
        out = _plain(capsys.readouterr().out)
        assert 'declares no contest templates at all' in out
        # No contradictory second message, and no empty list of alternatives.
        assert 'canonical' not in out
        assert 'Available' not in out


class TestVariantForPath:
    def test_maps_nested_cwd(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        assert (
            presets.variant_for_path(
                preset,
                root,
                root / 'problem-interactive' / 'sols',
                is_contest=False,
            )
            == 'interactive'
        )
        assert (
            presets.variant_for_path(preset, root, root / 'problem', is_contest=False)
            == 'default'
        )

    def test_maps_the_variant_root_itself(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        assert (
            presets.variant_for_path(
                preset, root, root / 'problem-interactive', is_contest=False
            )
            == 'interactive'
        )

    def test_preset_root_is_inside_no_template(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        assert presets.variant_for_path(preset, root, root, is_contest=False) is None

    def test_path_outside_the_preset_is_inside_no_template(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        assert (
            presets.variant_for_path(
                preset, root, tmp_path / 'elsewhere', is_contest=False
            )
            is None
        )

    def test_result_feeds_back_into_resolve_template(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        for target, expected in (
            (root / 'problem', root / 'problem'),
            (root / 'problem-interactive', root / 'problem-interactive'),
        ):
            variant = presets.variant_for_path(preset, root, target, is_contest=False)
            resolved = presets.resolve_template(
                preset, root, is_contest=False, variant=variant
            )
            assert resolved.path == expected

    def test_prefers_the_deepest_matching_variant(self, tmp_path):
        root = tmp_path / 'preset'
        root.mkdir()
        (root / 'templates' / 'interactive').mkdir(parents=True)
        (root / 'preset.rbx.yml').write_text(
            """---
name: "nested"
uri: "test/nested"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: outer
    path: "templates"
  - id: inner
    path: "templates/interactive"
"""
        )
        preset = presets.get_preset_yaml(root)
        assert (
            presets.variant_for_path(
                preset,
                root,
                root / 'templates' / 'interactive' / 'sols',
                is_contest=False,
            )
            == 'inner'
        )
        assert (
            presets.variant_for_path(
                preset, root, root / 'templates' / 'other', is_contest=False
            )
            == 'outer'
        )

    def test_contest_templates_are_separate(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        # The preset declares no contest templates at all, so nothing matches.
        assert (
            presets.variant_for_path(
                preset, root, root / 'problem-interactive', is_contest=True
            )
            is None
        )
        assert (
            presets.variant_for_path(preset, root, root / 'problem', is_contest=True)
            is None
        )
