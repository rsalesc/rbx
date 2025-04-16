import functools
import pathlib
import shutil
from typing import List, Optional

import iso639
import typer

from rbx import console
from rbx.box import header, package
from rbx.box.packaging.packager import (
    BaseContestPackager,
    BasePackager,
    BuiltContestStatement,
    BuiltProblemPackage,
    BuiltStatement,
)
from rbx.box.packaging.polygon import xml_schema as polygon_schema
from rbx.box.schema import TaskType
from rbx.config import get_testlib

DAT_TEMPLATE = """
@contest "{name}"
@contlen 300
@problems {problems}
@teams 0
@submissions 0
"""


def langs_to_code(langs: List[str]) -> List[str]:
    return [iso639.Language.from_name(lang).part1 for lang in langs]


def code_to_langs(langs: List[str]) -> List[str]:
    return [iso639.Language.from_part1(lang).name.lower() for lang in langs]


@functools.cache
def is_valid_lang_code(lang: str) -> bool:
    try:
        code_to_langs([lang])
    except iso639.LanguageNotFoundError:
        console.console.print(
            f'[warning]Language [item]{lang}[/item] is being skipped because it is not a iso639 language.[/warning]'
        )
        return False

    return True


class PolygonPackager(BasePackager):
    @classmethod
    def task_types(cls) -> List[TaskType]:
        return [TaskType.BATCH, TaskType.COMMUNICATION]

    def _validate(self):
        langs = self.languages()
        pkg = package.find_problem_package_or_die()

        lang_codes = set()
        for statement in pkg.statements:
            lang_codes.add(statement.title)

        for lang in langs:
            if lang not in lang_codes:
                console.console.print(
                    f'[error]No statement from language [item]{lang}[/item] found. '
                    'Polygon needs one statement for each language.[/error]'
                )
                raise typer.Exit(1)

    def _get_names(self) -> List[polygon_schema.Name]:
        return [
            polygon_schema.Name(
                language=code_to_langs([lang])[0],
                value=self.get_statement_for_language(lang).title,
            )
            for lang in self.languages()
        ]

    def _get_checker(self) -> polygon_schema.Checker:
        # TODO: support other checker languages
        return polygon_schema.Checker(
            name='rbx::checker',
            type='testlib',
            source=polygon_schema.File(path='files/check.cpp', type='cpp.g++17'),
            cpy=polygon_schema.File(path='check.cpp'),
        )

    def _get_interactor(self) -> Optional[polygon_schema.Interactor]:
        pkg = package.find_problem_package_or_die()
        if pkg.interactor is None:
            return None
        return polygon_schema.Interactor(
            source=polygon_schema.File(path='files/interactor.cpp', type='cpp.g++17'),
        )

    def _get_manual_test(self) -> polygon_schema.Test:
        # TODO: return samples
        return polygon_schema.Test(method='manual')

    def _get_single_testset(self) -> polygon_schema.Testset:
        pkg = package.find_problem_package_or_die()

        if pkg.modifiers:
            console.console.print(
                f'[warning]Your package specify custom limit modifiers for languages {list(pkg.modifiers)}.[/warning]'
            )
            console.console.print(
                '[warning]Polygon packages do not support language-based limit modifiers, so they will not be applied to the supplied limits.[/warning]'
            )

        console.console.print(
            f'[warning]Polygon packages cannot honor the {pkg.outputLimit}kb output limit.'
        )

        testcases = self.get_flattened_built_testcases()

        return polygon_schema.Testset(
            name='tests',
            timelimit=pkg.timelimit_for_language(None),
            memorylimit=pkg.memorylimit_for_language(None) * 1024 * 1024,
            size=len(testcases),
            inputPattern='tests/%03d',
            answerPattern='tests/%03d.a',
            tests=[self._get_manual_test() for _ in range(len(testcases))],
        )

    def _get_judging(self) -> polygon_schema.Judging:
        return polygon_schema.Judging(testsets=[self._get_single_testset()])

    def _get_files(self) -> List[polygon_schema.File]:
        return [
            polygon_schema.File(path='files/testlib.h', type='h.g++'),
            polygon_schema.File(path='files/rbx.h', type='h.g++'),
        ]

    def _statement_application_type(self, statement: BuiltStatement) -> str:
        return 'application/pdf'

    def _process_statement(
        self,
        built_statement: BuiltStatement,
        into_path: pathlib.Path,
    ) -> polygon_schema.Statement:
        language = code_to_langs([built_statement.statement.language])[0]
        final_path = into_path / 'statements' / language / built_statement.path.name

        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built_statement.path, final_path)

        return polygon_schema.Statement(
            path=str(final_path.resolve().relative_to(into_path.resolve())),
            language=language,
            type=self._statement_application_type(built_statement),  # type: ignore
        )

    def _process_statements(
        self, built_statements: List[BuiltStatement], into_path: pathlib.Path
    ) -> List[polygon_schema.Statement]:
        return [
            self._process_statement(built_statement, into_path)
            for built_statement in built_statements
        ]

    @classmethod
    def name(cls) -> str:
        return 'polygon'

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ):
        pkg = package.find_problem_package_or_die()

        problem = polygon_schema.Problem(
            names=self._get_names(),
            checker=self._get_checker(),
            judging=self._get_judging(),
            files=self._get_files(),
            interactor=self._get_interactor(),
            # TODO: revisit polygon problem statements
            # statements=self._process_statements(built_statements, into_path),
        )

        descriptor: str = problem.to_xml(
            skip_empty=True,
            encoding='utf-8',
            pretty_print=True,
            standalone=True,
        )  # type: ignore
        if isinstance(descriptor, bytes):
            descriptor = descriptor.decode()

        # Prepare files
        files_path = into_path / 'files'
        files_path.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(get_testlib(), files_path / 'testlib.h')
        shutil.copyfile(header.get_header(), files_path / 'rbx.h')
        shutil.copyfile(package.get_checker().path, files_path / 'check.cpp')
        shutil.copyfile(package.get_checker().path, into_path / 'check.cpp')
        if pkg.interactor is not None:
            shutil.copyfile(pkg.interactor.path, files_path / 'interactor.cpp')

        # Copy all testcases
        (into_path / 'tests').mkdir(parents=True, exist_ok=True)
        testcases = self.get_flattened_built_testcases()
        for i, testcase in enumerate(testcases):
            shutil.copyfile(
                testcase.inputPath,
                into_path / f'tests/{i + 1:03d}',
            )
            if testcase.outputPath is not None:
                shutil.copyfile(
                    testcase.outputPath,
                    into_path / f'tests/{i + 1:03d}.a',
                )
            else:
                (into_path / f'tests/{i + 1:03d}.a').touch()

        # Write problem.xml
        (into_path / 'problem.xml').write_text(descriptor)

        # Zip all.
        shutil.make_archive(str(build_path / 'problem'), 'zip', into_path)

        return build_path / 'problem.zip'


class PolygonContestPackager(BaseContestPackager):
    @classmethod
    def name(cls) -> str:
        return 'polygon'

    def _get_names(self) -> List[polygon_schema.Name]:
        names = [
            polygon_schema.Name(
                language=code_to_langs([lang])[0],
                value=self.get_statement_for_language(lang).title,
            )
            for lang in self.languages()
            if is_valid_lang_code(lang)
        ]
        if names:
            names[0].main = True
        return names

    def _process_statement(
        self,
        built_statement: BuiltContestStatement,
        into_path: pathlib.Path,
    ) -> polygon_schema.Statement:
        language = code_to_langs([built_statement.statement.language])[0]
        final_path = into_path / 'statements' / language / built_statement.path.name

        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built_statement.path, final_path)

        return polygon_schema.Statement(
            path=str(final_path.resolve().relative_to(into_path.resolve())),
            language=language,
            type='application/pdf',  # type: ignore
        )

    def _process_statements(
        self, built_statements: List[BuiltContestStatement], into_path: pathlib.Path
    ) -> List[polygon_schema.Statement]:
        return [
            self._process_statement(built_statement, into_path)
            for built_statement in built_statements
        ]

    def _get_problems(
        self, built_packages: List[BuiltProblemPackage]
    ) -> List[polygon_schema.ContestProblem]:
        return [
            polygon_schema.ContestProblem(
                index=built_package.problem.short_name,
                path=str(pathlib.Path('problems') / built_package.problem.short_name),
            )
            for built_package in built_packages
        ]

    def _get_dat(self, built_packages: List[BuiltProblemPackage]) -> str:
        dat = DAT_TEMPLATE.format(
            name=self.get_statement_for_language(self.languages()[0]).title,
            problems=len(built_packages),
        )
        return (
            dat
            + '\n'.join(
                f'@p {pkg.problem.short_name},{pkg.problem.short_name},20,0'
                for pkg in built_packages
            )
            + '\n'
        )

    def package(
        self,
        built_packages: List[BuiltProblemPackage],
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltContestStatement],
    ) -> pathlib.Path:
        filtered_statements = []
        for built_statement in built_statements:
            if not is_valid_lang_code(built_statement.statement.language):
                continue
            filtered_statements.append(built_statement)

        for built_package in built_packages:
            pkg_path = into_path / 'problems' / built_package.problem.short_name
            pkg_path.mkdir(parents=True, exist_ok=True)

            shutil.unpack_archive(built_package.path, pkg_path, format='zip')

        # Build contest descriptor.
        contest = polygon_schema.Contest(
            names=self._get_names(),
            statements=self._process_statements(filtered_statements, into_path),
            problems=self._get_problems(built_packages),
        )
        descriptor: str = contest.to_xml(
            skip_empty=True,
            encoding='utf-8',
            pretty_print=True,
            standalone=True,
        )  # type: ignore
        if isinstance(descriptor, bytes):
            descriptor = descriptor.decode()

        # Write contest.xml
        (into_path / 'contest.xml').write_text(descriptor)

        # Write contest.dat
        (into_path / 'contest.dat').write_text(self._get_dat(built_packages))

        # Zip all.
        shutil.make_archive(str(build_path / 'contest'), 'zip', into_path)

        return pathlib.Path('contest.zip')
