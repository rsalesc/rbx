from typing import List, Optional

from rbx.box.sanitizers import compilation_warnings as cw
from rbx.grading.steps import PreprocessLog


class _Dummy(cw.CompilationWarningSummarizer):
    def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
        return 'dummy'


def test_default_summarizer_when_no_match():
    s = cw.get_compilation_warning_summarizer_for(['python3', 'foo.py'])
    assert s.summarize([]) is None


def test_default_summarizer_when_cmd_empty():
    s = cw.get_compilation_warning_summarizer_for([])
    assert s.summarize([]) is None


def test_predicate_dispatch(monkeypatch):
    monkeypatch.setattr(cw, '_SUMMARIZERS', [(lambda exe: 'g++' in exe, _Dummy())])
    assert (
        cw.get_compilation_warning_summarizer_for(['g++', 'foo.cpp']).summarize([])
        == 'dummy'
    )
    assert cw.get_compilation_warning_summarizer_for(['python3']).summarize([]) is None


def test_dispatch_uses_first_match(monkeypatch):
    a = _Dummy()
    b = _Dummy()
    monkeypatch.setattr(
        cw,
        '_SUMMARIZERS',
        [
            (lambda exe: 'clang' in exe, a),
            (lambda exe: True, b),
        ],
    )
    assert cw.get_compilation_warning_summarizer_for(['/usr/bin/clang++']) is a
    assert cw.get_compilation_warning_summarizer_for(['python3']) is b
