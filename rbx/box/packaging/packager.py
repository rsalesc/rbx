import dataclasses
import pathlib
import shutil
import tempfile
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Type

import typer

from rbx import console
from rbx.box import environment, header, limits_info, naming, package
from rbx.box.contest import contest_package
from rbx.box.contest.schema import ContestProblem, ContestStatement
from rbx.box.formatting import href
from rbx.box.generators import get_all_built_testcases
from rbx.box.schema import Package, TaskType, Testcase, TestcaseGroup
from rbx.box.statements.build_statements import build_statement
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
        for statement in pkg.expanded_statements:
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

    def get_statement_for_language_or_null(self, lang: str) -> Optional[Statement]:
        pkg = package.find_problem_package_or_die()
        for statement in pkg.expanded_statements:
            if statement.language == lang:
                return statement
        return None

    def get_statement_for_language_or_die(self, lang: str) -> Statement:
        statement = self.get_statement_for_language_or_null(lang)
        if statement is None:
            raise ValueError(f'No statement for language {lang} found.')
        return statement


class BaseContestPackager(ABC):
    @classmethod
    @abstractmethod
    def name(cls) -> str:
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
        for statement in pkg.expanded_statements:
            res.add(statement.language)
        return list(res)

    def statement_types(self) -> List[StatementType]:
        return [StatementType.PDF]

    def get_statement_for_language(self, lang: str) -> ContestStatement:
        contest = contest_package.find_contest_package_or_die()
        for statement in contest.expanded_statements:
            if statement.language == lang:
                return statement
        raise


class ContestZipper(BaseContestPackager):
    def __init__(
        self, filename: str, zip_inner: bool = False, prefer_shortname: bool = True
    ):
        super().__init__()
        self.zip_inner = zip_inner
        self.filename = filename
        self.prefer_shortname = prefer_shortname

    def package(
        self,
        built_packages: List[BuiltProblemPackage],
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltContestStatement],
    ) -> pathlib.Path:
        for built_package in built_packages:
            if self.prefer_shortname:
                pkg_path = into_path / 'problems' / built_package.problem.short_name
            else:
                pkg_path = into_path / 'problems' / built_package.package.name

            if self.zip_inner:
                pkg_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(built_package.path, pkg_path.with_suffix('.zip'))
            else:
                pkg_path.mkdir(parents=True, exist_ok=True)
                shutil.unpack_archive(built_package.path, pkg_path, format='zip')

        # Zip all.
        shutil.make_archive(str(build_path / self.filename), 'zip', into_path)

        return build_path / pathlib.Path(self.filename).with_suffix('.zip')


async def run_packager(
    packager_cls: Type[BasePackager],
    verification: environment.VerificationParam,
    **kwargs,
) -> pathlib.Path:
    from rbx.box import builder

    header.generate_header()

    if limits_info.get_saved_limits_profile(packager_cls.name()) is not None:
        console.console.print(
            f'[warning]Using saved limits profile for [item]{packager_cls.name()}[/item].[/warning]'
        )

    with limits_info.use_profile(packager_cls.name()):
        if not await builder.verify(verification=verification):
            console.console.print(
                '[error]Build or verification failed, check the report.[/error]'
            )
            raise typer.Exit(1)

    pkg = package.find_problem_package_or_die()

    if pkg.type not in packager_cls.task_types():
        console.console.print(
            f'[error]Packager [item]{packager_cls.name()}[/item] does not support task type [item]{pkg.type}[/item].[/error]'
        )
        raise typer.Exit(1)

    packager = packager_cls(**kwargs)

    statement_types = packager.statement_types()
    built_statements = []

    with limits_info.use_profile(packager_cls.name()):
        for statement_type in statement_types:
            languages = packager.languages()
            for language in languages:
                statement = packager.get_statement_for_language_or_die(language)
                statement_path = build_statement(statement, pkg, statement_type)
                built_statements.append(
                    BuiltStatement(statement, statement_path, statement_type)
                )

    console.console.print(f'Packaging problem for [item]{packager.name()}[/item]...')

    with tempfile.TemporaryDirectory() as td, limits_info.use_profile(
        packager_cls.name()
    ):
        result_path = packager.package(
            package.get_build_path(), pathlib.Path(td), built_statements
        )

    console.console.print(
        f'[success]Problem packaged for [item]{packager.name()}[/item]![/success]'
    )
    console.console.print(f'Package was saved at {href(result_path)}')
    return result_path
