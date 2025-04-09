import atexit
import functools
import os
import pathlib
import shutil
import sys
from typing import Dict, List, Optional, Tuple

import ruyaml
import typer
from pydantic import ValidationError

from rbx import config, console, utils
from rbx.box import cd, environment
from rbx.box.environment import get_sandbox_type
from rbx.box.presets import get_installed_preset_or_null, get_preset_lock
from rbx.box.schema import (
    CodeItem,
    ExpectedOutcome,
    Generator,
    Package,
    Solution,
    Stress,
    TestcaseGroup,
    TestcaseSubgroup,
)
from rbx.config import get_builtin_checker
from rbx.grading.caching import DependencyCache
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.judge.storage import FilesystemStorage, Storage

YAML_NAME = 'problem.rbx.yml'
_DEFAULT_CHECKER = 'wcmp.cpp'
TEMP_DIR = None


def warn_preset_deactivated(root: pathlib.Path = pathlib.Path()):
    preset_lock = get_preset_lock(root)
    if preset_lock is None:
        return

    preset = get_installed_preset_or_null(preset_lock.preset_name)
    if preset is None:
        console.console.print(
            f'[warning]WARNING: [item]{preset_lock.preset_name}[/item] is not installed. '
            'Run [item]rbx presets sync && rbx activate[/item] to install and activate this preset.'
        )
        console.console.print()
        return

    if preset.env is not None and (
        not environment.get_environment_path(preset.name).is_file()
        or config.get_config().boxEnvironment != preset.name
    ):
        console.console.print(
            '[warning]WARNING: This package uses a preset that configures a custom environment, '
            f' but instead you are using the environment [item]{config.get_config().boxEnvironment}[/item]. '
            'Run [item]rbx activate[/item] to use the environment configured by your preset.'
        )
        console.console.print()
        return


@functools.cache
def find_problem_yaml(root: pathlib.Path = pathlib.Path()) -> Optional[pathlib.Path]:
    root = root.resolve()
    problem_yaml_path = root / YAML_NAME
    while root != pathlib.PosixPath('/') and not problem_yaml_path.is_file():
        root = root.parent
        problem_yaml_path = root / YAML_NAME
    if not problem_yaml_path.is_file():
        return None
    warn_preset_deactivated(root)
    return problem_yaml_path


@functools.cache
def find_problem_package(root: pathlib.Path = pathlib.Path()) -> Optional[Package]:
    problem_yaml_path = find_problem_yaml(root)
    if not problem_yaml_path:
        return None
    try:
        return utils.model_from_yaml(Package, problem_yaml_path.read_text())
    except ValidationError as e:
        console.console.print(e)
        console.console.print('[error]Error parsing problem.rbx.yml.[/error]')
        raise typer.Exit(1) from e


def find_problem_package_or_die(root: pathlib.Path = pathlib.Path()) -> Package:
    package = find_problem_package(root)
    if package is None:
        console.console.print(f'[error]Problem not found in {root.absolute()}[/error]')
        raise typer.Exit(1)
    return package


def find_problem(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    found = find_problem_yaml(root)
    if found is None:
        console.console.print(f'[error]Problem not found in {root.absolute()}[/error]')
        raise typer.Exit(1)
    return found.parent


def within_problem(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with cd.new_package_cd(find_problem()):
            return func(*args, **kwargs)

    return wrapper


def save_package(
    package: Optional[Package] = None, root: pathlib.Path = pathlib.Path()
) -> None:
    package = package or find_problem_package_or_die(root)
    problem_yaml_path = find_problem_yaml(root)
    if not problem_yaml_path:
        console.console.print(f'[error]Problem not found in {root.absolute()}[/error]')
        raise typer.Exit(1)
    problem_yaml_path.write_text(utils.model_to_yaml(package))


def get_ruyaml(root: pathlib.Path = pathlib.Path()) -> Tuple[ruyaml.YAML, ruyaml.Any]:
    problem_yaml_path = find_problem_yaml(root)
    if problem_yaml_path is None:
        console.console.print(
            f'Problem not found in {pathlib.Path().absolute()}', style='error'
        )
        raise typer.Exit(1)
    res = ruyaml.YAML()
    return res, res.load(problem_yaml_path.read_text())


@functools.cache
def get_problem_cache_dir(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    cache_dir = find_problem(root) / '.box'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@functools.cache
def get_problem_storage_dir(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    storage_dir = get_problem_cache_dir(root) / '.storage'
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def get_problem_runs_dir(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    runs_dir = get_problem_cache_dir(root) / 'runs'
    runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir


def get_problem_iruns_dir(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    iruns_dir = get_problem_runs_dir(root) / '.irun'
    iruns_dir.mkdir(parents=True, exist_ok=True)
    return iruns_dir


def get_problem_preprocessed_path(
    item: pathlib.Path, root: pathlib.Path = pathlib.Path()
) -> pathlib.Path:
    root_resolved = root.resolve()
    item_resolved = item.resolve()

    if not item_resolved.is_relative_to(root_resolved):
        final_path = pathlib.Path('remote') / item_resolved.name
    else:
        final_path = item_resolved.relative_to(root_resolved)
    path = get_problem_cache_dir(root) / '.preprocessed' / final_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@functools.cache
def get_cache_storage(root: pathlib.Path = pathlib.Path()) -> Storage:
    return FilesystemStorage(get_problem_storage_dir(root))


@functools.cache
def get_dependency_cache(root: pathlib.Path = pathlib.Path()) -> DependencyCache:
    return DependencyCache(get_problem_cache_dir(root), get_cache_storage(root))


@functools.cache
def get_file_cacher(root: pathlib.Path = pathlib.Path()) -> FileCacher:
    return FileCacher(get_cache_storage(root))


@functools.cache
def get_digest_as_string(
    digest: str, root: pathlib.Path = pathlib.Path()
) -> Optional[str]:
    cacher = get_file_cacher(root)
    try:
        content = cacher.get_file_content(digest)
        return content.decode()
    except KeyError:
        return None


def get_new_sandbox(root: pathlib.Path = pathlib.Path()) -> SandboxBase:
    sandbox = get_sandbox_type()(file_cacher=get_file_cacher(root), temp_dir=TEMP_DIR)
    atexit.register(lambda: sandbox.cleanup(delete=True))
    return sandbox


@functools.cache
def get_singleton_sandbox(root: pathlib.Path = pathlib.Path()) -> SandboxBase:
    return get_new_sandbox(root)


@functools.cache
def get_singleton_interactor_sandbox(
    root: pathlib.Path = pathlib.Path(),
) -> SandboxBase:
    return get_new_sandbox(root)


@functools.cache
def get_build_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    return find_problem(root) / 'build'


@functools.cache
def get_build_tests_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    return get_build_path(root) / 'tests'


@functools.cache
def get_build_testgroup_path(
    group: str, root: pathlib.Path = pathlib.Path()
) -> pathlib.Path:
    res = get_build_tests_path(root) / group
    res.mkdir(exist_ok=True, parents=True)
    return res


@functools.cache
def get_generator(name: str, root: pathlib.Path = pathlib.Path()) -> Generator:
    package = find_problem_package_or_die(root)
    for generator in package.generators:
        if generator.name == name:
            return generator
    console.console.print(f'[error]Generator [item]{name}[/item] not found[/error]')
    raise typer.Exit(1)


@functools.cache
def get_validator(root: pathlib.Path = pathlib.Path()) -> CodeItem:
    package = find_problem_package_or_die(root)
    if package.validator is None:
        console.console.print(
            '[error]Problem does not have a validator configured.[/error]'
        )
        raise typer.Exit(1)
    return package.validator


@functools.cache
def get_validator_or_nil(root: pathlib.Path = pathlib.Path()) -> Optional[CodeItem]:
    package = find_problem_package_or_die(root)
    if package.validator is None:
        return None
    return package.validator


@functools.cache
def get_checker(root: pathlib.Path = pathlib.Path()) -> CodeItem:
    package = find_problem_package_or_die(root)

    return package.checker or CodeItem(
        path=get_builtin_checker(_DEFAULT_CHECKER).absolute()
    )


@functools.cache
def get_interactor_or_nil(root: pathlib.Path = pathlib.Path()) -> Optional[CodeItem]:
    package = find_problem_package_or_die(root)
    return package.interactor


@functools.cache
def get_interactor(root: pathlib.Path = pathlib.Path()) -> CodeItem:
    interactor = get_interactor_or_nil(root)
    if interactor is None:
        console.console.print(
            '[error]Problem does not have an interactor configured.[/error]'
        )
        raise typer.Exit(1)
    return interactor


@functools.cache
def get_solutions(root: pathlib.Path = pathlib.Path()) -> List[Solution]:
    package = find_problem_package_or_die(root)
    return package.solutions


@functools.cache
def get_main_solution(root: pathlib.Path = pathlib.Path()) -> Optional[Solution]:
    for solution in get_solutions(root):
        if solution.outcome == ExpectedOutcome.ACCEPTED:
            return solution
    return None


@functools.cache
def get_solution(name: str, root: pathlib.Path = pathlib.Path()) -> Solution:
    for solution in get_solutions(root):
        if str(solution.path) == name:
            return solution
    console.console.print(f'[error]Solution [item]{name}[/item] not found[/error]')
    raise typer.Exit(1)


@functools.cache
def get_solution_or_nil(
    name: str, root: pathlib.Path = pathlib.Path()
) -> Optional[Solution]:
    for solution in get_solutions(root):
        if str(solution.path) == name:
            return solution
    return None


@functools.cache
def get_stress(name: str, root: pathlib.Path = pathlib.Path()) -> Stress:
    pkg = find_problem_package_or_die(root)
    for stress in pkg.stresses:
        if stress.name == name:
            return stress
    console.console.print(f'[error]Stress [item]{name}[/item] not found[/error]')
    raise typer.Exit(1)


@functools.cache
def get_testgroup(name: str, root: pathlib.Path = pathlib.Path()) -> TestcaseGroup:
    pkg = find_problem_package_or_die(root)
    for testgroup in pkg.testcases:
        if testgroup.name == name:
            return testgroup
    console.console.print(f'[error]Test group [item]{name}[/item] not found[/error]')
    raise typer.Exit(1)


@functools.cache
def get_test_groups_by_name(
    root: pathlib.Path = pathlib.Path(),
) -> Dict[str, TestcaseSubgroup]:
    pkg = find_problem_package_or_die(root)
    res = {}

    for testgroup in pkg.testcases:
        res[testgroup.name] = testgroup
        for subgroup in testgroup.subgroups:
            res[f'{testgroup.name}.{subgroup.name}'] = subgroup

    return res


# Return each compilation file and to where it should be moved inside
# the sandbox.
def get_compilation_files(code: CodeItem) -> List[Tuple[pathlib.Path, pathlib.Path]]:
    code_dir = code.path.parent.resolve()

    res = []
    for compilation_file in code.compilationFiles or []:
        compilation_file_path = pathlib.Path(compilation_file).resolve()
        if not compilation_file_path.is_file():
            console.console.print(
                f'[error]Compilation file [item]{compilation_file}[/item] for '
                f'code [item]{code.path}[/item] does not exist.[/error]',
            )
            raise typer.Exit(1)
        if not compilation_file_path.is_relative_to(code_dir):
            console.console.print(
                f'[error]Compilation file [item]{compilation_file}[/item] for '
                f"code [item]{code.path}[/item] is not under the code's folder.[/error]",
            )
            raise typer.Exit(1)

        res.append(
            (
                pathlib.Path(compilation_file),
                compilation_file_path.relative_to(code_dir),
            )
        )
    return res


@functools.cache
def get_shared_dir(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    shared_dir = get_problem_cache_dir(root) / '.shared'
    shared_dir.mkdir(parents=True, exist_ok=True)
    return shared_dir


@functools.cache
def get_empty_sentinel_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    path = get_shared_dir(root) / '.empty'
    path.write_text('')
    return path


@functools.cache
def get_fifos(root: pathlib.Path = pathlib.Path()) -> Tuple[pathlib.Path, pathlib.Path]:
    path = get_shared_dir(root) / '.fifos'
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    fifo_in = path / 'fifo.in'
    fifo_out = path / 'fifo.out'
    os.mkfifo(fifo_in)
    os.mkfifo(fifo_out)
    return fifo_in, fifo_out


@functools.cache
def get_merged_capture_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    path = get_shared_dir(root) / '.merged_capture'
    path.write_text('')
    return path


def clear_package_cache():
    pkgs = [sys.modules[__name__]]

    for pkg in pkgs:
        for fn in pkg.__dict__.values():
            if hasattr(fn, 'cache_clear'):
                fn.cache_clear()
