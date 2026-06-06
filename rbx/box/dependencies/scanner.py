import abc
import dataclasses
import enum
import pathlib
from typing import Callable, ClassVar, List, Optional, Set, Type


class DependencyKind(enum.Enum):
    COMPILATION = 'compilation'
    EXECUTION = 'execution'


@dataclasses.dataclass(frozen=True)
class Reference:
    """A single dependency reference discovered in a source file.

    ``spelling`` is the path/module exactly as written (e.g. ``../lib.h`` or
    ``.helper``); ``target`` is its resolved package-relative path, or ``None`` when
    the reference cannot be resolved to a file under the package root (system headers,
    builtin libraries, stdlib/third-party imports).
    """

    spelling: str
    target: Optional[pathlib.Path] = None


class DependencyScanner(abc.ABC):
    """Per-language extension point for discovering and rewriting dependencies.

    ``references`` reads a single file and returns its *direct* dependency edges,
    already resolved against the package root. ``rewrite`` (optional, gated by
    ``can_rewrite``) is a pure textual transform used by packaging to flatten sources
    for judges with a flat/inline file namespace.
    """

    kinds: ClassVar[Set[DependencyKind]] = set()
    can_rewrite: ClassVar[bool] = False

    @abc.abstractmethod
    def handles(self, language: str) -> bool: ...

    @abc.abstractmethod
    def references(self, file: pathlib.Path) -> List[Reference]: ...

    def rewrite(self, text: str, rename: Callable[[str], Optional[str]]) -> str:
        raise NotImplementedError(
            f'{type(self).__name__} does not support include/import rewriting.'
        )


_REGISTRY: List[DependencyScanner] = []


def register(scanner_cls: Type[DependencyScanner]) -> Type[DependencyScanner]:
    _REGISTRY.append(scanner_cls())
    return scanner_cls


def get_scanner(language: str) -> Optional[DependencyScanner]:
    for instance in _REGISTRY:
        if instance.handles(language):
            return instance
    return None
