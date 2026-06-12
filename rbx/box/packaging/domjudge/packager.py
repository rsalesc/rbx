import math
import pathlib
import shutil
from typing import List, Optional, Set, Tuple

import typer
import yaml

from rbx import console
from rbx.box import header, limits_info, naming, package
from rbx.box.formatting import href
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.packaging import flattening
from rbx.box.packaging.domjudge.testlib_patch import patch_testlib_for_domjudge
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.schema import ExpectedOutcome, TaskType
from rbx.box.statements.schema import Statement
from rbx.config import get_builtin_checker, get_testlib

# Builtin checkers that match the semantics of DOMjudge's default output
# validator (possibly modulo flags). Anything else ships as a custom validator.
_DEFAULT_VALIDATION_CHECKERS = {
    'wcmp.cpp': None,
    'ncmp.cpp': None,
    'yesno.cpp': None,
    'dcmp.cpp': 'float_tolerance 1e-6',
}

# DOMjudge reports MLE as RTE by default, hence the MLE mapping.
_SUBMISSION_DIRS = {
    ExpectedOutcome.ACCEPTED: 'accepted',
    ExpectedOutcome.WRONG_ANSWER: 'wrong_answer',
    ExpectedOutcome.TIME_LIMIT_EXCEEDED: 'time_limit_exceeded',
    ExpectedOutcome.RUNTIME_ERROR: 'run_time_error',
    ExpectedOutcome.MEMORY_LIMIT_EXCEEDED: 'run_time_error',
}

_CPP_SUFFIXES = {'.cpp', '.cc', '.cxx', '.c++'}


def _fmt_seconds(ms: int) -> str:
    """Format integer milliseconds as exact fractional seconds (no float rounding)."""
    return f'{ms // 1000}.{ms % 1000:03d}'


class DomjudgePackager(BasePackager):
    def __init__(
        self,
        testcase_entries: List[GenerationTestcaseEntry],
        language: Optional[str] = None,
    ):
        super().__init__(testcase_entries)
        self.language = language

    @classmethod
    def name(cls) -> str:
        return 'domjudge'

    @classmethod
    def task_types(cls) -> List[TaskType]:
        return [TaskType.BATCH]

    def languages(self) -> List[str]:
        if self.language is None:
            return super().languages()
        return [self.language]

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

    def _get_short_name(self) -> str:
        shortname = naming.get_problem_shortname_or_require()
        if shortname is not None:
            return shortname
        return package.find_problem_package_or_die().name

    def _get_color(self) -> Optional[str]:
        entry = naming.get_problem_entry_in_contest()
        if entry is None:
            return None
        _, problem = entry
        return problem.color

    def _get_ini(self) -> str:
        statement = self._get_main_statement()
        lang = statement.language if statement is not None else None
        title = naming.get_problem_title(lang, statement, fallback_to_title=True)
        limits = limits_info.get_limits(profile=self.name())
        assert limits.time is not None

        lines = [
            f'short-name = {self._get_short_name()}',
            f'name = {title.replace(chr(39), chr(96))}',
            f'timelimit = {_fmt_seconds(limits.time)}',
        ]
        color = self._get_color()
        if color is not None:
            lines.append(f'color = {color}')
        return '\n'.join(lines) + '\n'

    def _resolve_validation(self) -> Tuple[str, Optional[str]]:
        """Return (validation, validator_flags) for problem.yaml.

        Maps to DOMjudge's default output validator only when the checker
        resolves to one of rbx's bundled builtins; a same-named file inside the
        package may have been edited by the user and ships as custom.
        """
        checker = package.get_checker_or_builtin()
        checker_name = checker.path.name
        if checker_name in _DEFAULT_VALIDATION_CHECKERS:
            builtin_path = get_builtin_checker(checker_name)
            if (
                builtin_path.is_file()
                and checker.path.is_file()
                and checker.path.samefile(builtin_path)
            ):
                return 'default', _DEFAULT_VALIDATION_CHECKERS[checker_name]
        return 'custom', None

    def _get_problem_yaml(self) -> str:
        pkg = package.find_problem_package_or_die()
        limits = limits_info.get_limits(profile=self.name())
        assert limits.memory is not None
        output_kb = limits.output if limits.output is not None else pkg.outputLimit

        validation, validator_flags = self._resolve_validation()
        data = {
            'limits': {
                'memory': limits.memory,
                'output': math.ceil(output_kb / 1024),
            },
            'validation': validation,
        }
        if validator_flags is not None:
            data['validator_flags'] = validator_flags
        return yaml.safe_dump(data, default_flow_style=False)

    def _write_output_validators(self, into_path: pathlib.Path):
        checker = package.get_checker_or_builtin()
        if checker.path.suffix.lower() not in _CPP_SUFFIXES:
            console.console.print(
                f'[error]DOMjudge packaging requires a C++ (testlib) checker, '
                f'but found {href(checker.path)}.[/error]'
            )
            raise typer.Exit(1)

        reserved = {package.get_relative_source_path(checker): 'checker.cpp'}
        ns = flattening.build_flat_namespace([checker], reserved=reserved)

        into_path.mkdir(parents=True, exist_ok=True)
        ns.materialize(into_path)
        (into_path / 'testlib.h').write_text(
            patch_testlib_for_domjudge(get_testlib().read_text())
        )
        (into_path / 'rbx.h').write_text(header.get_header().read_text())

    def _write_testcases(self, data_path: pathlib.Path):
        sample_path = data_path / 'sample'
        secret_path = data_path / 'secret'
        sample_path.mkdir(parents=True, exist_ok=True)
        secret_path.mkdir(parents=True, exist_ok=True)

        counters = {True: 0, False: 0}
        for entry in self.get_built_testcase_entries():
            is_sample = entry.is_sample()
            dest_path = sample_path if is_sample else secret_path
            counters[is_sample] += 1
            index = counters[is_sample]

            testcase = entry.metadata.copied_to
            shutil.copyfile(testcase.inputPath, dest_path / f'{index:03d}.in')
            if testcase.outputPath is not None:
                shutil.copyfile(testcase.outputPath, dest_path / f'{index:03d}.ans')
            else:
                (dest_path / f'{index:03d}.ans').touch()

    def _write_submissions(self, into_path: pathlib.Path):
        used_names: Set[str] = set()
        for solution in package.get_solutions():
            dirname = _SUBMISSION_DIRS.get(solution.outcome)
            if dirname is None:
                console.console.print(
                    f'Skipping solution {href(solution.path)}: outcome '
                    f'[item]{solution.outcome.name}[/item] has no DOMjudge '
                    'submissions directory.'
                )
                continue
            name = solution.path.name
            if name in used_names:
                name = '__'.join(solution.path.parts)
            used_names.add(name)
            dest_path = into_path / dirname / name
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(solution.path), dest_path)

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        into_path.mkdir(parents=True, exist_ok=True)

        (into_path / 'domjudge-problem.ini').write_text(self._get_ini())
        (into_path / 'problem.yaml').write_text(self._get_problem_yaml())

        main_built_statement = self._get_main_built_statement(built_statements)
        if main_built_statement is not None:
            shutil.copyfile(main_built_statement.path, into_path / 'problem.pdf')

        self._write_testcases(into_path / 'data')

        validation, _ = self._resolve_validation()
        if validation == 'custom':
            self._write_output_validators(into_path / 'output_validators')

        self._write_submissions(into_path / 'submissions')

        # Zip all.
        shutil.make_archive(str(build_path / self.package_basename()), 'zip', into_path)

        return (build_path / self.package_basename()).with_suffix('.zip')
