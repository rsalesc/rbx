import dataclasses
import pathlib
from abc import ABC, abstractmethod
from typing import List, Tuple

from rbx.box import naming, package
from rbx.box.contest import contest_package
from rbx.box.contest.schema import ContestProblem, ContestStatement
from rbx.box.generators import get_all_built_testcases
from rbx.box.schema import Package, TaskType, Testcase, TestcaseGroup
from rbx.box.statements.schema import Statement, StatementType


@dataclasses.dataclass
class BuiltStatement:
    statement: Statement
    path: pathlib.Path
    output_type: StatementType


@dataclasses.dataclass
class BuiltContestStatement:
    statement: ContestStatement
    path: pathlib.Path
    output_type: StatementType


@dataclasses.dataclass
class BuiltProblemPackage:
    path: pathlib.Path
    package: Package
    problem: ContestProblem


class BasePackager(ABC):
    @classmethod
    @abstractmethod
    def name(cls) -> str:
        pass

    @classmethod
    def task_types(cls) -> List[TaskType]:
        return [TaskType.BATCH]

    def languages(self):
        pkg = package.find_problem_package_or_die()

        res = set()
        for statement in pkg.statements:
            res.add(statement.language)
        return list(res)

    def package_basename(self):
        pkg = package.find_problem_package_or_die()
        shortname = naming.get_problem_shortname()
        if shortname is not None:
            return f'{shortname}-{pkg.name}'
        return pkg.name

    def statement_types(self) -> List[StatementType]:
        return [StatementType.PDF]

    @abstractmethod
    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        pass

    # Helper methods.
    def get_built_testcases_per_group(self):
        return get_all_built_testcases()

    def get_built_testcases(self) -> List[Tuple[TestcaseGroup, List[Testcase]]]:
        pkg = package.find_problem_package_or_die()
        tests_per_group = self.get_built_testcases_per_group()
        return [(group, tests_per_group[group.name]) for group in pkg.testcases]

    def get_flattened_built_testcases(self) -> List[Testcase]:
        pkg = package.find_problem_package_or_die()
        tests_per_group = self.get_built_testcases_per_group()

        res = []
        for group in pkg.testcases:
            res.extend(tests_per_group[group.name])
        return res

    def get_statement_for_language(self, lang: str) -> Statement:
        pkg = package.find_problem_package_or_die()
        for statement in pkg.statements:
            if statement.language == lang:
                return statement
        raise


class BaseContestPackager(ABC):
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def package(
        self,
        built_packages: List[BuiltProblemPackage],
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltContestStatement],
    ) -> pathlib.Path:
        pass

    def languages(self):
        pkg = contest_package.find_contest_package_or_die()

        res = set()
        for statement in pkg.statements:
            res.add(statement.language)
        return list(res)

    def statement_types(self) -> List[StatementType]:
        return [StatementType.PDF]

    def get_statement_for_language(self, lang: str) -> ContestStatement:
        contest = contest_package.find_contest_package_or_die()
        for statement in contest.statements:
            if statement.language == lang:
                return statement
        raise
