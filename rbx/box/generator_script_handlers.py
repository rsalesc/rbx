import dataclasses
import pathlib
import shlex
from abc import abstractmethod
from typing import Iterable, List, Optional, Tuple

import typer

from rbx import console
from rbx.box.generation_schema import GenerationInput, GeneratorScriptEntry
from rbx.box.schema import GeneratorCall, GeneratorScript, Testcase
from rbx.box.stressing import generator_script_parser


@dataclasses.dataclass
class GeneratorScriptHandlerParams:
    script_entry: GeneratorScript
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
            inputs = [
                inp for inp in inputs if inp.group is None or inp.group == self.group
            ]
        yield from inputs

    def append(self, calls: List[GeneratorCall], comment: Optional[str] = None):
        if comment:
            self.script += f'\n# {comment}'
        for call in calls:
            name = self.normalize_call_name(call.name)
            self.script += f'\n{name} {call.args or ""}'


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
