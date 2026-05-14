from rbx.box.sanitizers.compilation_warnings import (
    CompilationWarningSummarizer,
    get_compilation_warning_summarizer_for,
)
from rbx.grading.steps import PreprocessLog


def _log() -> PreprocessLog:
    return PreprocessLog(
        cmd=['g++', 'a.cpp'], log='a.cpp:1:1: warning: x', warnings=True
    )


def test_base_summarizer_returns_none():
    assert CompilationWarningSummarizer().summarize([_log()]) is None


def test_get_summarizer_returns_base_when_no_match():
    summarizer = get_compilation_warning_summarizer_for(['python3', 'foo.py'])
    assert isinstance(summarizer, CompilationWarningSummarizer)
    assert summarizer.summarize([_log()]) is None
