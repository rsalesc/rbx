import pathlib
from typing import Tuple

import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import package


class TestcaseEntry(BaseModel):
    __test__ = False

    group: str
    index: int

    @staticmethod
    def make_interactive() -> 'TestcaseEntry':
        return TestcaseEntry(group='interactive', index=0)

    def key(self) -> Tuple[str, int]:
        return self.group, self.index

    def __str__(self) -> str:
        if self.group == 'interactive':
            return 'interactive testcase'
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

    def get_prefix_path(self) -> pathlib.Path:
        return package.get_build_testgroup_path(self.group) / f'{self.index:03d}'
