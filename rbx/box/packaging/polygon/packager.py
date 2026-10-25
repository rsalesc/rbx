import collections
import json
import pathlib
import shutil
from typing import Dict, List, Optional, Tuple

import typer

from rbx import console, utils
from rbx.box import graders, header, limits_info, naming, package
from rbx.box.contest import contest_package
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.lang import code_to_lang, code_to_langs, is_valid_lang_code
from rbx.box.packaging import flattening
from rbx.box.packaging.cms import polygon_loader as cms_polygon_loader
from rbx.box.packaging.cms import settings as cms_settings
from rbx.box.packaging.cms import support as cms_support
from rbx.box.packaging.packager import (
    BaseContestPackager,
    BasePackager,
    BuiltContestStatement,
    BuiltProblemPackage,
    BuiltStatement,
)
from rbx.box.packaging.polygon import xml_schema as polygon_schema
from rbx.box.packaging.polygon.utils import get_polygon_language_from_code_item
from rbx.box.schema import ExpectedOutcome, ScoreType, Solution, TaskType
from rbx.box.scoring import partial
from rbx.box.scoring.dependencies import Aggregation
from rbx.box.statements.schema import (
    ConversionStep,
    ConversionType,
    TexToPDF,
    rbxToTeX,
)
from rbx.config import get_testlib

# Where the grader lands under `files/`; CMS reads it under this name too.
GRADER_SOURCE = 'grader.cpp'

DAT_TEMPLATE = """
@contest "{name}"
@contlen 300
@problems {problems}
@teams 0
@submissions 0
"""


_SOLUTION_TAGS = {
    ExpectedOutcome.ACCEPTED: 'accepted',
    ExpectedOutcome.ACCEPTED_OR_TLE: 'time-limit-exceeded-or-accepted',
    ExpectedOutcome.WRONG_ANSWER: 'wrong-answer',
    ExpectedOutcome.TIME_LIMIT_EXCEEDED: 'time-limit-exceeded',
    ExpectedOutcome.TLE_OR_MLE: 'time-limit-exceeded-or-memory-limit-exceeded',
    ExpectedOutcome.MEMORY_LIMIT_EXCEEDED: 'memory-limit-exceeded',
}


def _get_solution_tag(solution: Solution, is_main: bool) -> Optional[str]:
    """The `problem.xml` tag for a solution, or `None` when it has none.

    Polygon has no tag for a runtime error, so it (like every other failure
    without an exact tag) becomes `rejected`. `ANY` has no tag at all: any
    failing tag would flag a passing run, and vice versa.
    """
    if is_main and solution.outcome == ExpectedOutcome.ACCEPTED:
        return 'main'
    # Polygon judges a partial result OK and has no tag for one, so any tag
    # would misjudge the solution.
    if solution.outcome in (ExpectedOutcome.ANY, ExpectedOutcome.PARTIALLY_CORRECT):
        return None
    return _SOLUTION_TAGS.get(solution.outcome, 'rejected')


def _warn_about_pc(checker_path: pathlib.Path) -> None:
    """Warn when a checker awards partial credit with `_pc`, which Polygon fails on.

    Checked on the source: testlib itself declares `_pc`, but a checker that never
    names it never uses it.
    """
    source = checker_path.read_text(encoding='utf-8', errors='replace')
    if '_pc(' not in source:
        return
    console.console.print(
        '[warning]The checker uses [item]_pc(...)[/item], which Polygon reports as '
        'a checker failure.[/warning]\n'
        '[warning]Award partial points with [item]quitp(percentage)[/item] '
        'instead: Polygon (in percent mode), CMS and rbx all read it.[/warning]'
    )


def _select_main_language(
    names: List[polygon_schema.Name], main_language: Optional[str]
):
    if names:
        if main_language is not None:
            lang_name = code_to_lang(main_language)
            found = False
            for name in names:
                if name.language == lang_name:
                    name.main = True
                    found = True
                    break
            if not found:
                console.console.print(
                    f'[error]Main language [item]{main_language}[/item] not found.[/error]'
                )
                raise typer.Exit(1)
        else:
            names[0].main = True


class PolygonPackager(BasePackager):
    def __init__(
        self,
        testcase_entries: List[GenerationTestcaseEntry],
        main_language: Optional[str] = None,
        cms: bool = False,
    ):
        super().__init__(testcase_entries)
        self.main_language = main_language
        # Also ship what only CMS's Polygon importer reads (`--cms`).
        self.cms = cms

    @classmethod
    def task_types(cls) -> List[TaskType]:
        return [TaskType.BATCH, TaskType.COMMUNICATION]

    def statement_export_params(self) -> List[ConversionStep]:
        # Polygon consumes structured blocks, so TikZ is externalized (uploaded
        # as PDF resources) and macros are extracted (to expand non-Polygon
        # commands out of the blocks). Forced at export — not user schema.
        return [
            rbxToTeX(type=ConversionType.rbxToTex, externalize=True),
            TexToPDF(type=ConversionType.TexToPDF, externalize=True, demacro=True),
        ]

    def _validate(self):
        langs = self.languages()
        pkg = package.find_problem_package_or_die()

        lang_codes = set()
        for statement in pkg.expanded_statements:
            lang_codes.add(statement.language)

        for lang in langs:
            if lang not in lang_codes:
                console.console.print(
                    f'[error]No statement from language [item]{lang}[/item] found. '
                    'Polygon needs one statement for each language.[/error]'
                )
                raise typer.Exit(1)

    def _get_name(self, lang: str) -> polygon_schema.Name:
        statement = self.get_statement_for_language_or_null(lang)
        return polygon_schema.Name(
            language=code_to_langs([lang])[0],
            value=naming.get_problem_title(lang, statement),
        )

    def _get_names(self) -> List[polygon_schema.Name]:
        names = [self._get_name(lang) for lang in self.languages()]

        _select_main_language(names, self.main_language)

        return names

    def _get_checker(self) -> polygon_schema.Checker:
        # TODO: support other checker languages
        return polygon_schema.Checker(
            name='rbx::checker',
            type='testlib',
            source=polygon_schema.File(
                path='files/check.cpp',
                type=get_polygon_language_from_code_item(
                    package.get_checker_or_builtin()
                ),
            ),
            cpy=polygon_schema.File(path='check.cpp'),
        )

    def _get_interactor(self) -> Optional[polygon_schema.Interactor]:
        pkg = package.find_problem_package_or_die()
        if pkg.interactor is None:
            return None
        return polygon_schema.Interactor(
            source=polygon_schema.File(
                path='files/interactor.cpp',
                type=get_polygon_language_from_code_item(pkg.interactor),
            ),
        )

    def _get_manual_test(self, is_sample: bool) -> polygon_schema.Test:
        return polygon_schema.Test(method='manual', sample=is_sample or None)

    def _get_tests_and_groups(
        self, entries: List[GenerationTestcaseEntry]
    ) -> Tuple[List[polygon_schema.Test], List[polygon_schema.Group]]:
        tests = [self._get_manual_test(entry.is_sample()) for entry in entries]
        pkg = package.find_problem_package_or_die()
        if pkg.score_type != ScoreType.POINTS:
            return tests, []

        # A `min` group pays its points times its lowest test, which is Polygon's
        # `complete-group` policy (measured with the percent mode on). Its score
        # goes on its last test, so a judge that sums test points instead of
        # reading the group's agrees with one that does. A `sum` group is
        # `each-test`: each test carries its own share and pays it.
        tests_of: Dict[str, List[int]] = collections.defaultdict(list)
        for i, entry in enumerate(entries):
            tests_of[entry.group_entry.group].append(i)
        for group_name, indices in tests_of.items():
            score = next(g.score for g in pkg.testcases if g.name == group_name)
            if pkg.aggregation_for(group_name) == Aggregation.SUM:
                points = partial.test_points(score, len(indices))
            else:
                points = [0.0] * (len(indices) - 1) + [float(score)]
            for i, test_points in zip(indices, points):
                tests[i].group = group_name
                tests[i].points = test_points
        last_test_of = {name: indices[-1] for name, indices in tests_of.items()}

        # A group with no built tests has nothing to judge; leave it out.
        group_deps = pkg.group_dependencies.over(list(last_test_of))
        groups = []
        for group in pkg.testcases:
            if group.name not in last_test_of:
                continue
            each_test = pkg.aggregation_for(group.name) == Aggregation.SUM
            feedback_policy = 'points' if each_test else 'icpc'
            groups.append(
                polygon_schema.Group(
                    name=group.name,
                    points=float(group.score),
                    points_policy='each-test' if each_test else 'complete-group',
                    feedback_policy='complete'
                    if group.name == 'samples'
                    else feedback_policy,
                    dependencies=[
                        polygon_schema.Dependency(group=dep)
                        for dep in group_deps.direct(group.name)
                    ],
                )
            )
        return tests, groups

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

        entries = self.get_built_testcase_entries()

        limits = limits_info.get_limits(None, profile='polygon')
        assert limits.time is not None
        assert limits.memory is not None

        tests, groups = self._get_tests_and_groups(entries)

        return polygon_schema.Testset(
            name='tests',
            timelimit=limits.time,
            memorylimit=limits.memory * 1024 * 1024,
            size=len(entries),
            # Polygon's own default; CMS's importer hardcodes it, whatever the
            # pattern says.
            inputPattern='tests/%02d',
            answerPattern='tests/%02d.a',
            tests=tests,
            groups=groups,
        )

    def _get_judging(self) -> polygon_schema.Judging:
        pkg = package.find_problem_package_or_die()
        return polygon_schema.Judging(
            testsets=[self._get_single_testset()],
            treatPointsAsPercent='true' if pkg.score_type == ScoreType.POINTS else None,
        )

    def _flatten_sources(self) -> flattening.FlatNamespace:
        pkg = package.find_problem_package_or_die()
        checker = package.get_checker_or_builtin()
        sources = [checker]
        reserved = {package.get_relative_source_path(checker): 'check.cpp'}
        if pkg.interactor is not None:
            sources.append(pkg.interactor)
            reserved[package.get_relative_source_path(pkg.interactor)] = (
                'interactor.cpp'
            )
        if pkg.grader is not None:
            sources.append(pkg.grader)
            reserved[package.get_relative_source_path(pkg.grader)] = GRADER_SOURCE
        sources.extend(package.get_solutions())
        # Polygon compiles each source to a program named after its stem.
        return flattening.build_flat_namespace(
            sources, reserved=reserved, enforce_stem_unique=True
        )

    def _get_solutions(
        self, ns: flattening.FlatNamespace
    ) -> List[polygon_schema.Solution]:
        res = []
        for i, solution in enumerate(package.get_solutions()):
            tag = _get_solution_tag(solution, is_main=i == 0)
            if tag is None:
                console.console.print(
                    f'[warning]Solution {solution.href()} expects outcome '
                    f'[item]{solution.outcome.name}[/item], which Polygon cannot '
                    'express; it will not be packaged.[/warning]'
                )
                continue
            res.append(
                polygon_schema.Solution(
                    tag=tag,  # type: ignore
                    source=polygon_schema.File(
                        path=f'solutions/{ns.flat_name_for(solution)}',
                        type=get_polygon_language_from_code_item(solution),
                    ),
                )
            )
        return res

    def _get_files(self, ns: flattening.FlatNamespace) -> List[polygon_schema.File]:
        files = [
            polygon_schema.File(path='files/testlib.h', type='h.g++'),
            polygon_schema.File(path='files/rbx.h', type='h.g++'),
        ]
        for dep in ns.dep_files():
            # A package shipping its own testlib.h/rbx.h overwrites the bundled
            # copy on materialize; declare the path once.
            if any(f.path == f'files/{dep.flat_name}' for f in files):
                continue
            ftype = (
                'h.g++'
                if dep.flat_name.endswith(('.h', '.hpp', '.hh', '.hxx'))
                else 'cpp.g++'
            )
            files.append(polygon_schema.File(path=f'files/{dep.flat_name}', type=ftype))
        grader = package.find_problem_package_or_die().grader
        if grader is not None:
            files.append(
                polygon_schema.File(
                    path=f'files/{GRADER_SOURCE}',
                    type=get_polygon_language_from_code_item(grader),
                    for_types='cpp.*',
                    stages=[polygon_schema.NamedRef(name='compile')],
                    assets=[polygon_schema.NamedRef(name='solution')],
                )
            )
        return files

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
            path=str(utils.abspath(final_path).relative_to(utils.abspath(into_path))),
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

    @classmethod
    def supports_graders(cls) -> bool:
        return True

    def _grader_files(self, ns: flattening.FlatNamespace) -> List[str]:
        """The grader and every file of its closure, by name under `files/`."""
        pkg = package.find_problem_package_or_die()
        if pkg.grader is None:
            return []
        from rbx.box.dependencies import graph as deps_graph

        closure = {package.get_relative_source_path(pkg.grader)}
        dep_graph = deps_graph.expand(pkg.grader)
        if dep_graph is not None:
            closure.update(pathlib.Path(dep) for dep in dep_graph.files())
        names = [f.flat_name for f in ns.files if f.source_path in closure]
        return sorted(set(names) | {'rbx.h'})

    async def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ):
        pkg = package.find_problem_package_or_die()

        ns = self._flatten_sources()
        _warn_about_pc(package.get_checker_or_builtin().path)

        problem = polygon_schema.Problem(
            short_name=pkg.name,
            names=self._get_names(),
            checker=self._get_checker(),
            judging=self._get_judging(),
            files=self._get_files(ns),
            interactor=self._get_interactor(),
            solutions=self._get_solutions(ns),
            # No problem statements: the Codeforces Gym (the consumer of these
            # zips, through its taskbook) accepts a PDF one but cannot serve it,
            # so the problem page fails with "Can't send statement". Without one
            # it falls back to the contest statement. Checked live, 2026-10.
            # Polygon's own `statements/.pdf/` path fares no better: the
            # taskbook drops dot-directories when it unpacks a contest.zip.
            # That is what `cms_polygon_loader.write_statements` relies on.
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
        # Solutions go to solutions/; check.cpp, interactor.cpp and every dep,
        # rewritten, go to files/.
        solutions_path = into_path / 'solutions'
        solution_names = {
            ns.flat_name_for(solution) for solution in package.get_solutions()
        }
        for flat_file in ns.files:
            if flat_file.is_root and flat_file.flat_name in solution_names:
                dest = solutions_path / flat_file.flat_name
            else:
                dest = files_path / flat_file.flat_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(flat_file.content)
        if pkg.grader is not None:
            # The sidecar Polygon itself writes next to a grader resource.
            (files_path / f'{GRADER_SOURCE}.json').write_text(
                json.dumps(
                    {
                        'forTypes': 'cpp.*',
                        'main': False,
                        'stages': ['COMPILE'],
                        'assets': ['SOLUTION'],
                    },
                    separators=(',', ':'),
                )
            )
        if self.attachments_path is not None and not self.cms:
            console.console.print(
                '[warning]Polygon packages cannot carry attachments: add '
                f'[item]{self.attachments_path.name}[/item] to the problem as a '
                'material by hand, in the Polygon UI.[/warning]'
            )
        # Root copy for the Polygon UI ('cpy').
        (into_path / 'check.cpp').write_bytes(
            ns.content_for(package.get_checker_or_builtin())
        )

        # Copy all testcases
        (into_path / 'tests').mkdir(parents=True, exist_ok=True)
        testcases = self.get_flattened_built_testcases()
        for i, testcase in enumerate(testcases):
            shutil.copyfile(
                graders.run_input(testcase.inputPath),
                into_path / f'tests/{i + 1:02d}',
            )
            if testcase.outputPath is not None:
                shutil.copyfile(
                    testcase.outputPath,
                    into_path / f'tests/{i + 1:02d}.a',
                )
            else:
                (into_path / f'tests/{i + 1:02d}.a').touch()

        if self.cms:
            cms_support.ensure_supported(pkg)
            cms_polygon_loader.write_statements(built_statements, into_path)
            cms_polygon_loader.write_files(
                pkg,
                self.get_built_testcase_entries(),
                files_path,
                cms_settings.resolve(),
                grader_files=self._grader_files(ns),
                attachments_path=self.attachments_path,
            )

        # Write problem.xml
        (into_path / 'problem.xml').write_text(descriptor)

        # Zip all.
        shutil.make_archive(str(build_path / 'problem'), 'zip', into_path)

        return build_path / 'problem.zip'


class PolygonContestPackager(BaseContestPackager):
    def __init__(self, main_language: Optional[str] = None, cms: bool = False):
        self.main_language = main_language
        self.cms = cms

    @classmethod
    def name(cls) -> str:
        return 'polygon'

    def check_contest(self) -> None:
        # `contest.dat` carries the contest title, which is read from a
        # statement.
        if self.languages():
            return
        contest = contest_package.find_contest_package_or_die()
        console.console.print(
            f'[error]Contest [item]{contest.name}[/item] cannot be packaged for '
            'Polygon: it declares no statements, and the package takes the '
            'contest title from one. Add a [item]statements[/item] entry to '
            '[item]contest.rbx.yml[/item].[/error]'
        )
        raise typer.Exit(1)

    def _get_names(self) -> List[polygon_schema.Name]:
        names = [
            polygon_schema.Name(
                language=code_to_langs([lang])[0],
                value=naming.get_contest_title(
                    lang, self.get_statement_for_language(lang)
                ),
            )
            for lang in self.languages()
            if is_valid_lang_code(lang)
        ]
        _select_main_language(names, self.main_language)
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
            path=str(utils.abspath(final_path).relative_to(utils.abspath(into_path))),
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
                # CMS's importer takes the problem directory from the basename
                # of `url` (in Polygon, a link to the problem) and ignores
                # `path`. Only with `--cms`: the Codeforces taskbook rejects a
                # `url` that is not an absolute URL.
                url=str(pathlib.Path('problems') / built_package.problem.short_name)
                if self.cms
                else None,
            )
            for built_package in built_packages
        ]

    def _get_dat(self, built_packages: List[BuiltProblemPackage]) -> str:
        dat = DAT_TEMPLATE.format(
            name=naming.get_contest_title(
                self.languages()[0],
                self.get_statement_for_language(self.languages()[0]),
            ),
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

        return build_path / 'contest.zip'
