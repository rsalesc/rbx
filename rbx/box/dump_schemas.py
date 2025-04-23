import pathlib

import mkdocs_gen_files

from rbx.box.contest.schema import Contest
from rbx.box.environment import Environment
from rbx.box.package import Package
from rbx.box.presets.lock_schema import PresetLock
from rbx.box.presets.schema import Preset
from rbx.box.statements.schema import Statement
from rbx.utils import dump_schema_str

models = [Package, Environment, Contest, Preset, PresetLock, Statement]

for model in models:
    path = pathlib.Path('schemas') / f'{model.__name__}.json'
    with mkdocs_gen_files.open(str(path), 'w') as f:
        f.write(dump_schema_str(model))
