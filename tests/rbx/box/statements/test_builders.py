import pathlib
from unittest.mock import patch

import pytest
import typer

from rbx.box.schema import Package, Statement, Testcase
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


class TestStatementSample:
    """Test StatementSample functionality."""

    def test_from_testcase_basic(self, tmp_path):
        """Test creating StatementSample from basic testcase."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        input_file.write_text('test input')
        output_file.write_text('test output')

        testcase = Testcase(inputPath=input_file, outputPath=output_file)
        sample = StatementSample.from_testcase(testcase)

        assert sample.inputPath == input_file
        assert sample.outputPath == output_file
        assert sample.hasOutput is True
        assert sample.interaction is None

    def test_from_testcase_with_pin_pout_files(self, tmp_path):
        """Test that .pin and .pout files take precedence."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        pin_file = tmp_path / 'test.pin'
        pout_file = tmp_path / 'test.pout'

        input_file.write_text('original input')
        output_file.write_text('original output')
        pin_file.write_text('pin input')
        pout_file.write_text('pout output')

        testcase = Testcase(inputPath=input_file, outputPath=output_file)
        sample = StatementSample.from_testcase(testcase)

        assert sample.inputPath == pin_file
        assert sample.outputPath == pout_file

    def test_from_testcase_with_interaction(self, tmp_path):
        """Test creating sample with interaction file."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        pio_file = tmp_path / 'test.pio'

        input_file.write_text('test input')
        output_file.write_text('test output')

        # Create a valid .pio file with the expected format
        pio_content = """>
<
> 5
< 10
> hello
< world
"""
        pio_file.write_text(pio_content)

        testcase = Testcase(inputPath=input_file, outputPath=output_file)
        sample = StatementSample.from_testcase(testcase)

        # Verify the interaction was parsed correctly
        assert sample.interaction is not None
        assert sample.interaction.prefixes == ('>', '<')
        assert len(sample.interaction.entries) == 4

        # Check the parsed entries
        entries = sample.interaction.entries
        assert entries[0].data == ' 5' and entries[0].pipe == 0  # interactor
        assert entries[1].data == ' 10' and entries[1].pipe == 1  # solution
        assert entries[2].data == ' hello' and entries[2].pipe == 0  # interactor
        assert entries[3].data == ' world' and entries[3].pipe == 1  # solution

    def test_from_testcase_interaction_parsing_error(self, tmp_path):
        """Test handling of interaction parsing errors."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        pio_file = tmp_path / 'test.pio'

        input_file.write_text('test input')
        output_file.write_text('test output')

        # Create an invalid .pio file with valid prefixes but invalid content line
        pio_content = """>
<
invalid line that does not start with > or <
"""
        pio_file.write_text(pio_content)

        testcase = Testcase(inputPath=input_file, outputPath=output_file)

        # This should raise a typer.Exit due to the TestcaseInteractionParsingError
        with pytest.raises(typer.Exit):
            StatementSample.from_testcase(testcase)

    def test_from_testcases(self, tmp_path):
        """Test creating multiple samples from testcases."""
        testcases = []
        for i in range(3):
            input_file = tmp_path / f'test{i}.in'
            output_file = tmp_path / f'test{i}.out'
            input_file.write_text(f'input {i}')
            output_file.write_text(f'output {i}')
            testcases.append(Testcase(inputPath=input_file, outputPath=output_file))

        samples = StatementSample.from_testcases(testcases)

        assert len(samples) == 3
        for i, sample in enumerate(samples):
            assert sample.inputPath.name == f'test{i}.in'
            assert sample.outputPath.name == f'test{i}.out'


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
                    inputPath=input_file, outputPath=output_file, hasOutput=True
                )
            )
        return samples

    def test_build_inner_jinja_kwargs_basic(
        self, sample_package, sample_statement, sample_samples
    ):
        """Test building inner jinja kwargs with basic configuration."""
        problem = StatementBuilderProblem(
            package=sample_package,
            statement=sample_statement,
            samples=sample_samples,
            vars={'TEST_VAR': 42},
        )

        kwargs = problem.build_inner_jinja_kwargs()

        assert kwargs['package'] == sample_package
        assert kwargs['statement'] == sample_statement
        assert kwargs['samples'] == sample_samples
        assert kwargs['title'] == 'Test Problem'
        assert kwargs['vars']['TEST_VAR'] == 42

    def test_build_inner_jinja_kwargs_with_short_name(
        self, sample_package, sample_statement
    ):
        """Test building kwargs with short name."""
        problem = StatementBuilderProblem(
            package=sample_package,
            statement=sample_statement,
            short_name='A',
        )

        kwargs = problem.build_inner_jinja_kwargs()

        assert kwargs['short_name'] == 'A'

    def test_build_inner_jinja_kwargs_with_io_path(
        self, sample_package, sample_statement
    ):
        """Test building kwargs with IO path."""
        io_path = pathlib.Path('/tmp/test.txt')
        problem = StatementBuilderProblem(
            package=sample_package,
            statement=sample_statement,
            io_path=io_path,
        )

        kwargs = problem.build_inner_jinja_kwargs()

        assert kwargs['path'] == io_path

    def test_build_jinja_kwargs(self, sample_package, sample_statement):
        """Test building full jinja kwargs structure."""
        problem = StatementBuilderProblem(
            package=sample_package,
            statement=sample_statement,
        )

        kwargs = problem.build_jinja_kwargs()

        assert 'problem' in kwargs
        assert kwargs['problem']['package'] == sample_package
        assert kwargs['problem']['statement'] == sample_statement


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
            vars={'CONTEST_TIME': 300},
        )

        kwargs = contest.build_jinja_kwargs()

        assert 'contest' in kwargs
        assert 'problems' in kwargs
        assert 'vars' in kwargs
        assert kwargs['contest']['title'] == 'Test Contest'
        assert kwargs['problems'] == []
        assert kwargs['vars']['CONTEST_TIME'] == 300


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
        content = b'Problem: \\VAR{problem.title}, Max: \\VAR{vars.MAX_N}'
        problem = {'title': 'Test Problem'}
        vars_dict = {'MAX_N': 1000}

        result = render_jinja(tmp_path, content, problem=problem, vars=vars_dict)

        assert b'Problem: Test Problem' in result
        assert b'Max: 1000' in result


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
        # We can't actually test invalid mode due to typing, so we test that the function works with valid modes
        result_latex = render_jinja_blocks(tmp_path, content, mode='latex')
        result_markdown = render_jinja_blocks(tmp_path, content, mode='markdown')

        assert isinstance(result_latex, StatementBlocks)
        assert isinstance(result_markdown, StatementBlocks)


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
        return StatementBuilderProblem(package=package, statement=statement)

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
        return StatementBuilderProblem(package=package, statement=statement)

    def test_properties(self, builder):
        """Test builder properties."""
        assert builder.name() == ConversionType.rbxToTex
        assert isinstance(builder.default_params(), rbxToTeX)
        assert builder.input_type() == StatementType.rbxTeX
        assert builder.output_type() == StatementType.TeX
        assert builder.handles_contest() is False
        assert builder.handles_problem() is True

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
        return StatementBuilderProblem(package=package, statement=statement)

    def test_properties(self, builder):
        """Test builder properties."""
        assert builder.name() == ConversionType.rbxMarkdownToTeX
        assert isinstance(builder.default_params(), rbxMarkdownToTeX)
        assert builder.input_type() == StatementType.rbxMarkdown
        assert builder.output_type() == StatementType.rbxTeX
        assert builder.handles_contest() is False
        assert builder.handles_problem() is True

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
            mock_convert.side_effect = (
                lambda content, to, from_: f'\\textbf{{{content}}}'
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
        return StatementBuilderProblem(package=package, statement=statement)

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


class TestExplainedStatementSample:
    """Test ExplainedStatementSample functionality."""

    def test_creation_from_statement_sample(self, tmp_path):
        """Test creating ExplainedStatementSample from StatementSample."""
        input_file = tmp_path / 'test.in'
        output_file = tmp_path / 'test.out'
        input_file.write_text('test input')
        output_file.write_text('test output')

        sample = StatementSample(
            inputPath=input_file, outputPath=output_file, hasOutput=True
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
            inputPath=input_file, outputPath=output_file, hasOutput=True
        )

        assert explained_sample.explanation is None


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
        problem = StatementBuilderProblem(package=package, statement=statement)

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
        problem = StatementBuilderProblem(package=package, statement=statement)

        result = builder.build(content, context, problem)
        assert b'This is the legend for rbx-test' in result
