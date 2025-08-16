import pathlib
import shutil
from typing import List, Optional

import typer

from rbx import console, utils
from rbx.box import lang
from rbx.box.packaging.importer import BaseImporter
from rbx.box.packaging.polygon.xml_schema import File, Problem, Statement, Testset
from rbx.box.schema import CodeItem, Interactor, Package, TaskType, TestcaseGroup
from rbx.box.statements.schema import Statement as BoxStatement
from rbx.box.statements.schema import StatementType


def _get_main_testset(problem: Problem) -> Testset:
    for testset in problem.judging.testsets:
        if testset.name == 'tests':
            return testset
    console.console.print(
        '[error][item]tests[/item] testset not found[/error]',
    )
    raise typer.Exit(1)


def _get_pdf_statements(problem: Problem) -> List[Statement]:
    statements = []
    for statement in problem.statements:
        if statement.type == 'application/pdf':
            statements.append(statement)
    return statements


def _get_statement_path(statement: Statement) -> pathlib.Path:
    return pathlib.Path('statements') / f'{statement.language}.pdf'


def _populate_tests(
    testset: Testset, pkg: Package, pkg_path: pathlib.Path, into_path: pathlib.Path
):
    if not testset.answerPattern:
        console.console.print(
            '[error][item]answer pattern[/item] not found for testset[/error]',
        )
        raise typer.Exit(1)

    for d, test in enumerate(testset.tests):
        folder_name = 'tests/samples' if test.sample else 'tests/tests'
        i = d + 1

        input_path = pathlib.Path(testset.inputPattern % i)
        dest_input_path = into_path / folder_name / f'{i:03d}.in'
        dest_input_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pkg_path / input_path, dest_input_path)

        answer_path = pathlib.Path(testset.answerPattern % i)
        dest_answer_path = into_path / folder_name / f'{i:03d}.ans'
        dest_answer_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pkg_path / answer_path, dest_answer_path)

    pkg.testcases = [
        TestcaseGroup(
            name='samples',
            testcaseGlob='tests/samples/*.in',
        ),
        TestcaseGroup(
            name='tests',
            testcaseGlob='tests/tests/*.in',
        ),
    ]


def _populate_titles(problem: Problem, pkg: Package):
    titles = {}
    for name in problem.names:
        iso639_code = lang.lang_to_code(name.language)
        titles[iso639_code] = name.value
    pkg.titles = titles


def _populate_statements(
    problem: Problem,
    pkg: Package,
    pkg_path: pathlib.Path,
    into_path: pathlib.Path,
    main_language: Optional[str] = None,
):
    name_per_language = {name.language: name for name in problem.names}
    pdf_statements = _get_pdf_statements(problem)
    pkg_statements = []
    found_main = False

    for statement in pdf_statements:
        statement_path = into_path / _get_statement_path(statement)
        statement_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pkg_path / statement.path, statement_path)

        iso639_code = lang.lang_to_code(statement.language)

        pkg_statement = BoxStatement(
            name=f'statement-{statement.language}',
            language=iso639_code,
            path=_get_statement_path(statement),
            type=StatementType.PDF,
        )

        if (
            main_language is not None
            and main_language == iso639_code
            and not found_main
        ):
            # If main statement, add it to the front of the list
            pkg_statements = [pkg_statement] + pkg_statements
            found_main = True
            continue

        name = name_per_language.get(statement.language)
        if name is not None and name.main and not found_main:
            # If main statement, add it to the front of the list
            pkg_statements = [pkg_statement] + pkg_statements
            found_main = True
            continue

        pkg_statements.append(pkg_statement)

    pkg.statements = pkg_statements

    if main_language is not None and not found_main:
        console.console.print(
            f'[error]Main statement of language [item]{main_language}[/item] not found.[/error]',
        )
        console.console.print(
            'If you want no statement in your imported package, '
            'leave the [item]--main-language[/item] flag unset.'
        )
        raise typer.Exit(1)

    if not pkg_statements:
        console.console.print(
            '[warning]Imported problem has no statements. Continuing without a statement.[/warning]',
        )


def _is_cpp_source(source: File) -> bool:
    if source.type is None:
        return False
    return 'cpp' in source.type


def _copy_checker(
    problem: Problem, pkg: Package, pkg_path: pathlib.Path, into_path: pathlib.Path
):
    if problem.checker is None:
        return
    if problem.checker.type != 'testlib' or not _is_cpp_source(problem.checker.source):
        console.console.print(
            f'[error][item]checker type[/item] not supported: [item]{problem.checker.type}[/item][/error]',
        )
        raise typer.Exit(1)
    shutil.copy(pkg_path / problem.checker.source.path, into_path / 'checker.cpp')

    pkg.checker = CodeItem(
        path=pathlib.Path('checker.cpp'),
    )


def _copy_interactor(
    problem: Problem, pkg: Package, pkg_path: pathlib.Path, into_path: pathlib.Path
):
    if problem.interactor is None:
        return
    shutil.copy(pkg_path / problem.interactor.source.path, into_path / 'interactor.cpp')

    if not _is_cpp_source(problem.interactor.source):
        console.console.print(
            f'[error]Only C++ interactor is supported, got [item]{problem.interactor.source.type}[/item][/error]',
        )
        raise typer.Exit(1)

    pkg.type = TaskType.COMMUNICATION
    pkg.interactor = Interactor(
        path=pathlib.Path('interactor.cpp'),
        legacy=True,
    )


def _copy_headers(
    problem: Problem, pkg: Package, pkg_path: pathlib.Path, into_path: pathlib.Path
):
    headers = []
    for file in problem.files:
        if file.type is None or not file.type.startswith('h.'):
            continue
        header_path = pkg_path / file.path
        dest_path = into_path / header_path.name
        if header_path.name == 'rbx.h':
            dest_path = into_path / 'rbx.override.h'
        shutil.copy(header_path, dest_path)
        headers.append(dest_path.name)

    if pkg.checker is not None:
        pkg.checker.compilationFiles = headers

    if pkg.interactor is not None:
        pkg.interactor.compilationFiles = headers


class PolygonImporter(BaseImporter):
    def __init__(self, main_language: Optional[str]):
        self.main_language = main_language

    @classmethod
    def name(cls) -> str:
        return 'polygon'

    async def import_package(self, pkg_path: pathlib.Path, into_path: pathlib.Path):
        problem_xml = pkg_path / 'problem.xml'
        if not problem_xml.exists():
            console.console.print(
                '[error][item]problem.xml[/item] not found[/error]',
            )
            raise typer.Exit(1)

        problem = Problem.from_xml(problem_xml.read_bytes())
        testset = _get_main_testset(problem)

        if testset.timelimit is None:
            testset.timelimit = 1000

        if testset.memorylimit is None:
            testset.memorylimit = 256 * 1024 * 1024

        pkg = Package(
            name=problem.short_name,
            timeLimit=testset.timelimit,
            memoryLimit=testset.memorylimit // (1024 * 1024),
            outputLimit=64 * 1024,
        )

        _populate_tests(testset, pkg, pkg_path, into_path)
        _populate_titles(problem, pkg)
        _populate_statements(problem, pkg, pkg_path, into_path, self.main_language)
        _copy_checker(problem, pkg, pkg_path, into_path)
        _copy_interactor(problem, pkg, pkg_path, into_path)
        _copy_headers(problem, pkg, pkg_path, into_path)

        (into_path / 'problem.rbx.yml').write_text(utils.model_to_yaml(pkg))
