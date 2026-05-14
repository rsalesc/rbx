from typing import TYPE_CHECKING, Callable, List, Optional, Tuple

from rbx.grading.steps import PreprocessLog, get_exe_from_command

if TYPE_CHECKING:
    from rbx.box.parallel.live_tasks import CompilationTask


class CompilationWarningSummarizer:
    """Turns the compiler logs that produced warnings into a short, single-line
    summary to show next to the ``WARNINGS`` status in the compilation live view.

    The base implementation returns ``None`` (no extra line). Compiler-specific
    subclasses register themselves in ``_SUMMARIZERS`` via :func:`register`,
    keyed by a predicate over the compiler executable string.
    """

    def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
        return None


_DEFAULT_SUMMARIZER = CompilationWarningSummarizer()

# Ordered list of (predicate, summarizer). Predicates run against the
# executable portion of ``log.cmd`` (see :func:`get_exe_from_command`).
_SUMMARIZERS: List[Tuple[Callable[[str], bool], CompilationWarningSummarizer]] = []


def register(
    predicate: Callable[[str], bool], summarizer: CompilationWarningSummarizer
) -> None:
    _SUMMARIZERS.append((predicate, summarizer))


def get_compilation_warning_summarizer_for(
    cmd: List[str],
) -> CompilationWarningSummarizer:
    if not cmd:
        return _DEFAULT_SUMMARIZER
    exe = get_exe_from_command(' '.join(cmd))
    if exe:
        for predicate, summarizer in _SUMMARIZERS:
            if predicate(exe):
                return summarizer
    return _DEFAULT_SUMMARIZER


def apply_warning_status(task: 'CompilationTask') -> None:
    """If ``task.item`` compiled with warnings (per the warning stack), flip the
    task to ``WARNINGS`` and attach a compiler-specific summary line.
    """
    from rbx.box.parallel.live_tasks import CompilationStatus
    from rbx.box.sanitizers import warning_stack

    stack = warning_stack.get_warning_stack()
    if task.item.path not in stack.warnings:
        return
    task.status = CompilationStatus.WARNINGS

    logs = stack.warning_logs.get(task.item.path, [])
    warning_logs = [log for log in logs if log.warnings]
    if not warning_logs:
        return
    summarizer = get_compilation_warning_summarizer_for(warning_logs[0].cmd)
    task.warning_summary = summarizer.summarize(warning_logs)
