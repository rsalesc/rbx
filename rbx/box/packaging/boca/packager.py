import pathlib
import shutil
from math import fabs
from typing import List, Optional

import typer

from rbx import console
from rbx.box import header, limits_info, naming, package
from rbx.box.environment import get_extension_or_default
from rbx.box.packaging.boca.extension import BocaExtension, BocaLanguage
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.schema import TaskType
from rbx.box.statements.schema import Statement
from rbx.config import get_default_app_path, get_testlib

_MAX_REP_TIME = (
    7  # TL to allow for additional rounding reps should be < _MAX_REP_TIME in seconds
)
_MAX_REPS = 10  # Maximum number of reps to add


def test_time(time):
    return max(1, round(time))


class BocaPackager(BasePackager):
    @classmethod
    def task_types(cls) -> List[TaskType]:
        return [TaskType.BATCH, TaskType.COMMUNICATION]

    def _get_main_statement(self) -> Optional[Statement]:
        pkg = package.find_problem_package_or_die()

        if not pkg.expanded_statements:
            return None

        return pkg.expanded_statements[0]

    def _get_main_built_statement(
        self, built_statements: List[BuiltStatement]
    ) -> Optional[BuiltStatement]:
        statement = self._get_main_statement()
        if statement is None:
            return None

        for built_statement in built_statements:
            if built_statement.statement == statement:
                return built_statement

        return None

    def _get_problem_name(self) -> str:
        # BOCA forces Java class names to be the name of the problem.
        return self.package_basename().replace('-', '_')

    def _get_problem_basename(self) -> str:
        extension = get_extension_or_default('boca', BocaExtension)
        shortname = naming.get_problem_shortname()
        if extension.preferContestLetter and shortname is not None:
            return shortname
        return self._get_problem_name()

    def _get_problem_info(self) -> str:
        statement = self._get_main_statement()
        lang = statement.language if statement is not None else None
        title = naming.get_title(lang, statement, fallback_to_title=True)
        return (
            f'basename={self._get_problem_basename()}\n'
            f'fullname={title}\n'
            f'descfile={self._get_problem_basename()}.pdf\n'
        )

    def _get_pkg_timelimit(self, language: BocaLanguage) -> int:
        limits = limits_info.get_limits(language, profile='boca')
        assert limits.time is not None
        return limits.time

    def _get_pkg_memorylimit(self, language: BocaLanguage) -> int:
        limits = limits_info.get_limits(language, profile='boca')
        assert limits.memory is not None
        return limits.memory

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
        if pkg.type == TaskType.COMMUNICATION:
            # Interactive tasks only support a single run.
            no_of_runs = 1
            time_limit = f'{self._get_pkg_timelimit(language) / 1000:.2f}'
        else:
            no_of_runs = self._get_number_of_runs(language)
            time_limit = test_time(
                self._get_pkg_timelimit(language) / 1000 * no_of_runs
            )
        return (
            '#!/bin/bash\n'
            f'echo {time_limit}\n'
            f'echo {no_of_runs}\n'
            f'echo {self._get_pkg_memorylimit(language)}\n'
            f'echo {pkg.outputLimit}\n'
            f'exit 0\n'
        )

    def _get_compare(self) -> str:
        compare_path = get_default_app_path() / 'packagers' / 'boca' / 'compare.sh'
        if not compare_path.exists():
            console.console.print(
                '[error]BOCA template compare script not found.[/error]'
            )
            raise typer.Exit(1)
        return compare_path.read_text()

    def _get_checker(self) -> str:
        extension = get_extension_or_default('boca', BocaExtension)

        checker_path = get_default_app_path() / 'packagers' / 'boca' / 'checker.sh'
        if not checker_path.exists():
            console.console.print(
                '[error]BOCA template checker script not found.[/error]'
            )
            raise typer.Exit(1)
        checker_text = checker_path.read_text()
        testlib = get_testlib().read_text()
        checker = package.get_checker().path.read_text()
        rbx_header = header.get_header().read_text()
        return (
            checker_text.replace('{{rbxFlags}}', extension.flags_with_defaults()['cc'])
            .replace('{{testlib_content}}', testlib)
            .replace('{{rbx_header_content}}', rbx_header)
            .replace('{{checker_content}}', checker)
        )

    def _get_interactor(self) -> str:
        extension = get_extension_or_default('boca', BocaExtension)

        interactor_path = (
            get_default_app_path() / 'packagers' / 'boca' / 'interactor_compile.sh'
        )
        if not interactor_path.exists():
            console.console.print(
                '[error]BOCA template interactor compile script not found.[/error]'
            )
            raise typer.Exit(1)

        interactor_text = interactor_path.read_text()
        interactor = package.get_interactor().path.read_text()
        return interactor_text.replace(
            '{{rbxFlags}}', extension.flags_with_defaults()['cc']
        ).replace('{{interactor_content}}', interactor)

    def _get_safeexec(self) -> str:
        safeexec_script_path = (
            get_default_app_path() / 'packagers' / 'boca' / 'safeexec_compile.sh'
        )
        safeexec_path = get_default_app_path() / 'packagers' / 'boca' / 'safeexec.c'
        if not safeexec_script_path.exists():
            console.console.print(
                '[error]BOCA template safeexec compile script not found.[/error]'
            )
            raise typer.Exit(1)
        if not safeexec_path.exists():
            console.console.print(
                '[error]BOCA template safeexec source code not found.[/error]'
            )
            raise typer.Exit(1)
        return safeexec_script_path.read_text().replace(
            '{{safeexec_content}}', safeexec_path.read_text()
        )

    def _get_compile(self, language: BocaLanguage) -> str:
        pkg = package.find_problem_package_or_die()
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
        if pkg.type == TaskType.COMMUNICATION:
            compile_text = compile_text.replace(
                'umask 0022', 'umask 0022\n\n' + self._get_interactor()
            )
            compile_text = compile_text.replace(
                'umask 0022', 'umask 0022\n\n' + self._get_safeexec()
            )
        compile_text = compile_text.replace(
            'umask 0022', 'umask 0022\n\n' + self._get_checker()
        )

        flags = extension.flags_with_defaults()
        if language in flags:
            compile_text = compile_text.replace('{{rbxFlags}}', flags[language])
        return compile_text

    def _copy_solutions(self, into_path: pathlib.Path):
        for solution in package.get_solutions():
            dest_path = (
                into_path
                / solution.path.stem
                / pathlib.Path(self._get_problem_name()).with_suffix(
                    solution.path.suffix
                )
            )
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(solution.path), dest_path)

    def _expand_run_script(self, run_path: pathlib.Path):
        pkg = package.find_problem_package_or_die()
        if pkg.type == TaskType.COMMUNICATION:
            runit_content = (
                get_default_app_path() / 'packagers' / 'boca' / 'interactor_run.sh'
            ).read_text()
            run_path.write_text(
                run_path.read_text().replace(
                    '{{runit_content}}',
                    runit_content,
                )
            )

    @classmethod
    def name(cls) -> str:
        return 'boca'

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        extension = get_extension_or_default('boca', BocaExtension)
        pkg = package.find_problem_package_or_die()
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
            if pkg.type == TaskType.COMMUNICATION:
                run_orig_path = (
                    get_default_app_path()
                    / 'packagers'
                    / 'boca'
                    / 'interactive'
                    / language
                )
            if not run_orig_path.is_file():
                console.console.print(
                    f'[error]Run script for language [item]{language}[/item] not found for task of type [item]{pkg.type}[/item].[/error]'
                )
                raise typer.Exit(1)
            shutil.copyfile(run_orig_path, run_path / language)
            self._expand_run_script(run_path / language)

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
        main_built_statement = self._get_main_built_statement(built_statements)
        if main_built_statement is not None:
            description_path = into_path / 'description'
            description_path.mkdir(parents=True, exist_ok=True)
            (description_path / 'problem.info').write_text(self._get_problem_info())
            shutil.copyfile(
                self._get_main_built_statement(built_statements).path,
                (description_path / self._get_problem_basename()).with_suffix('.pdf'),
            )

        # Copy solutions
        solutions_path = into_path / 'solutions'
        solutions_path.mkdir(parents=True, exist_ok=True)
        self._copy_solutions(solutions_path)

        # Prepare IO
        inputs_path = into_path / 'input'
        inputs_path.mkdir(parents=True, exist_ok=True)
        outputs_path = into_path / 'output'
        outputs_path.mkdir(parents=True, exist_ok=True)

        testcases = self.get_flattened_built_testcases()
        for i, testcase in enumerate(testcases):
            shutil.copyfile(testcase.inputPath, inputs_path / f'{i + 1:03d}')
            if testcase.outputPath is not None:
                shutil.copyfile(testcase.outputPath, outputs_path / f'{i + 1:03d}')
            else:
                (outputs_path / f'{i + 1:03d}').touch()

        # Zip all.
        shutil.make_archive(
            str(build_path / self._get_problem_name()), 'zip', into_path
        )

        return (build_path / self._get_problem_name()).with_suffix('.zip')
