import abc
import dataclasses
import enum
import pathlib
from typing import Callable, ClassVar, Dict, List, Optional, Set, Type

from rbx.grading.language_kind import LanguageKind


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

    A scanner is selected for a language when that language's kinds (see
    ``environment.language_kinds``) intersect ``language_kinds``, or when the
    language explicitly names the scanner in its ``scanners`` field.
    """

    name: ClassVar[str]
    language_kinds: ClassVar[Set[LanguageKind]] = set()
    dependency_kinds: ClassVar[Set[DependencyKind]] = set()
    can_rewrite: ClassVar[bool] = False

    @abc.abstractmethod
    def references(self, file: pathlib.Path) -> List[Reference]: ...

    def rewrite(self, text: str, rename: Callable[[str], Optional[str]]) -> str:
        raise NotImplementedError(
            f'{type(self).__name__} does not support include/import rewriting.'
        )


_REGISTRY: Dict[str, DependencyScanner] = {}


def register(scanner_cls: Type[DependencyScanner]) -> Type[DependencyScanner]:
    instance = scanner_cls()
    _REGISTRY[instance.name] = instance
    return scanner_cls


def get_scanner(name: str) -> Optional[DependencyScanner]:
    return _REGISTRY.get(name)


def get_scanners_for_kinds(
    kinds: Set[LanguageKind], names: Optional[List[str]] = None
) -> List[DependencyScanner]:
    """Scanners applicable to a language: every registered scanner whose
    ``language_kinds`` intersects ``kinds``, plus any explicitly named in ``names``
    (deduplicated, registration order)."""
    explicit = set(names or [])
    result = []
    for name, scanner in _REGISTRY.items():
        if scanner.language_kinds & kinds or name in explicit:
            result.append(scanner)
    return result
