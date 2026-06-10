import pathlib
from unittest.mock import patch

import pytest
import typer

from rbx.box import limits_info
from rbx.box.schema import Statement
from rbx.box.statements.build_statements import (
    execute_build,
    get_environment_languages_for_statement,
    needs_samples,
)
from rbx.box.statements.schema import StatementType


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

    with (
        patch(
            'rbx.box.statements.build_statements.environment.get_environment'
        ) as mock_get_env,
        patch(
            'rbx.box.statements.build_statements.environment.get_compilation_config'
        ) as mock_comp_cfg,
        patch(
            'rbx.box.statements.build_statements.environment.get_execution_config'
        ) as mock_exec_cfg,
    ):
        # Create environment object with real EnvironmentLanguage objects
        mock_env = type('Environment', (), {'languages': languages})()
        mock_get_env.return_value = mock_env

        def mock_compilation_config(lang_name, solution=False):
            # Return real CompilationConfig objects
            if lang_name == 'cpp':
                return CompilationConfig(commands=['g++ -std=c++17', 'echo compiled'])
            else:
                return CompilationConfig(commands=None)

        def mock_execution_config(lang_name, solution=False):
            # Return real ExecutionConfig objects
            if lang_name == 'python':
                return ExecutionConfig(command='python')
            else:
                return ExecutionConfig(command='')

        mock_comp_cfg.side_effect = mock_compilation_config
        mock_exec_cfg.side_effect = mock_execution_config

        yield mock_env


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


class TestNeedsSamples:
    """Test needs_samples function.

    In v2 the old ``inheritFromContest`` override is gone, so ``needs_samples``
    simply reflects the statement's own ``samples`` flag.
    """

    def test_needs_samples_true_when_enabled(self):
        statement = Statement(
            language='en',
            file=pathlib.Path('statement.rbx.tex'),
            type=StatementType.rbxTeX,
            samples=True,
        )
        assert needs_samples(statement) is True

    def test_needs_samples_false_when_disabled(self):
        statement = Statement(
            language='en',
            file=pathlib.Path('statement.rbx.tex'),
            type=StatementType.rbxTeX,
            samples=False,
        )
        assert needs_samples(statement) is False


class TestExecuteBuildStrictProfile:
    """Tests for strict --profile validation in execute_build."""

    @pytest.mark.test_pkg('problems/box1')
    async def test_execute_build_strict_profile_missing_exits(self, pkg_from_testdata):
        with pytest.raises(typer.Exit) as exc_info:
            await execute_build(
                verification=0,
                names=None,
                languages=None,
                output=StatementType.PDF,
                samples=False,
                vars=None,
                validate=False,
                profile='does-not-exist',
            )
        assert exc_info.value.exit_code == 1

    @pytest.mark.test_pkg('problems/box1')
    async def test_execute_build_strict_profile_applies(
        self, pkg_from_testdata, monkeypatch
    ):
        pathlib.Path('.limits').mkdir(exist_ok=True)
        pathlib.Path('.limits/icpc.yml').write_text('timeLimit: 5000\n')

        seen = {}

        async def fake_execute_build_on_statements(statements, *args, **kwargs):
            seen['profile'] = limits_info.get_active_profile()
            return

        monkeypatch.setattr(
            'rbx.box.statements.build_statements.execute_build_on_statements',
            fake_execute_build_on_statements,
        )
        await execute_build(
            verification=0,
            names=None,
            languages=None,
            output=StatementType.PDF,
            samples=False,
            vars=None,
            validate=False,
            profile='icpc',
        )
        assert seen['profile'] == 'icpc'

    @pytest.mark.test_pkg('problems/box1')
    async def test_execute_build_respects_global_profile_when_local_none(
        self, pkg_from_testdata, monkeypatch
    ):
        # Simulate the global `rbx -p icpc st b` callback by setting the contextvar
        # before invoking execute_build with profile=None (no local override).
        pathlib.Path('.limits').mkdir(exist_ok=True)
        pathlib.Path('.limits/icpc.yml').write_text('timeLimit: 5000\n')

        token = limits_info.profile_var.set('icpc')
        try:
            seen = {}

            async def fake_execute_build_on_statements(statements, *args, **kwargs):
                seen['profile'] = limits_info.get_active_profile()
                return

            monkeypatch.setattr(
                'rbx.box.statements.build_statements.execute_build_on_statements',
                fake_execute_build_on_statements,
            )

            await execute_build(
                verification=0,
                names=None,
                languages=None,
                output=StatementType.PDF,
                samples=False,
                vars=None,
                validate=False,
                profile=None,
            )
            assert seen['profile'] == 'icpc'
        finally:
            limits_info.profile_var.reset(token)
