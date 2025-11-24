import pathlib
from typing import Any, List, Optional, Union

import typer
from pydantic import BaseModel

from rbx import console
from rbx.box.schema import CodeItem, GeneratorCall, Solution, Testcase
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
        return (
            isinstance(other, GeneratorScriptEntry)
            and self.path.samefile(other.path)
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


class GenerationTestcaseEntry(BaseModel):
    group_entry: TestcaseEntry
    subgroup_entry: TestcaseEntry

    metadata: GenerationMetadata
    validator: Optional[CodeItem] = None
    extra_validators: List[CodeItem] = []
    output_validators: List[CodeItem] = []
    model_solution: Optional[Solution] = None

    def is_sample(self) -> bool:
        return self.group_entry.group == 'samples'


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
