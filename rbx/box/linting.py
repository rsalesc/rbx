import difflib
import pathlib
from typing import Optional, Type

import yamlfix
import yamlfix.model
from pydantic import BaseModel

from rbx import console
from rbx.box.cd import is_contest_package, is_preset_package, is_problem_package
from rbx.box.contest.schema import Contest
from rbx.box.presets import get_preset_yaml
from rbx.box.presets.schema import Preset
from rbx.box.schema import Package
from rbx.box.stats import find_problem_packages_from_contest
from rbx.utils import uploaded_schema_path


def fix_language_server(path: pathlib.Path, model_cls: Type[BaseModel]) -> bool:
    stream = []
    with path.open('r') as f:
        for line in f:
            if line.strip().startswith('# yaml-language-server:'):
                continue
            stream.append(line)
            if line.startswith('---'):
                stream.append(
                    f'# yaml-language-server: $schema={uploaded_schema_path(model_cls)}\n'
                )
    content = ''.join(stream)
    orig_text = path.read_text()
    path.write_text(content)
    return orig_text != content


def fix_yaml(
    path: pathlib.Path,
    verbose: bool = True,
    print_diff: bool = False,
    model_cls: Optional[Type[BaseModel]] = None,
):
    orig_text = path.read_text()

    # Config to go hand-to-hand with VSCode YAML extension,
    # which we offer first class support to. Unfortunately,
    # YAML extension is not perfect :(
    config = yamlfix.model.YamlfixConfig(
        quote_basic_values=True,
        quote_representation='"',
        comments_min_spaces_from_content=1,
    )
    _, changed = yamlfix.fix_files([str(path)], dry_run=False, config=config)

    # if model_cls is not None:
    #     if fix_language_server(path, model_cls):
    #         changed = True

    if changed and verbose:
        console.console.print(
            f'Formatting [item]{path}[/item].',
        )

    if print_diff and changed:
        unified_diff = difflib.unified_diff(
            orig_text.splitlines(), path.read_text().splitlines()
        )
        console.console.print(
            f'Diff for [item]{path}[/item].\n' + '\n'.join(unified_diff),
        )


def fix_package(root: pathlib.Path = pathlib.Path(), print_diff: bool = False):
    if is_preset_package(root):
        fix_yaml(root / 'preset.rbx.yml', model_cls=Preset, print_diff=print_diff)
        preset = get_preset_yaml(root)
        if preset.problem is not None:
            fix_yaml(
                root / preset.problem / 'problem.rbx.yml',
                model_cls=Package,
                print_diff=print_diff,
            )
        if preset.contest is not None:
            fix_package(root / preset.contest, print_diff=print_diff)
        return

    if is_problem_package(root):
        fix_yaml(root / 'problem.rbx.yml', model_cls=Package, print_diff=print_diff)
    if is_contest_package(root):
        fix_yaml(root / 'contest.rbx.yml', model_cls=Contest, print_diff=print_diff)
        for problem in find_problem_packages_from_contest(root):
            fix_yaml(
                problem / 'problem.rbx.yml',
                model_cls=Package,
                print_diff=print_diff,
            )
