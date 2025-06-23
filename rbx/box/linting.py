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
from rbx.box.stats import find_problem_packages_from_contest
from rbx.schema import Problem
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
    model_cls: Optional[Type[BaseModel]] = None,
):
    config = yamlfix.model.YamlfixConfig(quote_basic_values=True)
    _, changed = yamlfix.fix_files([str(path)], dry_run=False, config=config)

    if model_cls is not None:
        changed = changed or fix_language_server(path, model_cls)

    if changed and verbose:
        console.console.print(
            f'Formatting [item]{path}[/item].',
        )


def fix_package(root: pathlib.Path = pathlib.Path()):
    if is_preset_package(root):
        fix_yaml(root / 'preset.rbx.yml', model_cls=Preset)
        preset = get_preset_yaml(root)
        if preset.problem is not None:
            fix_yaml(root / preset.problem / 'problem.rbx.yml', model_cls=Problem)
        if preset.contest is not None:
            fix_package(root / preset.contest)
        return

    if is_problem_package(root):
        fix_yaml(root / 'problem.rbx.yml', model_cls=Problem)
    if is_contest_package(root):
        fix_yaml(root / 'contest.rbx.yml', model_cls=Contest)
        for problem in find_problem_packages_from_contest(root):
            fix_yaml(problem / 'problem.rbx.yml', model_cls=Problem)
