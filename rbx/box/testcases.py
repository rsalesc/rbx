import pathlib
import shutil
from typing import List, Tuple

import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import package
from rbx.box.package import get_build_testgroup_path, get_build_tests_path
from rbx.box.schema import Testcase, TestcaseGroup


class TestcaseEntry(BaseModel):
    group: str
    index: int

    def key(self) -> Tuple[str, int]:
        return self.group, self.index

    def __str__(self) -> str:
        return f'{self.group}/{self.index}'

    @classmethod
    def parse(cls, spec: str) -> 'TestcaseEntry':
        group, index = spec.split('/')
        return TestcaseEntry(group=group.strip(), index=int(index))


class TestcaseData(BaseModel):
    input: str
    output: str


def find_built_testcases(group: TestcaseGroup) -> List[Testcase]:
    inputs = find_built_testcase_inputs(group)

    testcases = []
    for input in inputs:
        output = input.with_suffix('.out')
        testcases.append(Testcase(inputPath=input, outputPath=output))
    return testcases


def find_built_testcase_inputs(group: TestcaseGroup) -> List[pathlib.Path]:
    testgroup_path = get_build_testgroup_path(group.name)
    if not testgroup_path.is_dir():
        console.console.print(
            f'Testgroup {group.name} is not generated in build folder'
        )
        raise typer.Exit(1)

    return sorted(testgroup_path.glob('*.in'))


def clear_built_testcases():
    shutil.rmtree(str(get_build_tests_path()), ignore_errors=True)


def get_samples() -> List[Testcase]:
    tcs = find_built_testcases(package.get_testgroup('samples'))
    return [
        Testcase(
            inputPath=tc.inputPath.resolve(),
            outputPath=tc.outputPath.resolve()
            if tc.outputPath is not None and tc.outputPath.is_file()
            else None,
        )
        for tc in tcs
    ]
