import dataclasses
import re
from collections import Counter
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple

from rbx import utils
from rbx.grading.steps import (
    PreprocessLog,
    _is_first_party_warning_file,
    get_exe_from_command,
    is_cxx_command,
)

if TYPE_CHECKING:
    from rbx.box.parallel.live_tasks import CompilationTask


@dataclasses.dataclass(frozen=True)
class _ParsedWarning:
    file: str
    line: int
    flag: Optional[str]
    msg: str


_CPP_WARNING_RE = re.compile(
    r'^(?P<file>[^:\n]+):(?P<line>\d+):(?:\d+:)?\s+warning:\s+'
    r'(?P<msg>.*?)(?:\s+\[(?P<flag>-W[^\]]+)\])?\s*$'
)


def _parse_cpp_warnings(log: str) -> List[_ParsedWarning]:
    results: List[_ParsedWarning] = []
    for raw_line in log.splitlines():
        line = utils.strip_ansi_codes(raw_line).rstrip()
        if not line or line.startswith('./'):
            continue
        match = _CPP_WARNING_RE.match(line)
        if match is None:
            continue
        file = match.group('file').strip()
        if not _is_first_party_warning_file(file):
            continue
        results.append(
            _ParsedWarning(
                file=file,
                line=int(match.group('line')),
                flag=match.group('flag'),
                msg=match.group('msg').strip(),
            )
        )
    return results


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


class CppCompilationWarningSummarizer(CompilationWarningSummarizer):
    _UNFLAGGED = '<unflagged>'

    def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
        seen = set()
        parsed: List[_ParsedWarning] = []
        for log in logs:
            for w in _parse_cpp_warnings(log.log):
                key = (w.file, w.line, w.flag, w.msg)
                if key in seen:
                    continue
                seen.add(key)
                parsed.append(w)

        if not parsed:
            return None

        counts = Counter(w.flag or self._UNFLAGGED for w in parsed)
        ordered = sorted(
            counts.items(),
            key=lambda kv: (-kv[1], kv[0] == self._UNFLAGGED, kv[0]),
        )

        def _render(flag: str, count: int) -> str:
            if flag == self._UNFLAGGED:
                return f'{count} warnings' if count != 1 else '1 warning'
            return f'{count}× {flag}'

        head = ordered[:2]
        rendered = ', '.join(_render(f, c) for f, c in head)
        remaining = len(ordered) - len(head)
        if remaining > 0:
            rendered += f' (+{remaining} more)'
        return rendered


def apply_warning_status(task: 'CompilationTask') -> None:
    """If ``task.item`` compiled with warnings (per the warning stack), flip the
    task to ``WARNINGS`` and attach a compiler-specific summary line.
    """
    # Lazy imports avoid an import cycle: ``live_tasks`` and ``warning_stack``
    # both transitively depend on this module, so they cannot be hoisted to
    # module scope.
    from rbx.box.parallel.live_tasks import CompilationStatus
    from rbx.box.sanitizers import warning_stack

    stack = warning_stack.get_warning_stack()
    if task.item.path not in stack.warnings:
        return

    logs = stack.warning_logs.get(task.item.path, [])
    warning_logs = [log for log in logs if log.warnings]
    if not warning_logs:
        return

    task.status = CompilationStatus.WARNINGS
    summarizer = get_compilation_warning_summarizer_for(warning_logs[0].cmd)
    task.warning_summary = summarizer.summarize(warning_logs)


register(is_cxx_command, CppCompilationWarningSummarizer())
