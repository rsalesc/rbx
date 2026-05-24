from typing import Dict, Type

from rbx.box.exception import RbxException
from rbx.box.linters.linter import Linter

_REGISTRY: Dict[str, Linter] = {}


def register(linter_cls: Type[Linter]) -> Type[Linter]:
    instance = linter_cls()
    _REGISTRY[instance.name] = instance
    return linter_cls


def get_linter(name: str) -> Linter:
    if name not in _REGISTRY:
        with RbxException() as e:
            e.print(f'[error]Unknown linter: [item]{name}[/item][/error]')
            known = ', '.join(sorted(_REGISTRY)) or '(none)'
            e.print(f'Known linters: {known}')
    return _REGISTRY[name]
