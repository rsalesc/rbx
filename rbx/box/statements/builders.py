import dataclasses
import pathlib
import re
import shutil
import typing
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional, Tuple

import pypandoc
import typer
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import naming
from rbx.box.fields import Primitive
from rbx.box.schema import LimitsProfile, Package, Testcase
from rbx.box.statements.latex_jinja import (
    JinjaDictWrapper,
    render_latex_template,
    render_latex_template_blocks,
    render_markdown_template_blocks,
)
from rbx.box.statements.schema import (
    ConversionStep,
    ConversionType,
    JinjaTeX,
    Statement,
    StatementType,
    TexToPDF,
    rbxMarkdownToTeX,
    rbxToTeX,
)
from rbx.box.testcase_utils import (
    TestcaseInteraction,
    TestcaseInteractionParsingError,
    parse_interaction,
)


@dataclasses.dataclass
class StatementCodeLanguage:
    id: str
    name: str
    command: str


@dataclasses.dataclass
class StatementBuilderContext:
    lang: str
    languages: List[StatementCodeLanguage]
    params: ConversionStep
    root: pathlib.Path

    def build_jinja_kwargs(self) -> Dict[str, Any]:
        res = {
            'lang': self.lang,
            'languages': self.languages,
            'keyed_languages': {lang.id: lang for lang in self.languages},
        }
        return res


class StatementBuilderItem(ABC):
    @abstractmethod
    def build_jinja_kwargs(self) -> Dict[str, Any]:
        pass


class StatementSample(BaseModel):
    inputPath: pathlib.Path
    outputPath: pathlib.Path
    hasOutput: bool = True
    interaction: Optional[TestcaseInteraction] = None

    @staticmethod
    def from_testcase(testcase: Testcase) -> 'StatementSample':
        input_path = testcase.inputPath
        output_path = testcase.outputPath

        pin_path = input_path.with_suffix('.pin')
        pout_path = input_path.with_suffix('.pout')
        pio_path = input_path.with_suffix('.pio')

        if pin_path.is_file():
            input_path = pin_path
        if pout_path.is_file():
            output_path = pout_path

        interaction = None
        if pio_path.is_file():
            try:
                interaction = parse_interaction(pio_path)
            except TestcaseInteractionParsingError as e:
                console.console.print(
                    f'Error parsing interactive sample: [error]{e}[/error]'
                )
                raise typer.Exit(1) from e

        return StatementSample(
            inputPath=input_path,
            outputPath=output_path or utils.get_empty_sentinel_path(),
            hasOutput=output_path is not None,
            interaction=interaction,
        )

    @staticmethod
    def from_testcases(testcases: List[Testcase]) -> List['StatementSample']:
        return [StatementSample.from_testcase(testcase) for testcase in testcases]


class ExplainedStatementSample(StatementSample):
    explanation: Optional[str] = None


@dataclasses.dataclass
class StatementBuilderProblem(StatementBuilderItem):
    package: Package
    statement: Statement
    limits: LimitsProfile
    samples: List[StatementSample] = dataclasses.field(default_factory=list)
    short_name: Optional[str] = None

    # Will only be filled by contests.
    io_path: Optional[pathlib.Path] = None

    vars: Optional[Dict[str, Primitive]] = None

    def build_inner_jinja_kwargs(self) -> Dict[str, Any]:
        kwargs = {
            'package': self.package,
            'statement': self.statement,
            'samples': self.samples,
            'vars': JinjaDictWrapper.from_dict(self.vars or {}, wrapper_key='vars'),
            'title': naming.get_title(
                self.statement.language, self.statement, self.package
            ),
            'limits': self.limits,
        }
        if self.short_name is not None:
            kwargs['short_name'] = self.short_name
        if self.io_path is not None:
            kwargs['path'] = self.io_path
        return kwargs

    def build_jinja_kwargs(self) -> Dict[str, Any]:
        inner = self.build_inner_jinja_kwargs()
        return {
            'problem': inner,
        }


@dataclasses.dataclass
class StatementBuilderContest(StatementBuilderItem):
    title: str
    location: Optional[str] = None
    date: Optional[str] = None
    problems: List[StatementBuilderProblem] = dataclasses.field(default_factory=list)
    vars: Optional[Dict[str, Primitive]] = None

    def build_inner_jinja_kwargs(self) -> Dict[str, Any]:
        res = {'title': self.title}
        if self.location:
            res['location'] = self.location
        if self.date:
            res['date'] = self.date
        return res

    def build_jinja_kwargs(self) -> Dict[str, Any]:
        res = {
            'contest': self.build_inner_jinja_kwargs(),
            'problems': [
                problem.build_inner_jinja_kwargs() for problem in self.problems
            ],
            'vars': JinjaDictWrapper.from_dict(self.vars or {}, wrapper_key='vars'),
        }
        return res


@dataclasses.dataclass
class StatementBlocks:
    blocks: Dict[str, str] = dataclasses.field(default_factory=dict)
    explanations: Dict[int, str] = dataclasses.field(default_factory=dict)


def prepare_assets(
    assets: List[Tuple[pathlib.Path, pathlib.Path]],
    dest_dir: pathlib.Path,
):
    dest_dir.mkdir(parents=True, exist_ok=True)

    for asset_in, asset_out in assets:
        if not asset_in.is_file():
            console.console.print(
                f'[error]Asset [item]{asset_in}[/item] does not exist in your package.[/error]'
            )
            raise typer.Exit(1)

        # dest_path = dest_dir / asset.resolve().relative_to(statement_dir)
        dest_path = dest_dir / asset_out
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(asset_in), str(dest_path))


def render_jinja(root: pathlib.Path, content: bytes, **kwargs) -> bytes:
    temp_file = '__input__.tex'
    temp_path = root / temp_file
    temp_path.write_bytes(content)

    result: str = render_latex_template(
        str(root),
        temp_file,
        kwargs,
    )
    return result.encode()


def render_jinja_blocks(
    root: pathlib.Path,
    content: bytes,
    mode: Literal['latex', 'markdown'] = 'latex',
    **kwargs,
) -> StatementBlocks:
    if mode == 'latex':
        temp_file = '__input__.tex'
        renderer = render_latex_template_blocks
    elif mode == 'markdown':
        temp_file = '__input__.md'
        renderer = render_markdown_template_blocks
    else:
        raise ValueError(f'Invalid mode: {mode}')

    temp_path = root / temp_file
    temp_path.write_bytes(content)

    result: Dict[str, str] = renderer(
        str(root),
        temp_file,
        kwargs,
    )

    pattern = re.compile(r'explanation_(\d+)')
    explanation_keys = []
    for key in result:
        if match := pattern.match(key):
            explanation_keys.append((key, int(match.group(1))))

    explanations = {value: result[key] for key, value in explanation_keys}
    return StatementBlocks(blocks=result, explanations=explanations)


class StatementBuilder(ABC):
    @abstractmethod
    def name(self) -> ConversionType:
        pass

    @abstractmethod
    def default_params(self) -> ConversionStep:
        pass

    @abstractmethod
    def input_type(self) -> StatementType:
        pass

    @abstractmethod
    def output_type(self) -> StatementType:
        pass

    def handles_contest(self) -> bool:
        return True

    def handles_problem(self) -> bool:
        return True

    def inject_assets(
        self, root: pathlib.Path, params: ConversionStep
    ) -> List[Tuple[pathlib.Path, pathlib.Path]]:
        return []

    @abstractmethod
    def build(
        self,
        input: bytes,
        context: StatementBuilderContext,
        item: StatementBuilderItem,
        verbose: bool = False,
    ) -> bytes:
        pass


class JinjaTeXBuilder(StatementBuilder):
    def name(self) -> ConversionType:
        return ConversionType.JinjaTeX

    def default_params(self) -> ConversionStep:
        return JinjaTeX(type=ConversionType.JinjaTeX)

    def input_type(self) -> StatementType:
        return StatementType.JinjaTeX

    def output_type(self) -> StatementType:
        return StatementType.TeX

    def build(
        self,
        input: bytes,
        context: StatementBuilderContext,
        item: StatementBuilderItem,
        verbose: bool = False,
    ) -> bytes:
        return render_jinja(
            context.root,
            input,
            **context.build_jinja_kwargs(),
            **item.build_jinja_kwargs(),
        )


class rbxTeXBuilder(StatementBuilder):
    def name(self) -> ConversionType:
        return ConversionType.rbxToTex

    def default_params(self) -> ConversionStep:
        return rbxToTeX(type=ConversionType.rbxToTex)

    def input_type(self) -> StatementType:
        return StatementType.rbxTeX

    def output_type(self) -> StatementType:
        return StatementType.TeX

    def handles_contest(self) -> bool:
        # This builder cannot build contest statements.
        return False

    def inject_assets(
        self, root: pathlib.Path, params: ConversionStep
    ) -> List[Tuple[pathlib.Path, pathlib.Path]]:
        params = typing.cast(rbxToTeX, params)
        if not params.template:
            return []
        return [(utils.abspath(root / params.template), params.template)]

    def build(
        self,
        input: bytes,
        context: StatementBuilderContext,
        item: StatementBuilderItem,
        verbose: bool = False,
    ) -> bytes:
        params = typing.cast(rbxToTeX, context.params)
        assert params.template is not None
        problem = typing.cast(StatementBuilderProblem, item)

        statement_blocks = render_jinja_blocks(
            context.root, input, **problem.build_inner_jinja_kwargs()
        )
        blocks = statement_blocks.blocks

        problem_kwargs = problem.build_jinja_kwargs()
        problem_kwargs['problem']['blocks'] = blocks
        if statement_blocks.explanations is not None:
            problem_kwargs['problem']['samples'] = [
                ExplainedStatementSample(
                    **typing.cast(StatementSample, sample).model_dump(),
                    explanation=statement_blocks.explanations.get(i),
                )
                for i, sample in enumerate(problem_kwargs['problem']['samples'])
            ]

        return render_jinja(
            context.root,
            f'%- extends "{params.template}"'.encode(),
            **context.build_jinja_kwargs(),
            **problem_kwargs,
        )


class rbxMarkdownToTeXBuilder(StatementBuilder):
    def name(self) -> ConversionType:
        return ConversionType.rbxMarkdownToTeX

    def default_params(self) -> ConversionStep:
        return rbxMarkdownToTeX(type=ConversionType.rbxMarkdownToTeX)

    def input_type(self) -> StatementType:
        return StatementType.rbxMarkdown

    def output_type(self) -> StatementType:
        return StatementType.rbxTeX

    def handles_contest(self) -> bool:
        # This builder cannot build contest statements.
        return False

    def build(
        self,
        input: bytes,
        context: StatementBuilderContext,
        item: StatementBuilderItem,
        verbose: bool = False,
    ) -> bytes:
        problem = typing.cast(StatementBuilderProblem, item)

        statement_blocks = render_jinja_blocks(
            context.root, input, mode='markdown', **problem.build_inner_jinja_kwargs()
        )
        blocks = statement_blocks.blocks

        result_str = ''
        for name, content in blocks.items():
            converted_content = pypandoc.convert_text(content, 'latex', 'markdown')
            result_str += f'%- block {name}\n{converted_content}\n%- endblock\n\n'

        return result_str.encode()


class TeX2PDFBuilder(StatementBuilder):
    def name(self) -> ConversionType:
        return ConversionType.TexToPDF

    def default_params(self) -> ConversionStep:
        return TexToPDF(type=ConversionType.TexToPDF)

    def input_type(self) -> StatementType:
        return StatementType.TeX

    def output_type(self) -> StatementType:
        return StatementType.PDF

    def build(
        self,
        input: bytes,
        context: StatementBuilderContext,
        item: StatementBuilderItem,
        verbose: bool = False,
    ) -> bytes:
        from rbx.box.statements.latex import (
            MAX_PDFLATEX_RUNS,
            Latex,
            decode_latex_output,
            should_rerun,
        )

        latex = Latex(input.decode())
        latex_result = latex.build_pdf(context.root)
        pdf = latex_result.pdf
        logs = decode_latex_output(latex_result.result.stdout)
        runs = 1

        while pdf is not None and should_rerun(logs) and runs < MAX_PDFLATEX_RUNS:
            console.console.print(
                'Re-running pdfLaTeX to get cross-references right...'
            )
            latex_result = latex.build_pdf(context.root)
            pdf = latex_result.pdf
            logs = decode_latex_output(latex_result.result.stdout)
            runs += 1

        if pdf is None:
            console.console.print(f'{logs}')
            console.console.print('[error]PdfLaTeX compilation failed.[/error]')
            raise typer.Exit(1)

        if verbose:
            console.console.print(f'{logs}')

        return pdf


BUILDER_LIST: List[StatementBuilder] = [
    TeX2PDFBuilder(),
    JinjaTeXBuilder(),
    rbxTeXBuilder(),
    rbxMarkdownToTeXBuilder(),
]
PROBLEM_BUILDER_LIST = [
    builder for builder in BUILDER_LIST if builder.handles_problem()
]
CONTEST_BUILDER_LIST = [
    builder for builder in BUILDER_LIST if builder.handles_contest()
]
