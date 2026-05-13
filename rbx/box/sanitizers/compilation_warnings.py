from typing import TYPE_CHECKING, Dict, List, Optional

from rbx.grading.steps import PreprocessLog

if TYPE_CHECKING:
    from rbx.box.parallel.live_tasks import CompilationTask


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
# lines from GCC/clang output is deferred to a separate issue (#446) and should
# be brainstormed before implementing.
_SUMMARIZERS: Dict[str, CompilationWarningSummarizer] = {}


def get_compilation_warning_summarizer(language: str) -> CompilationWarningSummarizer:
    return _SUMMARIZERS.get(language, _DEFAULT_SUMMARIZER)


def apply_warning_status(task: 'CompilationTask') -> None:
    """If ``task.item`` compiled with warnings (per the warning stack), flip the
    task to ``WARNINGS`` and attach a language-specific summary line.

    The cross-module imports are intentionally done lazily inside the function
    body to avoid an import cycle (``live_tasks.py`` must not import ``code.py``
    or ``warning_stack``).
    """
    from rbx.box.code import find_language_name
    from rbx.box.parallel.live_tasks import CompilationStatus
    from rbx.box.sanitizers import warning_stack

    stack = warning_stack.get_warning_stack()
    if task.item.path not in stack.warnings:
        return
    task.status = CompilationStatus.WARNINGS
    logs = stack.warning_logs.get(task.item.path, [])
    language = find_language_name(task.item)
    task.warning_summary = get_compilation_warning_summarizer(language).summarize(logs)
