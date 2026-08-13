import shutil
import subprocess

import pytest

from rbx.box.dependencies.amalgamation import AmalgamationError, amalgamate


def test_inlines_a_quoted_include(tmp_path):
    (tmp_path / 'lib.h').write_text('int helper();\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "lib.h"\nint main(){}\n')

    result = amalgamate(root)

    text = result.content.decode()
    assert 'int helper();' in text
    assert '#include "lib.h"' not in text
    assert result.inlined[0] == root.resolve()


def test_inlines_a_diamond_only_once(tmp_path):
    (tmp_path / 'base.h').write_text('int base;\n')
    (tmp_path / 'a.h').write_text('#include "base.h"\nint a;\n')
    (tmp_path / 'b.h').write_text('#include "base.h"\nint b;\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "a.h"\n#include "b.h"\nint main(){}\n')

    text = amalgamate(root).content.decode()

    assert text.count('int base;') == 1
    assert 'int a;' in text and 'int b;' in text


def test_drops_pragma_once(tmp_path):
    (tmp_path / 'lib.h').write_text('#pragma once\nint helper();\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "lib.h"\nint main(){}\n')

    assert '#pragma once' not in amalgamate(root).content.decode()


def test_keeps_system_includes(tmp_path):
    root = tmp_path / 'main.cpp'
    root.write_text('#include <vector>\nint main(){}\n')

    assert '#include <vector>' in amalgamate(root).content.decode()


def test_resolves_from_extra_roots(tmp_path):
    builtin = tmp_path / 'builtin'
    builtin.mkdir()
    (builtin / 'testlib.h').write_text('int testlib_marker;\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "testlib.h"\nint main(){}\n')

    result = amalgamate(root, extra_roots=[builtin])

    assert 'int testlib_marker;' in result.content.decode()


def test_errors_on_unresolvable_include(tmp_path):
    root = tmp_path / 'main.cpp'
    root.write_text('#include "nope.h"\nint main(){}\n')

    with pytest.raises(AmalgamationError) as exc:
        amalgamate(root)
    assert 'nope.h' in str(exc.value)
    assert 'main.cpp' in str(exc.value)


def test_keep_predicate_preserves_a_spelling(tmp_path):
    root = tmp_path / 'main.cpp'
    root.write_text('#include "nope.h"\nint main(){}\n')

    result = amalgamate(root, keep=lambda spelling: spelling == 'nope.h')

    assert '#include "nope.h"' in result.content.decode()
    assert result.kept == ['nope.h']


def test_tolerates_include_cycles(tmp_path):
    (tmp_path / 'a.h').write_text('#include "b.h"\nint a;\n')
    (tmp_path / 'b.h').write_text('#include "a.h"\nint b;\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "a.h"\nint main(){}\n')

    text = amalgamate(root).content.decode()

    assert text.count('int a;') == 1
    assert text.count('int b;') == 1


def test_inlines_a_subdirectory_include(tmp_path):
    nested = tmp_path / 'common'
    nested.mkdir()
    (nested / 'lib.h').write_text('int nested_marker;\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "common/lib.h"\nint main(){}\n')

    assert 'int nested_marker;' in amalgamate(root).content.decode()


def test_errors_on_unknown_extension(tmp_path):
    root = tmp_path / 'main.rs'
    root.write_text('fn main() {}\n')

    with pytest.raises(AmalgamationError):
        amalgamate(root)


@pytest.mark.skipif(shutil.which('g++') is None, reason='g++ not available')
def test_amalgamated_output_compiles(tmp_path):
    (tmp_path / 'lib.h').write_text('#pragma once\ninline int helper(){return 7;}\n')
    root = tmp_path / 'main.cpp'
    root.write_text(
        '#include <cstdio>\n#include "lib.h"\nint main(){printf("%d\\n", helper());}\n'
    )

    out = tmp_path / 'amalgamated.cpp'
    out.write_bytes(amalgamate(root).content)

    proc = subprocess.run(
        ['g++', '-std=gnu++17', '-o', str(tmp_path / 'a.out'), str(out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
