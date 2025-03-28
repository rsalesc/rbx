import pathlib
import shutil
from typing import List, Optional, Tuple

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
        if spec.count('/') != 1:
            console.console.print(
                f'[error]Invalid testcase spec [item]{spec}[/item]. Format should be [item]<group>/<index>[/item].[/error]',
            )
            raise typer.Exit(1)
        group, index = spec.split('/')
        return TestcaseEntry(group=group.strip(), index=int(index))


class TestcasePattern(BaseModel):
    group_prefix: List[str]
    index: Optional[int] = None

    def group(self) -> str:
        return '/'.join(self.group_prefix)

    def match(self, group_entry: TestcaseEntry) -> bool:
        # TODO: support subgroups.
        entry_parts = tuple(group_entry.group.split('/'))
        if self.index is not None:
            if self.index != group_entry.index:
                return False
            if tuple(self.group_prefix) != entry_parts:
                return False
            return True

        if len(self.group_prefix) > len(entry_parts):
            return False

        return tuple(self.group_prefix) == entry_parts[: len(self.group_prefix)]

    def with_no_index(self) -> 'TestcasePattern':
        return self.model_copy(update={'index': None})

    def intersecting_group(self, group: str) -> bool:
        if self.with_no_index().match(TestcaseEntry(group=group, index=0)):
            # If the group is inside the pattern, then it is a match.
            return True
        if TestcasePattern.parse(group).match(
            TestcaseEntry(group=self.group(), index=0)
        ):
            # If the group is a prefix of the pattern, then it is a match.
            return True
        return False

    def __str__(self) -> str:
        prefix = '/'.join(self.group_prefix)
        if self.index is None:
            return f'{prefix}/'
        return f'{prefix}/{self.index}'

    @classmethod
    def parse(cls, spec: str) -> 'TestcasePattern':
        parts = spec.split('/')
        if not parts:
            console.console.print(
                f'[error]Invalid testcase pattern [item]{spec}[/item].[/error]',
            )
            raise typer.Exit(1)

        if len(parts) == 1:
            return cls(group_prefix=parts, index=None)

        if parts[-1].isdigit():
            return cls(group_prefix=parts[:-1], index=int(parts[-1]))

        return cls(group_prefix=parts, index=None)


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
