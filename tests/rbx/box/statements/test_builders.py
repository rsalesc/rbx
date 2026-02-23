import pathlib
from unittest.mock import patch

import pytest
import typer

from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.schema import LimitsProfile, Package, Statement, Testcase
from rbx.box.statements.builders import (
    ExplainedStatementSample,
    JinjaTeXBuilder,
    StatementBlocks,
    StatementBuilderContest,
    StatementBuilderContext,
    StatementBuilderProblem,
    StatementCodeLanguage,
    StatementSample,
    TeX2PDFBuilder,
    get_rbxtex_blocks,
    prepare_assets,
    rbxMarkdownToTeXBuilder,
    rbxTeXBuilder,
    render_jinja,
    render_jinja_blocks,
)
from rbx.box.statements.schema import (
    ConversionType,
    JinjaTeX,
    StatementType,
    TexToPDF,
    rbxMarkdownToTeX,
    rbxToTeX,
)
from rbx.box.testcase_utils import TestcaseEntry


def create_dummy_entry():
    return GenerationTestcaseEntry(
        group_entry=TestcaseEntry(group='samples', index=1),
        subgroup_entry=TestcaseEntry(group='samples', index=1),
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=pathlib.Path('dummy'))
        ),
    )


class TestStatementCodeLanguage:
    """Test StatementCodeLanguage dataclass."""

    def test_creation(self):
        """Test creating a StatementCodeLanguage."""
        lang = StatementCodeLanguage(
            id='cpp', name='C++', command='g++ -o {output} {input}'
        )
        assert lang.id == 'cpp'
        assert lang.name == 'C++'
        assert lang.command == 'g++ -o {output} {input}'


class TestStatementBuilderContext:
    """Test StatementBuilderContext functionality."""

    def test_build_jinja_kwargs(self):
        """Test building jinja kwargs from context."""
        languages = [
            StatementCodeLanguage(id='cpp', name='C++', command='g++'),
            StatementCodeLanguage(id='py', name='Python', command='python'),
        ]
        params = JinjaTeX(type=ConversionType.JinjaTeX)
        context = StatementBuilderContext(
            lang='en',
            languages=languages,
            params=params,
            root=pathlib.Path('/tmp'),
        )

        kwargs = context.build_jinja_kwargs()

        assert kwargs['lang'] == 'en'
        assert kwargs['languages'] == languages
        assert kwargs['keyed_languages']['cpp'].name == 'C++'
        assert kwargs['keyed_languages']['py'].name == 'Python'


class TestStatementBuilderProblem:
    """Test StatementBuilderProblem functionality."""

    @pytest.fixture
    def sample_package(self):
        """Create a sample package for testing."""
        return Package(
            name='test-problem', timeLimit=1000, memoryLimit=256, vars={'MAX_N': 1000}
        )

    @pytest.fixture
    def sample_statement(self):
        """Create a sample statement for testing."""
        return Statement(
            name='statement',
            language='en',
            title='Test Problem',
            path=pathlib.Path('statement.tex'),
            type=StatementType.TeX,
        )

    @pytest.fixture
    def sample_limits(self):
        """Create a sample limits profile for testing."""
        return LimitsProfile(timeLimit=1000, memoryLimit=256)

    @pytest.fixture
    def sample_samples(self, tmp_path):
        """Create sample testcases."""
        samples = []
        for i in range(2):
            input_file = tmp_path / f'sample{i}.in'
            output_file = tmp_path / f'sample{i}.out'
            input_file.write_text(f'input {i}')
            output_file.write_text(f'output {i}')
            samples.append(
                StatementSample(
                    entry=create_dummy_entry(),
                    inputPath=input_file,
                    outputPath=output_file,
                    hasOutput=True,
                )
            )
        return samples

    def test_build_inner_jinja_kwargs_basic(
        self, sample_package, sample_statement, sample_limits, sample_samples
    ):
        """Test building inner jinja kwargs with basic configuration."""
        problem = StatementBuilderProblem(
            package=sample_package,
            statement=sample_statement,
            limits=sample_limits,
            samples=sample_samples,
            vars={'TEST_VAR': 42, 'NESTED.KEY': 'VALUE'},
        )

        kwargs = problem.build_inner_jinja_kwargs()

        assert kwargs['package'] == sample_package
        assert kwargs['statement'] == sample_statement
        # samples should be converted to ExplainedStatementSample
        assert len(kwargs['samples']) == len(sample_samples)
        assert kwargs['samples'][0].inputPath == sample_samples[0].inputPath
        assert kwargs['limits'] == sample_limits
        assert kwargs['title'] == 'Test Problem'
        assert kwargs['vars']['TEST_VAR'] == 42
        assert kwargs['vars']['NESTED']['KEY'] == 'VALUE'

    def test_build_inner_jinja_kwargs_with_short_name(
        self, sample_package, sample_statement, sample_limits
    ):
        """Test building kwargs with short name."""
        problem = StatementBuilderProblem(
            package=sample_package,
            statement=sample_statement,
            limits=sample_limits,
            short_name='A',
        )

        kwargs = problem.build_inner_jinja_kwargs()

        assert kwargs['short_name'] == 'A'

    def test_build_inner_jinja_kwargs_with_io_path(
        self, sample_package, sample_statement, sample_limits
    ):
        """Test building kwargs with IO path."""
        io_path = pathlib.Path('/tmp/test.txt')
        problem = StatementBuilderProblem(
            package=sample_package,
            statement=sample_statement,
            limits=sample_limits,
            io_path=io_path,
        )

        kwargs = problem.build_inner_jinja_kwargs()

        assert kwargs['path'] == io_path

    def test_build_jinja_kwargs(self, sample_package, sample_statement, sample_limits):
        """Test building full jinja kwargs structure."""
        problem = StatementBuilderProblem(
            package=sample_package,
            statement=sample_statement,
            limits=sample_limits,
        )

        kwargs = problem.build_jinja_kwargs()

        assert 'problem' in kwargs
        assert kwargs['problem']['package'] == sample_package
        assert kwargs['problem']['statement'] == sample_statement
        assert kwargs['problem']['limits'] == sample_limits


class TestStatementBuilderContest:
    """Test StatementBuilderContest functionality."""

    def test_build_inner_jinja_kwargs_basic(self):
        """Test building basic contest kwargs."""
        contest = StatementBuilderContest(title='Test Contest')

        kwargs = contest.build_inner_jinja_kwargs()

        assert kwargs['title'] == 'Test Contest'
        assert 'location' not in kwargs
        assert 'date' not in kwargs

    def test_build_inner_jinja_kwargs_full(self):
        """Test building contest kwargs with all fields."""
        contest = StatementBuilderContest(
            title='Test Contest',
            location='University',
            date='2023-12-01',
        )

        kwargs = contest.build_inner_jinja_kwargs()

        assert kwargs['title'] == 'Test Contest'
        assert kwargs['location'] == 'University'
        assert kwargs['date'] == '2023-12-01'

    def test_build_jinja_kwargs(self):
        """Test building full contest jinja kwargs."""
        contest = StatementBuilderContest(
            title='Test Contest',
            vars={'CONTEST_TIME': 300, 'NESTED.KEY': 'VALUE'},
        )

        kwargs = contest.build_jinja_kwargs()

        assert 'contest' in kwargs
        assert 'problems' in kwargs
        assert 'vars' in kwargs
        assert kwargs['contest']['title'] == 'Test Contest'
        assert kwargs['problems'] == []
        assert kwargs['vars']['CONTEST_TIME'] == 300
        assert kwargs['vars']['NESTED']['KEY'] == 'VALUE'


class TestPrepareAssets:
    """Test prepare_assets functionality."""

    def test_prepare_assets_basic(self, tmp_path):
        """Test copying assets to destination directory."""
        # Create source files
        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        asset1 = src_dir / 'image1.png'
        asset2 = src_dir / 'image2.jpg'
        asset1.write_text('image1 content')
        asset2.write_text('image2 content')

        # Prepare destination
        dest_dir = tmp_path / 'dest'
        assets = [
            (asset1, pathlib.Path('images/image1.png')),
            (asset2, pathlib.Path('image2.jpg')),
        ]

        prepare_assets(assets, dest_dir)

        # Verify assets were copied correctly
        assert (dest_dir / 'images/image1.png').exists()
        assert (dest_dir / 'image2.jpg').exists()
        assert (dest_dir / 'images/image1.png').read_text() == 'image1 content'
        assert (dest_dir / 'image2.jpg').read_text() == 'image2 content'

    def test_prepare_assets_nonexistent_source(self, tmp_path):
        """Test error handling for nonexistent source files."""
        dest_dir = tmp_path / 'dest'
        nonexistent = tmp_path / 'nonexistent.png'
        assets = [(nonexistent, pathlib.Path('image.png'))]

        with pytest.raises(typer.Exit):
            prepare_assets(assets, dest_dir)


class TestRenderJinja:
    """Test render_jinja functionality."""

    def test_render_jinja_basic(self, tmp_path):
        """Test basic jinja rendering."""
        content = b'Hello \\VAR{name}!'
        result = render_jinja(tmp_path, content, name='World')

        assert b'Hello World!' in result

    def test_render_jinja_with_complex_vars(self, tmp_path):
        """Test jinja rendering with complex variables."""
        content = b'Problem: \\VAR{problem.title}, Max: \\VAR{vars.MAX_N}, Nested: \\VAR{vars.NESTED.KEY}'
        problem = {'title': 'Test Problem'}
        vars_dict = {'MAX_N': 1000, 'NESTED': {'KEY': 'VALUE'}}

        result = render_jinja(tmp_path, content, problem=problem, vars=vars_dict)

        assert b'Problem: Test Problem' in result
        assert b'Max: 1000' in result
        assert b'Nested: VALUE' in result


class TestRenderJinjaBlocks:
    """Test render_jinja_blocks functionality."""

    def test_render_jinja_blocks_latex(self, tmp_path):
        """Test rendering latex blocks."""
        content = b"""
%- block legend
This is the legend with \\VAR{title}.
%- endblock

%- block input
Input description.
%- endblock
"""
        result = render_jinja_blocks(tmp_path, content, title='Test')

        assert isinstance(result, StatementBlocks)
        assert 'legend' in result.blocks
        assert 'input' in result.blocks
        assert 'This is the legend with Test' in result.blocks['legend']

    def test_render_jinja_blocks_markdown(self, tmp_path):
        """Test rendering markdown blocks."""
        content = b"""
{% block legend %}
This is the legend with {{ title }}.
{% endblock %}

{% block input %}
Input description.
{% endblock %}
"""
        result = render_jinja_blocks(tmp_path, content, mode='markdown', title='Test')

        assert isinstance(result, StatementBlocks)
        assert 'legend' in result.blocks
        assert 'input' in result.blocks

    def test_render_jinja_blocks_with_explanations(self, tmp_path):
        """Test rendering blocks with sample explanations."""
        content = b"""
%- block legend
Legend content.
%- endblock

%- block explanation_0
Explanation for sample 0.
%- endblock

%- block explanation_1
Explanation for sample 1.
%- endblock
"""
        result = render_jinja_blocks(tmp_path, content)

        assert 0 in result.explanations
        assert 1 in result.explanations
        assert 'Explanation for sample 0' in result.explanations[0]
        assert 'Explanation for sample 1' in result.explanations[1]

    def test_render_jinja_blocks_invalid_mode(self, tmp_path):
        """Test error handling for invalid mode."""
        content = b'test content'
        with pytest.raises(ValueError, match='Invalid mode'):
            render_jinja_blocks(tmp_path, content, mode='invalid')  # type: ignore:


class TestGetRbxTexBlocks:
    """Test get_rbxtex_blocks functionality."""

    @pytest.fixture
    def context(self, tmp_path):
        """Create a context for testing."""
        return StatementBuilderContext(
            lang='en',
            languages=[],
            params=JinjaTeX(type=ConversionType.JinjaTeX),
            root=tmp_path,
        )

    def test_get_rbxtex_blocks_problem(self, context, tmp_path):
        """Test get_rbxtex_blocks with a problem item."""
        package = Package(name='test-problem', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='statement', path=pathlib.Path('stmt.tex'), type=StatementType.JinjaTeX
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)

        # Setup samples with explanations in blocks
        samples = [
            StatementSample(
                entry=create_dummy_entry(),
                inputPath=tmp_path / '1.in',
                outputPath=tmp_path / '1.out',
            )
        ]

        problem = StatementBuilderProblem(
            package=package, statement=statement, limits=limits, samples=samples
        )

        content = b"""
%- block legend
Legend content.
%- endblock

%- block explanation_0
Explanation for sample 0.
%- endblock
"""

        blocks, kwargs = get_rbxtex_blocks(content, context, problem)

        assert 'legend' in blocks.blocks
        assert blocks.explanations[0].strip() == 'Explanation for sample 0.'

        # Verify kwargs update
        assert 'blocks' in kwargs['problem']
        assert kwargs['problem']['blocks'] == blocks.blocks
        assert (
            kwargs['problem']['samples'][0].explanation.strip()
            == 'Explanation for sample 0.'
        )

    def test_get_rbxtex_blocks_contest(self, context):
        """Test get_rbxtex_blocks with a contest item."""
        contest = StatementBuilderContest(title='Test Contest')

        content = b"""
%- block intro
Welcome to the contest.
%- endblock
"""

        blocks, kwargs = get_rbxtex_blocks(content, context, contest)

        assert 'intro' in blocks.blocks
        assert 'intro' in blocks.blocks
        assert kwargs['contest']['title'] == 'Test Contest'

    def test_get_rbxtex_blocks_block_overrides_explanation_path(
        self, context, tmp_path
    ):
        """Test that explanation block takes precedence over explanationPath on sample."""
        package = Package(name='test-problem', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='statement', path=pathlib.Path('stmt.tex'), type=StatementType.JinjaTeX
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)

        # Create a sample with an explanationPath file
        explanation_file = tmp_path / 'sample0_explanation.tex'
        explanation_file.write_text('Explanation from file.')

        samples = [
            StatementSample(
                entry=create_dummy_entry(),
                inputPath=tmp_path / '1.in',
                outputPath=tmp_path / '1.out',
                explanationPath=explanation_file,
            )
        ]

        problem = StatementBuilderProblem(
            package=package, statement=statement, limits=limits, samples=samples
        )

        content = b"""
%- block legend
Legend content.
%- endblock

%- block explanation_0
Explanation from block.
%- endblock
"""

        blocks, kwargs = get_rbxtex_blocks(content, context, problem)

        # Block explanation should take precedence over file-based explanation
        assert 'Explanation from block.' in blocks.explanations[0]

        # kwargs samples should also use the block-based explanation
        assert 'Explanation from block.' in kwargs['problem']['samples'][0].explanation

    def test_get_rbxtex_blocks_externalize(self, context, tmp_path):
        """Test get_rbxtex_blocks with externalize=True."""
        package = Package(name='test-problem', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='statement', path=pathlib.Path('stmt.tex'), type=StatementType.JinjaTeX
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)

        samples = [
            StatementSample(
                entry=create_dummy_entry(),
                inputPath=tmp_path / '1.in',
                outputPath=tmp_path / '1.out',
            )
        ]

        problem = StatementBuilderProblem(
            package=package, statement=statement, limits=limits, samples=samples
        )

        content = b"""
%- block diagram
\\begin{tikzpicture}
\\node {A};
\\end{tikzpicture}
%- endblock

%- block explanation_0
\\begin{tikzpicture}
\\node {B};
\\end{tikzpicture}
%- endblock
"""

        blocks, kwargs = get_rbxtex_blocks(content, context, problem, externalize=True)

        # Check explicit block externalization
        assert 'diagram' in blocks.blocks
        assert '\\tikzsetnextfilename{diagram_0}' in blocks.blocks['diagram']
        assert '\\begin{tikzpicture}' in blocks.blocks['diagram']

        # Check explantion block in blocks
        assert 'explanation_0' in blocks.blocks
        assert (
            '\\tikzsetnextfilename{explanation_0_0}' in blocks.blocks['explanation_0']
        )

        # Check kwargs update
        samples_in_kwargs = kwargs['problem']['samples']
        assert len(samples_in_kwargs) == 1
        assert (
            '\\tikzsetnextfilename{explanation_0_0}' in samples_in_kwargs[0].explanation
        )

        # Ensure blocks in kwargs are also updated
        assert (
            '\\tikzsetnextfilename{diagram_0}' in kwargs['problem']['blocks']['diagram']
        )


class TestJinjaTeXBuilder:
    """Test JinjaTeXBuilder functionality."""

    @pytest.fixture
    def builder(self):
        """Create a JinjaTeXBuilder instance."""
        return JinjaTeXBuilder()

    @pytest.fixture
    def context(self, tmp_path):
        """Create a StatementBuilderContext for testing."""
        return StatementBuilderContext(
            lang='en',
            languages=[StatementCodeLanguage(id='cpp', name='C++', command='g++')],
            params=JinjaTeX(type=ConversionType.JinjaTeX),
            root=tmp_path,
        )

    @pytest.fixture
    def problem_item(self):
        """Create a StatementBuilderProblem for testing."""
        package = Package(name='test-problem', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='statement',
            path=pathlib.Path('statement.tex'),
            type=StatementType.JinjaTeX,
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)
        return StatementBuilderProblem(
            package=package, statement=statement, limits=limits
        )

    def test_properties(self, builder):
        """Test builder properties."""
        assert builder.name() == ConversionType.JinjaTeX
        assert isinstance(builder.default_params(), JinjaTeX)
        assert builder.input_type() == StatementType.JinjaTeX
        assert builder.output_type() == StatementType.TeX
        assert builder.handles_contest() is True
        assert builder.handles_problem() is True

    def test_build(self, builder, context, problem_item):
        """Test building with JinjaTeX."""
        input_content = b'Hello \\VAR{problem.package.name}!'

        result = builder.build(input_content, context, problem_item)

        assert b'Hello test-problem!' in result


class TestrbxTeXBuilder:
    """Test rbxTeXBuilder functionality."""

    @pytest.fixture
    def builder(self):
        """Create an rbxTeXBuilder instance."""
        return rbxTeXBuilder()

    @pytest.fixture
    def context_with_template(self, tmp_path):
        """Create context with template."""
        template_file = tmp_path / 'template.tex'
        template_file.write_text('\\VAR{problem.blocks.legend}')

        params = rbxToTeX(
            type=ConversionType.rbxToTex, template=pathlib.Path('template.tex')
        )
        return StatementBuilderContext(
            lang='en',
            languages=[],
            params=params,
            root=tmp_path,
        )

    @pytest.fixture
    def problem_item(self):
        """Create a StatementBuilderProblem for testing."""
        package = Package(name='test-problem', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='statement',
            path=pathlib.Path('statement.rbx.tex'),
            type=StatementType.rbxTeX,
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)
        return StatementBuilderProblem(
            package=package, statement=statement, limits=limits
        )

    def test_properties(self, builder):
        """Test builder properties."""
        assert builder.name() == ConversionType.rbxToTex
        assert isinstance(builder.default_params(), rbxToTeX)
        assert builder.input_type() == StatementType.rbxTeX
        assert builder.output_type() == StatementType.TeX
        assert builder.handles_problem() is True

    def test_build_contest(self, builder, tmp_path):
        """Test building contest statement."""
        # Create a template that uses contest variables (or is generic)
        template_file = tmp_path / 'contest_template.tex'
        template_file.write_text('\\VAR{contest.blocks.intro}')

        params = rbxToTeX(
            type=ConversionType.rbxToTex, template=pathlib.Path('contest_template.tex')
        )
        context = StatementBuilderContext(
            lang='en',
            languages=[],
            params=params,
            root=tmp_path,
        )

        contest = StatementBuilderContest(title='Test Contest')
        input_content = b"""
%- block intro
Welcome to \\VAR{contest.title}.
%- endblock
"""
        result = builder.build(input_content, context, contest)
        assert b'Welcome to Test Contest' in result
        # Verify blocks.yml is written
        assert (tmp_path / 'blocks.yml').exists()

    def test_inject_assets_with_template(self, builder, tmp_path):
        """Test asset injection with template."""
        template_file = tmp_path / 'template.tex'
        template_file.write_text('template content')

        params = rbxToTeX(
            type=ConversionType.rbxToTex, template=pathlib.Path('template.tex')
        )
        assets = builder.inject_assets(tmp_path, params)

        assert len(assets) == 1
        assert assets[0][1] == pathlib.Path('template.tex')

    def test_inject_assets_no_template(self, builder, tmp_path):
        """Test asset injection without template."""
        # Use default template path
        params = rbxToTeX(type=ConversionType.rbxToTex)
        assets = builder.inject_assets(tmp_path, params)

        # Should return assets with default template
        assert len(assets) == 1

    def test_build(self, builder, context_with_template, problem_item, tmp_path):
        """Test building with rbxTeX."""
        input_content = b"""
%- block legend
This is the legend.
%- endblock
"""

        result = builder.build(input_content, context_with_template, problem_item)

        assert b'This is the legend' in result
        # Verify blocks.yml is written for non-externalized builds
        blocks_yml_path = context_with_template.root / 'blocks.yml'
        assert blocks_yml_path.exists()
        blocks_yml = blocks_yml_path.read_text()
        assert 'legend' in blocks_yml

    def test_build_with_explanations(self, builder, problem_item, tmp_path):
        """Test building with sample explanations."""
        # Create a template that includes sample explanations
        template_file = tmp_path / 'template.tex'
        template_content = """\\documentclass{article}
\\begin{document}
\\VAR{problem.blocks.legend}

%- for sample in problem.samples
%- if sample.explanation
Sample \\VAR{loop.index0}: \\VAR{sample.explanation}
%- endif
%- endfor
\\end{document}"""
        template_file.write_text(template_content)

        # Create context with the enhanced template
        params = rbxToTeX(
            type=ConversionType.rbxToTex, template=pathlib.Path('template.tex')
        )
        context = StatementBuilderContext(
            lang='en',
            languages=[],
            params=params,
            root=tmp_path,
        )

        input_content = b"""
%- block legend
Legend content.
%- endblock

%- block explanation_0
Explanation for first sample.
%- endblock
"""

        # Add samples to the problem
        sample = StatementSample(
            entry=create_dummy_entry(),
            inputPath=tmp_path / 'sample.in',
            outputPath=tmp_path / 'sample.out',
            hasOutput=True,
        )
        problem_item.samples = [sample]

        result = builder.build(input_content, context, problem_item)

        # Verify the template was rendered with the legend content
        assert b'Legend content.' in result
        # Verify the explanation was processed and included in the output
        assert b'Sample 0: Explanation for first sample.' in result
        # Verify blocks.yml is written
        blocks_yml_path = tmp_path / 'blocks.yml'
        assert blocks_yml_path.exists()
        blocks_yml = blocks_yml_path.read_text()
        assert 'legend' in blocks_yml

    def test_build_with_externalize(self, builder, problem_item, tmp_path):
        """Test building with externalize writes blocks.yml, blocks.ext.yml and blocks.sub.yml."""
        template_file = tmp_path / 'template.tex'
        template_file.write_text('\\VAR{problem.blocks.diagram}')

        params = rbxToTeX(
            type=ConversionType.rbxToTex,
            template=pathlib.Path('template.tex'),
            externalize=True,
        )
        context = StatementBuilderContext(
            lang='en',
            languages=[],
            params=params,
            root=tmp_path,
        )

        input_content = b"""
%- block diagram
\\begin{tikzpicture}
\\node {Test};
\\end{tikzpicture}
%- endblock
"""

        result = builder.build(input_content, context, problem_item)

        assert b'\\begin{tikzpicture}' in result

        # Non-externalized blocks file
        assert (tmp_path / 'blocks.yml').exists()
        blocks_yml = (tmp_path / 'blocks.yml').read_text()
        assert 'diagram' in blocks_yml
        assert 'tikzsetnextfilename' not in blocks_yml

        # Externalized blocks file
        assert (tmp_path / 'blocks.ext.yml').exists()
        blocks_ext_yml = (tmp_path / 'blocks.ext.yml').read_text()
        assert 'diagram' in blocks_ext_yml
        assert 'tikzsetnextfilename' in blocks_ext_yml

        # Substituted blocks file
        assert (tmp_path / 'blocks.sub.yml').exists()


class TestrbxMarkdownToTeXBuilder:
    """Test rbxMarkdownToTeXBuilder functionality."""

    @pytest.fixture
    def builder(self):
        """Create an rbxMarkdownToTeXBuilder instance."""
        return rbxMarkdownToTeXBuilder()

    @pytest.fixture
    def context(self, tmp_path):
        """Create a StatementBuilderContext for testing."""
        return StatementBuilderContext(
            lang='en',
            languages=[],
            params=rbxMarkdownToTeX(type=ConversionType.rbxMarkdownToTeX),
            root=tmp_path,
        )

    @pytest.fixture
    def problem_item(self):
        """Create a StatementBuilderProblem for testing."""
        package = Package(name='test-problem', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='statement',
            path=pathlib.Path('statement.rbx.md'),
            type=StatementType.rbxMarkdown,
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)
        return StatementBuilderProblem(
            package=package, statement=statement, limits=limits
        )

    def test_properties(self, builder):
        """Test builder properties."""
        assert builder.name() == ConversionType.rbxMarkdownToTeX
        assert isinstance(builder.default_params(), rbxMarkdownToTeX)
        assert builder.input_type() == StatementType.rbxMarkdown
        assert builder.output_type() == StatementType.rbxTeX
        assert builder.handles_problem() is True

    def test_build_contest(self, builder, context, tmp_path):
        """Test building contest statement with markdown."""
        contest = StatementBuilderContest(title='Test Contest')
        input_content = b"""
{% block intro %}
Welcome to {{ contest.title }}.
{% endblock %}
"""
        with patch('pypandoc.convert_text') as mock_convert:
            mock_convert.return_value = 'Converted Text'
            result = builder.build(input_content, context, contest)
            assert b'Converted Text' in result

    def test_build(self, builder, context, problem_item):
        """Test building markdown to tex."""
        input_content = b"""
{% block legend %}
This is **bold** text and *italic* text.
{% endblock %}

{% block input %}
- List item 1
- List item 2
{% endblock %}
"""

        with patch('pypandoc.convert_text') as mock_convert:
            mock_convert.side_effect = lambda content, to, from_: (
                f'\\textbf{{{content}}}'
            )

            result = builder.build(input_content, context, problem_item)

            assert isinstance(result, bytes)
            result_str = result.decode()
            assert '%- block legend' in result_str
            assert '%- block input' in result_str
            # Verify pypandoc was called for each block
            assert mock_convert.call_count >= 2


class TestTeX2PDFBuilder:
    """Test TeX2PDFBuilder functionality."""

    @pytest.fixture
    def builder(self):
        """Create a TeX2PDFBuilder instance."""
        return TeX2PDFBuilder()

    @pytest.fixture
    def context(self, tmp_path):
        """Create a StatementBuilderContext for testing."""
        return StatementBuilderContext(
            lang='en',
            languages=[],
            params=TexToPDF(type=ConversionType.TexToPDF),
            root=tmp_path,
        )

    @pytest.fixture
    def problem_item(self):
        """Create a StatementBuilderProblem for testing."""
        package = Package(name='test-problem', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='statement',
            path=pathlib.Path('statement.tex'),
            type=StatementType.TeX,
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)
        return StatementBuilderProblem(
            package=package, statement=statement, limits=limits
        )

    def test_properties(self, builder):
        """Test builder properties."""
        assert builder.name() == ConversionType.TexToPDF
        assert isinstance(builder.default_params(), TexToPDF)
        assert builder.input_type() == StatementType.TeX
        assert builder.output_type() == StatementType.PDF
        assert builder.handles_contest() is True
        assert builder.handles_problem() is True

    def test_build_success(self, builder, context, problem_item):
        """Test successful PDF building."""
        input_content = b'\\documentclass{article}\\begin{document}Hello\\end{document}'

        # The mock_pdflatex fixture should handle this automatically
        result = builder.build(input_content, context, problem_item)

        assert isinstance(result, bytes)

    def test_build_with_verbose(self, builder, context, problem_item):
        """Test building with verbose output."""
        input_content = b'\\documentclass{article}\\begin{document}Hello\\end{document}'

        result = builder.build(input_content, context, problem_item, verbose=True)

        assert isinstance(result, bytes)

    def test_build_failure(self, builder, context, problem_item):
        """Test handling of PDF build failure."""
        input_content = b'\\documentclass{article}\\begin{document}Hello\\end{document}'

        with patch('rbx.box.statements.latex.Latex') as mock_latex_class:
            import subprocess

            from rbx.box.statements.latex import LatexResult

            # Mock failed compilation
            mock_latex = mock_latex_class.return_value
            mock_latex.build_pdf.return_value = LatexResult(
                result=subprocess.CompletedProcess(
                    args='', returncode=1, stdout=b'error', stderr=b''
                ),
                pdf=None,
            )

            with pytest.raises(typer.Exit):
                builder.build(input_content, context, problem_item)

    def test_build_rerun(self, builder, context, problem_item):
        """Test PDF build rerun logic."""
        input_content = b'\\documentclass{article}\\begin{document}Hello\\end{document}'

        with (
            patch('rbx.box.statements.latex.Latex') as mock_latex_class,
            patch('rbx.box.statements.latex.should_rerun') as mock_should_rerun,
        ):
            import subprocess

            from rbx.box.statements.latex import LatexResult

            # Mock successful compilation
            mock_latex = mock_latex_class.return_value
            mock_latex.build_pdf.return_value = LatexResult(
                result=subprocess.CompletedProcess(
                    args='', returncode=0, stdout=b'output', stderr=b''
                ),
                pdf=b'pdf content',
            )

            # Mock should_rerun to return True once, then False
            mock_should_rerun.side_effect = [True, False]

            result = builder.build(input_content, context, problem_item)

            assert isinstance(result, bytes)
            assert mock_latex.build_pdf.call_count == 2

    def test_build_with_demacro(self, builder, problem_item, tmp_path):
        """Test building with demacro enabled collects macro definitions."""
        params = TexToPDF(type=ConversionType.TexToPDF, demacro=True)
        context = StatementBuilderContext(
            lang='en',
            languages=[],
            params=params,
            root=tmp_path,
        )
        input_content = b'\\documentclass{article}\\begin{document}Hello\\end{document}'

        with patch(
            'rbx.box.statements.builders.collect_macro_definitions'
        ) as mock_collect:
            mock_defs = mock_collect.return_value
            result = builder.build(input_content, context, problem_item)

            assert isinstance(result, bytes)
            mock_collect.assert_called_once_with(tmp_path / 'statement.tex')
            mock_defs.to_json_file.assert_called_once_with(tmp_path / 'macros.json')


class TestExplainedStatementSample:
    """Test ExplainedStatementSample functionality."""

    def test_creation_from_statement_sample(self, tmp_path):
        """Test creating ExplainedStatementSample from StatementSample."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        input_file.write_text('test input')
        output_file.write_text('test output')

        sample = StatementSample(
            entry=create_dummy_entry(),
            inputPath=input_file,
            outputPath=output_file,
            hasOutput=True,
        )

        explained_sample = ExplainedStatementSample(
            **sample.model_dump(), explanation='This is an explanation'
        )

        assert explained_sample.inputPath == input_file
        assert explained_sample.outputPath == output_file
        assert explained_sample.hasOutput is True
        assert explained_sample.explanation == 'This is an explanation'

    def test_creation_without_explanation(self, tmp_path):
        """Test creating ExplainedStatementSample without explanation."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        input_file.write_text('test input')
        output_file.write_text('test output')

        explained_sample = ExplainedStatementSample(
            entry=create_dummy_entry(),
            inputPath=input_file,
            outputPath=output_file,
            hasOutput=True,
        )

        assert explained_sample.explanation is None

    def test_from_statement_sample_with_explanation_path(self, tmp_path):
        """Test creating ExplainedStatementSample with explanation path."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        explanation_file = tmp_path / 'test.tex'
        input_file.write_text('test input')
        output_file.write_text('test output')
        explanation_file.write_text('Explanation from file')

        sample = StatementSample(
            entry=create_dummy_entry(),
            inputPath=input_file,
            outputPath=output_file,
            explanationPath=explanation_file,
        )

        explained = ExplainedStatementSample.from_statement_sample(sample)

        assert explained.explanation == 'Explanation from file'

    def test_from_statement_sample_with_explanation_block(self, tmp_path):
        """Test creating ExplainedStatementSample with explanation block."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        input_file.write_text('test input')
        output_file.write_text('test output')

        sample = StatementSample(
            entry=create_dummy_entry(),
            inputPath=input_file,
            outputPath=output_file,
        )

        explained = ExplainedStatementSample.from_statement_sample(
            sample, explanation_block='Explanation from block'
        )

        assert explained.explanation == 'Explanation from block'

    def test_from_statement_sample_path_takes_precedence(self, tmp_path):
        """Test that explanation path takes precedence over explanation block."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        explanation_file = tmp_path / 'test.tex'
        input_file.write_text('test input')
        output_file.write_text('test output')
        explanation_file.write_text('Explanation from file')

        sample = StatementSample(
            entry=create_dummy_entry(),
            inputPath=input_file,
            outputPath=output_file,
            explanationPath=explanation_file,
        )

        explained = ExplainedStatementSample.from_statement_sample(
            sample, explanation_block='Explanation from block'
        )

        assert explained.explanation == 'Explanation from file'

    def test_from_statement_samples(self, tmp_path):
        """Test creating multiple ExplainedStatementSamples."""
        samples = []
        for i in range(3):
            input_file = tmp_path / f'test{i}.in'
            output_file = tmp_path / f'test{i}.out'
            input_file.write_text(f'input {i}')
            output_file.write_text(f'output {i}')
            samples.append(
                StatementSample(
                    entry=create_dummy_entry(),
                    inputPath=input_file,
                    outputPath=output_file,
                )
            )

        explained_samples = ExplainedStatementSample.from_statement_samples(samples)

        assert len(explained_samples) == 3
        assert explained_samples[0].explanation is None
        assert explained_samples[1].explanation is None
        assert explained_samples[2].explanation is None


class TestIntegration:
    """Integration tests for statement builders."""

    def test_full_pipeline_jinja_to_pdf(self, tmp_path):
        """Test complete pipeline from JinjaTeX to PDF."""
        # Create test package and statement
        package = Package(
            name='integration-test',
            timeLimit=1000,
            memoryLimit=256,
            vars={'MAX_N': 1000},
        )
        statement = Statement(
            name='main',
            path=tmp_path / 'statement.jinja.tex',
            type=StatementType.JinjaTeX,
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)

        # Create test content
        content = (
            b'Problem: \\VAR{problem.package.name}, Max: \\VAR{problem.statement.name}'
        )

        # Test JinjaTeX builder
        jinja_builder = JinjaTeXBuilder()
        context = StatementBuilderContext(
            lang='en',
            languages=[],
            params=jinja_builder.default_params(),
            root=tmp_path,
        )
        problem = StatementBuilderProblem(
            package=package, statement=statement, limits=limits
        )

        tex_result = jinja_builder.build(content, context, problem)
        assert b'Problem: integration-test' in tex_result
        assert b'Max: main' in tex_result

        # Test TeX2PDF builder
        pdf_builder = TeX2PDFBuilder()
        pdf_context = StatementBuilderContext(
            lang='en',
            languages=[],
            params=pdf_builder.default_params(),
            root=tmp_path,
        )

        pdf_result = pdf_builder.build(tex_result, pdf_context, problem)
        assert isinstance(pdf_result, bytes)

    def test_rbx_tex_with_template_pipeline(self, tmp_path):
        """Test rbxTeX to TeX pipeline with template."""
        # Create template
        template_file = tmp_path / 'template.tex'
        template_file.write_text(
            '\\documentclass{article}\\begin{document}\\VAR{problem.blocks.legend}\\end{document}'
        )

        # Create package and statement
        package = Package(name='rbx-test', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='main',
            path=tmp_path / 'statement.rbx.tex',
            type=StatementType.rbxTeX,
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)

        # Create rbxTeX content - using package.name instead of problem.package.name
        content = b"""
%- block legend
This is the legend for \\VAR{package.name}.
%- endblock
"""

        # Test rbxTeX builder
        builder = rbxTeXBuilder()
        params = rbxToTeX(
            type=ConversionType.rbxToTex, template=pathlib.Path('template.tex')
        )
        context = StatementBuilderContext(
            lang='en', languages=[], params=params, root=tmp_path
        )
        problem = StatementBuilderProblem(
            package=package, statement=statement, limits=limits
        )

        result = builder.build(content, context, problem)
        assert b'This is the legend for rbx-test' in result
        # Verify blocks.yml is written
        assert (tmp_path / 'blocks.yml').exists()
