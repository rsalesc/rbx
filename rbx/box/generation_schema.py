import pathlib
from typing import Any, List, Optional, Union

import typer
from pydantic import BaseModel

from rbx import console, utils
from rbx.box.schema import CodeItem, GeneratorCall, Solution, Testcase, Visualizer
from rbx.box.testcase_utils import TestcaseEntry

TestcaseOrScriptEntry = Union[TestcaseEntry, 'GeneratorScriptEntry']


class GeneratorScriptEntry(BaseModel):
    path: pathlib.Path
    line: int

    def __str__(self) -> str:
        return f'{self.path}:{self.line}'

    def __hash__(self) -> int:
        return hash((self.path, self.line))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, GeneratorScriptEntry):
            return False
        try:
            return self.path.samefile(other.path) and self.line == other.line
        except FileNotFoundError:
            return (
                self.path.absolute() == other.path.absolute()
                and self.line == other.line
            )

    @classmethod
    def parse(cls, spec: str) -> 'GeneratorScriptEntry':
        if spec.count(':') != 1:
            raise ValueError(f'Invalid generator script spec: {spec}')
        path, line = spec.split(':')
        return GeneratorScriptEntry(path=pathlib.Path(path), line=int(line))


class GenerationInput(BaseModel):
    copied_from: Optional[Testcase] = None
    generator_call: Optional[GeneratorCall] = None
    generator_script: Optional[GeneratorScriptEntry] = None
    content: Optional[str] = None


class GenerationMetadata(GenerationInput):
    copied_to: Testcase

    def __str__(self) -> str:
        if self.generator_call is not None:
            return utils.escape_markup(str(self.generator_call))
        elif self.copied_from is not None:
            return f'{self.copied_from.inputPath}'
        return ''


class GenerationTestcaseEntry(BaseModel):
    group_entry: TestcaseEntry
    subgroup_entry: TestcaseEntry

    metadata: GenerationMetadata
    validator: Optional[CodeItem] = None
    extra_validators: List[CodeItem] = []
    output_validators: List[CodeItem] = []
    model_solution: Optional[Solution] = None

    visualizer: Optional[Visualizer] = None
    solution_visualizer: Optional[Visualizer] = None

    def is_sample(self) -> bool:
        return self.group_entry.group == 'samples'

    def __str__(self) -> str:
        result = f'{self.group_entry}'
        metadata_str = str(self.metadata)
        if metadata_str:
            result += f' ({metadata_str})'
        return result


def get_parsed_entry(spec: str) -> TestcaseOrScriptEntry:
    try:
        if spec.count(':') == 1:
            return GeneratorScriptEntry.parse(spec)
        elif spec.count('/') == 1:
            return TestcaseEntry.parse(spec)
    except Exception:
        pass

    console.console.print(f'[error]Invalid testcase spec: {spec}[/error]')
    raise typer.Exit(1)
