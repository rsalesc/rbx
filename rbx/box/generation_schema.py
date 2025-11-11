import pathlib
from typing import List, Optional

from pydantic import BaseModel

from rbx.box.schema import CodeItem, GeneratorCall, Solution, Testcase
from rbx.box.testcase_utils import TestcaseEntry


class GeneratorScriptEntry(BaseModel):
    path: pathlib.Path
    line: int

    def __str__(self) -> str:
        return f'{self.path}:{self.line}'


class GenerationInput(BaseModel):
    copied_from: Optional[Testcase] = None
    generator_call: Optional[GeneratorCall] = None
    generator_script: Optional[GeneratorScriptEntry] = None


class GenerationMetadata(GenerationInput):
    copied_to: Testcase


class GenerationTestcaseEntry(BaseModel):
    group_entry: TestcaseEntry
    subgroup_entry: TestcaseEntry

    metadata: GenerationMetadata
    validator: Optional[CodeItem] = None
    extra_validators: List[CodeItem] = []
    model_solution: Optional[Solution] = None

    def is_sample(self) -> bool:
        return self.group_entry.group == 'samples'
