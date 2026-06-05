import pathlib
import sys
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

        async def mock_compile_side_effect(
            commands, params, artifacts, sandbox, dependency_cache
        ):
            # Simulate setting digest values for output artifacts
            for output in artifacts.outputs:
                if output.digest is not None:
                    cacher = package.get_file_cacher()
                    # Add the file to the actual file cacher to avoid KeyError
                    # Use the digest returned by put_file_content
                    actual_digest = await cacher.put_file_content(b'mock file content')
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

    async def test_compile_cpp_commands_content(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that C++ compilation commands are properly constructed."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        assert isinstance(commands, list)
        assert len(commands) == 1
        # Should be the exact C++ compilation command with all modifications
        expected_cmd = [
            'g++',
            '-std=c++20',
            '-O2',
            '-o',
            'executable',
            'solution.cpp',
            '-fdiagnostics-color=always',
            '-ffp-contract=off' if sys.platform == 'darwin' else '',
            '-Wall',
            '-Wshadow',
            '-Wno-unused-result',
            '-Wno-sign-compare',
            '-Wno-char-subscripts',
            '-I.',
        ]

        assert commands[0] == ' '.join([cmd for cmd in expected_cmd if cmd])

    async def test_compile_java_commands_content(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that Java compilation commands are properly constructed."""
        java_file = testing_pkg.add_file(
            'Solution.java', src='compile_test/simple.java'
        )
        code_item = CodeItem(path=java_file, language='java')

        await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        assert isinstance(commands, list)
        assert len(commands) == 2
        # Should be the exact Java compilation commands from default.rbx.yml
        # Notice how the source file gets renamed to Simple.java,
        # which is the name of the Java class contained in Solution.java.
        assert commands[0] == 'javac -Xlint -encoding UTF-8 Simple.java'
        assert commands[1] == 'jar cvf Main.jar @glob:*.class'

    async def test_compile_python_no_compilation(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that Python files bypass compilation."""
        py_file = testing_pkg.add_file('solution.py', src='compile_test/simple.py')
        code_item = CodeItem(path=py_file, language='py')

        result = await code.compile_item(code_item)

        assert isinstance(result, str)
        assert len(result) > 0
        # Python files don't need compilation
        mock_steps_with_caching.assert_not_called()

    async def test_compile_sanitizer_flags_added(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that sanitizer flags are properly added to commands."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item, sanitized=code.SanitizationLevel.FORCE)

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        # Should contain sanitizer flags
        assert any('-fsanitize=address,undefined' in cmd for cmd in commands)
        assert any('-fno-omit-frame-pointer' in cmd for cmd in commands)
        assert any('-g' in cmd for cmd in commands)

    async def test_compile_warning_flags_added(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that warning flags are properly added to commands."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item, force_warnings=True)

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        # Should contain warning flags
        assert any('-Wall' in cmd for cmd in commands)
        assert any('-Wshadow' in cmd for cmd in commands)

    async def test_compile_combined_flags(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that sanitizer and warning flags work together."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(
            code_item, sanitized=code.SanitizationLevel.FORCE, force_warnings=True
        )

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]

        # Should contain both sanitizer and warning flags
        assert any('-fsanitize=address,undefined' in cmd for cmd in commands)
        assert any('-Wall' in cmd for cmd in commands)

    async def test_compile_artifacts_input_files(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compilation artifacts contain correct input files."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item)

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

    async def test_compile_artifacts_output_files(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compilation artifacts contain correct output files."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # Should have exactly one output file (the executable)
        assert len(artifacts.outputs) == 1
        output = artifacts.outputs[0]
        assert output.executable is True
        assert output.digest is not None

    async def test_compile_non_passthrough_uses_executable_output_src(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """When passthrough is not set, output src should be executable."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']
        output = artifacts.outputs[0]

        assert output.src.name == 'executable'

    async def test_compile_passthrough_uses_compilable_output_src(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """When passthrough is set, output src should be compilable (source file)."""
        from rbx.box import environment as env

        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        # Force passthrough in compilation config without mutating cached object
        with mock.patch('rbx.box.code.get_compilation_config') as mock_get_cfg:

            def _side_effect(language, solution=False):
                orig = env.get_compilation_config(language, solution)
                return env.BaseCompilationConfig(
                    commands=orig.commands,
                    sandbox=orig.sandbox,
                    passthrough=True,
                )

            mock_get_cfg.side_effect = _side_effect

            await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']
        output = artifacts.outputs[0]

        # Should point to the compilable (mapped source) instead of executable
        assert output.src.name == 'solution.cpp'

    async def test_compile_artifacts_with_testlib(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that testlib.h is included in artifacts when available."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # Should include testlib.h
        testlib_input = next(
            (inp for inp in artifacts.inputs if inp.dest.name == 'testlib.h'), None
        )
        assert testlib_input is not None

    async def test_compile_artifacts_with_jngen(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that jngen.h is included in artifacts when available."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # Should include jngen.h
        jngen_input = next(
            (inp for inp in artifacts.inputs if inp.dest.name == 'jngen.h'), None
        )
        assert jngen_input is not None

    async def test_compile_artifacts_with_tgen(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that tgen.h is included in artifacts when available."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        tgen_input = next(
            (inp for inp in artifacts.inputs if inp.dest.name == 'tgen.h'), None
        )
        assert tgen_input is not None

    async def test_builtin_headers_placed_in_source_dir(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Builtin headers are placed in the source's directory for subdir sources."""
        gen = testing_pkg.add_file('gens/gen.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=gen, language='cpp'))

        artifacts = mock_steps_with_caching.call_args.kwargs['artifacts']
        testlib = next(
            (i for i in artifacts.inputs if i.dest.name == 'testlib.h'), None
        )
        assert testlib is not None
        assert testlib.dest == pathlib.Path('gens/testlib.h')

    async def test_builtin_headers_flat_unchanged(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Flat packages keep builtin headers at the package root."""
        sol = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=sol, language='cpp'))

        artifacts = mock_steps_with_caching.call_args.kwargs['artifacts']
        testlib = next(
            (i for i in artifacts.inputs if i.dest.name == 'testlib.h'), None
        )
        assert testlib is not None
        assert testlib.dest == pathlib.Path('testlib.h')

    async def test_compile_sandbox_params_basic(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test basic sandbox parameters setup."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        sandbox_params = call_args.kwargs['params']

        # Should have sandbox parameters
        assert sandbox_params is not None
        # Should have some basic limits for non-sanitized compilation
        assert sandbox_params.timeout is not None
        assert sandbox_params.address_space is not None

    async def test_compile_sandbox_params_sanitized_removes_limits(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that sanitized compilation removes memory and time limits."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item, sanitized=code.SanitizationLevel.FORCE)

        call_args = mock_steps_with_caching.call_args
        sandbox_params = call_args.kwargs['params']

        # Sanitized builds should have no memory/time limits
        assert sandbox_params.address_space is None
        assert sandbox_params.timeout is None
        assert sandbox_params.wallclock_timeout is None

    async def test_compile_bits_stdcpp_added_for_cpp(
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

            await code.compile_item(code_item)

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

    async def test_compile_precompilation_enabled_by_default(
        self,
        testing_pkg: testing_package.TestingPackage,
        mock_steps_with_caching,
        mock_precompile_header,
    ):
        """Test that precompilation is enabled by default for C++."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item)

        call_args = mock_steps_with_caching.call_args
        artifacts = call_args.kwargs['artifacts']

        # For simple.cpp, exactly these header files should be present
        expected_header_files = {'testlib.h', 'jngen.h', 'tgen.h', 'rbx.h', 'stdc++.h'}

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
        processed_header_files = {'testlib.h', 'jngen.h', 'tgen.h', 'rbx.h'}

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

    async def test_precompile_targets_source_dir_header(
        self,
        testing_pkg: testing_package.TestingPackage,
        mock_steps_with_caching,
        mock_precompile_header,
    ):
        """Precompiled headers for a subdir source target the source dir."""
        gen = testing_pkg.add_file('gens/gen.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=gen, language='cpp'))

        # _precompile_header is called positionally: (..., artifacts,
        # input_artifact, ...) i.e. the candidate header is the 5th positional
        # arg (index 4).
        precompiled_dests = [
            call.args[4].dest for call in mock_precompile_header.call_args_list
        ]
        assert pathlib.Path('gens/testlib.h') in precompiled_dests

    async def test_compile_precompilation_disabled(
        self,
        testing_pkg: testing_package.TestingPackage,
        mock_steps_with_caching,
        mock_precompile_header,
    ):
        """Test that precompilation can be disabled."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        await code.compile_item(code_item, precompile=False)

        # Should not call precompile_header
        mock_precompile_header.assert_not_called()

    async def test_compile_warning_pragmas_processed(
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

        await code.compile_item(code_item)

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

    async def test_compile_failure_raises_compilation_error(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that compilation failure raises CompilationError."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        with mock.patch('rbx.box.code.steps_with_caching.compile') as mock_compile:
            mock_compile.side_effect = steps.CompilationError()

            with pytest.raises(steps.CompilationError):
                await code.compile_item(code_item)

    async def test_compile_nonexistent_file_raises_exit(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compiling nonexistent file raises typer.Exit."""
        nonexistent_file = testing_pkg.path('nonexistent.cpp')
        code_item = CodeItem(path=nonexistent_file, language='cpp')

        with pytest.raises(typer.Exit):
            await code.compile_item(code_item)

        mock_steps_with_caching.assert_not_called()

    async def test_compile_metadata_set_for_sanitized(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compilation metadata is set for sanitized builds."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        with mock.patch('rbx.box.code.package.get_file_cacher') as mock_get_cacher:
            mock_cacher = mock.MagicMock()
            mock_cacher.set_metadata = mock.AsyncMock()
            mock_cacher.put_file_content = mock.AsyncMock(return_value='mock_digest')
            mock_get_cacher.return_value = mock_cacher

            await code.compile_item(code_item, sanitized=code.SanitizationLevel.FORCE)

            # Should set metadata indicating sanitized build
            mock_cacher.set_metadata.assert_called_once()
            call_args = mock_cacher.set_metadata.call_args
            assert call_args[0][1] == 'compilation'
            assert call_args[0][2].is_sanitized is True

    async def test_compile_metadata_cleared_for_non_sanitized(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compilation metadata is cleared for non-sanitized builds."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        with mock.patch('rbx.box.code.package.get_file_cacher') as mock_get_cacher:
            mock_cacher = mock.MagicMock()
            mock_cacher.set_metadata = mock.AsyncMock()
            mock_cacher.put_file_content = mock.AsyncMock(return_value='mock_digest')
            mock_get_cacher.return_value = mock_cacher

            await code.compile_item(code_item, sanitized=code.SanitizationLevel.NONE)

            # Should clear metadata for non-sanitized build
            mock_cacher.set_metadata.assert_called_once()
            call_args = mock_cacher.set_metadata.call_args
            assert call_args[0][1] == 'compilation'
            assert call_args[0][2] is None

    async def test_compile_verbose_mode_works(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that verbose mode doesn't break compilation."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        # Should not raise any exceptions
        result = await code.compile_item(code_item, verbose=True)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_compile_sanitization_level_prefer_vs_force(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test different sanitization levels."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        # Test PREFER level (default)
        await code.compile_item(code_item, sanitized=code.SanitizationLevel.PREFER)
        mock_steps_with_caching.assert_called()

        # Test FORCE level
        mock_steps_with_caching.reset_mock()
        await code.compile_item(code_item, sanitized=code.SanitizationLevel.FORCE)
        mock_steps_with_caching.assert_called()

        # Test NONE level
        mock_steps_with_caching.reset_mock()
        await code.compile_item(code_item, sanitized=code.SanitizationLevel.NONE)
        mock_steps_with_caching.assert_called()

    async def test_compile_returns_digest_string(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """Test that compile_item returns a valid digest string."""
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        result = await code.compile_item(code_item)

        # Should return a non-empty string (digest)
        assert isinstance(result, str)
        assert len(result) > 0
        # Digest should be hex-like
        assert all(c in '0123456789abcdef' for c in result.lower())

    async def test_compile_records_warning_logs_when_warnings_enabled(
        self, testing_pkg: testing_package.TestingPackage, monkeypatch
    ):
        """Warning-bearing compiler logs are forwarded to the warning stack."""
        from rbx.box import setter_config
        from rbx.box.sanitizers import warning_stack
        from rbx.grading.steps import GradingLogsHolder, PreprocessLog

        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        warning_log = PreprocessLog(
            cmd=['g++', 'solution.cpp'],
            log='solution.cpp:1:1: warning: unused variable',
            warnings=True,
        )
        clean_log = PreprocessLog(
            cmd=['jar', 'cvf', 'Main.jar'],
            log='',
            warnings=False,
        )

        async def compile_side_effect(
            commands, params, artifacts, sandbox, dependency_cache
        ):
            for output in artifacts.outputs:
                if output.digest is not None:
                    cacher = package.get_file_cacher()
                    output.digest.value = await cacher.put_file_content(
                        b'mock file content'
                    )
            artifacts.logs = GradingLogsHolder(preprocess=[warning_log, clean_log])
            return True

        monkeypatch.setattr(
            'rbx.box.code.steps_with_caching.compile',
            mock.AsyncMock(side_effect=compile_side_effect),
        )
        cfg = setter_config.get_setter_config()
        monkeypatch.setattr(cfg.warnings, 'enabled', True)

        warning_stack.get_warning_stack().clear()
        await code.compile_item(code_item)

        stack = warning_stack.get_warning_stack()
        assert code_item.path in stack.warnings
        assert stack.warning_logs[code_item.path] == [warning_log]

    async def test_compile_nested_source_mirrors_path(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """A subdir source is compiled at its package-relative path."""
        gen = testing_pkg.add_file('gens/gen.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=gen, language='cpp'))

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]
        artifacts = call_args.kwargs['artifacts']

        # Compile command references the mirrored, package-relative source
        # (and not the flat basename).
        tokens = commands[0].split()
        assert 'gens/gen.cpp' in tokens
        assert 'gen.cpp' not in tokens
        # The compilable artifact is placed at its package-relative path.
        compilable = next(
            (i for i in artifacts.inputs if i.dest == pathlib.Path('gens/gen.cpp')),
            None,
        )
        assert compilable is not None

    async def test_compile_flat_source_unchanged(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        """A flat source keeps its basename (mirroring is a no-op at root)."""
        sol = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=sol, language='cpp'))

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]
        artifacts = call_args.kwargs['artifacts']
        # Flat package: package-relative path == basename, so the source token
        # is the plain basename and the compilable artifact stays at the root.
        assert 'solution.cpp' in commands[0].split()
        compilable = next(
            (i for i in artifacts.inputs if i.dest == pathlib.Path('solution.cpp')),
            None,
        )
        assert compilable is not None


class TestRelativeSourcePath:
    def test_nested_source_is_package_relative(
        self, testing_pkg: testing_package.TestingPackage
    ):
        gen = testing_pkg.add_file('gens/gen.cpp')
        assert package.get_relative_source_path(CodeItem(path=gen)) == pathlib.Path(
            'gens/gen.cpp'
        )

    def test_flat_source_is_basename(self, testing_pkg: testing_package.TestingPackage):
        sol = testing_pkg.add_file('solution.cpp')
        assert package.get_relative_source_path(CodeItem(path=sol)) == pathlib.Path(
            'solution.cpp'
        )

    def test_external_source_falls_back_to_basename(
        self, testing_pkg: testing_package.TestingPackage, tmp_path: pathlib.Path
    ):
        # A path outside the package root keeps the legacy flat basename.
        external = tmp_path / 'somewhere' / 'remote.cpp'
        assert package.get_relative_source_path(
            CodeItem(path=external)
        ) == pathlib.Path('remote.cpp')


class TestCompilationFiles:
    def test_dest_is_package_relative(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A compilation file lands at its package-relative path inside the sandbox."""
        testing_pkg.add_file('lib.h')
        gen = testing_pkg.add_file('gens/gen.cpp')
        code_item = CodeItem(path=gen, language='cpp', compilationFiles=['lib.h'])
        assert package.get_compilation_files(code_item) == [
            (pathlib.Path('lib.h'), pathlib.Path('lib.h'))
        ]

    def test_dest_preserves_nested_subdir(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A compilation file in a nested dir keeps its package-relative path."""
        testing_pkg.add_file('headers/lib.h')
        gen = testing_pkg.add_file('gens/gen.cpp')
        code_item = CodeItem(
            path=gen, language='cpp', compilationFiles=['headers/lib.h']
        )
        assert package.get_compilation_files(code_item) == [
            (pathlib.Path('headers/lib.h'), pathlib.Path('headers/lib.h'))
        ]

    def test_accepts_file_outside_code_dir(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A compilation file outside the code's folder is now accepted."""
        # lib.h at root, source in gens/: rejected before, allowed now.
        testing_pkg.add_file('lib.h')
        gen = testing_pkg.add_file('gens/gen.cpp')
        code_item = CodeItem(path=gen, language='cpp', compilationFiles=['lib.h'])
        # Must not raise, and lands at its package-relative path.
        assert package.get_compilation_files(code_item) == [
            (pathlib.Path('lib.h'), pathlib.Path('lib.h'))
        ]

    def test_rejects_missing_file(self, testing_pkg: testing_package.TestingPackage):
        """A non-existent compilation file is rejected."""
        gen = testing_pkg.add_file('gen.cpp')
        code_item = CodeItem(path=gen, language='cpp', compilationFiles=['nope.h'])
        with pytest.raises(typer.Exit):
            package.get_compilation_files(code_item)

    def test_rejects_file_outside_package(
        self, testing_pkg: testing_package.TestingPackage, tmp_path: pathlib.Path
    ):
        """A compilation file outside the package directory is rejected."""
        outside = tmp_path / 'outside.h'
        outside.write_text('')
        gen = testing_pkg.add_file('gen.cpp')
        code_item = CodeItem(path=gen, language='cpp', compilationFiles=[str(outside)])
        with pytest.raises(typer.Exit):
            package.get_compilation_files(code_item)
