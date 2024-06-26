import dataclasses
import pathlib
import shutil
import tempfile
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import typer

from codefreaker import console
from codefreaker.box.schema import Package
from codefreaker.box.statements.latex import Latex
from codefreaker.box.statements.latex_jinja import (
    render_latex_template,
    render_latex_template_blocks,
)
from codefreaker.box.statements.schema import Statement, StatementType


@dataclasses.dataclass
class StatementCodeLanguage:
    name: str
    command: str


@dataclasses.dataclass
class StatementBuilderInput:
    id: str
    content: bytes
    languages: List[StatementCodeLanguage]
    package: Package
    statement: Statement

    def build_jinja_kwargs(self) -> Dict[str, Any]:
        return {
            'languages': self.languages,
            'package': self.package,
            'statement': self.statement,
        }


@dataclasses.dataclass
class StatementBuilderOutput:
    content: bytes


@dataclasses.dataclass
class ProblemWithStatement:
    package: Package
    statement: Statement
    blocks: Dict[str, str] = dataclasses.field(default_factory=dict)

    def has_block(self, block: str) -> bool:
        return block in self.blocks

    def get_block(self, block: str) -> str:
        return self.blocks[block]


def prepare_assets(statement: Statement, dest_dir: pathlib.Path):
    statement_path = statement.path.resolve()
    statement_dir = statement_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)

    for asset in statement.assets:
        if not asset.is_file() or not asset.resolve().is_relative_to(statement_dir):
            console.console.print(
                f'[error]Asset {asset} is not relative to statement {statement_path}.[/error]'
            )
            raise typer.Exit(1)

        dest_path = dest_dir / asset.resolve().relative_to(statement_dir)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(asset), str(dest_path))


def render_jinja(st: Statement, content: bytes, **kwargs) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        temp_dir = pathlib.Path(td)
        prepare_assets(st, temp_dir)

        temp_file = '__input__.tex'
        temp_path = temp_dir / temp_file
        temp_path.write_bytes(content)

        result: str = render_latex_template(
            str(temp_dir),
            temp_file,
            kwargs,
        )
        return result.encode()


def render_jinja_blocks(st: Statement, content: bytes, **kwargs) -> Dict[str, str]:
    with tempfile.TemporaryDirectory() as td:
        temp_dir = pathlib.Path(td)
        prepare_assets(st, temp_dir)

        temp_file = '__input__.tex'
        temp_path = temp_dir / temp_file
        temp_path.write_bytes(content)

        result: Dict[str, str] = render_latex_template_blocks(
            str(temp_dir),
            temp_file,
            kwargs,
        )
        return result


class StatementBuilder(ABC):
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def input_type(self) -> StatementType:
        pass

    @abstractmethod
    def output_type(self) -> StatementType:
        pass

    @abstractmethod
    def build(
        self, input: StatementBuilderInput, verbose: bool = False
    ) -> StatementBuilderOutput:
        pass


class JinjaTeXBuilder(StatementBuilder):
    def name(self) -> str:
        return 'jinja-tex'

    def input_type(self) -> StatementType:
        return StatementType.JinjaTeX

    def output_type(self) -> StatementType:
        return StatementType.TeX

    def build(
        self, input: StatementBuilderInput, verbose: bool = False
    ) -> StatementBuilderOutput:
        return StatementBuilderOutput(
            content=render_jinja(
                input.statement, input.content, **input.build_jinja_kwargs()
            )
        )


class CodefreakerTeXBuilder(StatementBuilder):
    def name(self) -> str:
        return 'cfk-tex'

    def input_type(self) -> StatementType:
        return StatementType.CodefreakerTeX

    def output_type(self) -> StatementType:
        return StatementType.TeX

    def build(
        self, input: StatementBuilderInput, verbose: bool = False
    ) -> StatementBuilderOutput:
        blocks = render_jinja_blocks(
            input.statement, input.content, **input.build_jinja_kwargs()
        )

        input_str = '%- extends "codefreaker.br.tex"'
        problems = [ProblemWithStatement(input.package, input.statement, blocks)]
        return StatementBuilderOutput(
            content=render_jinja(
                input.statement,
                input_str.encode(),
                **input.build_jinja_kwargs(),
                problems=problems,
            )
        )


class TeX2PDFBuilder(StatementBuilder):
    def name(self) -> str:
        return 'tex2pdf'

    def input_type(self) -> StatementType:
        return StatementType.TeX

    def output_type(self) -> StatementType:
        return StatementType.PDF

    def build(
        self, input: StatementBuilderInput, verbose: bool = False
    ) -> StatementBuilderOutput:
        latex = Latex(input.content.decode())
        with tempfile.TemporaryDirectory() as td:
            temp_dir = pathlib.Path(td)
            prepare_assets(input.statement, temp_dir)
            latex_result = latex.build_pdf(temp_dir)
        pdf = latex_result.pdf
        if pdf is None:
            console.console.print(f'{latex_result.result.stdout.decode()}')
            console.console.print('[error]PdfLaTeX compilation failed.[/error]')
            raise typer.Exit(1)

        if verbose:
            console.console.print(f'{latex_result.result.stdout.decode()}')

        return StatementBuilderOutput(content=pdf)


BUILDER_LIST = [TeX2PDFBuilder(), JinjaTeXBuilder(), CodefreakerTeXBuilder()]
