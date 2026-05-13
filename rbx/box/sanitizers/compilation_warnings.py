from typing import Dict, List, Optional

from rbx.grading.steps import PreprocessLog


class CompilationWarningSummarizer:
    """Turns the compiler logs that produced warnings into a short, single-line
    summary to show next to the ``WARNINGS`` status in the compilation live view.

    The base implementation returns ``None`` (no extra line). Language-specific
    subclasses register themselves in ``_SUMMARIZERS``.
    """

    def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
        return None


_DEFAULT_SUMMARIZER = CompilationWarningSummarizer()

# Per-language summarizers register here, keyed by the language name returned by
# ``rbx.box.code.find_language_name``. A C++ summarizer that extracts concise
# lines from GCC/clang output is deferred to a separate issue (see issue #397 /
# the linked follow-up) and should be brainstormed before implementing.
_SUMMARIZERS: Dict[str, CompilationWarningSummarizer] = {}


def get_compilation_warning_summarizer(language: str) -> CompilationWarningSummarizer:
    return _SUMMARIZERS.get(language, _DEFAULT_SUMMARIZER)
