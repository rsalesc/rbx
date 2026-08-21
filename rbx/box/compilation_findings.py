"""What the compile phase has to say about each solution, as a fact on disk.

``rbx run`` already knows all of this -- ``WarningStack`` holds the compiler
logs of every first-party file that warned, and a solution that fails to
compile raises ``CompilationError`` -- but it only ever *prints* it. A reader
of ``.rbx/runs`` therefore cannot tell a solution that failed to compile from
one that was never declared: the failed one is filtered out of the skeleton's
``solutions`` (see ``_get_compiled_solutions_for_skeleton``) and vanishes.

This module turns those two facts into records that ride on the skeleton, and
writes the compiler output itself to a file beside it. The output does not go
into the YAML on purpose: it is unbounded -- a template error is a screenful
per line -- and the skeleton is parsed in full by every reader.

See ``docs/plans/2026-08-20-vscode-compilation-findings-design.md``.
"""

import pathlib
from typing import Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel

from rbx import utils
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.grading.steps import CompilationError, PreprocessLog

COMPILATION_DIR = 'compilation'


class CompilationWarning(BaseModel):
    """One warning the compiler emitted, as the summarizer parsed it."""

    file: str
    line: int
    # Absent for a warning the compiler did not attribute to a flag.
    flag: Optional[str] = None
    msg: str


class SolutionCompilation(BaseModel):
    """What the compile phase produced for one solution worth reporting on.

    Only solutions with something to report get a record: a package whose
    solutions all compiled cleanly contributes an empty list.
    """

    path: pathlib.Path
    # The declaration, carried here because a solution that failed to compile is
    # absent from ``SolutionReportSkeleton.solutions`` and a reader still has to
    # be able to draw it the way it draws every other solution.
    outcome: ExpectedOutcome
    status: Literal['WARNINGS', 'FAILED']
    # Relative to the runs dir, e.g. ``compilation/0.log``. Relative so a
    # package read on another host (or moved since the run) still resolves it.
    log: pathlib.Path
    warnings: List[CompilationWarning] = []
    # Why the compilation failed, when there is a one-line answer:
    # "'g++' was not found". Never set for a warning record.
    reason: Optional[str] = None


def _parsed_warnings_for(logs: Sequence[PreprocessLog]) -> List[CompilationWarning]:
    # Lazy import: ``compilation_warnings`` lazy-imports back into the sanitizer
    # package, and hoisting this to module scope reintroduces that cycle.
    from rbx.box.sanitizers import compilation_warnings

    warning_logs = [log for log in logs if log.warnings]
    if not warning_logs:
        return []
    summarizer = compilation_warnings.get_compilation_warning_summarizer_for(
        warning_logs[0].cmd
    )
    return [
        CompilationWarning(file=w.file, line=w.line, flag=w.flag, msg=w.msg)
        for w in summarizer.parse(warning_logs)
    ]


def _log_text(logs: Sequence[PreprocessLog]) -> str:
    # ANSI is stripped here rather than at the source: rbx sets CLICOLOR_FORCE
    # so the *console* gets a coloured error, and the same bytes in an editor
    # tab would be a screenful of escape sequences.
    return '\n'.join(utils.strip_ansi_codes(log.log) for log in logs)


def _failure_text(exception: BaseException) -> str:
    logs = getattr(exception, 'logs', None)
    if logs:
        return _log_text(logs)
    # No compiler ran -- the compiler itself was not found, say -- so the only
    # account of the failure is what the exception printed.
    return utils.strip_ansi_codes(str(exception))


def _failure_reason(exception: BaseException) -> Optional[str]:
    if isinstance(exception, CompilationError) and exception.not_found_executable:
        return f"'{exception.not_found_executable}' was not found"
    return None


def build_solution_compilations(
    solutions: Sequence[Solution],
    failures: Dict[pathlib.Path, BaseException],
    runs_dir: pathlib.Path,
) -> List[SolutionCompilation]:
    """Records for every solution the compile phase has something to say about.

    Declaration order is preserved, and the index of a record in the returned
    list is the name of its log file -- so the two cannot drift.

    ``runs_dir`` must already exist: this is called right after the skeleton's
    directory is prepared, which is after the wipe that marks a new run.
    """
    from rbx.box.sanitizers import warning_stack

    stack = warning_stack.get_warning_stack()

    records: List[SolutionCompilation] = []
    for solution in solutions:
        path = pathlib.Path(solution.path)
        if path in failures:
            status: Literal['WARNINGS', 'FAILED'] = 'FAILED'
            text = _failure_text(failures[path])
            warnings: List[CompilationWarning] = []
            reason = _failure_reason(failures[path])
        else:
            logs = stack.warning_logs.get(path, [])
            warnings = _parsed_warnings_for(logs)
            if not warnings:
                # Compiled cleanly, or warned in a language whose compiler has
                # no parser here -- either way there is nothing to draw.
                continue
            status = 'WARNINGS'
            text = _log_text([log for log in logs if log.warnings])
            reason = None

        log_path = pathlib.Path(COMPILATION_DIR) / f'{len(records)}.log'
        destination = runs_dir / log_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text)

        records.append(
            SolutionCompilation(
                path=path,
                outcome=solution.outcome,
                status=status,
                log=log_path,
                warnings=warnings,
                reason=reason,
            )
        )
    return records
