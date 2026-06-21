import dataclasses
import pathlib
import shlex
from abc import abstractmethod
from typing import Iterable, List, Optional, Set, Tuple

import typer

from rbx import console
from rbx.box.generation_schema import GenerationInput, GeneratorScriptEntry
from rbx.box.schema import GeneratorCall, GeneratorScript, Testcase
from rbx.box.stressing import generator_script_parser


def _group_matches(annotation: Optional[str], key: str) -> bool:
    """Whether a line's @testgroup ``annotation`` applies to run-key ``key``.

    Untagged lines (``None``) always match. Otherwise the annotation must equal
    the key or be a path-prefix of it, so a parent-group tag flows into its
    subgroups while a sibling subgroup's tag does not. ``key`` is the full
    ``group`` or ``group/subgroup`` path the script is being run for.
    """
    if annotation is None:
        return True
    return key == annotation or key.startswith(annotation + '/')


@dataclasses.dataclass
class GeneratorScriptHandlerParams:
    script_entry: GeneratorScript
    # Full ``group`` or ``group/subgroup`` path used as the filter key.
    group: Optional[str] = None


class GeneratorScriptHandler:
    script: str
    script_entry: GeneratorScript
    group: Optional[str] = None

    def __init__(self, script: str, params: GeneratorScriptHandlerParams):
        self.script = script
        self.script_entry = params.script_entry
        self.group = params.group

    @abstractmethod
    def parse(self) -> Iterable[GenerationInput]:
        pass

    @abstractmethod
    def append(self, calls: List[GeneratorCall], comment: Optional[str] = None):
        pass

    @abstractmethod
    def remove(self, start_lines: Set[int]) -> None:
        pass

    def normalize_call_name(self, call_name: str) -> str:
        if self.script_entry.root == pathlib.Path():
            return call_name
        call_path = pathlib.Path(call_name)
        if not call_path.is_relative_to(self.script_entry.root):
            console.console.print(
                f'[error]Invalid call name: {call_name}, should be relative to script root {self.script_entry.root}[/error]'
            )
            raise typer.Exit(1)
        return str(call_path.relative_to(self.script_entry.root))


class RbxGeneratorScriptHandler(GeneratorScriptHandler):
    def parse(self) -> Iterable[GenerationInput]:
        inputs = generator_script_parser.parse_and_transform(
            self.script, self.script_entry.path
        )
        if self.group is not None:
            inputs = [inp for inp in inputs if _group_matches(inp.group, self.group)]
        yield from inputs

    def append(self, calls: List[GeneratorCall], comment: Optional[str] = None):
        if comment:
            self.script += f'\n# {comment}'
        for call in calls:
            name = self.normalize_call_name(call.name)
            self.script += f'\n{name} {call.args or ""}'

    def _call_lines(
        self, calls: List[GeneratorCall], comment: Optional[str], indent: str
    ) -> List[str]:
        lines: List[str] = []
        if comment:
            lines.append(f'{indent}# {comment}')
        for call in calls:
            name = self.normalize_call_name(call.name)
            lines.append(f'{indent}{name} {call.args or ""}'.rstrip())
        return lines

    def append_in_block(
        self,
        block_start_line: int,
        calls: List[GeneratorCall],
        comment: Optional[str] = None,
    ) -> None:
        """Insert ``calls`` inside the @testgroup block opened at
        ``block_start_line`` (before its closing brace), indented to match it."""
        block = next(
            (
                b
                for b in generator_script_parser.testgroup_blocks(self.script)
                if b.start_line == block_start_line
            ),
            None,
        )
        if block is None:
            raise ValueError(f'No @testgroup block starts at line {block_start_line}.')
        lines = self.script.splitlines()
        # Indent to match the last non-blank body line, else two spaces.
        indent = '  '
        for ln in range(block.end_line - 2, block.start_line - 1, -1):
            if lines[ln].strip():
                indent = lines[ln][: len(lines[ln]) - len(lines[ln].lstrip())] or '  '
                break
        insert_at = block.end_line - 1  # 0-indexed line of the `}`
        lines[insert_at:insert_at] = self._call_lines(calls, comment, indent)
        self.script = '\n'.join(lines) + ('\n' if self.script.endswith('\n') else '')

    def append_new_block(
        self,
        group_path: str,
        calls: List[GeneratorCall],
        comment: Optional[str] = None,
    ) -> None:
        """Append a fresh ``@testgroup <group_path> { ... }`` block scoping
        ``calls`` to exactly that run-key."""
        body = self._call_lines(calls, comment, '  ')
        block = '\n'.join([f'@testgroup {group_path} {{', *body, '}'])
        sep = '\n' if self.script and not self.script.endswith('\n') else ''
        self.script = f'{self.script}{sep}\n{block}\n'

    def remove(self, start_lines: Set[int]) -> None:
        spans = {
            s.start_line: s
            for s in generator_script_parser.statement_spans(self.script)
        }
        lines = self.script.splitlines()  # 0-indexed; 1-indexed line N is lines[N-1]

        drop = set()
        for start in start_lines:
            span = spans.get(start)
            if span is None:
                continue  # no statement starts there; ignore defensively
            for ln in range(span.start_line, span.end_line + 1):
                drop.add(ln)
            # Walk upward over contiguous comment lines (stop at blank or code).
            prev = span.start_line - 1
            # Textual heuristic: treat lines starting with // or # as comments.
            while prev >= 1:
                stripped = lines[prev - 1].strip()
                if stripped.startswith('//') or stripped.startswith('#'):
                    drop.add(prev)
                    prev -= 1
                else:
                    break

        kept = [line for i, line in enumerate(lines, start=1) if i not in drop]
        self.script = _normalize_blank_lines('\n'.join(kept))


def _normalize_blank_lines(text: str) -> str:
    out = []
    for line in text.splitlines():
        if not line.strip() and out and not out[-1].strip():
            continue  # collapse consecutive blanks
        out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return '\n'.join(out)


def _parse_box_testplan_line(line: str) -> Tuple[int, str, str]:
    comma_parts = line.split(';', maxsplit=1)
    if len(comma_parts) != 2:
        console.console.print(f'[error]Invalid testplan line: {line}[/error]')
        raise typer.Exit(1)
    try:
        group = int(comma_parts[0].strip())
    except ValueError:
        console.console.print(f'[error]Invalid testplan line: {line}[/error]')
        raise typer.Exit(1) from None
    line = comma_parts[1].strip()
    if not line:
        console.console.print(f'[error]Invalid testplan line: {line}[/error]')
        raise typer.Exit(1)

    call = shlex.split(line)[0]
    args = shlex.join(shlex.split(line)[1:])

    if call.strip() == 'copy':
        call = '@copy'
    if call.endswith('.exe'):
        call = call[:-4]

    return group, call, args


def _parse_box_testplan_lines(script: str) -> Iterable[Tuple[str, str, int, int]]:
    lines = script.splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        group, call, args = _parse_box_testplan_line(line)
        yield call, args, group, i + 1


def _get_last_group(script: str) -> int:
    last_group = 0
    for _, _, group, _ in _parse_box_testplan_lines(script):
        last_group = max(last_group, group)
    return last_group


class BoxGeneratorScriptHandler(GeneratorScriptHandler):
    def parse(self) -> Iterable[GenerationInput]:
        for call, args, _, line in _parse_box_testplan_lines(self.script):
            entry = GeneratorScriptEntry(
                path=self.script_entry.path,
                line=line,
            )
            if call == '@copy':
                yield GenerationInput(
                    copied_from=Testcase(inputPath=pathlib.Path(args.strip())),
                    generator_script=entry,
                )
            else:
                yield GenerationInput(
                    generator_call=GeneratorCall(
                        name=call,
                        args=args,
                    ),
                    generator_script=entry,
                )

    def append(self, calls: List[GeneratorCall], comment: Optional[str] = None):
        if comment:
            self.script += f'\n# {comment}'
        group = _get_last_group(self.script) + 1
        for call in calls:
            name = pathlib.Path(self.normalize_call_name(call.name)).with_suffix('.exe')
            self.script += f'\n{group} ; {name} {call.args or ""}'

    def remove(self, start_lines: Set[int]) -> None:
        raise NotImplementedError(
            'Removing tests is only supported for rbx-format scripts.'
        )


REGISTERED_HANDLERS = {
    'rbx': RbxGeneratorScriptHandler,
    'box': BoxGeneratorScriptHandler,
}


def get_generator_script_handler(
    script: str,
    params: GeneratorScriptHandlerParams,
) -> GeneratorScriptHandler:
    if params.script_entry.format not in REGISTERED_HANDLERS:
        console.console.print(
            f'[error]Invalid generator script format: {params.script_entry.format}[/error]'
        )
        raise typer.Exit(1)
    return REGISTERED_HANDLERS[params.script_entry.format](script, params)
