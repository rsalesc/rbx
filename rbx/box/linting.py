import pathlib

import yamlfix

from rbx import console
from rbx.box.cd import is_contest_package, is_problem_package
from rbx.box.stats import find_problem_packages_from_contest


def fix_yaml(path: pathlib.Path, verbose: bool = True):
    _, changed = yamlfix.fix_files([str(path)], dry_run=False)
    if changed and verbose:
        console.console.print(
            f'Formatting [item]{path}[/item].',
        )


def fix_package(root: pathlib.Path = pathlib.Path()):
    if is_problem_package(root):
        fix_yaml(root / 'problem.rbx.yml')
    if is_contest_package(root):
        fix_yaml(root / 'contest.rbx.yml')
        for problem in find_problem_packages_from_contest(root):
            fix_yaml(problem / 'problem.rbx.yml')
