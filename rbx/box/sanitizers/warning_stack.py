import functools
import pathlib
import shutil
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Set, Tuple

from rbx import console, utils
from rbx.box.formatting import href
from rbx.box.schema import CodeItem
from rbx.config import CACHE_DIR_NAME
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.steps import GradingFileOutput, PreprocessLog

if TYPE_CHECKING:
    from rbx.box.linters.asset_kind import AssetKind
    from rbx.box.linters.linter import LinterMessage
    from rbx.box.testset_findings import DuplicateTest


WARNINGS_DIR_NAME = 'warnings'


def sanitizer_log_name(path: pathlib.Path) -> pathlib.Path:
    """The name a first-party file's sanitizer log is kept under.

    Public, and pure, so the reader side resolves a log exactly the way the
    writer side put it there: `rbx issues` links these logs off a `report.yml`
    that records only that a sanitizer fired, so it has to rebuild the name from
    the solution's path. A second copy of the rule would be a second thing to
    keep in step.
    """
    return path.with_suffix(path.suffix + '.log')


class WarningStack:
    def __init__(self, root: pathlib.Path):
        self.root = root
        # Every file with something to say: compiler warnings, linter messages
        # or both.
        self.warnings = set()
        # The files the *compiler* warned about -- a subset of `warnings`, which
        # also holds the files only a linter flagged.
        self.compiler_warnings: Set[pathlib.Path] = set()
        self.warning_logs: Dict[pathlib.Path, List[PreprocessLog]] = {}
        self.sanitizer_warnings = {}
        self.linter_warnings: Dict[pathlib.Path, List['LinterMessage']] = {}
        # What role each file played, when the caller knew: the run turns these
        # facts into issues, and a validator's warning is worded and coded
        # differently from a solution's.
        self.kinds: Dict[pathlib.Path, 'AssetKind'] = {}
        # Tests that repeat an earlier one, in the order the build met them.
        self.duplicate_tests: List['DuplicateTest'] = []
        # Paths whose compiler warnings / linter messages / sanitizer findings
        # another report already showed in this process -- the issues section
        # at the end of `rbx run` (#968). The stack still records them, so the
        # live view and the run's compilation records read the same facts; it
        # just does not print them a second time.
        self.reported_compilation: Set[pathlib.Path] = set()
        self.reported_linter: Set[pathlib.Path] = set()
        self.reported_sanitizer: Set[pathlib.Path] = set()
        self.reported_duplicates = False

    def mark_reported(
        self,
        compilation: Iterable[pathlib.Path] = (),
        linter: Iterable[pathlib.Path] = (),
        sanitizer: Iterable[pathlib.Path] = (),
        duplicates: bool = False,
    ) -> None:
        """Leave these out of the report: something else already said it."""
        self.reported_compilation.update(compilation)
        self.reported_linter.update(linter)
        self.reported_sanitizer.update(sanitizer)
        self.reported_duplicates = self.reported_duplicates or duplicates

    def add_duplicate_test(self, duplicate: 'DuplicateTest') -> None:
        # A command can build the testset more than once in a process.
        if duplicate not in self.duplicate_tests:
            self.duplicate_tests.append(duplicate)

    def unreported_duplicate_tests(self) -> List['DuplicateTest']:
        return [] if self.reported_duplicates else list(self.duplicate_tests)

    def shows_compiler_warnings(self, path: pathlib.Path) -> bool:
        return path in self.compiler_warnings and path not in self.reported_compilation

    def shows_linter_warnings(self, path: pathlib.Path) -> bool:
        return bool(self.linter_warnings.get(path)) and path not in self.reported_linter

    def unreported_warnings(self) -> List[pathlib.Path]:
        """The files with something left to show once other reports had their say."""
        return sorted(
            path
            for path in self.warnings
            if self.shows_compiler_warnings(path) or self.shows_linter_warnings(path)
        )

    def unreported_sanitizer_warnings(self) -> List[pathlib.Path]:
        return sorted(
            path
            for path in self.sanitizer_warnings
            if path not in self.reported_sanitizer
        )

    def _remember_kind(self, code: CodeItem, kind: Optional['AssetKind']) -> None:
        if kind is not None:
            self.kinds[code.path] = kind

    def add_warning(
        self,
        code: CodeItem,
        logs: Optional[List[PreprocessLog]] = None,
        kind: Optional['AssetKind'] = None,
    ):
        self.warnings.add(code.path)
        self.compiler_warnings.add(code.path)
        self._remember_kind(code, kind)
        if logs:
            self.warning_logs[code.path] = logs

    async def add_sanitizer_warning(
        self, cacher: FileCacher, code: CodeItem, reference: GradingFileOutput
    ):
        if code.path in self.sanitizer_warnings:
            return
        dest_path = _get_warning_runs_dir(self.root).joinpath(
            sanitizer_log_name(code.path)
        )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        f = await reference.get_file(cacher)
        if f is None:
            return
        with f:
            with dest_path.open('wb') as fout:
                shutil.copyfileobj(f, fout)
        self.sanitizer_warnings[code.path] = dest_path

    def add_linter_warning(
        self,
        code: CodeItem,
        messages: List['LinterMessage'],
        kind: Optional['AssetKind'] = None,
    ) -> None:
        if not messages:
            return
        self.warnings.add(code.path)
        self._remember_kind(code, kind)
        self.linter_warnings.setdefault(code.path, []).extend(messages)

    def clear(self):
        self.warnings.clear()
        self.compiler_warnings.clear()
        self.warning_logs.clear()
        self.kinds.clear()
        self.duplicate_tests.clear()
        self.sanitizer_warnings.clear()
        self.linter_warnings.clear()
        self.reported_compilation.clear()
        self.reported_linter.clear()
        self.reported_sanitizer.clear()
        self.reported_duplicates = False


@functools.cache
def _get_warning_stack(root: pathlib.Path) -> WarningStack:
    return WarningStack(root)


@functools.cache
def _get_cache_dir(root: pathlib.Path) -> pathlib.Path:
    dir = root / CACHE_DIR_NAME
    dir.mkdir(parents=True, exist_ok=True)
    return dir


@functools.cache
def _get_warning_runs_dir(root: pathlib.Path) -> pathlib.Path:
    dir = _get_cache_dir(root) / WARNINGS_DIR_NAME
    shutil.rmtree(dir, ignore_errors=True)
    dir.mkdir(parents=True, exist_ok=True)
    return dir


def get_warning_stack() -> WarningStack:
    current_root = utils.abspath(pathlib.Path.cwd())
    return _get_warning_stack(current_root)


def format_linter_location(message: 'LinterMessage') -> str:
    if message.line is None:
        return ''
    if message.col:
        return f'{message.line}:{message.col}'
    return str(message.line)


def group_linter_messages(
    messages: List['LinterMessage'],
) -> List[Tuple[str, List[str]]]:
    """Group linter messages by identical text, collecting their locations.

    Returns a list of ``(message, locations)`` pairs in first-seen order.
    Locations are formatted as ``line:col`` (or ``line``) strings, deduped
    while preserving order; messages with no location yield an empty list.
    """
    grouped: Dict[str, List[str]] = {}
    for message in messages:
        locations = grouped.setdefault(message.message, [])
        loc = format_linter_location(message)
        if loc and loc not in locations:
            locations.append(loc)
    return list(grouped.items())


def _summarize_warnings_for(path, stack, compilation_warnings) -> Optional[str]:
    logs = stack.warning_logs.get(path, [])
    warning_logs = [log for log in logs if log.warnings]
    if not warning_logs:
        return None
    summarizer = compilation_warnings.get_compilation_warning_summarizer_for(
        warning_logs[0].cmd
    )
    return summarizer.summarize(warning_logs)


def print_warning_stack_report():
    # Lazy import avoids a potential cycle between this module and
    # ``compilation_warnings`` (which already lazy-imports back into here).
    from rbx.box.sanitizers import compilation_warnings

    stack = get_warning_stack()
    warnings = stack.unreported_warnings()
    sanitizer_warnings = stack.unreported_sanitizer_warnings()
    duplicates = stack.unreported_duplicate_tests()
    if not warnings and not sanitizer_warnings and not duplicates:
        return
    console.console.rule('[status]Warning stack[/status]')
    console.console.print(
        f'[warning]There were some warnings within the code that run at {href(stack.root.absolute())}[/warning]'
    )
    if warnings:
        console.console.print(f'{len(warnings)} compilation warnings')
        console.console.print(
            'You can use [item]rbx compile[/item] to reproduce the issues with the files below.'
        )
        for path in warnings:
            summary = (
                _summarize_warnings_for(path, stack, compilation_warnings)
                if stack.shows_compiler_warnings(path)
                else None
            )
            suffix = f' [warning]({summary})[/warning]' if summary else ''
            console.console.print(f'- {href(path)}{suffix}')
            linter_messages = (
                stack.linter_warnings.get(path, [])
                if stack.shows_linter_warnings(path)
                else []
            )
            for message, locations in group_linter_messages(linter_messages):
                if not locations:
                    prefix = ''
                elif len(locations) == 1:
                    prefix = f'{locations[0]} '
                else:
                    prefix = f'lines {", ".join(locations)}: '
                console.console.print(f'    [warning]{prefix}{message}[/warning]')
        console.console.print()

    if sanitizer_warnings:
        console.console.print(f'{len(sanitizer_warnings)} sanitizer warnings')
        for path in sanitizer_warnings:
            console.console.print(
                f'- {href(path)}, example log at {href(stack.sanitizer_warnings[path])}'
            )
        console.console.print()

    if duplicates:
        console.console.print(f'{len(duplicates)} duplicate tests')
        for duplicate in duplicates:
            console.console.print(f'- {describe_duplicate_test(duplicate)}')
        console.console.print()


def describe_duplicate_test(duplicate: 'DuplicateTest') -> str:
    """One line for a duplicate test, shared with the issues view."""
    if duplicate.reason == 'call':
        call = f' ([item]{duplicate.call}[/item])' if duplicate.call else ''
        return (
            f'test [item]{duplicate.test}[/item] is generated by the same call as '
            f'[item]{duplicate.of}[/item]{call}'
        )
    return (
        f'test [item]{duplicate.test}[/item] has the same input as '
        f'[item]{duplicate.of}[/item]'
    )
