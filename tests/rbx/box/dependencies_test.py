import pathlib
from typing import List

import pytest

from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, DependencyScanner, Reference


class _Dummy(DependencyScanner):
    kinds = {DependencyKind.COMPILATION}

    def handles(self, language: str) -> bool:
        return language == 'dummy'

    def references(self, file: pathlib.Path) -> List[Reference]:
        return []


def test_register_and_get_scanner():
    scanner.register(_Dummy)
    assert isinstance(scanner.get_scanner('dummy'), _Dummy)
    assert scanner.get_scanner('nope') is None


def test_rewrite_unsupported_by_default():
    with pytest.raises(NotImplementedError):
        _Dummy().rewrite('x', lambda s: None)
