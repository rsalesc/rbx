import pathlib
import shutil
from typing import List

import typer

from rbx import console
from rbx.box import header, package
from rbx.box.environment import get_extension_or_default
from rbx.box.packaging.boca.extension import BocaExtension, BocaLanguage
from rbx.box.packaging.boca.packager import BocaPackager
from rbx.box.packaging.packager import BuiltStatement
from rbx.box.schema import ExpectedOutcome, TaskType
from rbx.config import get_default_app_path, get_testlib
from rbx.grading.judge.digester import digest_cooperatively


class MojPackager(BocaPackager):
    def __init__(self, for_boca: bool = False):
        super().__init__()
        self.for_boca = for_boca

    @classmethod
    def task_types(cls) -> List[TaskType]:
        return [TaskType.COMMUNICATION, TaskType.BATCH]

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
        # ol = pkg.outputLimit
        limits = [
            f'ULIMITS[-v]={ml * 1024}',
            # f'ULIMITS[-f]={ol}',
        ]
        return '\n'.join(limits) + '\n'

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

    def _get_interactor(self) -> str:
        return package.get_interactor().path.read_text()

    def _expand_language_vars(self, language: BocaLanguage, dir: pathlib.Path):
        extension = get_extension_or_default('boca', BocaExtension)

        for path in dir.glob('**/*'):
            if not path.is_file():
                continue

            replaced = path.read_text()
            replaced = replaced.replace(
                '{{rbxMaxMemory}}', f'{self._get_pkg_memorylimit(language)}'
            ).replace(
                '{{rbxInitialMemory}}',
                f'{min(512, int(self._get_pkg_memorylimit(language) * 0.9))}',
            )

            flags = extension.flags_with_defaults()
            if language in flags:
                replaced = replaced.replace('{{rbxFlags}}', flags[language])

            path.write_text(replaced)

            if path.suffix == '.sh':
                path.chmod(0o755)

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

    @classmethod
    def name(cls) -> str:
        return 'moj'

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        pkg = package.find_problem_package_or_die()

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

        # Prepare rbx.h
        rbx_header_path = into_path / 'scripts' / 'rbx.h'
        rbx_header_path.parent.mkdir(parents=True, exist_ok=True)
        rbx_header_path.write_text(header.get_header().read_text())

        # Prepare checker
        checker_path = into_path / 'scripts' / 'checker.cpp'
        checker_path.parent.mkdir(parents=True, exist_ok=True)
        checker_path.write_text(self._get_checker())

        # Prepare interactor
        if pkg.type == TaskType.COMMUNICATION:
            interactor_path = into_path / 'scripts' / 'interactor.cpp'
            interactor_path.parent.mkdir(parents=True, exist_ok=True)
            interactor_path.write_text(self._get_interactor())

            interactor_prep_path = into_path / 'scripts' / 'interactor_prep.sh'
            interactor_prep_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(
                get_default_app_path()
                / 'packagers'
                / 'moj'
                / 'scripts'
                / 'interactor_prep.sh',
                interactor_prep_path,
            )
            interactor_prep_path.chmod(0o755)

            interactor_run_path = into_path / 'scripts' / 'interactor_run.sh'
            interactor_run_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(
                get_default_app_path()
                / 'packagers'
                / 'moj'
                / 'scripts'
                / 'interactor_run.sh',
                interactor_run_path,
            )
            interactor_run_path.chmod(0o755)

        # Prepare language scripts
        extension = get_extension_or_default('boca', BocaExtension)
        for language in extension.languages:
            language_path = into_path / 'scripts' / language
            language_path.parent.mkdir(parents=True, exist_ok=True)
            src_path = (
                get_default_app_path() / 'packagers' / 'moj' / 'scripts' / language
            )
            if src_path.exists():
                shutil.copytree(src_path, language_path)
                self._expand_language_vars(language, language_path)

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
            shutil.copyfile(testcase.inputPath, inputs_path / f'{i + 1:03d}')
            if testcase.outputPath is not None:
                shutil.copyfile(testcase.outputPath, outputs_path / f'{i + 1:03d}')
            else:
                (outputs_path / f'{i + 1:03d}').touch()

        # Zip all.
        shutil.make_archive(str(build_path / self.package_basename()), 'zip', into_path)

        return (build_path / self.package_basename()).with_suffix('.zip')
