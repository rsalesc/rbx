from rbx.box.sanitizers.compilation_warnings import (
    CppCompilationWarningSummarizer,
    get_compilation_warning_summarizer_for,
)
from rbx.grading.steps import PreprocessLog


def _log(stderr: str, cmd=None) -> PreprocessLog:
    return PreprocessLog(
        cmd=cmd or ['g++', 'sol.cpp', '-o', 'sol'],
        log=stderr,
        warnings=True,
    )


def test_empty_logs_returns_none():
    s = CppCompilationWarningSummarizer()
    assert s.summarize([]) is None


def test_all_filtered_returns_none():
    s = CppCompilationWarningSummarizer()
    stderr = "testlib.h:1:1: warning: unused parameter 'n' [-Wunused-parameter]\n"
    assert s.summarize([_log(stderr)]) is None


def test_single_flag():
    s = CppCompilationWarningSummarizer()
    stderr = (
        "sol.cpp:1:1: warning: unused variable 'x' [-Wunused-variable]\n"
        "sol.cpp:2:1: warning: unused variable 'y' [-Wunused-variable]\n"
    )
    assert s.summarize([_log(stderr)]) == '2× -Wunused-variable'


def test_unflagged_warnings_bucket():
    s = CppCompilationWarningSummarizer()
    stderr = (
        'sol.cpp:1:1: warning: control reaches end of non-void function\n'
        'sol.cpp:2:1: warning: control reaches end of non-void function\n'
    )
    assert s.summarize([_log(stderr)]) == '2 warnings'


def test_two_flags_sorted_by_count_then_name():
    s = CppCompilationWarningSummarizer()
    stderr = (
        "sol.cpp:1:1: warning: unused variable 'x' [-Wunused-variable]\n"
        "sol.cpp:2:1: warning: unused variable 'y' [-Wunused-variable]\n"
        'sol.cpp:3:1: warning: sign compare [-Wsign-compare]\n'
    )
    assert s.summarize([_log(stderr)]) == '2× -Wunused-variable, 1× -Wsign-compare'


def test_three_or_more_flags_appends_overflow():
    s = CppCompilationWarningSummarizer()
    stderr = (
        'sol.cpp:1:1: warning: a [-Wfoo]\n'
        'sol.cpp:2:1: warning: a [-Wfoo]\n'
        'sol.cpp:3:1: warning: b [-Wbar]\n'
        'sol.cpp:4:1: warning: c [-Wbaz]\n'
    )
    assert s.summarize([_log(stderr)]) == '2× -Wfoo, 1× -Wbar (+1 more)'


def test_dedup_across_logs():
    s = CppCompilationWarningSummarizer()
    stderr = "sol.cpp:5:9: warning: unused variable 'x' [-Wunused-variable]\n"
    assert s.summarize([_log(stderr), _log(stderr)]) == '1× -Wunused-variable'


def test_registered_for_cxx_commands():
    s_gpp = get_compilation_warning_summarizer_for(['g++', 'sol.cpp'])
    s_clangpp = get_compilation_warning_summarizer_for(['/usr/bin/clang++', 'sol.cpp'])
    s_gcc = get_compilation_warning_summarizer_for(['gcc', 'sol.c'])
    s_py = get_compilation_warning_summarizer_for(['python3', 'sol.py'])
    assert isinstance(s_gpp, CppCompilationWarningSummarizer)
    assert isinstance(s_clangpp, CppCompilationWarningSummarizer)
    assert isinstance(s_gcc, CppCompilationWarningSummarizer)
    assert not isinstance(s_py, CppCompilationWarningSummarizer)


def test_dedup_keeps_distinct_messages_at_same_location():
    # Same (file, line, flag) but different messages — must NOT collapse.
    s = CppCompilationWarningSummarizer()
    stderr = (
        "sol.cpp:1:1: warning: unused variable 'x' [-Wunused-variable]\n"
        "sol.cpp:1:1: warning: unused variable 'y' [-Wunused-variable]\n"
    )
    assert s.summarize([_log(stderr)]) == '2× -Wunused-variable'
