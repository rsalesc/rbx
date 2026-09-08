import dataclasses
import pathlib
import re
from typing import Callable, List, Optional, Sequence, Set

from rbx import utils
from rbx.box.dependencies import scanner as deps_scanner
from rbx.box.dependencies.scanner import DependencyScanner
from rbx.box.exception import RbxException

# Suffix -> registered scanner name, used when the caller passes no scanner.
_SCANNER_BY_SUFFIX = {
    '.c': 'cpp',
    '.cc': 'cpp',
    '.cpp': 'cpp',
    '.cxx': 'cpp',
    '.h': 'cpp',
    '.hh': 'cpp',
    '.hpp': 'cpp',
    '.hxx': 'cpp',
}

_PRAGMA_ONCE = re.compile(r'^[ \t]*#[ \t]*pragma[ \t]+once[ \t]*\r?\n?', re.MULTILINE)


class AmalgamationError(RbxException):
    """A source could not be reduced to a single self-contained translation unit.

    ``RbxException`` renders through a rich console, which would reflow long file
    paths; this one carries a plain message instead so callers can match on it and
    print it themselves.
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


@dataclasses.dataclass(frozen=True)
class AmalgamationResult:
    """The outcome of :func:`amalgamate`.

    ``content`` is the single translation unit. ``inlined`` lists every file that
    contributed, in the order it was inlined (the root first). ``kept`` lists the
    spellings deliberately left as directives, in encounter order.
    """

    content: bytes
    inlined: List[pathlib.Path]
    kept: List[str]


def _infer_scanner(root: pathlib.Path) -> DependencyScanner:
    name = _SCANNER_BY_SUFFIX.get(root.suffix.lower())
    if name is None:
        raise AmalgamationError(
            f'Cannot amalgamate {root}: no dependency scanner is known for the '
            f'{root.suffix!r} extension. Pass an explicit `scanner=`.'
        )
    found = deps_scanner.get_scanner(name)
    if found is None:
        raise AmalgamationError(f'Dependency scanner {name!r} is not registered.')
    return found


def _resolve(
    spelling: str,
    including_file: pathlib.Path,
    extra_roots: Sequence[pathlib.Path],
) -> Optional[pathlib.Path]:
    """Resolve ``spelling`` beside the including file first, then in ``extra_roots``.

    Unlike the scanners' own resolution, this is deliberately *not* confined to the
    package root: amalgamation must reach builtin headers (testlib, rbx.h) that live
    in the app's resources.
    """
    candidates = [including_file.parent / spelling]
    candidates.extend(root / spelling for root in extra_roots)
    for candidate in candidates:
        resolved = utils.abspath(candidate)
        if resolved.is_file():
            return resolved
    return None


def _render_provenance(
    target: pathlib.Path,
    relative_to: Optional[pathlib.Path],
    extra_roots: Sequence[pathlib.Path],
) -> str:
    """How an inlined file is named in the ``// amalgamated from`` comment.

    Absolute when there is no anchor, which is what a caller inspecting a build on
    the machine that produced it wants. With an anchor -- packagers pass the package
    root -- the comment must not leak anything about that machine, since it travels
    inside the shipped package: a file under the anchor is named relative to it, one
    coming from an ``extra_roots`` search directory is labelled ``<builtin>/``, and
    anything else is reduced to its bare name under ``<external>/`` rather than to a
    ``../..`` path that would still spell out the directories above the package.
    """
    if relative_to is None:
        return str(target)
    for root, label in [(relative_to, ''), *((r, '<builtin>') for r in extra_roots)]:
        try:
            relative = target.relative_to(utils.abspath(root))
        except ValueError:
            continue
        return f'{label}/{relative.as_posix()}' if label else relative.as_posix()
    return f'<external>/{target.name}'


def amalgamate(
    root: pathlib.Path,
    *,
    extra_roots: Sequence[pathlib.Path] = (),
    keep: Optional[Callable[[str], bool]] = None,
    scanner: Optional[DependencyScanner] = None,
    relative_to: Optional[pathlib.Path] = None,
) -> AmalgamationResult:
    """Reduce ``root`` and its dependency closure to one self-contained source.

    Every resolvable dependency directive is replaced by the referenced file's own
    amalgamated content, each file contributing at most once (keyed on its resolved
    path), so diamonds collapse and cycles terminate. ``#pragma once`` is dropped,
    since that deduplication already guarantees single inclusion and the pragma would
    otherwise warn in a merged unit. References the scanner does not report -- C++
    ``<...>`` system includes -- are left untouched.

    A directive that cannot be resolved raises :class:`AmalgamationError` naming the
    including file and the spelling, unless ``keep`` returns ``True`` for it, in which
    case the directive survives verbatim.

    ``relative_to`` anchors the ``// amalgamated from`` provenance comments, which
    are absolute paths on the running machine without it. Callers that ship the
    result -- packagers -- must pass one, or the setter's own directory layout
    travels inside the package; see :func:`_render_provenance`.

    ``extra_roots`` are extra search directories for otherwise unresolvable spellings.
    This is how callers make builtin headers (``testlib.h``, ``rbx.h``) inlinable
    without this module knowing what they are.
    """
    root = utils.abspath(root)
    used_scanner = scanner if scanner is not None else _infer_scanner(root)
    if not used_scanner.can_splice:
        raise AmalgamationError(
            f'Cannot amalgamate {root}: the {used_scanner.name!r} dependency scanner '
            'does not support splicing.'
        )

    inlined: List[pathlib.Path] = []
    kept: List[str] = []
    visited: Set[pathlib.Path] = set()

    def render(path: pathlib.Path) -> bytes:
        if path in visited:
            return b''
        visited.add(path)
        inlined.append(path)

        text = _PRAGMA_ONCE.sub('', path.read_text(encoding='utf-8'))
        data = text.encode('utf-8')
        out = bytearray()
        pos = 0
        for start, end, spelling in used_scanner.reference_spans(text):
            out += data[pos:start]
            target = _resolve(spelling, path, extra_roots)
            if target is None:
                if keep is not None and keep(spelling):
                    kept.append(spelling)
                    out += data[start:end]
                else:
                    raise AmalgamationError(
                        f'Cannot amalgamate {root}: {path} references {spelling!r}, '
                        'which does not resolve to a file. Move the dependency next '
                        'to the source, add its directory to the search roots, or '
                        'drop the reference.'
                    )
            else:
                provenance = _render_provenance(target, relative_to, extra_roots)
                out += f'// amalgamated from {provenance}\n'.encode()
                out += render(target)
                out += b'\n'
            pos = end
        out += data[pos:]
        return bytes(out)

    content = render(root)
    return AmalgamationResult(content=content, inlined=inlined, kept=kept)
