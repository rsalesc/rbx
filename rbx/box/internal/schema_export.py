import pathlib
from typing import List, Type

from pydantic import BaseModel

from rbx.box.contest.schema import Contest
from rbx.box.environment import Environment
from rbx.box.package import Package
from rbx.box.presets.lock_schema import PresetLock
from rbx.box.presets.registry_schema import PresetRegistry
from rbx.box.presets.schema import Preset
from rbx.box.schema import LimitsProfile
from rbx.box.statements.schema import Statement
from rbx.utils import dump_schema_str

MODELS: List[Type[BaseModel]] = [
    Package,
    Environment,
    Contest,
    Preset,
    PresetLock,
    PresetRegistry,
    Statement,
    LimitsProfile,
]


def export_schemas(into: pathlib.Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        (into / f'{model.__name__}.json').write_text(dump_schema_str(model))
