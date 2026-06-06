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


class TestCppReferences:
    def test_quoted_and_angle_and_builtin(self, testing_pkg):
        from rbx.box.dependencies import cpp

        testing_pkg.add_file('lib.h').write_text('#pragma once\n')
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include "../lib.h"\n'
            '#include <cstdio>\n'
            '#include "testlib.h"\n'
            'int main(){}\n'
        )
        refs = cpp.CppScanner().references(pathlib.Path('gens/gen.cpp'))
        by_spelling = {r.spelling: r.target for r in refs}
        # Quoted package include resolves to its package-relative path.
        assert by_spelling['../lib.h'] == pathlib.Path('lib.h')
        # Quoted builtin (not a package file) -> unresolved.
        assert by_spelling['testlib.h'] is None
        # Angle includes are never reported.
        assert 'cstdio' not in by_spelling

    def test_ignores_commented_include(self, testing_pkg):
        from rbx.box.dependencies import cpp

        testing_pkg.add_file('lib.h').write_text('#pragma once\n')
        src = testing_pkg.add_file('a.cpp')
        src.write_text('/* #include "lib.h" */\nint main(){}\n')
        assert cpp.CppScanner().references(pathlib.Path('a.cpp')) == []


class TestCppRewrite:
    def test_rewrites_mapped_leaves_others(self):
        from rbx.box.dependencies import cpp

        text = '#include "../lib.h"\n#include <cstdio>\n#include "keep.h"\n'
        out = cpp.CppScanner().rewrite(text, {'../lib.h': 'lib__x.h'}.get)
        assert '#include "lib__x.h"' in out
        assert '#include <cstdio>' in out  # angle untouched
        assert '#include "keep.h"' in out  # unmapped untouched

    def test_preserves_commented_include(self):
        from rbx.box.dependencies import cpp

        text = '/* #include "lib.h" */\n#include "lib.h"\n'
        out = cpp.CppScanner().rewrite(text, {'lib.h': 'flat.h'}.get)
        assert '/* #include "lib.h" */' in out  # comment untouched
        assert '#include "flat.h"' in out  # real directive rewritten
