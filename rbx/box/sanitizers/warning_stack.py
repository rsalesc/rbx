import functools
import pathlib
import shutil
from typing import TYPE_CHECKING, Dict, List, Optional

from rbx import console, utils
from rbx.box.formatting import href
from rbx.box.schema import CodeItem
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.steps import GradingFileOutput, PreprocessLog

if TYPE_CHECKING:
    from rbx.box.linters.linter import LinterMessage


class WarningStack:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.warnings = set()
        self.warning_logs: Dict[pathlib.Path, List[PreprocessLog]] = {}
        self.sanitizer_warnings = {}
        self.linter_warnings: Dict[pathlib.Path, List['LinterMessage']] = {}

    def add_warning(self, code: CodeItem, logs: Optional[List[PreprocessLog]] = None):
        self.warnings.add(code.path)
        if logs:
            self.warning_logs[code.path] = logs

    async def add_sanitizer_warning(
        self, cacher: FileCacher, code: CodeItem, reference: GradingFileOutput
    ):
        if code.path in self.sanitizer_warnings:
            return
        dest_path = _get_warning_runs_dir(self.root).joinpath(
            code.path.with_suffix(code.path.suffix + '.log')
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
        self, code: CodeItem, messages: List['LinterMessage']
    ) -> None:
        if not messages:
            return
        self.warnings.add(code.path)
        self.linter_warnings.setdefault(code.path, []).extend(messages)

    def clear(self):
        self.warnings.clear()
        self.warning_logs.clear()
        self.sanitizer_warnings.clear()
        self.linter_warnings.clear()


@functools.cache
def _get_warning_stack(root: pathlib.Path) -> WarningStack:
    return WarningStack(root)


@functools.cache
def _get_cache_dir(root: pathlib.Path) -> pathlib.Path:
    dir = root / '.box'
    dir.mkdir(parents=True, exist_ok=True)
    return dir


@functools.cache
def _get_warning_runs_dir(root: pathlib.Path) -> pathlib.Path:
    dir = _get_cache_dir(root) / 'warnings'
    shutil.rmtree(dir, ignore_errors=True)
    dir.mkdir(parents=True, exist_ok=True)
    return dir


def get_warning_stack() -> WarningStack:
    current_root = utils.abspath(pathlib.Path.cwd())
    return _get_warning_stack(current_root)


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
    if not stack.warnings and not stack.sanitizer_warnings:
        return
    console.console.rule('[status]Warning stack[/status]')
    console.console.print(
        f'[warning]There were some warnings within the code that run at {href(stack.root.absolute())}[/warning]'
    )
    if stack.warnings:
        console.console.print(f'{len(stack.warnings)} compilation warnings')
        console.console.print(
            'You can use [item]rbx compile[/item] to reproduce the issues with the files below.'
        )
        for path in sorted(stack.warnings):
            summary = _summarize_warnings_for(path, stack, compilation_warnings)
            suffix = f' [warning]({summary})[/warning]' if summary else ''
            console.console.print(f'- {href(path)}{suffix}')
            for message in stack.linter_warnings.get(path, []):
                loc = ''
                if message.line is not None:
                    loc = (
                        f'{message.line}:{message.col} '
                        if message.col
                        else (f'{message.line} ')
                    )
                console.console.print(f'    [warning]{loc}{message.message}[/warning]')
        console.console.print()

    if stack.sanitizer_warnings:
        console.console.print(f'{len(stack.sanitizer_warnings)} sanitizer warnings')
        for path in sorted(stack.sanitizer_warnings):
            console.console.print(
                f'- {href(path)}, example log at {href(stack.sanitizer_warnings[path])}'
            )
        console.console.print()
