import pytest

from rbx.box.exception import RbxException
from rbx.box.linters import registry
from rbx.box.linters.linter import Linter


@registry.register
class _RegLinter(Linter):
    name = 'reg_test'

    def lint(self, code, source):
        return []


def test_register_and_get():
    assert isinstance(registry.get_linter('reg_test'), _RegLinter)


def test_get_unknown_raises():
    with pytest.raises(RbxException):
        registry.get_linter('does_not_exist')
