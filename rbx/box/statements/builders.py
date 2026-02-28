import dataclasses
import pathlib
import re
import shutil
import typing
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional, Tuple, TypeVar

import pypandoc
import typer
from pydantic import BaseModel, Field

from rbx import console, utils
from rbx.box import naming
from rbx.box.fields import Primitive
from rbx.box.schema import LimitsProfile, Package
from rbx.box.statements import texsoup_utils
from rbx.box.statements.demacro_utils import collect_macro_definitions
from rbx.box.statements.latex_jinja import (
    JinjaDictGetter,
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
from rbx.box.testcase_sample_utils import StatementSample


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
    contest: Optional['StatementBuilderContest'] = None

    def build_jinja_kwargs(self) -> Dict[str, Any]:
        res = {
            'lang': self.lang,
            'languages': self.languages,
            'keyed_languages': {lang.id: lang for lang in self.languages},
        }
        if self.contest is not None:
            contest_kwargs = self.contest.build_jinja_kwargs()
            if 'contest' in contest_kwargs:
                res['contest'] = contest_kwargs['contest']
        return res


class StatementBuilderItem(ABC):
    @abstractmethod
    def build_jinja_kwargs(
        self,
    ) -> Dict[str, Any]:
        pass


class ExplainedStatementSample(StatementSample):
    explanation: Optional[str] = None

    @staticmethod
    def from_statement_sample(
        statement_sample: StatementSample, explanation_block: Optional[str] = None
    ) -> 'ExplainedStatementSample':
        return ExplainedStatementSample(
            **statement_sample.model_dump(),
            explanation=statement_sample.explanationPath.read_text()
            if statement_sample.explanationPath is not None
            and statement_sample.explanationPath.is_file()
            else explanation_block,
        )

    @staticmethod
    def from_statement_samples(
        statement_samples: List[StatementSample],
    ) -> List['ExplainedStatementSample']:
        samples = [
            ExplainedStatementSample.from_statement_sample(
                sample,
            )
            for i, sample in enumerate(statement_samples)
        ]
        return samples


@dataclasses.dataclass
class StatementBuilderProblem(StatementBuilderItem):
    package: Package
    statement: Statement
    limits: LimitsProfile
    profiles: Dict[str, LimitsProfile] = dataclasses.field(default_factory=dict)
    samples: List[StatementSample] = dataclasses.field(default_factory=list)
    short_name: Optional[str] = None

    # Will only be filled by contests.
    io_path: Optional[pathlib.Path] = None

    vars: Optional[Dict[str, Primitive]] = None

    def build_inner_jinja_kwargs(
        self,
    ) -> Dict[str, Any]:
        kwargs = dict(JinjaDictWrapper.from_dict(self.vars or {}, wrapper_key='vars'))
        kwargs.update(
            {
                'package': self.package,
                'statement': self.statement,
                'samples': ExplainedStatementSample.from_statement_samples(
                    self.samples,
                ),
                'vars': JinjaDictWrapper.from_dict(self.vars or {}, wrapper_key='vars'),
                'title': naming.get_problem_title(
                    self.statement.language, self.statement, self.package
                ),
                'limits': self.limits,
                'profiles': JinjaDictGetter('profiles', **self.profiles),
            }
        )
        if self.short_name is not None:
            kwargs['short_name'] = self.short_name
        if self.io_path is not None:
            kwargs['path'] = self.io_path
        return kwargs

    def build_jinja_kwargs(
        self,
    ) -> Dict[str, Any]:
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

    def _get_vars(self) -> Dict[str, Primitive]:
        return JinjaDictWrapper.from_dict(self.vars or {}, wrapper_key='vars')

    def build_inner_jinja_kwargs(self) -> Dict[str, Any]:
        res = {'title': self.title, 'vars': self._get_vars()}
        if self.location:
            res['location'] = self.location
        if self.date:
            res['date'] = self.date
        return res

    def build_jinja_kwargs(
        self,
    ) -> Dict[str, Any]:
        res = {
            'contest': self.build_inner_jinja_kwargs(),
            'problems': [
                problem.build_inner_jinja_kwargs() for problem in self.problems
            ],
            'vars': self._get_vars(),  # Kept for backward compatibility.
        }
        return res


class StatementBlocks(BaseModel):
    blocks: Dict[str, str] = Field(default_factory=dict)
    explanations: Dict[int, str] = Field(default_factory=dict)


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


def _inject_explanations_back(
    statement_blocks: StatementBlocks,
    explained_samples: List[ExplainedStatementSample],
):
    statement_blocks.explanations = {
        i: sample.explanation
        for i, sample in enumerate(explained_samples)
        if sample.explanation is not None
    }


def get_rbxtex_blocks(
    input: bytes,
    context: StatementBuilderContext,
    item: StatementBuilderItem,
    mode: Literal['latex', 'markdown'] = 'latex',
    externalize: bool = False,
) -> Tuple[StatementBlocks, Dict[str, Any]]:
    if isinstance(item, StatementBuilderProblem):
        statement_blocks = render_jinja_blocks(
            context.root,
            input,
            mode=mode,
            **item.build_inner_jinja_kwargs(),
        )
    else:
        statement_blocks = render_jinja_blocks(
            context.root,
            input,
            mode=mode,
            **item.build_jinja_kwargs(),
        )
    if externalize:
        statement_blocks.blocks = externalize_blocks(statement_blocks.blocks)

    item_kwargs = item.build_jinja_kwargs()
    if isinstance(item, StatementBuilderProblem):
        # Build samples.
        for i, sample in enumerate(item_kwargs['problem']['samples']):
            if i in statement_blocks.explanations:
                # Sample will come from a block, not from the file.
                sample.explanation = statement_blocks.explanations[i]
                continue
            if sample.explanation is None:
                # No explanation provided.
                continue
            # Render samples.
            sample.explanation = render_jinja(
                context.root,
                sample.explanation.encode(),
                mode=mode,
                **item.build_inner_jinja_kwargs(),
            ).decode()

        # Externalize samples.
        if externalize:
            item_kwargs['problem']['samples'] = externalize_explained_samples(
                item_kwargs['problem']['samples']
            )

        _inject_explanations_back(statement_blocks, item_kwargs['problem']['samples'])
        item_kwargs['problem']['blocks'] = statement_blocks.blocks
    elif isinstance(item, StatementBuilderContest):
        item_kwargs['contest']['blocks'] = statement_blocks.blocks
    return statement_blocks, item_kwargs


VarBlock = TypeVar('VarBlock')


def externalize_blocks(blocks: Dict[VarBlock, str]) -> Dict[VarBlock, str]:
    res = {}
    for key in blocks:
        tex_node = texsoup_utils.parse_latex(blocks[key])
        texsoup_utils.add_labels_to_tikz_nodes(tex_node, prefix=str(key))
        res[key] = str(tex_node)
    return res


def externalize_explained_samples(
    samples: List[ExplainedStatementSample],
) -> List[ExplainedStatementSample]:
    for idx, sample in enumerate(samples):
        if sample.explanation is None:
            continue
        tex_node = texsoup_utils.parse_latex(sample.explanation)
        texsoup_utils.add_labels_to_tikz_nodes(tex_node, prefix=f'explanation_{idx}')
        sample.explanation = str(tex_node)
    return samples


def substitute_externalized_blocks(blocks: Dict[Any, str]) -> Dict[Any, str]:
    res = {}
    for key in blocks:
        tex_node = texsoup_utils.parse_latex(blocks[key])
        texsoup_utils.replace_labeled_tikz_nodes(tex_node)
        res[key] = str(tex_node)
    return res


def substitute_externalized_samples(
    samples: List[ExplainedStatementSample],
) -> List[ExplainedStatementSample]:
    for sample in samples:
        if sample.explanation is None:
            continue
        tex_node = texsoup_utils.parse_latex(sample.explanation)
        texsoup_utils.replace_labeled_tikz_nodes(tex_node)
        sample.explanation = str(tex_node)
    return samples


class StatementBuilder(ABC):
    @classmethod
    def name(cls) -> ConversionType:
        raise NotImplementedError

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

    def explanation_suffix(self) -> Optional[str]:
        return None

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
    @classmethod
    def name(cls) -> ConversionType:
        return ConversionType.JinjaTeX

    def default_params(self) -> ConversionStep:
        return JinjaTeX(type=ConversionType.JinjaTeX)

    def input_type(self) -> StatementType:
        return StatementType.JinjaTeX

    def output_type(self) -> StatementType:
        return StatementType.TeX

    def explanation_suffix(self) -> Optional[str]:
        return '.tex'

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
    @classmethod
    def name(cls) -> ConversionType:
        return ConversionType.rbxToTex

    def default_params(self) -> ConversionStep:
        return rbxToTeX(type=ConversionType.rbxToTex)

    def input_type(self) -> StatementType:
        return StatementType.rbxTeX

    def output_type(self) -> StatementType:
        return StatementType.TeX

    def handles_contest(self) -> bool:
        return True

    def inject_assets(
        self, root: pathlib.Path, params: ConversionStep
    ) -> List[Tuple[pathlib.Path, pathlib.Path]]:
        params = typing.cast(rbxToTeX, params)
        if not params.template:
            return []
        return [(utils.abspath(root / params.template), params.template)]

    def explanation_suffix(self) -> Optional[str]:
        return '.tex'

    def build(
        self,
        input: bytes,
        context: StatementBuilderContext,
        item: StatementBuilderItem,
        verbose: bool = False,
    ) -> bytes:
        params = typing.cast(rbxToTeX, context.params)
        assert params.template is not None

        # Get non-externalized version first.
        statement_blocks, item_kwargs = get_rbxtex_blocks(
            input,
            context,
            item,
            mode='latex',
        )
        non_externalized_tex = render_jinja(
            context.root,
            f'%- extends "{params.template}"'.encode(),
            **context.build_jinja_kwargs(),
            **item_kwargs,
            blocks=statement_blocks.blocks,
        )
        (context.root / 'blocks.yml').write_text(utils.model_to_yaml(statement_blocks))
        if not params.externalize:
            return non_externalized_tex

        # Produce externalized version.
        statement_blocks, item_kwargs = get_rbxtex_blocks(
            input,
            context,
            item,
            mode='latex',
            externalize=params.externalize,
        )

        externalized_tex = render_jinja(
            context.root,
            f'%- extends "{params.template}"'.encode(),
            **context.build_jinja_kwargs(),
            **item_kwargs,
            blocks=statement_blocks.blocks,
        )
        (context.root / 'blocks.ext.yml').write_text(
            utils.model_to_yaml(statement_blocks)
        )

        # Produce substituted version.
        statement_blocks.blocks = substitute_externalized_blocks(
            statement_blocks.blocks
        )
        statement_blocks.explanations = substitute_externalized_blocks(
            statement_blocks.explanations
        )
        (context.root / 'blocks.sub.yml').write_text(
            utils.model_to_yaml(statement_blocks)
        )
        return externalized_tex


class rbxMarkdownToTeXBuilder(StatementBuilder):
    @classmethod
    def name(cls) -> ConversionType:
        return ConversionType.rbxMarkdownToTeX

    def default_params(self) -> ConversionStep:
        return rbxMarkdownToTeX(type=ConversionType.rbxMarkdownToTeX)

    def input_type(self) -> StatementType:
        return StatementType.rbxMarkdown

    def output_type(self) -> StatementType:
        return StatementType.rbxTeX

    def handles_contest(self) -> bool:
        return True

    def explanation_suffix(self) -> Optional[str]:
        return '.md'

    def build(
        self,
        input: bytes,
        context: StatementBuilderContext,
        item: StatementBuilderItem,
        verbose: bool = False,
    ) -> bytes:
        statement_blocks, _ = get_rbxtex_blocks(input, context, item, mode='markdown')

        result_str = ''
        for name, content in statement_blocks.blocks.items():
            converted_content = pypandoc.convert_text(content, 'latex', 'markdown')
            result_str += f'%- block {name}\n{converted_content}\n%- endblock\n\n'

        return result_str.encode()


class TeX2PDFBuilder(StatementBuilder):
    @classmethod
    def name(cls) -> ConversionType:
        return ConversionType.TexToPDF

    def default_params(self) -> ConversionStep:
        return TexToPDF(type=ConversionType.TexToPDF)

    def input_type(self) -> StatementType:
        return StatementType.TeX

    def output_type(self) -> StatementType:
        return StatementType.PDF

    def explanation_suffix(self) -> Optional[str]:
        return '.tex'

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

        input_str = input.decode()

        params = typing.cast(TexToPDF, context.params)

        if params.externalize:
            tex_node = texsoup_utils.parse_latex(input_str)
            texsoup_utils.inject_externalization_for_tikz(tex_node)
            (context.root / texsoup_utils.EXTERNALIZATION_DIR).mkdir(
                exist_ok=True, parents=True
            )
            input_str = str(tex_node)

        latex = Latex(input_str)
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

        if params.demacro:
            macro_defs = collect_macro_definitions(context.root / 'statement.tex')
            macro_defs.to_json_file(context.root / 'macros.json')

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
