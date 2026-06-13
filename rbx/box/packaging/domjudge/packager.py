import math
import pathlib
import shutil
from typing import Dict, List, Optional, Set

import typer
import yaml

from rbx import console
from rbx.box import code, environment, header, limits_info, naming, package
from rbx.box.formatting import href
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.packaging import flattening
from rbx.box.packaging.domjudge.testlib_patch import patch_testlib_for_domjudge
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.schema import ExpectedOutcome, Solution, TaskType
from rbx.box.statements.schema import Statement
from rbx.config import get_testlib
from rbx.grading.language_kind import LanguageKind

# DOMjudge `@EXPECTED_RESULTS@` verdict tokens (canonical hyphenated spelling).
# See SubmissionService::PROBLEM_RESULT_REMAP in DOMjudge.
_DJ_CORRECT = 'CORRECT'
_DJ_WRONG_ANSWER = 'WRONG-ANSWER'
_DJ_TIMELIMIT = 'TIMELIMIT'
_DJ_RUN_ERROR = 'RUN-ERROR'
_DJ_NO_OUTPUT = 'NO-OUTPUT'
_DJ_OUTPUT_LIMIT = 'OUTPUT-LIMIT'

# Every rbx outcome maps to the set of DOMjudge verdict tokens that satisfy it,
# so no solution is ever dropped from the package. DOMjudge has no memory-limit
# verdict (an over-memory run surfaces as RTE, sometimes TLE), so MLE is the one
# lossy mapping; everything else is exact. `ANY` lists every runtime verdict
# (anything but a compile error is acceptable).
_EXPECTED_RESULTS: Dict[ExpectedOutcome, List[str]] = {
    ExpectedOutcome.ACCEPTED: [_DJ_CORRECT],
    ExpectedOutcome.WRONG_ANSWER: [_DJ_WRONG_ANSWER],
    ExpectedOutcome.TIME_LIMIT_EXCEEDED: [_DJ_TIMELIMIT],
    ExpectedOutcome.RUNTIME_ERROR: [_DJ_RUN_ERROR],
    ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED: [_DJ_OUTPUT_LIMIT],
    ExpectedOutcome.MEMORY_LIMIT_EXCEEDED: [_DJ_RUN_ERROR, _DJ_TIMELIMIT],
    ExpectedOutcome.ACCEPTED_OR_TLE: [_DJ_CORRECT, _DJ_TIMELIMIT],
    ExpectedOutcome.TLE_OR_RTE: [_DJ_TIMELIMIT, _DJ_RUN_ERROR],
    ExpectedOutcome.INCORRECT: [
        _DJ_WRONG_ANSWER,
        _DJ_RUN_ERROR,
        _DJ_TIMELIMIT,
        _DJ_OUTPUT_LIMIT,
        _DJ_NO_OUTPUT,
    ],
    ExpectedOutcome.ANY: [
        _DJ_CORRECT,
        _DJ_WRONG_ANSWER,
        _DJ_TIMELIMIT,
        _DJ_RUN_ERROR,
        _DJ_OUTPUT_LIMIT,
        _DJ_NO_OUTPUT,
    ],
}

# Single-verdict tokens that have a dedicated DOMjudge submission directory.
# DOMjudge derives the expected verdict from the directory name, so dropping a
# solution here needs no source annotation (and avoids a spurious import
# warning). `output_limit` is a DOMjudge extension over the 4 ICPC-spec dirs.
_STANDARD_DIRS: Dict[str, str] = {
    _DJ_CORRECT: 'accepted',
    _DJ_WRONG_ANSWER: 'wrong_answer',
    _DJ_TIMELIMIT: 'time_limit_exceeded',
    _DJ_RUN_ERROR: 'run_time_error',
    _DJ_OUTPUT_LIMIT: 'output_limit',
}

# Solutions whose expectation needs more than one verdict go here with an
# `@EXPECTED_RESULTS@` annotation. The directory name is deliberately NOT a
# verdict token: DOMjudge keeps the annotation verbatim (multiple acceptable
# verdicts) instead of collapsing it to the directory's single verdict.
_MIXED_DIR = 'mixed'


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

    def _get_problem_yaml(self) -> str:
        # The rbx checker is always shipped as a custom output validator (below),
        # so DOMjudge judges with exactly the same checker rbx uses locally
        # instead of approximating it with DOMjudge's default validator.
        pkg = package.find_problem_package_or_die()
        limits = limits_info.get_limits(profile=self.name())
        assert limits.memory is not None
        output_kb = limits.output if limits.output is not None else pkg.outputLimit

        data = {
            'limits': {
                'memory': limits.memory,
                'output': math.ceil(output_kb / 1024),
            },
            'validation': 'custom',
        }
        return yaml.safe_dump(data, default_flow_style=False)

    def _write_output_validators(self, into_path: pathlib.Path):
        checker = package.get_checker_or_builtin()
        if LanguageKind.CPP not in environment.language_kinds(
            code.find_language(checker)
        ):
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

    def _expected_results(self, solution: Solution) -> List[str]:
        return _EXPECTED_RESULTS.get(
            solution.outcome, _EXPECTED_RESULTS[ExpectedOutcome.ANY]
        )

    def _comment_prefix(self, solution: Solution) -> str:
        kinds = environment.language_kinds(code.find_language(solution))
        return '#' if LanguageKind.PYTHON in kinds else '//'

    def _write_submissions(self, into_path: pathlib.Path):
        # DOMjudge auto-judges these on import and surfaces any verdict mismatch
        # on the jury "Judging verifier" page, so every rbx solution ships with a
        # faithful expectation. Single-verdict outcomes use the matching standard
        # directory; the rest go to `mixed/` with an `@EXPECTED_RESULTS@`
        # annotation listing every acceptable verdict.
        used_names: Set[str] = set()
        for solution in package.get_solutions():
            tokens = self._expected_results(solution)
            standard_dir = _STANDARD_DIRS.get(tokens[0]) if len(tokens) == 1 else None

            name = solution.path.name
            if name in used_names:
                name = '__'.join(solution.path.parts)
            used_names.add(name)

            if standard_dir is not None:
                dest_path = into_path / standard_dir / name
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(str(solution.path), dest_path)
                continue

            dest_path = into_path / _MIXED_DIR / name
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            source = solution.path.read_text()
            if source and not source.endswith('\n'):
                source += '\n'
            annotation = (
                f'{self._comment_prefix(solution)} '
                f'@EXPECTED_RESULTS@: {", ".join(tokens)}\n'
            )
            dest_path.write_text(source + annotation)

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

        # The rbx checker is always shipped as a custom output validator.
        self._write_output_validators(into_path / 'output_validators')

        self._write_submissions(into_path / 'submissions')

        # Zip all.
        shutil.make_archive(str(build_path / self.package_basename()), 'zip', into_path)

        return (build_path / self.package_basename()).with_suffix('.zip')
