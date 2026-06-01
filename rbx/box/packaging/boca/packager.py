import math
import pathlib
import shutil
from typing import List, Optional, Tuple

import typer

from rbx import console, utils
from rbx.box import header, limits_info, naming, package
from rbx.box.environment import get_extension_or_default
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.packaging.boca.boca_language_utils import (
    get_boca_template_name,
    get_emitted_boca_languages,
    get_rbx_language_from_boca_language,
)
from rbx.box.packaging.boca.extension import (
    BocaExtension,
    BocaLanguage,
)
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.schema import TaskType, TimingGroupOrigin
from rbx.box.statements.schema import Statement
from rbx.config import get_default_app_path, get_testlib

_MAX_REPS = 10  # Maximum number of reps to add


def _fmt_seconds(ms: int) -> str:
    """Format integer milliseconds as exact fractional seconds (no float rounding)."""
    return f'{ms // 1000}.{ms % 1000:03d}'


def _compute_reps(tl_ms: int, min_ms: Optional[int]) -> Tuple[int, bool]:
    """Return (repetitions, was_capped) for a BOCA limits script.

    When `min_ms` is None, always a single run. Otherwise run enough times for the
    accumulated budget (reps * tl) to reach `min_ms`, capped at `_MAX_REPS`. The effective
    per-run TL stays exactly `tl_ms` regardless of the cap.
    """
    if tl_ms <= 0:
        return 1, False
    if min_ms is None:
        return 1, False
    reps = max(1, math.ceil(min_ms / tl_ms))
    if reps > _MAX_REPS:
        return _MAX_REPS, True
    return reps, False


class BocaPackager(BasePackager):
    def __init__(
        self,
        testcase_entries: List[GenerationTestcaseEntry],
        language: Optional[str] = None,
    ):
        super().__init__(testcase_entries)
        self.language = language

    def languages(self) -> List[str]:
        if self.language is None:
            return super().languages()
        return [self.language]

    @classmethod
    def task_types(cls) -> List[TaskType]:
        return [TaskType.BATCH, TaskType.COMMUNICATION]

    def _get_main_statement(self) -> Optional[Statement]:
        pkg = package.find_problem_package_or_die()

        if not pkg.expanded_statements:
            return None

        if self.language is None:
            return pkg.expanded_statements[0]

        for statement in pkg.expanded_statements:
            if statement.language == self.language:
                return statement

        return None

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

    def _get_zip_filename(self) -> str:
        if self.language is None:
            return self._get_problem_name()
        return f'{self._get_problem_name()}-{self.language}'

    def _get_problem_basename(self) -> str:
        extension = get_extension_or_default('boca', BocaExtension)
        if extension.preferContestLetter:
            # Strict path: enforce explicit variant selection in dispatcher mode.
            shortname = naming.get_problem_shortname_or_require()
            if shortname is not None:
                return shortname
            # Stand-alone problem (no contest at all): no letter to use.
            return package.find_problem_package_or_die().name.replace('-', '_')
        # Lenient path: user opted out of the letter prefix, so we use the
        # package name directly without going through the strict letter
        # resolution. This matches the pre-strictness behavior for
        # preferContestLetter=False.
        return package.find_problem_package_or_die().name.replace('-', '_')

    def _get_problem_info(self) -> str:
        statement = self._get_main_statement()
        lang = statement.language if statement is not None else None
        title = naming.get_problem_title(lang, statement, fallback_to_title=True)
        return (
            f'basename={self._get_problem_basename()}\n'
            f'fullname="{title}"\n'
            f'descfile={self._get_problem_basename()}.pdf\n'
        )

    def _get_pkg_timelimit(self, language: BocaLanguage) -> int:
        # Limit modifiers are keyed by the underlying rbx language, so a BOCA
        # variant (e.g. the legacy `cc` alias of `cpp`) must be mapped back to
        # its rbx language before lookup -- otherwise it misses the modifier and
        # falls back to the base limit (#493).
        rbx_language = get_rbx_language_from_boca_language(language)
        limits = limits_info.get_limits(rbx_language, profile='boca')
        assert limits.time is not None
        return limits.time

    def _get_pkg_memorylimit(self, language: BocaLanguage) -> int:
        rbx_language = get_rbx_language_from_boca_language(language)
        limits = limits_info.get_limits(rbx_language, profile='boca')
        assert limits.memory is not None
        return limits.memory

    def _get_number_of_runs(self, language: BocaLanguage) -> int:
        extension = get_extension_or_default('boca', BocaExtension)
        tl_ms = self._get_pkg_timelimit(language)
        reps, capped = _compute_reps(tl_ms, extension.minRunningTime)
        if capped:
            console.console.print(
                f'[warning]minRunningTime of {extension.minRunningTime}ms could not be '
                f'fully honored for language [item]{language}[/item] (TL is {tl_ms}ms); '
                f'capping at {reps} run(s). The effective TL stays exact.[/warning]'
            )
        return reps

    def _get_limits(self, language: BocaLanguage) -> str:
        pkg = package.find_problem_package_or_die()
        tl_ms = self._get_pkg_timelimit(language)
        if pkg.type == TaskType.COMMUNICATION:
            # Interactive tasks only support a single run.
            no_of_runs = 1
        else:
            no_of_runs = self._get_number_of_runs(language)
        time_limit = _fmt_seconds(tl_ms * no_of_runs)
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

    def _replace_common(self, text: str, lang: str) -> str:
        extension = get_extension_or_default('boca', BocaExtension)
        flags = extension.flags_with_defaults()
        if lang in flags:
            text = text.replace('{{rbxFlags}}', flags[lang])
        return text.replace(
            '{{rbxPython3}}', 'pypy3' if extension.usePypy else 'python3'
        )

    def _get_checker(self) -> str:
        checker_path = get_default_app_path() / 'packagers' / 'boca' / 'checker.sh'
        if not checker_path.exists():
            console.console.print(
                '[error]BOCA template checker script not found.[/error]'
            )
            raise typer.Exit(1)
        checker_text = checker_path.read_text()
        testlib = get_testlib().read_text()
        checker = package.get_checker_or_builtin().path.read_text()
        rbx_header = header.get_header().read_text()
        return (
            self._replace_common(checker_text, 'cc')
            .replace('{{testlib_content}}', testlib)
            .replace('{{rbx_header_content}}', rbx_header)
            .replace('{{checker_content}}', checker)
        )

    def _get_interactor(self) -> str:
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
        return self._replace_common(interactor_text, 'cc').replace(
            '{{interactor_content}}', interactor
        )

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

    def _get_pipe(self) -> str:
        pipe_script_path = (
            get_default_app_path() / 'packagers' / 'boca' / 'pipe_compile.sh'
        )
        pipe_path = get_default_app_path() / 'packagers' / 'boca' / 'pipe.c'
        if not pipe_script_path.exists():
            console.console.print(
                '[error]BOCA template pipe compile script not found.[/error]'
            )
            raise typer.Exit(1)
        if not pipe_path.exists():
            console.console.print(
                '[error]BOCA template pipe source code not found.[/error]'
            )
            raise typer.Exit(1)
        return pipe_script_path.read_text().replace(
            '{{pipe_content}}', pipe_path.read_text()
        )

    def _get_compile(self, language: BocaLanguage) -> str:
        pkg = package.find_problem_package_or_die()

        template_name = get_boca_template_name(language)
        compile_path = (
            get_default_app_path() / 'packagers' / 'boca' / 'compile' / template_name
        )
        if not compile_path.is_file():
            console.console.print(
                f'[error]Compile script for template [item]{template_name}[/item] not found.[/error]'
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
                'umask 0022', 'umask 0022\n\n' + self._get_pipe()
            )
        compile_text = compile_text.replace(
            'umask 0022', 'umask 0022\n\n' + self._get_checker()
        )

        compile_text = self._replace_common(compile_text, language)
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

    def _expand_run_script(self, run_path: pathlib.Path, language: BocaLanguage):
        pkg = package.find_problem_package_or_die()
        content = run_path.read_text()
        if pkg.type == TaskType.COMMUNICATION:
            runit_content = (
                get_default_app_path() / 'packagers' / 'boca' / 'interactor_run.sh'
            ).read_text()
            content = content.replace('{{runit_content}}', runit_content)

        content = self._replace_common(content, language)
        run_path.write_text(content)

    def _validate_package(self, into_path: pathlib.Path):
        for file in into_path.rglob('*'):
            if not file.is_file():
                continue
            if file.is_relative_to(into_path / 'input'):
                continue
            relfile = utils.relpath(file, into_path)
            if 'input' in str(relfile):
                console.console.print(
                    '[error]File whose name contains [item]input[/item] is not allowed in a BOCA package.[/error]'
                )
                console.console.print(
                    f'[error]Offending file: [item]{relfile}[/item][/error]'
                )
                raise typer.Exit(1)

    @classmethod
    def name(cls) -> str:
        return 'boca'

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        pkg = package.find_problem_package_or_die()
        # Prepare limits
        if 'boca' not in limits_info.get_available_profile_names():
            console.console.print(
                '[error]Required limits profile [item]boca[/item] not found.[/error]'
            )
            console.console.print(
                '[error]Make sure to run [item]rbx time -p boca[/item] to create the limits profile.[/error]'
            )
            raise typer.Exit(1)
        emitted_languages = get_emitted_boca_languages()
        limits_path = into_path / 'limits'
        limits_path.mkdir(parents=True, exist_ok=True)
        for language in emitted_languages:
            (limits_path / language).write_text(self._get_limits(language))

        # Prepare compare
        compare_path = into_path / 'compare'
        compare_path.mkdir(parents=True, exist_ok=True)
        for language in emitted_languages:
            (compare_path / language).write_text(self._get_compare())

        # Prepare run
        run_path = into_path / 'run'
        run_path.mkdir(parents=True, exist_ok=True)
        for language in emitted_languages:
            template_name = get_boca_template_name(language)
            sub = 'interactive' if pkg.type == TaskType.COMMUNICATION else 'run'
            run_orig_path = (
                get_default_app_path() / 'packagers' / 'boca' / sub / template_name
            )
            if not run_orig_path.is_file():
                console.console.print(
                    f'[error]Run script for template [item]{template_name}[/item] not found for task of type [item]{pkg.type}[/item].[/error]'
                )
                raise typer.Exit(1)
            shutil.copyfile(run_orig_path, run_path / language)
            self._expand_run_script(run_path / language, language)

        # Prepare compile.
        compile_path = into_path / 'compile'
        compile_path.mkdir(parents=True, exist_ok=True)
        for language in emitted_languages:
            (compile_path / language).write_text(self._get_compile(language))

        # Prepare tests
        tests_path = into_path / 'tests'
        tests_path.mkdir(parents=True, exist_ok=True)
        for language in emitted_languages:
            (tests_path / language).write_text('exit 0\n')

        # Problem statement
        main_built_statement = self._get_main_built_statement(built_statements)
        description_path = into_path / 'description'
        description_path.mkdir(parents=True, exist_ok=True)
        (description_path / 'problem.info').write_text(self._get_problem_info())
        pdf_path = (description_path / self._get_problem_basename()).with_suffix('.pdf')
        if main_built_statement is not None:
            shutil.copyfile(
                main_built_statement.path,
                pdf_path,
            )
        else:
            pdf_path.touch(exist_ok=True)

        # Copy solutions
        # WARNING: this is broken, BOCA has a weird check
        # for files with a substring "input". It's too
        # dangerous to ship extra files in the package, let's
        # avoid it for now.
        # solutions_path = into_path / 'solutions'
        # solutions_path.mkdir(parents=True, exist_ok=True)
        # self._copy_solutions(solutions_path)

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

        self._validate_package(into_path)

        # Zip all.
        shutil.make_archive(
            str(build_path / self._get_zip_filename()), 'zip', into_path
        )

        boca_profile = limits_info.get_display_limits_profile('boca')
        if boca_profile is not None:
            limits_info.render_limits_table(
                boca_profile, title='BOCA time limits (per language group)'
            )
            defaulted = [
                lang
                for report in (boca_profile.groups or [])
                if report.origin == TimingGroupOrigin.DEFAULTED
                for lang in report.languages
            ]
            if defaulted:
                console.console.print(
                    '[warning]⚠ These languages have no solution and no whenEmpty '
                    'rule, so they ship the base time limit: '
                    f'{", ".join(defaulted)}.[/warning]'
                )

        return (build_path / self._get_zip_filename()).with_suffix('.zip')
