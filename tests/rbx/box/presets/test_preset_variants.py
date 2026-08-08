import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.presets.schema import PackageVariant


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

    def test_accepts_dashes_and_underscores(self):
        assert PackageVariant(id='interactive-points_2', path=pathlib.Path('p')).id
