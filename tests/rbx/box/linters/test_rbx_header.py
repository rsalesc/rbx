from rbx.box.linters.cpp.rbx_header import RbxHeaderLinter
from rbx.box.linters.linter import LinterSeverity
from rbx.box.schema import CodeItem, Grader


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


# Graders: rbx.h must come after every task header beside the grader.


def _lint_grader(tmp_path, src: str):
    (tmp_path / 'task.h').write_text('int f();\n')
    grader = Grader(path=tmp_path / 'grader.cpp', secret='s3cr3t')
    return RbxHeaderLinter().lint(grader, src)


def test_grader_including_rbx_h_after_the_task_header_is_ok(tmp_path):
    src = '#include <cstdio>\n#include "task.h"\n#include "rbx.h"\n'
    assert _lint_grader(tmp_path, src) == []


def test_grader_including_rbx_h_before_the_task_header_is_flagged(tmp_path):
    msgs = _lint_grader(tmp_path, '#include "rbx.h"\n#include "task.h"\n')
    assert len(msgs) == 1
    assert msgs[0].severity is LinterSeverity.ERROR
    assert msgs[0].line == 1
    assert '"task.h"' in msgs[0].message


def test_grader_rbx_h_before_task_header_inside_a_conditional(tmp_path):
    src = '#ifndef X\n#include "rbx.h"\n#endif\n#include "task.h"\n'
    assert len(_lint_grader(tmp_path, src)) == 1


def test_grader_may_include_rbx_h_before_builtin_or_system_headers(tmp_path):
    src = '#include "rbx.h"\n#include "testlib.h"\n#include <vector>\n'
    assert _lint_grader(tmp_path, src) == []


def test_grader_ignores_quoted_headers_that_are_not_beside_it(tmp_path):
    src = '#include "rbx.h"\n#include "bits/stdc++.h"\n'
    assert _lint_grader(tmp_path, src) == []


def test_grader_without_rbx_h_is_ok(tmp_path):
    assert _lint_grader(tmp_path, '#include "task.h"\n') == []


def test_generator_rule_does_not_apply_to_graders(tmp_path):
    # A grader including rbx.h is the norm, not an error.
    assert _lint_grader(tmp_path, '#include "rbx.h"\nint main() {}\n') == []
