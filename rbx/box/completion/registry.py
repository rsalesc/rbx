import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from click.shell_completion import CompletionItem


@dataclass
class CompletionContext:
    args: List[str]
    command: Tuple[str, ...]
    option_values: Dict[str, str]
    package_root: Optional[Path]


Completer = Callable[[CompletionContext, str], List[CompletionItem]]

# key -> either a dotted path 'module:function' (string => lazy import) or the
# already-resolved completer callable (registered in-process via the decorator).
_REGISTRY: Dict[str, Union[str, Completer]] = {}
# id(function) -> key, for the generator's reverse lookup
_REVERSE: Dict[int, str] = {}


def register_completer_path(key: str, dotted: str) -> None:
    _REGISTRY[key] = dotted


def register_completer(key: str) -> Callable[[Completer], Completer]:
    def deco(fn: Completer) -> Completer:
        _REGISTRY[key] = fn
        _REVERSE[id(fn)] = key
        return fn

    return deco


def key_for_function(fn: Completer) -> Optional[str]:
    return _REVERSE.get(id(fn))


def load_completer(key: str) -> Completer:
    target = _REGISTRY[key]
    if not isinstance(target, str):
        return target
    module_name, _, qualname = target.partition(':')
    module = importlib.import_module(module_name)
    obj = module
    for part in qualname.split('.'):
        obj = getattr(obj, part)
    return obj  # type: ignore[return-value]
