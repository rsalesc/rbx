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
