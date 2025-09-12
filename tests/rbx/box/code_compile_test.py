import pathlib
from unittest import mock

import pytest
import typer

from rbx.box import code, package
from rbx.box.schema import CodeItem
from rbx.box.testing import testing_package
from rbx.grading import steps
from rbx.grading.steps import GradingFileInput


class TestCompileItem:
    """Test suite for compile_item function."""

    @pytest.fixture(autouse=True)
    def mock_steps_with_caching(self, testing_pkg: testing_package.TestingPackage):
        """Mock steps_with_caching.compile to avoid heavy operations."""

        def mock_compile_side_effect(
            commands, params, artifacts, sandbox, dependency_cache
        ):
            # Simulate setting digest values for output artifacts
            for output in artifacts.outputs:
                if output.digest is not None:
                    cacher = package.get_file_cacher()
                    # Add the file to the actual file cacher to avoid KeyError
                    # Use the digest returned by put_file_content
                    actual_digest = cacher.put_file_content(b'mock file content')
                    output.digest.value = actual_digest
            return True

        with mock.patch('rbx.box.code.steps_with_caching.compile') as mock_compile:
            mock_compile.side_effect = mock_compile_side_effect
            yield mock_compile

    @pytest.fixture(autouse=True)
    def mock_precompile_header(self):
        """Mock _precompile_header to avoid heavy operations."""
        with mock.patch('rbx.box.code._precompile_header') as mock_precompile:
            mock_precompile.return_value = GradingFileInput(
                src=pathlib.Path('test.h.gch'),
                dest=pathlib.Path('test.h.gch'),
                hash=False,
            )
            yield mock_precompile

    def test_compile_cpp_commands_content(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that C++ compilation commands are properly constructed."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        assert isinstance(commands, list)
        assert len(commands) == 1
        # Should be the exact C++ compilation command with all modifications
        expected_cmd = 'g++ -std=c++20 -O2 -o executable solution.cpp -fdiagnostics-color=always -Wall -Wshadow -Wno-unused-result -Wno-sign-compare -Wno-char-subscripts -I.'
        assert commands[0] == expected_cmd

    def test_compile_java_commands_content(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that Java compilation commands are properly constructed."""
        java_file = testing_pkg.add_file(
            'Solution.java', src='compile_test/simple.java'
        )
        code_item = CodeItem(path=java_file, language='java')

        code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        assert isinstance(commands, list)
        assert len(commands) == 2
        # Should be the exact Java compilation commands from default.rbx.yml
        # Notice how the source file gets renamed to Simple.java,
        # which is the name of the Java class contained in Solution.java.
        assert commands[0] == 'javac -Xlint -encoding UTF-8 Simple.java'
        assert commands[1] == 'jar cvf Main.jar @glob:*.class'

    def test_compile_python_no_compilation(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that Python files bypass compilation."""
        py_file = testing_pkg.add_file('solution.py', src='compile_test/simple.py')
        code_item = CodeItem(path=py_file, language='py')

        result = code.compile_item(code_item)

        assert isinstance(result, str)
        assert len(result) > 0
        # Python files don't need compilation
        mock_steps_with_caching.assert_not_called()

    def test_compile_sanitizer_flags_added(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that sanitizer flags are properly added to commands."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item, sanitized=code.SanitizationLevel.FORCE)

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        # Should contain sanitizer flags
        assert any('-fsanitize=address,undefined' in cmd for cmd in commands)
        assert any('-fno-omit-frame-pointer' in cmd for cmd in commands)
        assert any('-g' in cmd for cmd in commands)

    def test_compile_warning_flags_added(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that warning flags are properly added to commands."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item, force_warnings=True)

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        # Should contain warning flags
        assert any('-Wall' in cmd for cmd in commands)
        assert any('-Wshadow' in cmd for cmd in commands)

    def test_compile_combined_flags(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that sanitizer and warning flags work together."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(
            code_item, sanitized=code.SanitizationLevel.FORCE, force_warnings=True
        )

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        # Should contain both sanitizer and warning flags
        assert any('-fsanitize=address,undefined' in cmd for cmd in commands)
        assert any('-Wall' in cmd for cmd in commands)

    def test_compile_artifacts_input_files(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compilation artifacts contain correct input files."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # Should have input files
        assert len(artifacts.inputs) > 0

        # Should include the main source file (mapped to compilable.cpp)
        main_source_input = next(
            (inp for inp in artifacts.inputs if inp.dest.name == 'solution.cpp'), None
        )
        assert main_source_input is not None
        assert main_source_input.src == cpp_file

        # Should include rbx.h
        rbx_header_input = next(
            (inp for inp in artifacts.inputs if inp.dest.name == 'rbx.h'), None
        )
        assert rbx_header_input is not None

    def test_compile_artifacts_output_files(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compilation artifacts contain correct output files."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # Should have exactly one output file (the executable)
        assert len(artifacts.outputs) == 1
        output = artifacts.outputs[0]
        assert output.executable is True
        assert output.digest is not None

    def test_compile_artifacts_with_testlib(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that testlib.h is included in artifacts when available."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # Should include testlib.h
        testlib_input = next(
            (inp for inp in artifacts.inputs if inp.dest.name == 'testlib.h'), None
        )
        assert testlib_input is not None

    def test_compile_artifacts_with_jngen(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that jngen.h is included in artifacts when available."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # Should include jngen.h
        jngen_input = next(
            (inp for inp in artifacts.inputs if inp.dest.name == 'jngen.h'), None
        )
        assert jngen_input is not None

    def test_compile_sandbox_params_basic(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test basic sandbox parameters setup."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        sandbox_params = call_args.kwargs['params']

        # Should have sandbox parameters
        assert sandbox_params is not None
        # Should have some basic limits for non-sanitized compilation
        assert sandbox_params.timeout is not None
        assert sandbox_params.address_space is not None

    def test_compile_sandbox_params_sanitized_removes_limits(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that sanitized compilation removes memory and time limits."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item, sanitized=code.SanitizationLevel.FORCE)

        call_args = mock_steps_with_caching.call_args
        sandbox_params = call_args.kwargs['params']

        # Sanitized builds should have no memory/time limits
        assert sandbox_params.address_space is None
        assert sandbox_params.timeout is None
        assert sandbox_params.wallclock_timeout is None

    def test_compile_bits_stdcpp_added_for_cpp(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that bits/stdc++.h is added for C++ compilation."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        with mock.patch('rbx.box.code.maybe_get_bits_stdcpp_for_commands') as mock_bits:
            mock_bits.return_value = GradingFileInput(
                src=pathlib.Path('bits/stdc++.h'),
                dest=pathlib.Path('bits/stdc++.h'),
            )

            code.compile_item(code_item)

            call_args = mock_steps_with_caching.call_args
            commands = call_args[0][0]
            artifacts = call_args.kwargs['artifacts']

            # Should call the bits function
            mock_bits.assert_called_once()

            # Should include -I. flag for C++ commands
            assert any('-I.' in cmd for cmd in commands)

            # Should include bits/stdc++.h in artifacts
            bits_input = next(
                (inp for inp in artifacts.inputs if 'stdc++.h' in str(inp.dest)), None
            )
            assert bits_input is not None

    def test_compile_precompilation_enabled_by_default(
        self,
        testing_pkg: testing_package.TestingPackage,
        mock_steps_with_caching,
        mock_precompile_header,
    ):
        """Test that precompilation is enabled by default for C++."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # For simple.cpp, exactly these header files should be present
        expected_header_files = {'testlib.h', 'jngen.h', 'rbx.h', 'stdc++.h'}

        # Find all header files in artifacts
        actual_header_files = {
            inp.dest.name
            for inp in artifacts.inputs
            if inp.dest.suffix in ['.h', '.hpp']
        }

        # Assert exact set of header files
        assert actual_header_files == expected_header_files

        # Only testlib.h, jngen.h, and rbx.h should be processed with warning pragmas
        # stdc++.h is a system header that doesn't get processed
        processed_header_files = {'testlib.h', 'jngen.h', 'rbx.h'}

        for inp in artifacts.inputs:
            if inp.dest.suffix in ['.h', '.hpp']:
                processed_content = inp.src.read_text()
                if inp.dest.name in processed_header_files:
                    # These should have warning pragmas
                    assert '#pragma GCC diagnostic push' in processed_content
                    assert '#pragma GCC diagnostic pop' in processed_content
                    assert '#pragma GCC diagnostic ignored "-Wall"' in processed_content
                    assert (
                        '#pragma GCC diagnostic ignored "-Wshadow"' in processed_content
                    )

    def test_compile_precompilation_disabled(
        self,
        testing_pkg: testing_package.TestingPackage,
        mock_steps_with_caching,
        mock_precompile_header,
    ):
        """Test that precompilation can be disabled."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        code.compile_item(code_item, precompile=False)

        # Should not call precompile_header
        mock_precompile_header.assert_not_called()

    def test_compile_warning_pragmas_processed(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that warning pragmas are added to header files during compilation."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')

        # Create a custom header file that will be processed
        custom_header = testing_pkg.add_file('custom.h')
        custom_header.write_text("""#ifndef CUSTOM_H
#define CUSTOM_H

int custom_function();

#endif""")

        code_item = CodeItem(
            path=cpp_file, language='cpp', compilationFiles=['custom.h']
        )

        code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # Find the custom header input artifact
        custom_header_input = next(
            (inp for inp in artifacts.inputs if inp.dest.name == 'custom.h'), None
        )
        assert custom_header_input is not None

        # Check that the header file was processed with warning pragmas
        processed_content = custom_header_input.src.read_text()

        # Should contain the exact expected content with warning pragmas wrapped around
        expected_content = """#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wall"
#pragma GCC diagnostic ignored "-Wshadow"
#ifndef CUSTOM_H
#define CUSTOM_H

int custom_function();

#endif
#pragma GCC diagnostic pop
"""

        assert processed_content == expected_content

        # Should be a different file (preprocessed version)
        assert custom_header_input.src != custom_header

    def test_compile_failure_raises_compilation_error(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that compilation failure raises CompilationError."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        with mock.patch('rbx.box.code.steps_with_caching.compile') as mock_compile:
            mock_compile.side_effect = steps.CompilationError()

            with pytest.raises(steps.CompilationError):
                code.compile_item(code_item)

    def test_compile_nonexistent_file_raises_exit(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compiling nonexistent file raises typer.Exit."""
        nonexistent_file = testing_pkg.path('nonexistent.cpp')
        code_item = CodeItem(path=nonexistent_file, language='cpp')

        with pytest.raises(typer.Exit):
            code.compile_item(code_item)

        mock_steps_with_caching.assert_not_called()

    def test_compile_metadata_set_for_sanitized(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compilation metadata is set for sanitized builds."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        with mock.patch('rbx.box.code.package.get_file_cacher') as mock_get_cacher:
            mock_cacher = mock.Mock()
            mock_get_cacher.return_value = mock_cacher

            code.compile_item(code_item, sanitized=code.SanitizationLevel.FORCE)

            # Should set metadata indicating sanitized build
            mock_cacher.set_metadata.assert_called_once()
            call_args = mock_cacher.set_metadata.call_args
            assert call_args[0][1] == 'compilation'
            assert call_args[0][2].is_sanitized is True

    def test_compile_metadata_cleared_for_non_sanitized(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compilation metadata is cleared for non-sanitized builds."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        with mock.patch('rbx.box.code.package.get_file_cacher') as mock_get_cacher:
            mock_cacher = mock.Mock()
            mock_get_cacher.return_value = mock_cacher

            code.compile_item(code_item, sanitized=code.SanitizationLevel.NONE)

            # Should clear metadata for non-sanitized build
            mock_cacher.set_metadata.assert_called_once()
            call_args = mock_cacher.set_metadata.call_args
            assert call_args[0][1] == 'compilation'
            assert call_args[0][2] is None

    def test_compile_verbose_mode_works(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that verbose mode doesn't break compilation."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        # Should not raise any exceptions
        result = code.compile_item(code_item, verbose=True)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_compile_sanitization_level_prefer_vs_force(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test different sanitization levels."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        # Test PREFER level (default)
        code.compile_item(code_item, sanitized=code.SanitizationLevel.PREFER)
        mock_steps_with_caching.assert_called()

        # Test FORCE level
        mock_steps_with_caching.reset_mock()
        code.compile_item(code_item, sanitized=code.SanitizationLevel.FORCE)
        mock_steps_with_caching.assert_called()

        # Test NONE level
        mock_steps_with_caching.reset_mock()
        code.compile_item(code_item, sanitized=code.SanitizationLevel.NONE)
        mock_steps_with_caching.assert_called()

    def test_compile_returns_digest_string(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compile_item returns a valid digest string."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        result = code.compile_item(code_item)

        # Should return a non-empty string (digest)
        assert isinstance(result, str)
        assert len(result) > 0
        # Digest should be hex-like
        assert all(c in '0123456789abcdef' for c in result.lower())
