import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.presets.schema import (
    Library,
    PackageVariant,
    ReplacementMode,
    TrackedAsset,
    VariableExpansion,
)


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
