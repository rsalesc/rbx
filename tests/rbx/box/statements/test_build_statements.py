import os
import pathlib
from typing import List, cast
from unittest.mock import MagicMock, patch

import pytest
import typer

from rbx.box.schema import Package, Statement
from rbx.box.statements.build_statements import (
    build_statement,
    build_statement_bytes,
    get_builder,
    get_builders,
    get_environment_languages_for_statement,
    get_implicit_builders,
    get_relative_assets,
)
from rbx.box.statements.builders import BUILDER_LIST
from rbx.box.statements.schema import (
    ConversionStep,
    ConversionType,
    JinjaTeX,
    StatementType,
    TexToPDF,
    rbxToTeX,
)
from rbx.box.testing import testing_package


@pytest.fixture
def chdir_tmp_path(tmp_path):
    """Fixture to change to tmp_path directory and restore original directory after test."""
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        yield tmp_path
    finally:
        os.chdir(original_cwd)


@pytest.fixture
def mock_environment():
    """Fixture providing a mock environment with sample languages."""
    from rbx.box.environment import (
        CompilationConfig,
        EnvironmentLanguage,
        ExecutionConfig,
    )

    # Create real EnvironmentLanguage objects using proper Pydantic models
    languages = [
        EnvironmentLanguage(
            name='cpp',
            readableName='C++',
            extension='.cpp',
            execution=ExecutionConfig(
                command='g++ -o {executable} {compilable} && ./{executable}'
            ),
        ),
        EnvironmentLanguage(
            name='python',
            readableName='Python',
            extension='.py',
            execution=ExecutionConfig(command='python {compilable}'),
        ),
        EnvironmentLanguage(
            name='java',
            readableName=None,  # Test fallback to name
            extension='.java',
            execution=ExecutionConfig(command='java {compilable}'),
        ),
    ]

    with patch(
        'rbx.box.statements.build_statements.environment.get_environment'
    ) as mock_get_env, patch(
        'rbx.box.statements.build_statements.environment.get_compilation_config'
    ) as mock_comp_cfg, patch(
        'rbx.box.statements.build_statements.environment.get_execution_config'
    ) as mock_exec_cfg:
        # Create environment object with real EnvironmentLanguage objects
        mock_env = type('Environment', (), {'languages': languages})()
        mock_get_env.return_value = mock_env

        def mock_compilation_config(lang_name):
            # Return real CompilationConfig objects
            if lang_name == 'cpp':
                return CompilationConfig(commands=['g++ -std=c++17', 'echo compiled'])
            else:
                return CompilationConfig(commands=None)

        def mock_execution_config(lang_name):
            # Return real ExecutionConfig objects
            if lang_name == 'python':
                return ExecutionConfig(command='python')
            else:
                return ExecutionConfig(command='')

        mock_comp_cfg.side_effect = mock_compilation_config
        mock_exec_cfg.side_effect = mock_execution_config

        yield mock_env


@pytest.fixture
def mock_samples():
    """Fixture to mock get_samples function to avoid package system dependencies."""
    with patch('rbx.box.statements.build_statements.get_samples') as mock_get_samples:
        mock_get_samples.return_value = []
        yield mock_get_samples


class TestGetEnvironmentLanguagesForStatement:
    """Test get_environment_languages_for_statement function."""

    def test_get_languages_with_compilation_commands(self, mock_environment):
        """Test language extraction when compilation config has commands."""
        languages = get_environment_languages_for_statement()

        assert len(languages) == 3

        # Find languages by id
        lang_map = {lang.id: lang for lang in languages}

        # C++ should use compilation commands
        cpp_lang = lang_map['cpp']
        assert cpp_lang.name == 'C++'
        assert cpp_lang.command == 'g++ -std=c++17 && echo compiled'

        # Python should use execution command
        python_lang = lang_map['python']
        assert python_lang.name == 'Python'
        assert python_lang.command == 'python'

        # Java should fall back to name when readableName is None
        java_lang = lang_map['java']
        assert java_lang.name == 'java'
        assert java_lang.command == ''


class TestGetBuilder:
    """Test get_builder function."""

    def test_get_existing_builder(self):
        """Test getting an existing builder from the list."""
        builder = get_builder(ConversionType.JinjaTeX, BUILDER_LIST)

        assert builder is not None
        assert builder.name() == ConversionType.JinjaTeX

    def test_get_nonexistent_builder_raises_exit(self):
        """Test that requesting a non-existent builder raises typer.Exit."""
        fake_conversion_type = cast(ConversionType, 'nonexistent_builder')

        with pytest.raises(typer.Exit):
            get_builder(fake_conversion_type, BUILDER_LIST)


class TestGetImplicitBuilders:
    """Test get_implicit_builders function."""

    def test_direct_conversion_possible(self):
        """Test when direct conversion is possible."""
        # JinjaTeX to TeX should be directly possible
        builders = get_implicit_builders(StatementType.JinjaTeX, StatementType.TeX)

        assert builders is not None
        assert len(builders) == 1
        assert builders[0].name() == ConversionType.JinjaTeX

    def test_multi_step_conversion(self):
        """Test when multi-step conversion is needed."""
        # JinjaTeX to PDF should require multiple steps
        builders = get_implicit_builders(StatementType.JinjaTeX, StatementType.PDF)

        assert builders is not None
        assert len(builders) >= 2
        # Should include JinjaTeX->TeX and TeX->PDF
        builder_names = [builder.name() for builder in builders]
        assert ConversionType.JinjaTeX in builder_names
        assert ConversionType.TexToPDF in builder_names

    def test_impossible_conversion(self):
        """Test when conversion is not possible."""
        # Create fake statement types that have no conversion path
        fake_input_type = cast(StatementType, 'FakeInputType')
        fake_output_type = cast(StatementType, 'FakeOutputType')

        builders = get_implicit_builders(fake_input_type, fake_output_type)

        assert builders is None


class TestGetBuilders:
    """Test get_builders function."""

    def test_no_steps_with_same_input_output_types(self):
        """Test when input and output types are the same with no steps."""
        builders = get_builders(
            statement_id='test',
            steps=[],
            configure=[],
            input_type=StatementType.TeX,
            output_type=StatementType.TeX,
        )

        assert builders == []

    def test_explicit_steps(self):
        """Test with explicitly defined conversion steps."""
        steps = [
            JinjaTeX(type=ConversionType.JinjaTeX),
            TexToPDF(type=ConversionType.TexToPDF),
        ]

        builders = get_builders(
            statement_id='test',
            steps=steps,
            configure=[],
            input_type=StatementType.JinjaTeX,
            output_type=None,
        )

        assert len(builders) == 2
        assert builders[0][0].name() == ConversionType.JinjaTeX
        assert builders[1][0].name() == ConversionType.TexToPDF

    def test_implicit_conversion_with_output_type(self):
        """Test implicit conversion when output type is specified."""
        builders = get_builders(
            statement_id='test',
            steps=[],
            configure=[],
            input_type=StatementType.JinjaTeX,
            output_type=StatementType.PDF,
        )

        assert len(builders) >= 2
        builder_names = [builder[0].name() for builder in builders]
        assert ConversionType.JinjaTeX in builder_names
        assert ConversionType.TexToPDF in builder_names

    def test_configure_overrides(self):
        """Test that configure parameters override default parameters."""
        configure_steps: List[ConversionStep] = [
            rbxToTeX(type=ConversionType.rbxToTex, template=pathlib.Path('custom.tex'))
        ]

        builders = get_builders(
            statement_id='test',
            steps=[rbxToTeX(type=ConversionType.rbxToTex)],
            configure=configure_steps,
            input_type=StatementType.rbxTeX,
            output_type=None,
        )

        assert len(builders) == 1
        builder, params = builders[0]
        assert builder.name() == ConversionType.rbxToTex
        # Check if params is rbxToTeX before accessing template
        if isinstance(params, rbxToTeX):
            assert params.template == pathlib.Path('custom.tex')


class TestGetRelativeAssets:
    """Test get_relative_assets function."""

    def test_basic_asset_resolution(self, chdir_tmp_path):
        """Test basic asset file resolution."""
        # Create test files in the working directory
        asset_file = chdir_tmp_path / 'test.png'
        asset_file.write_text('fake image content')

        assets = get_relative_assets(chdir_tmp_path, ['test.png'])

        assert len(assets) == 1
        abs_path, rel_path = assets[0]
        assert abs_path.name == 'test.png'
        assert rel_path == pathlib.Path('test.png')

    def test_glob_pattern_asset_resolution(self, chdir_tmp_path):
        """Test asset resolution with glob patterns."""
        # Create multiple test files
        for i in range(3):
            (chdir_tmp_path / f'image{i}.png').write_text(f'content {i}')

        # Use real glob implementation with actual files
        assets = get_relative_assets(chdir_tmp_path, ['*.png'])

        assert len(assets) == 3
        png_files = [rel_path.name for _, rel_path in assets]
        assert 'image0.png' in png_files
        assert 'image1.png' in png_files
        assert 'image2.png' in png_files

    def test_nonexistent_asset_raises_exit(self, chdir_tmp_path):
        """Test that non-existent asset without glob raises typer.Exit."""
        with pytest.raises(typer.Exit):
            get_relative_assets(chdir_tmp_path, ['nonexistent.png'])

    def test_asset_outside_relative_path_raises_exit(self, tmp_path):
        """Test that asset outside relative path raises typer.Exit."""
        # Create asset outside the base directory
        outside_dir = tmp_path.parent / 'outside'
        outside_dir.mkdir()
        outside_asset = outside_dir / 'outside.txt'
        outside_asset.write_text('outside content')

        base_dir = tmp_path / 'base'
        base_dir.mkdir()

        # Change to base directory for this test
        original_cwd = os.getcwd()
        try:
            os.chdir(base_dir)
            with pytest.raises(typer.Exit):
                get_relative_assets(base_dir, [str(outside_asset)])
        finally:
            os.chdir(original_cwd)


class TestBuildStatementBytesExtended:
    """Extended tests for build_statement_bytes function covering untested parameters."""

    @pytest.fixture
    def sample_package(self):
        """Create a sample package for testing."""
        return Package(
            name='test-problem', timeLimit=1000, memoryLimit=256, vars={'MAX_N': 1000}
        )

    @pytest.fixture
    def sample_statement(self, tmp_path):
        """Create a sample statement for testing."""
        statement_file = tmp_path / 'statement.jinja.tex'
        statement_file.write_text('Problem: \\VAR{problem.package.name}')

        return Statement(
            name='test-statement',
            language='en',
            title='Test Problem',
            path=statement_file,
            type=StatementType.JinjaTeX,
            assets=[],
        )

    @pytest.fixture
    def mock_limits(self):
        """Mock the limits_info.get_limits_profile function."""
        with patch(
            'rbx.box.statements.build_statements.limits_info.get_limits_profile'
        ) as mock:
            # Return a simple limits profile mock
            mock.return_value = MagicMock()
            yield mock

    def test_build_simple_statement(
        self, sample_package, sample_statement, mock_samples, mock_limits
    ):
        """Test building a simple statement."""
        content, output_type = build_statement_bytes(
            statement=sample_statement,
            pkg=sample_package,
            output_type=StatementType.TeX,
        )

        assert isinstance(content, bytes)
        assert output_type == StatementType.TeX
        assert b'Problem: test-problem' in content

    def test_build_with_assets(
        self, sample_package, chdir_tmp_path, mock_samples, mock_limits
    ):
        """Test building statement with assets."""
        # Create asset files
        asset_file = chdir_tmp_path / 'style.sty'
        asset_file.write_text('% Custom style file')

        statement_file = chdir_tmp_path / 'statement.jinja.tex'
        statement_file.write_text('\\usepackage{style}\nProblem content')

        statement = Statement(
            name='test-statement',
            language='en',
            path=statement_file,
            type=StatementType.JinjaTeX,
            assets=['style.sty'],
        )

        content, output_type = build_statement_bytes(
            statement=statement,
            pkg=sample_package,
            output_type=StatementType.TeX,
        )

        assert isinstance(content, bytes)
        assert output_type == StatementType.TeX
        assert b'Problem content' in content

    def test_build_with_custom_vars(
        self, sample_package, tmp_path, mock_samples, mock_limits
    ):
        """Test building statement with custom variables."""
        statement_file = tmp_path / 'statement.jinja.tex'
        statement_file.write_text(
            'Max N: \\VAR{problem.vars.MAX_N}, Custom: \\VAR{problem.vars.CUSTOM_VAR}, Nested: \\VAR{problem.vars.NESTED.KEY}'
        )

        statement = Statement(
            name='test-statement',
            language='en',
            path=statement_file,
            type=StatementType.JinjaTeX,
        )

        content, output_type = build_statement_bytes(
            statement=statement,
            pkg=sample_package,
            output_type=StatementType.TeX,
            custom_vars={'CUSTOM_VAR': 'custom_value', 'NESTED.KEY': 'VALUE'},
        )

        assert b'Max N: 1000' in content
        assert b'Custom: custom_value' in content
        assert b'Nested: VALUE' in content

    def test_build_nonexistent_statement_file_raises_exit(
        self, sample_package, tmp_path
    ):
        """Test that non-existent statement file raises typer.Exit."""
        nonexistent_file = tmp_path / 'nonexistent.tex'

        statement = Statement(
            name='test-statement',
            language='en',
            path=nonexistent_file,
            type=StatementType.TeX,
        )

        with pytest.raises(typer.Exit):
            build_statement_bytes(
                statement=statement,
                pkg=sample_package,
            )

    def test_build_with_overridden_params(
        self, sample_package, sample_statement, mock_samples, tmp_path, mock_limits
    ):
        """Test building statement with overridden parameters."""
        # Create a custom template for overridden params
        custom_template = tmp_path / 'custom.tex'
        custom_template.write_text(
            'Custom template content: \\VAR{problem.package.name}'
        )

        overridden_params = {
            ConversionType.JinjaTeX: cast(
                ConversionStep, JinjaTeX(type=ConversionType.JinjaTeX)
            )
        }

        content, output_type = build_statement_bytes(
            statement=sample_statement,
            pkg=sample_package,
            output_type=StatementType.TeX,
            overridden_params=overridden_params,
            overridden_params_root=tmp_path,
        )

        assert isinstance(content, bytes)
        assert output_type == StatementType.TeX
        # The overridden parameters are passed but the original statement template is still used
        assert b'Problem: test-problem' in content

    def test_build_with_overridden_assets(
        self, sample_package, sample_statement, mock_samples, tmp_path, mock_limits
    ):
        """Test building statement with overridden assets."""
        # Create custom asset files
        custom_asset1 = tmp_path / 'custom1.sty'
        custom_asset1.write_text('% Custom style 1')
        custom_asset2 = tmp_path / 'custom2.cls'
        custom_asset2.write_text('% Custom class')

        overridden_assets = [
            (custom_asset1, pathlib.Path('custom1.sty')),
            (custom_asset2, pathlib.Path('custom2.cls')),
        ]

        content, output_type = build_statement_bytes(
            statement=sample_statement,
            pkg=sample_package,
            output_type=StatementType.TeX,
            overridden_assets=overridden_assets,
        )

        assert isinstance(content, bytes)
        assert output_type == StatementType.TeX

    def test_build_with_short_name(
        self, sample_package, mock_samples, mock_limits, tmp_path
    ):
        """Test building statement with custom short_name."""
        # Create a statement that uses short_name in the template
        statement_file = tmp_path / 'statement.jinja.tex'
        statement_file.write_text('Problem: \\VAR{problem.short_name or "Unknown"}')

        statement = Statement(
            name='test-statement',
            language='en',
            title='Test Problem',
            path=statement_file,
            type=StatementType.JinjaTeX,
            assets=[],
        )

        content, output_type = build_statement_bytes(
            statement=statement,
            pkg=sample_package,
            output_type=StatementType.TeX,
            short_name='PROB_A',
        )

        assert isinstance(content, bytes)
        assert output_type == StatementType.TeX
        assert b'PROB_A' in content

    def test_build_with_use_samples_false(
        self, sample_package, sample_statement, mock_limits
    ):
        """Test building statement with use_samples=False."""
        # Don't use mock_samples fixture to test actual behavior
        with patch(
            'rbx.box.statements.build_statements.get_samples'
        ) as mock_get_samples:
            mock_get_samples.return_value = []

            content, output_type = build_statement_bytes(
                statement=sample_statement,
                pkg=sample_package,
                output_type=StatementType.TeX,
                use_samples=False,
            )

            assert isinstance(content, bytes)
            assert output_type == StatementType.TeX
            # get_samples should NOT be called when use_samples=False based on the conditional logic
            mock_get_samples.assert_not_called()

    def test_build_with_combined_overrides(
        self, sample_package, sample_statement, mock_samples, tmp_path, mock_limits
    ):
        """Test building statement with multiple override parameters combined."""
        # Create custom template and assets
        custom_template = tmp_path / 'combined.tex'
        custom_template.write_text(
            'Combined: \\VAR{problem.short_name} - \\VAR{problem.package.name}'
        )
        custom_asset = tmp_path / 'combined.sty'
        custom_asset.write_text('% Combined style')

        overridden_params = {
            ConversionType.JinjaTeX: cast(
                ConversionStep, JinjaTeX(type=ConversionType.JinjaTeX)
            )
        }
        overridden_assets = [(custom_asset, pathlib.Path('combined.sty'))]

        content, output_type = build_statement_bytes(
            statement=sample_statement,
            pkg=sample_package,
            output_type=StatementType.TeX,
            short_name='COMBINED',
            overridden_params_root=tmp_path,
            overridden_params=overridden_params,
            overridden_assets=overridden_assets,
            use_samples=False,
            custom_vars={'EXTRA_VAR': 'extra_value'},
        )

        assert isinstance(content, bytes)
        assert output_type == StatementType.TeX
        # The basic template should still be used since overridden_params doesn't specify a custom template
        assert b'Problem: test-problem' in content


class TestBuildStatement:
    """Test build_statement function."""

    @pytest.fixture
    def sample_package(self):
        """Create a sample package for testing."""
        return Package(
            name='test-problem',
            timeLimit=1000,
            memoryLimit=256,
        )

    @pytest.fixture
    def mock_limits(self):
        """Mock the limits_info.get_limits_profile function."""
        with patch(
            'rbx.box.statements.build_statements.limits_info.get_limits_profile'
        ) as mock:
            # Return a simple limits profile mock
            mock.return_value = MagicMock()
            yield mock

    def test_build_statement_creates_file(
        self, sample_package, tmp_path, mock_samples, mock_limits, mock_environment
    ):
        """Test that build_statement creates the output file."""
        statement_file = tmp_path / 'statement.jinja.tex'
        statement_file.write_text('Simple statement content')

        statement = Statement(
            name='test-statement',
            language='en',
            path=statement_file,
            type=StatementType.JinjaTeX,
        )

        # Mock the package build path
        build_dir = tmp_path / 'build'
        build_dir.mkdir()

        with patch(
            'rbx.box.statements.build_statements.package.get_build_path',
            return_value=build_dir,
        ), patch(
            'rbx.box.statements.build_statements.naming.get_problem_shortname',
            return_value='A',
        ):
            result_path = build_statement(
                statement=statement,
                pkg=sample_package,
                output_type=StatementType.TeX,
            )

        assert result_path.exists()
        assert result_path.name == 'test-statement.tex'
        assert result_path.parent == build_dir
        content = result_path.read_text()
        assert 'Simple statement content' in content


class TestBuildStatementsIntegration:
    """Integration tests using testing package fixtures."""

    def test_full_statement_build_pipeline(
        self, testing_pkg: testing_package.TestingPackage, mock_samples
    ):
        """Test complete statement building pipeline with testing package."""
        # Set up a complete problem package
        problem_yml = testing_pkg.add_file('problem.rbx.yml')
        problem_yml.write_text("""
name: "integration-test"
timeLimit: 1000
memoryLimit: 256
statements:
  - name: "main"
    title: "Integration Test Problem"
    path: "statement/main.jinja.tex"
    type: "JinjaTeX"
    language: "en"
    assets:
      - "statement/style.sty"
vars:
  MAX_N: 100000
""")

        # Create statement content
        statement_file = testing_pkg.add_file('statement/main.jinja.tex')
        statement_file.write_text("""
\\documentclass{article}
\\usepackage{style}
\\begin{document}
\\title{\\VAR{problem.statement.title}}
\\maketitle

Problem \\VAR{problem.package.name} with constraint MAX_N = \\VAR{problem.vars.MAX_N}.

\\end{document}
""")

        # Create asset file
        asset_file = testing_pkg.add_file('statement/style.sty')
        asset_file.write_text('% Custom style package')

        pkg = testing_pkg.yml
        statement = pkg.expanded_statements[0]

        result_path = build_statement(
            statement=statement,
            pkg=pkg,
            output_type=StatementType.TeX,
        )

        # Verify the output
        assert result_path.exists()
        content = result_path.read_text()
        assert 'Integration Test Problem' in content
        assert 'integration-test' in content
        assert 'MAX_N = 100000' in content

    def test_build_with_samples(self, testing_pkg: testing_package.TestingPackage):
        """Test building statement with sample testcases."""
        # Set up problem with samples
        problem_yml = testing_pkg.add_file('problem.rbx.yml')
        problem_yml.write_text("""
name: "sample-test"
timeLimit: 1000
memoryLimit: 256
testcases:
  - name: "samples"
    testcaseGlob: "tests/*.in"
statements:
  - name: "main"
    path: "statement.jinja.tex"
    type: "JinjaTeX"
""")

        # Create sample test files
        sample1_in = testing_pkg.add_file('tests/sample1.in')
        sample1_in.write_text('5\n1 2 3 4 5')
        sample1_out = testing_pkg.add_file('tests/sample1.out')
        sample1_out.write_text('15')
        sample2_in = testing_pkg.add_file('tests/sample2.in')
        sample2_in.write_text('3\n10 20 30')
        sample2_out = testing_pkg.add_file('tests/sample2.out')
        sample2_out.write_text('60')

        # Create statement with sample references
        statement_file = testing_pkg.add_file('statement.jinja.tex')
        statement_file.write_text("""
Problem with \\VAR{problem.samples|length} samples:

%- for sample in problem.samples
Sample \\VAR{loop.index}: Input has \\VAR{sample.inputPath.read_text().strip().split('\\n')[0]} elements.
%- endfor
""")

        # Mock get_samples to return our test samples
        with patch(
            'rbx.box.statements.build_statements.get_samples'
        ) as mock_get_samples:
            # Create real Testcase objects instead of mocks
            from rbx.box.schema import Testcase

            testcases = [
                Testcase(
                    inputPath=testing_pkg.path('tests/sample1.in'),
                    outputPath=testing_pkg.path('tests/sample1.out'),
                ),
                Testcase(
                    inputPath=testing_pkg.path('tests/sample2.in'),
                    outputPath=testing_pkg.path('tests/sample2.out'),
                ),
            ]
            mock_get_samples.return_value = testcases

            pkg = testing_pkg.yml
            statement = pkg.expanded_statements[0]

            result_path = build_statement(
                statement=statement,
                pkg=pkg,
                output_type=StatementType.TeX,
                use_samples=True,
            )

            content = result_path.read_text()
            assert 'Problem with 2 samples' in content
            assert 'Sample 1: Input has 5 elements' in content
            assert 'Sample 2: Input has 3 elements' in content
