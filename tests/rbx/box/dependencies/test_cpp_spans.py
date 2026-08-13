from rbx.box.dependencies.cpp import CppScanner


def test_reference_spans_covers_whole_directive():
    text = 'int a;\n#include "lib.h"\nint b;\n'
    spans = CppScanner().reference_spans(text)
    assert len(spans) == 1
    start, end, spelling = spans[0]
    assert spelling == 'lib.h'
    assert text[start:end].strip() == '#include "lib.h"'


def test_reference_spans_skips_system_includes():
    text = '#include <vector>\n#include "lib.h"\n'
    spans = CppScanner().reference_spans(text)
    assert [s[2] for s in spans] == ['lib.h']


def test_reference_spans_are_sorted_and_disjoint():
    text = '#include "a.h"\n#include "b.h"\n#include "c.h"\n'
    spans = CppScanner().reference_spans(text)
    assert [s[2] for s in spans] == ['a.h', 'b.h', 'c.h']
    for (_, prev_end, _), (next_start, _, _) in zip(spans, spans[1:]):
        assert prev_end <= next_start


def test_cpp_scanner_can_splice():
    assert CppScanner.can_splice is True
