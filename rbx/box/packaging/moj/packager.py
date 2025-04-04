import pathlib
import shutil
from typing import List

import typer

from rbx import console
from rbx.box import package
from rbx.box.environment import get_extension_or_default
from rbx.box.packaging.boca.extension import BocaExtension
from rbx.box.packaging.boca.packager import BocaPackager
from rbx.box.packaging.packager import BuiltStatement
from rbx.box.schema import ExpectedOutcome
from rbx.config import get_default_app_path, get_testlib
from rbx.grading.judge.digester import digest_cooperatively


class MojPackager(BocaPackager):
    def __init__(self, for_boca: bool = False):
        super().__init__()
        self.for_boca = for_boca

    def _get_problem_info(self) -> str:
        statement = self._get_main_statement()
        return (
            f'basename={self._get_problem_name()}\n'
            f'fullname={statement.title}\n'
            f'descfile={self._get_problem_name()}.pdf\n'
        )

    def _get_tl(self) -> str:
        extension = get_extension_or_default('boca', BocaExtension)

        pkg = package.find_problem_package_or_die()
        res = f'TL[default]={pkg.timeLimit / 1000}\n'
        for language in extension.languages:
            res += f'TL[{language}]={self._get_pkg_timelimit(language) / 1000}\n'
        return res

    def _get_limits(self) -> str:
        pkg = package.find_problem_package_or_die()
        ml = pkg.memoryLimit
        ol = pkg.outputLimit
        return f'ULIMITS[-f]={ol}\n' f'ULIMITS[-v]={ml * 1024}\n'

    def _get_compare(self) -> str:
        extension = get_extension_or_default('boca', BocaExtension)

        compare_path = (
            get_default_app_path() / 'packagers' / 'moj' / 'scripts' / 'compare.sh'
        )
        if not compare_path.exists():
            console.console.print(
                '[error]MOJ template compare script not found.[/error]'
            )
            raise typer.Exit(1)
        with package.get_checker().path.open('rb') as f:
            checker_hash = digest_cooperatively(f)
        return (
            compare_path.read_text()
            .replace('{{rbxFlags}}', extension.flags_with_defaults()['cc'])
            .replace('{{checkerHash}}', checker_hash)
        )

    def _get_checker(self) -> str:
        return package.get_checker().path.read_text()

    def _copy_solutions_moj(self, into_path: pathlib.Path):
        into_path = into_path / 'sols'
        has_good = False
        for solution in package.get_solutions():
            tag = 'wrong'
            if solution.outcome == ExpectedOutcome.ACCEPTED:
                tag = 'good'
                has_good = True
            elif solution.outcome.is_slow():
                tag = 'slow'
            dest_path = into_path / tag / solution.path.name
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(solution.path), dest_path)

        if not has_good:
            console.console.print('[error]No good solution found.[/error]')
            raise typer.Exit(1)

    def name(self) -> str:
        return 'moj'

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        # Prepare dummy files
        author_path = into_path / 'author'
        author_path.parent.mkdir(parents=True, exist_ok=True)
        author_path.write_text('Unknown\n')

        tags_path = into_path / 'tags'
        tags_path.parent.mkdir(parents=True, exist_ok=True)
        tags_path.write_text('')

        # Prepare limits
        limits_path = into_path / 'conf'
        limits_path.parent.mkdir(parents=True, exist_ok=True)
        limits_path.write_text(self._get_limits())

        # Prepare TL
        if self.for_boca:
            tl_path = into_path / 'tl'
            tl_path.parent.mkdir(parents=True, exist_ok=True)
            tl_path.write_text(self._get_tl())

        # Prepare compare
        compare_path = into_path / 'scripts' / 'compare.sh'
        compare_path.parent.mkdir(parents=True, exist_ok=True)
        compare_path.write_text(self._get_compare())
        compare_path.chmod(0o755)

        # Prepare testlib
        testlib_path = into_path / 'scripts' / 'testlib.h'
        testlib_path.parent.mkdir(parents=True, exist_ok=True)
        testlib_path.write_text(get_testlib().read_text())

        # Prepare checker
        checker_path = into_path / 'scripts' / 'checker.cpp'
        checker_path.parent.mkdir(parents=True, exist_ok=True)
        checker_path.write_text(self._get_checker())

        # Problem statement
        enunciado_path = into_path / 'docs' / 'enunciado.pdf'
        enunciado_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            self._get_main_built_statement(built_statements).path,
            enunciado_path,
        )

        # Copy solutions
        if self.for_boca:
            self._copy_solutions(into_path, fix_java=False)
        else:
            self._copy_solutions_moj(into_path)

        # Prepare IO
        inputs_path = into_path / 'tests' / 'input'
        inputs_path.mkdir(parents=True, exist_ok=True)
        outputs_path = into_path / 'tests' / 'output'
        outputs_path.mkdir(parents=True, exist_ok=True)

        testcases = self.get_flattened_built_testcases()
        for i, testcase in enumerate(testcases):
            shutil.copyfile(testcase.inputPath, inputs_path / f'{i+1:03d}')
            if testcase.outputPath is not None:
                shutil.copyfile(testcase.outputPath, outputs_path / f'{i+1:03d}')
            else:
                (outputs_path / f'{i+1:03d}').touch()

        # Zip all.
        shutil.make_archive(
            str(build_path / self._get_problem_name()), 'zip', into_path
        )

        return (build_path / self._get_problem_name()).with_suffix('.zip')
