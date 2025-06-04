import pathlib
import shutil
from typing import List, Optional

from rbx.box import naming, package
from rbx.box.contest import contest_package
from rbx.box.contest.schema import ContestStatement
from rbx.box.packaging.packager import (
    BaseContestPackager,
    BasePackager,
    BuiltContestStatement,
    BuiltProblemPackage,
    BuiltStatement,
)
from rbx.box.schema import ExpectedOutcome, TaskType
from rbx.box.statements.schema import Statement


class PkgPackager(BasePackager):
    @classmethod
    def task_types(cls) -> List[TaskType]:
        return [TaskType.BATCH, TaskType.COMMUNICATION]

    @classmethod
    def name(cls) -> str:
        return 'pkg'

    def _get_problem_basename(self) -> str:
        shortname = naming.get_problem_shortname()
        if shortname is not None:
            return shortname
        return self.package_basename()

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

    def _copy_accepted_solutions(self, into_path: pathlib.Path):
        for solution in package.get_solutions():
            if solution.outcome != ExpectedOutcome.ACCEPTED:
                continue
            dest_path = into_path / solution.path.name
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(solution.path), dest_path)

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        into_path.mkdir(parents=True, exist_ok=True)

        main_statement = self._get_main_built_statement(built_statements)
        if main_statement is not None:
            statement_path = into_path / 'statement.pdf'
            shutil.copyfile(main_statement.path, statement_path)

        # Prepare tests
        tests_path = into_path / 'tests'
        tests_path.mkdir(parents=True, exist_ok=True)

        testcases = self.get_flattened_built_testcases()
        for i, testcase in enumerate(testcases):
            shutil.copyfile(testcase.inputPath, tests_path / f'{i + 1:03d}.in')
            if testcase.outputPath is not None:
                shutil.copyfile(testcase.outputPath, tests_path / f'{i + 1:03d}.ans')
            else:
                (tests_path / f'{i + 1:03d}.ans').touch()

        # Copy solutions.
        solutions_path = into_path / 'solutions'
        solutions_path.mkdir(parents=True, exist_ok=True)
        self._copy_accepted_solutions(solutions_path)

        # Zip all.
        shutil.make_archive(
            str(build_path / self._get_problem_basename()), 'zip', into_path
        )

        return (build_path / self._get_problem_basename()).with_suffix('.zip')


class PkgContestPackager(BaseContestPackager):
    @classmethod
    def name(cls) -> str:
        return 'pkg'

    def _get_main_statement(self) -> Optional[ContestStatement]:
        pkg = contest_package.find_contest_package_or_die()
        if not pkg.expanded_statements:
            return None
        return pkg.expanded_statements[0]

    def _get_main_built_statement(
        self, built_statements: List[BuiltContestStatement]
    ) -> Optional[BuiltContestStatement]:
        statement = self._get_main_statement()
        if statement is None:
            return None
        for built_statement in built_statements:
            if built_statement.statement == statement:
                return built_statement
        return None

    def package(
        self,
        built_packages: List[BuiltProblemPackage],
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltContestStatement],
    ) -> pathlib.Path:
        into_path.mkdir(parents=True, exist_ok=True)

        # Add contest-level statement.
        main_statement = self._get_main_built_statement(built_statements)
        if main_statement is not None:
            statement_path = into_path / 'statement.pdf'
            shutil.copyfile(main_statement.path, statement_path)

        # Add problems.
        for built_package in built_packages:
            pkg_path = into_path / built_package.problem.short_name
            shutil.unpack_archive(built_package.path, pkg_path, format='zip')

        # Zip all.
        shutil.make_archive(str(build_path / 'contest'), 'zip', into_path)

        return (build_path / 'contest').with_suffix('.zip')
