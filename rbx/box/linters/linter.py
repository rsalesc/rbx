import abc
import enum
from typing import ClassVar, List, Optional, Set

from pydantic import BaseModel

from rbx.box.linters.asset_kind import AssetKind
from rbx.box.schema import CodeItem


class LinterSeverity(enum.Enum):
    WARNING = 'warning'
    ERROR = 'error'


class LinterMessage(BaseModel):
    severity: LinterSeverity
    message: str
    line: Optional[int] = None  # 1-based
    col: Optional[int] = None  # 1-based


class Linter(abc.ABC):
    # Lowercase identifier referenced in env.rbx.yml.
    name: ClassVar[str]
    # Env language names this linter supports (e.g. {'cpp'}).
    languages: ClassVar[Set[str]]
    # Interface-level restriction; empty set means "all asset kinds".
    applies_to: ClassVar[Set[AssetKind]] = set()

    @abc.abstractmethod
    def lint(self, code: CodeItem, source: str) -> List[LinterMessage]:
        """Analyze raw source text and return messages. Pure, synchronous."""
        ...
