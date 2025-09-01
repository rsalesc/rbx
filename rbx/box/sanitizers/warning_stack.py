import functools
import pathlib
import shutil

from rbx import console, utils
from rbx.box.formatting import href
from rbx.box.schema import CodeItem
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.steps import GradingFileOutput


class WarningStack:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.warnings = set()
        self.sanitizer_warnings = {}

    def add_warning(self, code: CodeItem):
        self.warnings.add(code.path)

    def add_sanitizer_warning(
        self, cacher: FileCacher, code: CodeItem, reference: GradingFileOutput
    ):
        if code.path in self.sanitizer_warnings:
            return
        dest_path = _get_warning_runs_dir(self.root).joinpath(
            code.path.with_suffix(code.path.suffix + '.log')
        )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        f = reference.get_file(cacher)
        if f is None:
            return
        with f:
            with dest_path.open('wb') as fout:
                shutil.copyfileobj(f, fout)
        self.sanitizer_warnings[code.path] = dest_path

    def clear(self):
        self.warnings.clear()
        self.sanitizer_warnings.clear()


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


def print_warning_stack_report():
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
            console.console.print(f'- {href(path)}')
        console.console.print()

    if stack.sanitizer_warnings:
        console.console.print(f'{len(stack.sanitizer_warnings)} sanitizer warnings')
        for path in sorted(stack.sanitizer_warnings):
            console.console.print(
                f'- {href(path)}, example log at {href(stack.sanitizer_warnings[path])}'
            )
        console.console.print()
