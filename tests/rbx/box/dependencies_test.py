import pathlib
from typing import List

import pytest

from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, DependencyScanner, Reference
from rbx.grading.language_kind import LanguageKind


class _Dummy(DependencyScanner):
    name = 'dummy'
    language_kinds = {LanguageKind.CXX}
    dependency_kinds = {DependencyKind.COMPILATION}

    def references(self, file: pathlib.Path) -> List[Reference]:
        return []


def test_register_and_get_scanner():
    scanner.register(_Dummy)
    assert isinstance(scanner.get_scanner('dummy'), _Dummy)
    assert scanner.get_scanner('nope') is None


def test_get_scanners_by_kind_and_explicit_name():
    scanner.register(_Dummy)
    # Selected automatically by language kind...
    cxx = scanner.get_scanners_for_kinds({LanguageKind.CXX})
    assert any(s.name == 'dummy' for s in cxx)
    # ...not by an unrelated kind...
    py = scanner.get_scanners_for_kinds({LanguageKind.PYTHON})
    assert not any(s.name == 'dummy' for s in py)
    # ...unless named explicitly.
    py_named = scanner.get_scanners_for_kinds({LanguageKind.PYTHON}, ['dummy'])
    assert any(s.name == 'dummy' for s in py_named)


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


class TestPythonReferences:
    def test_relative_sibling_and_stdlib(self, testing_pkg):
        from rbx.box.dependencies import python

        testing_pkg.add_file('sols/helper.py').write_text('X = 1\n')
        main = testing_pkg.add_file('sols/main.py')
        main.write_text(
            'import os\n'
            'from . import helper\n'
            'import helper as h2\n'
            'print(helper.X, h2.X, os.getpid())\n'
        )
        refs = python.PythonScanner().references(pathlib.Path('sols/main.py'))
        targets = {r.target for r in refs if r.target is not None}
        assert pathlib.Path('sols/helper.py') in targets
        # stdlib os never resolves to a package file.
        assert all(r.target != pathlib.Path('os.py') for r in refs)

    def test_parent_package_import(self, testing_pkg):
        from rbx.box.dependencies import python

        testing_pkg.add_file('common/util.py').write_text('Y = 2\n')
        src = testing_pkg.add_file('sols/sub/main.py')
        src.write_text('from ...common import util\n')
        refs = python.PythonScanner().references(pathlib.Path('sols/sub/main.py'))
        assert any(r.target == pathlib.Path('common/util.py') for r in refs)

    def test_deep_import_ships_intermediate_init_markers(self, testing_pkg):
        from rbx.box.dependencies import python

        testing_pkg.add_file('a/__init__.py').write_text('')
        testing_pkg.add_file('a/b/__init__.py').write_text('')
        testing_pkg.add_file('a/b/c.py').write_text('Z = 1\n')
        main = testing_pkg.add_file('main.py')
        main.write_text('import a.b.c\n')
        refs = python.PythonScanner().references(pathlib.Path('main.py'))
        targets = {r.target for r in refs if r.target is not None}
        # The leaf AND every existing intermediate __init__.py must be discovered.
        assert pathlib.Path('a/b/c.py') in targets
        assert pathlib.Path('a/__init__.py') in targets
        assert pathlib.Path('a/b/__init__.py') in targets


class TestExpand:
    def test_cpp_transitive_excludes_root(self, testing_pkg):
        from rbx.box.dependencies import graph
        from rbx.box.dependencies.scanner import DependencyKind
        from rbx.box.schema import CodeItem

        testing_pkg.add_file('lib.h').write_text('#include "extra.h"\n')
        testing_pkg.add_file('extra.h').write_text('#pragma once\n')
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text('#include "../lib.h"\nint main(){}\n')

        g = graph.expand(CodeItem(path=gen, language='cpp'))
        assert g is not None
        assert g.kinds == {DependencyKind.COMPILATION}
        assert g.files() == [pathlib.Path('extra.h'), pathlib.Path('lib.h')]

    def test_cycle_safe(self, testing_pkg):
        from rbx.box.dependencies import graph
        from rbx.box.schema import CodeItem

        testing_pkg.add_file('a.h').write_text('#include "b.h"\n')
        testing_pkg.add_file('b.h').write_text('#include "a.h"\n')
        src = testing_pkg.add_file('m.cpp')
        src.write_text('#include "a.h"\nint main(){}\n')
        g = graph.expand(CodeItem(path=src, language='cpp'))
        assert set(g.files()) == {pathlib.Path('a.h'), pathlib.Path('b.h')}

    def test_none_for_unhandled_language(self, testing_pkg):
        from rbx.box.dependencies import graph
        from rbx.box.schema import CodeItem

        j = testing_pkg.add_file('Main.java')
        j.write_text('class Main {}\n')
        assert graph.expand(CodeItem(path=j, language='java')) is None

    def test_c_source_dispatches_to_cpp_scanner_by_kind(self, testing_pkg):
        # A 'c' language has kinds {CXX, C}; the cpp scanner declares {CXX}, so it is
        # selected by kind intersection -- no dependence on the language name.
        from rbx.box.dependencies import graph
        from rbx.box.schema import CodeItem

        testing_pkg.add_file('lib.h').write_text('#pragma once\n')
        src = testing_pkg.add_file('m.c')
        src.write_text('#include "lib.h"\nint main(){}\n')
        g = graph.expand(CodeItem(path=src, language='c'))
        assert g is not None
        assert pathlib.Path('lib.h') in g.files()

    def test_language_kinds_derive_from_toolchain(self, testing_pkg):
        from rbx.box import environment

        assert environment.language_kinds(environment.get_language('cpp')) == {
            LanguageKind.CPP,
            LanguageKind.CXX,
        }
        assert environment.language_kinds(environment.get_language('c')) == {
            LanguageKind.C,
            LanguageKind.CXX,
        }
        assert environment.language_kinds(environment.get_language('py')) == {
            LanguageKind.PYTHON
        }
        assert LanguageKind.JVM in environment.language_kinds(
            environment.get_language('java')
        )
