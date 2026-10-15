"""The published statement build report (#909).

``<package>/.rbx/statements/report.yml``: which statement outputs exist, where,
whether the last build of each failed, and why -- located in the files the
setter edits. It is what lets an editor preview a statement and put its errors
on the right line without knowing how rbx names outputs, stages overlays or
words its LaTeX log.

A published contract, under the same rules as the run report
(``rbx/box/run_report.py``):

- **Structured, never rendered.** Enum values, paths, line numbers, seconds.
- **Read off, never recomputed.** Locations come from the build's own source
  map (:mod:`rbx.box.statements.sourcemap`); a reader never re-derives one.
- **Versioned.** Bump ``REPORT_VERSION`` when an older reader would misread the
  file. Readers ignore versions they do not know.

One entry per output, upserted by :meth:`StatementOutput.key` when its build
finishes, so building ``en`` leaves ``pt``'s entry alone. Paths are relative to
the package root when inside it, absolute otherwise (the bundled preset's
template, say). The report lives in the cache dir, so ``rbx clear`` forgets it
with everything else.

See ``docs/plans/2026-10-15-statement-preview-design.md``.
"""

import contextlib
import datetime
import enum
import pathlib
import time
from typing import Iterator, List, Optional, Tuple

import jinja2
import yaml
from pydantic import BaseModel, ValidationError

from rbx import console, utils
from rbx.box.exception import describe_exception
from rbx.box.statements import sourcemap
from rbx.box.statements.latex import LatexCompilationError
from rbx.config import CACHE_DIR_NAME

REPORT_VERSION = 1


class FindingOrigin(str, enum.Enum):
    LATEX = 'latex'
    TEMPLATE = 'template'
    BUILD = 'build'


class Severity(str, enum.Enum):
    ERROR = 'error'
    WARNING = 'warning'


class StatementFinding(BaseModel):
    origin: FindingOrigin
    severity: Severity = Severity.ERROR
    message: str
    # Absent when nothing locates it; a reader shows it on `source`.
    file: Optional[str] = None
    line: Optional[int] = None  # 1-based
    # The text TeX was reading when it stopped.
    context: Optional[str] = None


class OutputStatus(str, enum.Enum):
    OK = 'ok'
    FAILED = 'failed'


class StatementOutput(BaseModel):
    kind: str  # statement | tutorial | document
    # The contest statement/document name; problem statements have none.
    name: Optional[str] = None
    language: Optional[str] = None
    variant: Optional[str] = None
    format: str  # the output's extension: pdf | tex | md
    path: str
    source: Optional[str] = None
    status: OutputStatus
    builtAt: datetime.datetime
    seconds: float
    findings: List[StatementFinding] = []
    # The full pdflatex log of the last compile, while the overlay keeps it.
    log: Optional[str] = None

    def key(self) -> Tuple[str, Optional[str], Optional[str], Optional[str], str]:
        return (self.kind, self.name, self.language, self.variant, self.format)


class StatementBuildReport(BaseModel):
    version: int = REPORT_VERSION
    outputs: List[StatementOutput] = []


def report_path(root: pathlib.Path) -> pathlib.Path:
    return root / CACHE_DIR_NAME / 'statements' / 'report.yml'


def read_report(path: pathlib.Path) -> StatementBuildReport:
    """The report at ``path``; empty when absent, unreadable or of another
    version -- an entry this process cannot read is one it cannot upsert."""
    try:
        data = yaml.safe_load(path.read_text())
        if isinstance(data, dict) and data.get('version') == REPORT_VERSION:
            return StatementBuildReport.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError):
        pass
    return StatementBuildReport()


def record(root: pathlib.Path, output: StatementOutput) -> None:
    """Upsert ``output`` into the package's report, atomically: the editor may be
    reading it, and a half-written file parses."""
    path = report_path(root)
    report = read_report(path)
    outputs = [o for o in report.outputs if o.key() != output.key()]
    outputs.append(output)
    report.outputs = sorted(outputs, key=lambda o: [str(k) for k in o.key()])
    utils.write_text_atomic(
        path,
        yaml.safe_dump(
            report.model_dump(mode='json', exclude_none=True),
            sort_keys=False,
            allow_unicode=True,
        ),
    )


def _rel(root: pathlib.Path, path: pathlib.Path) -> str:
    absolute = utils.abspath(path)
    try:
        return absolute.relative_to(utils.abspath(root)).as_posix()
    except ValueError:
        return str(absolute)


def _jinja_error(exc: BaseException) -> Optional[jinja2.TemplateError]:
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, jinja2.TemplateError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _finding(
    root: pathlib.Path,
    origin: FindingOrigin,
    message: str,
    pos: Optional[sourcemap.SourcePos],
    context: Optional[str] = None,
) -> StatementFinding:
    return StatementFinding(
        origin=origin,
        message=message,
        file=_rel(root, pos.path) if pos is not None else None,
        line=pos.line if pos is not None else None,
        context=context,
    )


def findings_for(
    root: pathlib.Path, exc: BaseException, tracker: sourcemap.SourceTracker
) -> List[StatementFinding]:
    """What went wrong, located in the setter's files where the map allows."""
    if isinstance(exc, LatexCompilationError):
        return [
            _finding(
                root,
                FindingOrigin.LATEX,
                error.message,
                tracker.locate(exc.cwd / error.file, error.line)
                if error.file is not None and error.line is not None
                else None,
                error.context,
            )
            for error in exc.errors
        ] or [_finding(root, FindingOrigin.LATEX, 'pdflatex failed.', None)]
    template_error = _jinja_error(exc)
    if template_error is not None:
        message = template_error.message or type(template_error).__name__
        return [
            _finding(
                root,
                FindingOrigin.TEMPLATE,
                message,
                tracker.locate_template_error(exc),
            )
        ]
    return [_finding(root, FindingOrigin.BUILD, describe_exception(exc), None)]


def _print_findings(findings: List[StatementFinding]) -> None:
    """The located errors, one line each, the way compilers print them -- which
    terminals (VS Code's among them) turn into links to the source line. The
    unlocated ones were already printed by whatever raised them."""
    for finding in findings:
        if finding.file is None or finding.line is None:
            continue
        where = utils.escape_markup(f'{finding.file}:{finding.line}:')
        message = utils.escape_markup(finding.message)
        console.console.print(f'[error]{where}[/error] {message}', highlight=False)


@contextlib.contextmanager
def recording(
    root: pathlib.Path,
    *,
    kind: str,
    output: pathlib.Path,
    source: Optional[pathlib.Path] = None,
    name: Optional[str] = None,
    language: Optional[str] = None,
    variant: Optional[str] = None,
    log: Optional[pathlib.Path] = None,
) -> Iterator[sourcemap.SourceTracker]:
    """Build one statement output inside the block, then publish how it went.

    The block runs under :func:`sourcemap.tracking`; it registers what it stages
    on the yielded tracker's ``origins``, which is how a failure is located.
    """
    started = time.monotonic()
    built_at = datetime.datetime.now(datetime.timezone.utc)

    def publish(status: OutputStatus, findings: List[StatementFinding]) -> None:
        record(
            root,
            StatementOutput(
                kind=kind,
                name=name,
                language=language,
                variant=variant,
                format=output.name.rsplit('.', 1)[-1],
                path=_rel(root, output),
                source=_rel(root, source) if source is not None else None,
                status=status,
                builtAt=built_at,
                seconds=round(time.monotonic() - started, 3),
                findings=findings,
                log=_rel(root, log) if log is not None and log.is_file() else None,
            ),
        )

    with sourcemap.tracking() as tracker:
        if source is not None:
            tracker.origins.source(source)
        try:
            yield tracker
        except Exception as exc:
            findings = findings_for(root, exc, tracker)
            _print_findings(findings)
            publish(OutputStatus.FAILED, findings)
            raise
    publish(OutputStatus.OK, [])
