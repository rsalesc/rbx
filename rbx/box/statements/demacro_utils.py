import dataclasses
from typing import Dict, Iterator, Optional


@dataclasses.dataclass
class MacroDef:
    name: str
    n_args: int
    default: Optional[str]
    body: str
    source_file: Optional[str] = None


class MacroDefinitions:
    def __init__(self) -> None:
        self._defs: Dict[str, MacroDef] = {}

    def add(self, macro_def: MacroDef) -> None:
        self._defs[macro_def.name] = macro_def

    def get(self, name: str) -> Optional[MacroDef]:
        return self._defs.get(name)

    def merge(self, other: 'MacroDefinitions') -> None:
        for name in other:
            macro = other.get(name)
            if macro is not None:
                self.add(macro)

    def __contains__(self, name: str) -> bool:
        return name in self._defs

    def __iter__(self) -> Iterator[str]:
        return iter(self._defs)

    def __len__(self) -> int:
        return len(self._defs)
