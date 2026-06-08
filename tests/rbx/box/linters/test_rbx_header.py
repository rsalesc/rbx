from rbx.box.linters.cpp.rbx_header import RbxHeaderLinter
from rbx.box.linters.linter import LinterSeverity
from rbx.box.schema import CodeItem


def _lint(src: str):
    return RbxHeaderLinter().lint(CodeItem(path='gen.cpp'), src)


def test_quoted_include_is_flagged():
    msgs = _lint('#include "rbx.h"\nint main() {}\n')
    assert len(msgs) == 1
    assert msgs[0].severity is LinterSeverity.ERROR


def test_angled_include_is_flagged():
    assert len(_lint('#include <rbx.h>\nint main() {}\n')) == 1


def test_include_with_subdir_basename_is_flagged():
    assert len(_lint('#include "sub/rbx.h"\nint main() {}\n')) == 1


def test_other_includes_are_ignored():
    src = '#include <bits/stdc++.h>\n#include "testlib.h"\nint main() {}\n'
    assert _lint(src) == []


def test_no_include_is_ok():
    assert _lint('int main() { return 0; }\n') == []


def test_message_has_location_and_hints():
    msgs = _lint('\n#include "rbx.h"\nint main() {}\n')
    assert msgs[0].line == 2
    assert msgs[0].col is not None
    # Both escape hatches and the docs link are surfaced.
    assert 'rbx-header-linter: disable' in msgs[0].message
    assert 'env.rbx.yml' in msgs[0].message
    assert 'rbx.rsalesc.dev/generators-and-rbx-h' in msgs[0].message


def test_multiple_includes_yield_multiple_messages():
    src = '#include "rbx.h"\n#include <rbx.h>\nint main() {}\n'
    assert len(_lint(src)) == 2


def test_string_literal_mentioning_rbx_h_is_not_flagged():
    # A string that contains the text must not be detected as an include.
    assert _lint('const char* s = "#include \\"rbx.h\\"";\nint main(){}\n') == []
