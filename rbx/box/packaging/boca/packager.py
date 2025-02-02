import pathlib
import shutil
from math import fabs
from typing import List

import typer

from rbx import console
from rbx.box import package
from rbx.box.environment import get_extension_or_default
from rbx.box.packaging.boca.extension import BocaExtension, BocaLanguage
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.statements.schema import Statement
from rbx.config import get_default_app_path, get_testlib

_MAX_REP_TIME = (
    7  # TL to allow for additional rounding reps should be < _MAX_REP_TIME in seconds
)
_MAX_REPS = 10  # Maximum number of reps to add


def test_time(time):
    return max(1, round(time))


class BocaPackager(BasePackager):
    def _get_main_statement(self) -> Statement:
        pkg = package.find_problem_package_or_die()

        if not pkg.statements:
            console.console.print('[error]No statements found.[/error]')
            raise typer.Exit(1)

        return pkg.statements[0]

    def _get_main_built_statement(
        self, built_statements: List[BuiltStatement]
    ) -> BuiltStatement:
        statement = self._get_main_statement()
        for built_statement in built_statements:
            if built_statement.statement == statement:
                return built_statement

        console.console.print(
            '[error]Main statement not found among built statements.[/error]'
        )
        raise typer.Exit(1)

    def _get_problem_name(self) -> str:
        pkg = package.find_problem_package_or_die()
        return pkg.name

    def _get_problem_info(self) -> str:
        pkg = package.find_problem_package_or_die()
        statement = self._get_main_statement()
        return (
            f'basename={pkg.name}\n'
            f'fullname={statement.title}\n'
            f'descfile={self._get_problem_name()}.pdf\n'
        )

    def _get_pkg_timelimit(self, language: BocaLanguage) -> int:
        pkg = package.find_problem_package_or_die()
        return pkg.timelimit_for_language(language)

    def _get_pkg_memorylimit(self, language: BocaLanguage) -> int:
        pkg = package.find_problem_package_or_die()
        return pkg.memorylimit_for_language(language)

    def _get_number_of_runs(self, language: BocaLanguage) -> int:
        pkg = package.find_problem_package_or_die()
        extension = get_extension_or_default('boca', BocaExtension)
        pkg_timelimit = self._get_pkg_timelimit(language)
        time = pkg_timelimit / 1000  # convert to seconds

        if time >= _MAX_REP_TIME:
            return 1

        def rounding_error(time):
            return fabs(time - test_time(time))

        def error_percentage(time, runs):
            return rounding_error(time * runs) / (time * runs)

        if error_percentage(time, 1) < 1e-6:
            return 1

        for i in range(1, _MAX_REPS + 1):
            if error_percentage(time, i) <= extension.maximumTimeError:
                console.console.print(
                    f'[warning]Using {i} run(s) to define integer TL for BOCA when using language [item]{language}[/item] '
                    f'(original TL is {pkg_timelimit}ms, new TL is {test_time(time * i) * 1000}ms).[/warning]'
                )
                return i

        percent_str = f'{round(extension.maximumTimeError * 100)}%'
        console.console.print(
            f'[error]Error while defining limits for problem [item]{pkg.name}[/item], language [item]{language}[/item].[/error]'
        )
        console.console.print(
            f'[error]Introducing an error of less than {percent_str} in the TL in less than '
            f'{_MAX_REPS} runs is not possible.[/error]'
        )
        console.console.print(
            f'[error]Original TL for [item]{language}[/item] is {pkg_timelimit}ms, please review it.[/error]'
        )
        raise typer.Exit(1)

    def _get_limits(self, language: BocaLanguage) -> str:
        pkg = package.find_problem_package_or_die()
        no_of_runs = self._get_number_of_runs(language)
        return (
            '#!/bin/bash\n'
            f'echo {test_time(self._get_pkg_timelimit(language) / 1000 * no_of_runs)}\n'
            f'echo {no_of_runs}\n'
            f'echo {self._get_pkg_memorylimit(language)}\n'
            f'echo {pkg.outputLimit}\n'
            f'exit 0\n'
        )

    def _get_compare(self) -> str:
        compare_path = get_default_app_path() / 'packagers' / 'boca' / 'compare'
        if not compare_path.exists():
            console.console.print(
                '[error]BOCA template compare script not found.[/error]'
            )
            raise typer.Exit(1)
        return compare_path.read_text()

    def _get_checker(self) -> str:
        checker_path = get_default_app_path() / 'packagers' / 'boca' / 'checker.sh'
        if not checker_path.exists():
            console.console.print(
                '[error]BOCA template checker script not found.[/error]'
            )
            raise typer.Exit(1)
        checker_text = checker_path.read_text()
        testlib = get_testlib().read_text()
        checker = package.get_checker().path.read_text()
        return checker_text.replace('{{testlib_content}}', testlib).replace(
            '{{checker_content}}', checker
        )

    def _get_compile(self, language: BocaLanguage) -> str:
        extension = get_extension_or_default('boca', BocaExtension)

        compile_path = (
            get_default_app_path() / 'packagers' / 'boca' / 'compile' / language
        )
        if not compile_path.is_file():
            console.console.print(
                f'[error]Compile script for language [item]{language}[/item] not found.[/error]'
            )
            raise typer.Exit(1)

        compile_text = compile_path.read_text()

        assert 'umask 0022' in compile_text
        compile_text = compile_text.replace(
            'umask 0022', 'umask 0022\n\n' + self._get_checker()
        )

        flags = extension.flags_with_defaults()
        if language in flags:
            compile_text = compile_text.replace('{{rbxFlags}}', flags[language])
        return compile_text

    def name(self) -> str:
        return 'boca'

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        extension = get_extension_or_default('boca', BocaExtension)

        # Prepare limits
        limits_path = into_path / 'limits'
        limits_path.mkdir(parents=True, exist_ok=True)
        for language in extension.languages:
            (limits_path / language).write_text(self._get_limits(language))

        # Prepare compare
        compare_path = into_path / 'compare'
        compare_path.mkdir(parents=True, exist_ok=True)
        for language in extension.languages:
            (compare_path / language).write_text(self._get_compare())

        # Prepare run
        run_path = into_path / 'run'
        run_path.mkdir(parents=True, exist_ok=True)
        for language in extension.languages:
            run_orig_path = (
                get_default_app_path() / 'packagers' / 'boca' / 'run' / language
            )
            if not run_orig_path.is_file():
                console.console.print(
                    f'[error]Run script for language [item]{language}[/item] not found.[/error]'
                )
                raise typer.Exit(1)
            shutil.copyfile(run_orig_path, run_path / language)

        # Prepare compile.
        compile_path = into_path / 'compile'
        compile_path.mkdir(parents=True, exist_ok=True)
        for language in extension.languages:
            (compile_path / language).write_text(self._get_compile(language))

        # Prepare tests
        tests_path = into_path / 'tests'
        tests_path.mkdir(parents=True, exist_ok=True)
        for language in extension.languages:
            (tests_path / language).write_text('exit 0\n')

        # Problem statement
        description_path = into_path / 'description'
        description_path.mkdir(parents=True, exist_ok=True)
        (description_path / 'problem.info').write_text(self._get_problem_info())
        shutil.copyfile(
            self._get_main_built_statement(built_statements).path,
            (description_path / self._get_problem_name()).with_suffix('.pdf'),
        )

        # Prepare IO
        inputs_path = into_path / 'input'
        inputs_path.mkdir(parents=True, exist_ok=True)
        outputs_path = into_path / 'output'
        outputs_path.mkdir(parents=True, exist_ok=True)

        testcases = self.get_flattened_built_testcases()
        for i, testcase in enumerate(testcases):
            shutil.copyfile(testcase.inputPath, inputs_path / f'{i+1:03d}')
            if testcase.outputPath is not None:
                shutil.copyfile(testcase.outputPath, outputs_path / f'{i+1:03d}')
            else:
                (outputs_path / f'{i+1:03d}').touch()

        # Zip all.
        shutil.make_archive(
            str(build_path / self._get_problem_name()), 'zip', into_path
        )

        return (build_path / self._get_problem_name()).with_suffix('.zip')
