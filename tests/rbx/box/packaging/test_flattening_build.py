import pathlib

import pytest
import typer

from rbx.box.packaging import flattening
from rbx.box.schema import CodeItem


def test_build_flat_namespace_flattens_and_rewrites_checker(testing_pkg):
    testing_pkg.add_file('common/consts.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.add_file('common/lib.h').write_text(
        '#pragma once\n#include "consts.h"\n'
    )
    testing_pkg.add_file('checkers/check.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    checker = CodeItem(path=pathlib.Path('checkers/check.cpp'))
    ns = flattening.build_flat_namespace(
        [checker],
        reserved={pathlib.Path('checkers/check.cpp'): 'check.cpp'},
    )
    assert {f.flat_name for f in ns.files} == {'check.cpp', 'lib.h', 'consts.h'}
    checker_text = ns.content_for(checker).decode()
    assert '#include "lib.h"' in checker_text
    assert '#include "../common/lib.h"' not in checker_text
    assert '#include "testlib.h"' in checker_text  # builtin, untouched
    lib = next(f for f in ns.files if f.flat_name == 'lib.h')
    assert '#include "consts.h"' in lib.content.decode()  # 2-hop dep rewritten
    assert ns.flat_name_for(checker) == 'check.cpp'


def test_build_flat_namespace_flat_source_is_byte_identical(testing_pkg):
    # A flat source whose only includes are builtins/system headers ships
    # unchanged under its reserved name with no extra files -- the byte-identical
    # regression guard for flat packages (#526). Per-target guards in
    # test_polygon_flatten / test_boca_flatten / test_moj_flatten assert the same
    # invariant through each packager's materialized output.
    original = '#include "testlib.h"\n#include <cstdio>\nint main() { return 0; }\n'
    testing_pkg.add_file('check.cpp').write_text(original)
    checker = CodeItem(path=pathlib.Path('check.cpp'))
    ns = flattening.build_flat_namespace(
        [checker], reserved={pathlib.Path('check.cpp'): 'check.cpp'}
    )
    assert [f.flat_name for f in ns.files] == ['check.cpp']
    assert ns.dep_files() == []
    assert ns.content_for(checker).decode() == original  # byte-for-byte unchanged


def test_build_flat_namespace_ships_manual_compilation_files(testing_pkg):
    # A manual compilationFiles header that the source does NOT #include is still
    # collected and shipped (#526) -- this path is independent of #include
    # auto-discovery.
    testing_pkg.add_file('extra/helper.h').write_text('#pragma once\nint H=1;\n')
    testing_pkg.add_file('check.cpp').write_text('#include "testlib.h"\nint main(){}\n')
    checker = CodeItem(
        path=pathlib.Path('check.cpp'), compilationFiles=['extra/helper.h']
    )
    ns = flattening.build_flat_namespace(
        [checker], reserved={pathlib.Path('check.cpp'): 'check.cpp'}
    )
    assert {f.flat_name for f in ns.files} == {'check.cpp', 'helper.h'}
    helper = next(f for f in ns.files if f.flat_name == 'helper.h')
    assert helper.content.decode() == '#pragma once\nint H=1;\n'


def test_build_flat_namespace_rewrites_to_mangled_names_on_collision(testing_pkg):
    # Two deps share the basename util.h, so both get mangled flat names. The
    # rewritten includes must point at the mangled names -- this fails if the
    # source were shipped verbatim (no rewrite).
    testing_pkg.add_file('x/util.h').write_text('#pragma once\nint X=1;\n')
    testing_pkg.add_file('y/util.h').write_text('#pragma once\nint Y=1;\n')
    testing_pkg.add_file('main.cpp').write_text(
        '#include "x/util.h"\n#include "y/util.h"\nint main(){}\n'
    )
    root = CodeItem(path=pathlib.Path('main.cpp'))
    ns = flattening.build_flat_namespace([root])
    assert {f.flat_name for f in ns.files} == {'main.cpp', 'x__util.h', 'y__util.h'}
    txt = ns.content_for(root).decode()
    assert '"x/util.h"' not in txt and '"y/util.h"' not in txt
    assert '#include "x__util.h"' in txt and '#include "y__util.h"' in txt


def test_build_flat_namespace_reads_out_of_package_root(testing_pkg, tmp_path):
    # A root whose source lives outside the package (like the builtin checker)
    # has only a basename mirror path; its bytes must be read from the real path.
    external = tmp_path / 'builtin_checker.cpp'
    external.write_text('#include "testlib.h"\nint main(){}\n')
    code = CodeItem(path=external)
    ns = flattening.build_flat_namespace(
        [code], reserved={pathlib.Path('builtin_checker.cpp'): 'check.cpp'}
    )
    assert {f.flat_name for f in ns.files} == {'check.cpp'}
    assert ns.content_for(code).decode() == '#include "testlib.h"\nint main(){}\n'


def test_build_flat_namespace_errors_on_unrewritable_crossdir(testing_pkg):
    testing_pkg.add_file('common/helper.py').write_text('x = 1\n')
    # A parent-relative import genuinely resolves to a cross-directory package file
    # (an absolute import would resolve as a sibling of the importing file, which
    # would not exist and so would not trip the guardrail). The Python scanner is
    # non-rewritable, so flattening this source must fail loudly.
    testing_pkg.add_file('gens/g.py').write_text(
        'from ..common.helper import x\nprint(x)\n'
    )
    gen = CodeItem(path=pathlib.Path('gens/g.py'))
    with pytest.raises(typer.Exit):
        flattening.build_flat_namespace([gen])


def test_build_flat_namespace_guards_compilationfile_crossdir(testing_pkg):
    # A non-rewritable source whose manual compilationFiles entry itself pulls in
    # a cross-directory dependency must also fail loudly (the helper would ship
    # incomplete on a flat judge).
    testing_pkg.add_file('other/leaf.py').write_text('y = 2\n')
    testing_pkg.add_file('lib/mid.py').write_text('from ..other.leaf import y\n')
    testing_pkg.add_file('gens/g.py').write_text('print(1)\n')
    gen = CodeItem(path=pathlib.Path('gens/g.py'), compilationFiles=['lib/mid.py'])
    with pytest.raises(typer.Exit):
        flattening.build_flat_namespace([gen])


def test_build_flat_namespace_errors_on_out_of_package_include(testing_pkg):
    # A quoted include that escapes the package root resolves locally (the header
    # exists at the source's real on-disk location) but cannot survive flattening:
    # its target is outside the package, so it is never collected/shipped and the
    # '..' spelling breaks on a flat judge. This must fail loudly, not ship silently
    # broken (the rewritable counterpart of the non-rewritable guardrail).
    outside = testing_pkg.root.parent / 'shared'
    outside.mkdir(parents=True, exist_ok=True)
    (outside / 'lib.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.add_file('checkers/check.cpp').write_text(
        '#include "../../shared/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    checker = CodeItem(path=pathlib.Path('checkers/check.cpp'))
    with pytest.raises(typer.Exit):
        flattening.build_flat_namespace(
            [checker], reserved={pathlib.Path('checkers/check.cpp'): 'check.cpp'}
        )


def test_build_flat_namespace_errors_on_out_of_package_include_in_dep(testing_pkg):
    # The escaping include lives in a transitively-pulled in-package dep, not the
    # root, so the guard must walk the whole rewritable closure.
    outside = testing_pkg.root.parent / 'shared'
    outside.mkdir(parents=True, exist_ok=True)
    (outside / 'other.h').write_text('#pragma once\nint M=1;\n')
    testing_pkg.add_file('common/lib.h').write_text(
        '#pragma once\n#include "../../shared/other.h"\n'
    )
    testing_pkg.add_file('checkers/check.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    checker = CodeItem(path=pathlib.Path('checkers/check.cpp'))
    with pytest.raises(typer.Exit):
        flattening.build_flat_namespace(
            [checker], reserved={pathlib.Path('checkers/check.cpp'): 'check.cpp'}
        )


def test_build_flat_namespace_allows_unresolved_non_parent_include(testing_pkg):
    # A quoted include with no '..' that does not resolve in-package (a builtin or a
    # quoted system header like "bits/stdc++.h") resolves beside the source on the
    # judge and must NOT trip the out-of-package guard -- false-positive guard.
    testing_pkg.add_file('check.cpp').write_text(
        '#include "bits/stdc++.h"\n#include "testlib.h"\nint main(){}\n'
    )
    checker = CodeItem(path=pathlib.Path('check.cpp'))
    ns = flattening.build_flat_namespace(
        [checker], reserved={pathlib.Path('check.cpp'): 'check.cpp'}
    )
    assert {f.flat_name for f in ns.files} == {'check.cpp'}
    # The unresolved system-style include is left untouched.
    assert '#include "bits/stdc++.h"' in ns.content_for(checker).decode()
