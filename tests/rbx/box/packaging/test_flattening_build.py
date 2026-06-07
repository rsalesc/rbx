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
