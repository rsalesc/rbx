import collections
import dataclasses
import pathlib
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set

import typer

from rbx import console
from rbx.box.dependencies import graph as deps_graph
from rbx.box.dependencies import scanner as deps_scanner
from rbx.box.dependencies.scanner import DependencyKind, DependencyScanner, Reference
from rbx.box.schema import CodeItem


def _sanitize(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9._]', '_', name)


def _mangle(path: pathlib.Path) -> str:
    return _sanitize('__'.join(path.parts))


def assign_flat_names(
    paths: Iterable[pathlib.Path],
    *,
    reserved: Mapping[pathlib.Path, str] = {},
    enforce_stem_unique: bool = False,
) -> Dict[pathlib.Path, str]:
    """Assign a unique flat name to every path in ``paths``.

    A path whose basename (and stem, when ``enforce_stem_unique``) is globally
    unique and does not clash a reserved name keeps its bare basename, so flat
    packages stay byte-identical. Colliding paths get a ``__``-joined, sanitized
    rendering of their package-relative path, with a deterministic ``__<n>``
    counter fallback for residual collisions. Deterministic and order-independent.

    Only paths present in ``paths`` are assigned; ``reserved`` keys absent from
    ``paths`` are ignored. ``reserved`` values must be mutually distinct (they
    bypass collision handling), otherwise a :class:`ValueError` is raised.
    """
    if len(set(reserved.values())) != len(reserved):
        raise ValueError('reserved flat names must be mutually distinct')
    ordered = sorted(set(paths))
    result: Dict[pathlib.Path, str] = {}
    taken: set = set()
    taken_stems: set = set()

    def _claim(path: pathlib.Path, name: str) -> None:
        result[path] = name
        taken.add(name)
        taken_stems.add(pathlib.Path(name).stem)

    for path in ordered:
        if path in reserved:
            _claim(path, reserved[path])

    basename_counts: Dict[str, int] = {}
    stem_counts: Dict[str, int] = {}
    mangle_counts: Dict[str, int] = {}
    for path in ordered:
        if path in reserved:
            continue
        basename_counts[path.name] = basename_counts.get(path.name, 0) + 1
        stem_counts[path.stem] = stem_counts.get(path.stem, 0) + 1
        mangled = _mangle(path)
        mangle_counts[mangled] = mangle_counts.get(mangled, 0) + 1

    for path in ordered:
        if path in reserved:
            continue
        bare_ok = (
            basename_counts[path.name] == 1
            and mangle_counts[_mangle(path)] == 1
            # bare name must not collide with an already-claimed reserved name
            and path.name not in taken
            and (
                not enforce_stem_unique
                or (stem_counts[path.stem] == 1 and path.stem not in taken_stems)
            )
        )
        candidate = path.name if bare_ok else _mangle(path)
        if candidate in taken or (
            enforce_stem_unique and pathlib.Path(candidate).stem in taken_stems
        ):
            stem = pathlib.Path(candidate).stem
            suffix = pathlib.Path(candidate).suffix
            n = 1
            while f'{stem}__{n}{suffix}' in taken or (
                enforce_stem_unique and f'{stem}__{n}' in taken_stems
            ):
                n += 1
            candidate = f'{stem}__{n}{suffix}'
        _claim(path, candidate)
    return result


@dataclasses.dataclass(frozen=True)
class FlatFile:
    flat_name: str
    source_path: pathlib.Path  # package-relative original
    content: bytes  # rewritten for rewritable members, original bytes otherwise
    is_root: bool
    origin_code: Optional[CodeItem] = None


@dataclasses.dataclass
class FlatNamespace:
    files: List[FlatFile]
    name_of: Dict[pathlib.Path, str]

    def root_files(self) -> List[FlatFile]:
        return [f for f in self.files if f.is_root]

    def dep_files(self) -> List[FlatFile]:
        return [f for f in self.files if not f.is_root]

    def file_for(self, code: CodeItem) -> FlatFile:
        from rbx.box import package

        rel = package.get_relative_source_path(code)
        for f in self.files:
            if f.source_path == rel:
                return f
        raise KeyError(f'{rel} not in flat namespace')

    def flat_name_for(self, code: CodeItem) -> str:
        return self.file_for(code).flat_name

    def content_for(self, code: CodeItem) -> bytes:
        return self.file_for(code).content

    def materialize(self, into_dir: pathlib.Path) -> None:
        into_dir.mkdir(parents=True, exist_ok=True)
        for f in self.files:
            (into_dir / f.flat_name).write_bytes(f.content)


def _package_root() -> pathlib.Path:
    from rbx import utils

    return utils.abspath(pathlib.Path())


def _scanners_for(code: CodeItem) -> List[DependencyScanner]:
    from rbx.box import environment
    from rbx.box.code import find_language

    language = find_language(code)
    return deps_scanner.get_scanners_for_kinds(
        environment.language_kinds(language), language.scanners
    )


def _rewritable_scanner(code: CodeItem) -> Optional[DependencyScanner]:
    for s in _scanners_for(code):
        if s.can_rewrite and DependencyKind.COMPILATION in s.dependency_kinds:
            return s
    return None


def _rename_for(refs: List[Reference], name_of: Dict[pathlib.Path, str]):
    by_spelling = {r.spelling: r for r in refs}

    def rename(spelling: str) -> Optional[str]:
        ref = by_spelling.get(spelling)
        if ref is None or ref.target is None:
            return None
        return name_of.get(ref.target)

    return rename


def _walk(
    scanner: DependencyScanner,
    start: pathlib.Path,
    members: Set[pathlib.Path],
    refs_by_path: Dict[pathlib.Path, List[Reference]],
    rewritable: Dict[pathlib.Path, DependencyScanner],
    root_dir: pathlib.Path,
) -> None:
    """BFS a manual compilationFile's own quoted-include closure."""
    queue = collections.deque([start])
    while queue:
        current = queue.popleft()
        if current in refs_by_path:
            continue
        refs = scanner.references(root_dir / current)
        refs_by_path[current] = refs
        members.add(current)
        rewritable.setdefault(current, scanner)
        for ref in refs:
            if ref.target is not None and ref.target not in refs_by_path:
                queue.append(ref.target)


def _guard_non_rewritable(
    code: CodeItem,
    rel: pathlib.Path,
    comp_dests: Sequence[pathlib.Path],
    root_dir: pathlib.Path,
) -> None:
    """Fail loudly when a non-rewritable source (or one of its compilationFiles)
    pulls in a cross-directory dependency that cannot be flattened.

    Walks the source's whole resolving closure (the source plus each manual
    ``compilationFiles`` entry and their transitive references) and flags any
    reference whose target lives in a different directory than the file that
    references it -- such an import/include cannot resolve once flattened.
    """
    scanners = _scanners_for(code)
    if not scanners:
        return
    cross_dir: Set[pathlib.Path] = set()
    seen: Set[pathlib.Path] = set()
    queue = collections.deque([rel, *comp_dests])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        abs_current = root_dir / current
        if not abs_current.is_file():
            continue
        for s in scanners:
            for ref in s.references(abs_current):
                if ref.target is None:
                    continue
                if ref.target.parent != current.parent:
                    cross_dir.add(ref.target)
                if ref.target not in seen:
                    queue.append(ref.target)
    if not cross_dir:
        return
    listed = ', '.join(str(t) for t in sorted(cross_dir))
    console.console.print(
        f'[error]Cannot flatten {code.href()} for a flat judge: it depends on '
        f'cross-directory files [item]{listed}[/item] but its language does not '
        f'support include/import rewriting.[/error]\n'
        f'[error]Flatten it manually or keep its dependencies in the same '
        f'directory. See issue #525.[/error]'
    )
    raise typer.Exit(1)


def build_flat_namespace(
    sources: Sequence[CodeItem],
    *,
    reserved: Mapping[pathlib.Path, str] = {},
    enforce_stem_unique: bool = False,
) -> FlatNamespace:
    from rbx import utils
    from rbx.box import package

    members: Set[pathlib.Path] = set()
    refs_by_path: Dict[pathlib.Path, List[Reference]] = {}
    rewritable: Dict[pathlib.Path, DependencyScanner] = {}
    roots: Dict[pathlib.Path, CodeItem] = {}
    # Real on-disk location of each member. In-package deps live at ``root_dir /
    # path``; a root whose source lives outside the package (e.g. the builtin
    # checker, whose mirror path is only a basename) must be read from its actual
    # path instead.
    src_abs: Dict[pathlib.Path, pathlib.Path] = {}
    root_dir = _package_root()

    for code in sources:
        rel = package.get_relative_source_path(code)
        roots[rel] = code
        src_abs[rel] = utils.abspath(code.path)
        scanner = _rewritable_scanner(code)

        graph = deps_graph.expand(code, require_kind=DependencyKind.COMPILATION)
        if graph is not None:
            for path, refs in graph.nodes.items():
                members.add(path)
                refs_by_path.setdefault(path, refs)
                if scanner is not None:
                    rewritable.setdefault(path, scanner)
        else:
            members.add(rel)

        comp_dests = [dest for _, dest in package.get_compilation_files(code)]
        for dest in comp_dests:
            members.add(dest)
            if scanner is not None:
                _walk(scanner, dest, members, refs_by_path, rewritable, root_dir)

        if scanner is None:
            _guard_non_rewritable(code, rel, comp_dests, root_dir)

    name_of = assign_flat_names(
        members, reserved=reserved, enforce_stem_unique=enforce_stem_unique
    )

    files: List[FlatFile] = []
    for path in sorted(members):
        raw = src_abs.get(path, root_dir / path).read_bytes()
        if path in rewritable:
            rename = _rename_for(refs_by_path.get(path, []), name_of)
            content = (
                rewritable[path].rewrite(raw.decode('utf-8'), rename).encode('utf-8')
            )
        else:
            content = raw
        files.append(
            FlatFile(
                flat_name=name_of[path],
                source_path=path,
                content=content,
                is_root=path in roots,
                origin_code=roots.get(path),
            )
        )
    return FlatNamespace(files=files, name_of=name_of)
