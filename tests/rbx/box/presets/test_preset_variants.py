import pathlib
from typing import Any

import pytest
from pydantic import ValidationError

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
