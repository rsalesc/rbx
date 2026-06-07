# Flatten + ship exported sources (Polygon, BOCA) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make C++ sources that build locally via the Phase-1 mirrored layout (subdirectory placement, `#include "../lib.h"`, custom `compilationFiles`) also build on the flat export targets — Polygon offline, Polygon upload, BOCA — by shipping each source's compilation closure under one shared collision-free naming scheme and rewriting quoted includes (#525 + #526 + #527).

**Architecture:** A new pure module `rbx/box/packaging/flattening.py` exposes (a) `assign_flat_names(...)` — a pure, package-independent naming function (the heart of #527), and (b) `build_flat_namespace(sources, ...)` — collects each source's transitive quoted-include deps via the existing `rbx.box.dependencies` engine, folds in manual `compilationFiles`, assigns flat names, and rewrites includes with `CppScanner.rewrite`. It returns a `FlatNamespace` the three packagers *materialize* their own way (copy into `files/`, upload, or inline heredocs).

**Tech Stack:** Python 3, Pydantic v2, tree-sitter (via existing `dependencies/cpp.py`), Typer, pytest. Single quotes, absolute imports only (ruff `TID`). Errors via `console.console.print('[error]…[/error]')` + `raise typer.Exit(1)`. Use the `/commit` skill (`.claude/skills/commit.md`) for every commit — conventional commits, co-author trailer.

**Design doc:** `docs/plans/2026-06-07-packaging-flatten-export-design.md`

**Key existing primitives (do not rebuild):**
- `rbx.box.dependencies.graph.expand(code, require_kind=DependencyKind.COMPILATION) -> Optional[DependencyGraph]`; `graph.root` (pkg-relative source path), `graph.files()` (pkg-relative deps, root excluded), `graph.nodes[path] -> List[Reference]`.
- `rbx.box.dependencies.scanner.Reference(spelling, target)` — `target is None` for system/testlib/rbx/unresolved.
- `rbx.box.dependencies.cpp.CppScanner.rewrite(text, rename: Callable[[str], Optional[str]]) -> str`; `can_rewrite=True` (C++), `False` (Python).
- `rbx.box.dependencies.scanner.get_scanners_for_kinds(kinds, names)`; `rbx.box.environment.language_kinds(language)`; `rbx.box.code.find_language(code)`.
- `rbx.box.package.get_relative_source_path(code) -> pathlib.Path` (pkg-relative mirror path, basename fallback).
- `rbx.box.package.get_compilation_files(code) -> List[Tuple[pathlib.Path, pathlib.Path]]` (each `(rel, rel)`).

---

## Phase A — Core `flattening.py` module

### Task A1: Pure flat-name assignment — unique basenames kept

**Files:**
- Create: `rbx/box/packaging/flattening.py`
- Test: `tests/rbx/box/packaging/test_flattening.py`

**Step 1: Write the failing test**

```python
import pathlib

from rbx.box.packaging import flattening


def _p(*parts: str) -> pathlib.Path:
    return pathlib.Path(*parts)


def test_unique_basenames_keep_bare_name():
    names = flattening.assign_flat_names(
        [_p('check.cpp'), _p('lib', 'util.h'), _p('gens', 'gen.cpp')]
    )
    assert names == {
        _p('check.cpp'): 'check.cpp',
        _p('lib', 'util.h'): 'util.h',
        _p('gens', 'gen.cpp'): 'gen.cpp',
    }
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/test_flattening.py::test_unique_basenames_keep_bare_name -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: assign_flat_names`.

**Step 3: Write minimal implementation**

```python
import pathlib
import re
from typing import Dict, Iterable, List, Mapping


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
    """
    paths = sorted(set(paths))
    result: Dict[pathlib.Path, str] = {}
    taken: set = set()
    taken_stems: set = set()

    def _claim(path: pathlib.Path, name: str) -> None:
        result[path] = name
        taken.add(name)
        taken_stems.add(pathlib.Path(name).stem)

    # Reserved names win and are claimed first.
    for path in paths:
        if path in reserved:
            _claim(path, reserved[path])

    basename_counts: Dict[str, int] = {}
    stem_counts: Dict[str, int] = {}
    for path in paths:
        if path in reserved:
            continue
        basename_counts[path.name] = basename_counts.get(path.name, 0) + 1
        stem_counts[path.stem] = stem_counts.get(path.stem, 0) + 1

    for path in paths:
        if path in reserved:
            continue
        bare_ok = (
            basename_counts[path.name] == 1
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
            while (
                f'{stem}__{n}{suffix}' in taken
                or (enforce_stem_unique and f'{stem}__{n}' in taken_stems)
            ):
                n += 1
            candidate = f'{stem}__{n}{suffix}'
        _claim(path, candidate)
    return result
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/packaging/test_flattening.py::test_unique_basenames_keep_bare_name -v`
Expected: PASS.

**Step 5: Commit** (use `/commit` skill) — `feat(packaging): add flat-name assignment helper`.

---

### Task A2: Naming — collisions, stems, reserved, determinism

**Files:** Modify: `tests/rbx/box/packaging/test_flattening.py`

**Step 1: Write the failing tests**

```python
def test_basename_collision_uses_double_underscore_path():
    names = flattening.assign_flat_names(
        [_p('gens', 'a', 'gen.cpp'), _p('gens', 'b', 'gen.cpp')]
    )
    assert names == {
        _p('gens', 'a', 'gen.cpp'): 'gens__a__gen.cpp',
        _p('gens', 'b', 'gen.cpp'): 'gens__b__gen.cpp',
    }


def test_reserved_names_are_honored_and_force_others_to_mangle():
    names = flattening.assign_flat_names(
        [_p('checker.cpp'), _p('sub', 'check.cpp')],
        reserved={_p('checker.cpp'): 'check.cpp'},
    )
    # checker.cpp -> reserved 'check.cpp'; the other 'check.cpp' must NOT take it.
    assert names[_p('checker.cpp')] == 'check.cpp'
    assert names[_p('sub', 'check.cpp')] == 'sub__check.cpp'


def test_enforce_stem_unique_mangles_same_stem_diff_ext():
    names = flattening.assign_flat_names(
        [_p('a', 'gen.cpp'), _p('b', 'gen.cc')], enforce_stem_unique=True
    )
    assert names[_p('a', 'gen.cpp')] == 'a__gen.cpp'
    assert names[_p('b', 'gen.cc')] == 'b__gen.cc'


def test_residual_mangle_collision_gets_counter():
    # 'a/b__c.h' and 'a__b/c.h' both mangle to 'a__b__c.h'.
    names = flattening.assign_flat_names([_p('a', 'b__c.h'), _p('a__b', 'c.h')])
    assert sorted(names.values()) == ['a__b__c.h', 'a__b__c__1.h']


def test_assignment_is_order_independent():
    a = flattening.assign_flat_names([_p('x', 'g.cpp'), _p('y', 'g.cpp')])
    b = flattening.assign_flat_names([_p('y', 'g.cpp'), _p('x', 'g.cpp')])
    assert a == b
```

**Step 2: Run** — `uv run pytest tests/rbx/box/packaging/test_flattening.py -v`. Expected: the 5 new tests PASS (A1 implementation already covers them); if `test_residual_mangle_collision_gets_counter` fails, fix the counter loop until green.

**Step 3:** No new impl expected. If a test reveals a gap, fix `assign_flat_names` minimally.

**Step 4: Run all naming tests** — Expected: PASS.

**Step 5: Commit** — `test(packaging): cover flat-name collisions, stems, determinism`.

---

### Task A3: `FlatFile` / `FlatNamespace` data model + `materialize`

**Files:** Modify: `rbx/box/packaging/flattening.py`, `tests/rbx/box/packaging/test_flattening.py`

**Step 1: Write the failing test**

```python
def test_flatnamespace_materialize_writes_every_file(tmp_path):
    ns = flattening.FlatNamespace(
        files=[
            flattening.FlatFile('check.cpp', _p('check.cpp'), b'CHK', True, None),
            flattening.FlatFile('lib.h', _p('sub', 'lib.h'), b'LIB', False, None),
        ],
        name_of={_p('check.cpp'): 'check.cpp', _p('sub', 'lib.h'): 'lib.h'},
    )
    ns.materialize(tmp_path)
    assert (tmp_path / 'check.cpp').read_bytes() == b'CHK'
    assert (tmp_path / 'lib.h').read_bytes() == b'LIB'
    assert [f.flat_name for f in ns.dep_files()] == ['lib.h']
    assert [f.flat_name for f in ns.root_files()] == ['check.cpp']
```

**Step 2: Run** — Expected: FAIL (`FlatNamespace`/`FlatFile` undefined).

**Step 3: Implement** (add to `flattening.py`):

```python
import dataclasses
from typing import List, Optional

from rbx.box.schema import CodeItem


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
```

**Step 4: Run** — Expected: PASS.

**Step 5: Commit** — `feat(packaging): add FlatFile/FlatNamespace data model`.

---

### Task A4: `build_flat_namespace` — collect, name, rewrite (C++ happy path)

**Files:** Modify: `rbx/box/packaging/flattening.py`; Create test fixtures under `tests/rbx/box/packaging/testdata/flatten_checker/`; Test: `tests/rbx/box/packaging/test_flattening_build.py`

**Step 1: Create a package fixture** with a subdir checker doing a cross-dir include. Mirror the structure of an existing minimal package fixture (copy from an existing `tests/rbx/box/**/testdata/<pkg>/problem.rbx.yml` that defines a checker; consult `tests/rbx/box/conftest.py` for the `cleandir_with_testdata` / `pkg_from_testdata` fixtures and the `@pytest.mark.test_pkg('<dir>')` marker). The fixture must contain:
- `problem.rbx.yml` with `checker: { path: checkers/check.cpp }`
- `checkers/check.cpp` containing `#include "../common/lib.h"` and `#include "testlib.h"`
- `common/lib.h` (a trivial header, may itself `#include "consts.h"`)
- `common/consts.h`

**Step 2: Write the failing test**

```python
import pathlib

import pytest

from rbx.box import package
from rbx.box.packaging import flattening


@pytest.mark.test_pkg('flatten_checker')
def test_build_flat_namespace_flattens_and_rewrites_checker(pkg_from_testdata):
    checker = package.get_checker_or_builtin()
    ns = flattening.build_flat_namespace(
        [checker], reserved={package.get_relative_source_path(checker): 'check.cpp'}
    )
    flat = {f.flat_name for f in ns.files}
    # checker + its transitive quoted-include deps are all present, flat.
    assert flat == {'check.cpp', 'lib.h', 'consts.h'}
    # testlib.h stays untouched (target is None); the cross-dir include is rewritten.
    checker_text = ns.content_for(checker).decode()
    assert '#include "lib.h"' in checker_text
    assert '#include "../common/lib.h"' not in checker_text
    assert '#include "testlib.h"' in checker_text
    # lib.h's own include is rewritten to the flat name too.
    lib = next(f for f in ns.files if f.flat_name == 'lib.h')
    assert '#include "consts.h"' in lib.content.decode()
```

> Adjust the fixture (and the asserted dep set) if `lib.h` does not include `consts.h`; keep at least one transitive (2-hop) dep to prove the BFS rewrites non-root files.

**Step 3: Run** — Expected: FAIL (`build_flat_namespace` undefined).

**Step 4: Implement** (add to `flattening.py`):

```python
from typing import Sequence

from rbx.box.dependencies import graph as deps_graph
from rbx.box.dependencies import scanner as deps_scanner
from rbx.box.dependencies.scanner import DependencyKind, DependencyScanner, Reference


def _rewritable_scanner(code: CodeItem) -> Optional[DependencyScanner]:
    from rbx.box import environment
    from rbx.box.code import find_language

    language = find_language(code)
    scanners = deps_scanner.get_scanners_for_kinds(
        environment.language_kinds(language), language.scanners
    )
    for s in scanners:
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


def build_flat_namespace(
    sources: Sequence[CodeItem],
    *,
    reserved: Mapping[pathlib.Path, str] = {},
    enforce_stem_unique: bool = False,
) -> FlatNamespace:
    from rbx.box import package

    members: set = set()
    refs_by_path: Dict[pathlib.Path, List[Reference]] = {}
    rewritable: Dict[pathlib.Path, DependencyScanner] = {}
    roots: Dict[pathlib.Path, CodeItem] = {}

    for code in sources:
        rel = package.get_relative_source_path(code)
        roots[rel] = code
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

        # Manual compilationFiles: ship the bytes; scan+rewrite if rewritable.
        for _, dest in package.get_compilation_files(code):
            members.add(dest)
            if scanner is not None:
                _walk(scanner, dest, members, refs_by_path, rewritable)

        # Guardrail: a non-rewritable source with cross-directory resolving deps
        # cannot be flattened.
        if scanner is None:
            _guard_non_rewritable(code, rel)

    name_of = assign_flat_names(
        members, reserved=reserved, enforce_stem_unique=enforce_stem_unique
    )

    files: List[FlatFile] = []
    for path in sorted(members):
        text_bytes = (package_root_path() / path).read_bytes()
        if path in rewritable:
            scanner = rewritable[path]
            rename = _rename_for(refs_by_path.get(path, []), name_of)
            content = scanner.rewrite(text_bytes.decode('utf-8'), rename).encode('utf-8')
        else:
            content = text_bytes
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
```

Add the small helpers:

```python
def package_root_path() -> pathlib.Path:
    from rbx import utils

    return utils.abspath(pathlib.Path())


def _walk(scanner, start, members, refs_by_path, rewritable):
    """BFS a manual compilationFile's own quoted-include closure."""
    import collections

    queue = collections.deque([start])
    while queue:
        current = queue.popleft()
        if current in refs_by_path:
            continue
        refs = scanner.references(package_root_path() / current)
        refs_by_path[current] = refs
        members.add(current)
        rewritable.setdefault(current, scanner)
        for ref in refs:
            if ref.target is not None and ref.target not in refs_by_path:
                queue.append(ref.target)
```

> `scanner.references` takes a path that exists on disk; pass the absolute path (`package_root_path() / current`). The C++ scanner resolves targets relative to the package root internally.

**Step 5: Run** — `uv run pytest tests/rbx/box/packaging/test_flattening_build.py -v`. Expected: PASS.

**Step 6: Commit** — `feat(packaging): build flat namespace with include rewriting (#525, #526)`.

---

### Task A5: Guardrail for non-rewritable cross-directory sources

**Files:** Modify: `rbx/box/packaging/flattening.py`; add a fixture `tests/rbx/box/packaging/testdata/flatten_py_crossdir/` (a Python generator at `gens/g.py` doing `from common.helper import x`, with `common/helper.py` present and a `problem.rbx.yml` referencing the generator); Test: `tests/rbx/box/packaging/test_flattening_build.py`

**Step 1: Write the failing test**

```python
@pytest.mark.test_pkg('flatten_py_crossdir')
def test_build_flat_namespace_errors_on_unrewritable_crossdir(pkg_from_testdata):
    import typer

    gen = package.get_generator('g')  # adjust to the fixture's generator accessor
    with pytest.raises(typer.Exit):
        flattening.build_flat_namespace([gen])
```

**Step 2: Run** — Expected: FAIL (no error raised; namespace builds).

**Step 3: Implement `_guard_non_rewritable`:**

```python
import typer

from rbx.box import console


def _guard_non_rewritable(code: CodeItem, rel: pathlib.Path) -> None:
    # All applicable scanners (any kind) so we can see resolving cross-dir deps.
    graph = deps_graph.expand(code)
    if graph is None:
        return
    cross_dir = [t for t in graph.files() if t.parent != rel.parent]
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
```

> Verify `code.href()` exists on `CodeItem` (it is used in `package.py`); if not, fall back to `str(code.path)`.

**Step 4: Run** — Expected: PASS. Also re-run the whole module: `uv run pytest tests/rbx/box/packaging/test_flattening.py tests/rbx/box/packaging/test_flattening_build.py -v` → all green.

**Step 5: Commit** — `feat(packaging): guard non-rewritable cross-directory sources`.

---

## Phase B — Polygon offline packager

### Task B1: Ship + rewrite checker/interactor closure into `files/`

**Files:** Modify: `rbx/box/packaging/polygon/packager.py` (`_get_files` ~159, `package()` ~225-233). Test: `tests/rbx/box/packaging/test_polygon_flatten.py`

**Step 1: Write the failing test** — using the `flatten_checker` fixture, run the Polygon packager end-to-end (follow the existing Polygon packaging test under `tests/` for how to invoke `run_packager`/`PolygonPackager` and unzip the output), then assert:
- `files/check.cpp`, `files/lib.h`, `files/consts.h` all exist in the produced package;
- `files/check.cpp` contains `#include "lib.h"` (rewritten), not `../common/lib.h`;
- the produced `problem.xml` `_get_files()` lists `files/lib.h` and `files/consts.h` (plus testlib/rbx).

**Step 2: Run** — Expected: FAIL (deps not shipped; includes not rewritten).

**Step 3: Implement.** In `PolygonPackager.package()`, replace the hard-coded checker/interactor copies (lines 230-233) with a flat namespace:

```python
from rbx.box.packaging import flattening

sources = [package.get_checker_or_builtin()]
reserved = {
    package.get_relative_source_path(package.get_checker_or_builtin()): 'check.cpp'
}
if pkg.interactor is not None:
    sources.append(pkg.interactor)
    reserved[package.get_relative_source_path(pkg.interactor)] = 'interactor.cpp'

ns = flattening.build_flat_namespace(sources, reserved=reserved)
ns.materialize(files_path)  # writes check.cpp, interactor.cpp + every dep
# Root copy at package root for the Polygon UI ('cpy').
(into_path / 'check.cpp').write_bytes(
    ns.content_for(package.get_checker_or_builtin())
)
```

Keep writing `testlib.h` and `rbx.h` into `files_path` as before (they are builtins, not namespace members). Store `ns` so `_get_files()` can read it: compute it in `package()` and pass the dep list down, or recompute. Simplest: make `_get_files()` accept the namespace. Refactor `_get_files()`:

```python
def _get_files(self, ns: 'flattening.FlatNamespace') -> List[polygon_schema.File]:
    files = [
        polygon_schema.File(path='files/testlib.h', type='h.g++'),
        polygon_schema.File(path='files/rbx.h', type='h.g++'),
    ]
    for dep in ns.dep_files():
        ftype = 'h.g++' if dep.flat_name.endswith(('.h', '.hpp', '.hh')) else 'cpp.g++'
        files.append(polygon_schema.File(path=f'files/{dep.flat_name}', type=ftype))
    return files
```

Build `ns` once near the top of `package()` (before constructing `polygon_schema.Problem`) and thread it into `files=self._get_files(ns)` and the materialize step. Remove the now-redundant `shutil.copyfile(... 'check.cpp')` lines.

**Step 4: Run** — `uv run pytest tests/rbx/box/packaging/test_polygon_flatten.py -v`. Expected: PASS. (The real-`g++` compile assertion, if added, may fail locally — see the environment note; gate it behind the `docker`/`slow` marker.)

**Step 5: Commit** — `feat(polygon): ship + rewrite checker/interactor deps in offline package (#525, #526)`.

---

## Phase C — BOCA (and MOJ) inline embedding

### Task C1: Generalize `checker.sh` / `interactor_compile.sh` to N embedded files

**Files:** Modify: `rbx/resources/packagers/boca/checker.sh`, `rbx/resources/packagers/boca/interactor_compile.sh`.

Replace the three fixed heredocs in `checker.sh` (lines 16-32) with two placeholders the packager fills in: `{{embedded_files}}` (the `read`/`printf` block that writes every flat file to disk) and `{{embedded_hash_inputs}}` (the space-separated filename list for `md5sum`). Result:

```sh
{{embedded_files}}

checker_hash=($(cat {{embedded_hash_inputs}} | md5sum))
```

Do the same for `interactor_compile.sh`: replace its single `read`/`printf` (lines 22-27) with `{{embedded_files}}` and its hash line (`cat $INTERACTOR_PATH rbx.h testlib.h`) with `cat {{embedded_hash_inputs}}`. Keep `$CHECKER_PATH`/`$INTERACTOR_PATH` = `checker.cpp`/`interactor.cpp` so the compile lines are unchanged.

**Step:** This is a template-only change; verify with the Task C2 test. Commit together with C2.

---

### Task C2: Emit the embedded-files block from BOCA `_get_checker`/`_get_interactor`

**Files:** Modify: `rbx/box/packaging/boca/packager.py` (`_get_checker` 208-224, `_get_interactor` 226-240); add a shared helper. Test: `tests/rbx/box/packaging/test_boca_flatten.py`

**Step 1: Write the failing test** — render the BOCA package for the `flatten_checker` fixture (follow the existing BOCA packaging test under `tests/`), read the generated `compile/cc` (or equivalent) script, and assert:
- it contains a heredoc writing `lib.h` and `consts.h` (the deps), plus `testlib.h`, `rbx.h`, `checker.cpp`;
- the embedded `checker.cpp` body contains `#include "lib.h"` (rewritten);
- the `md5sum` line references all embedded files.

**Step 2: Run** — Expected: FAIL.

**Step 3: Implement** a shared helper on `BocaPackager`:

```python
def _embed_block(self, named_contents: List[Tuple[str, str]]) -> Tuple[str, str]:
    """Return (embedded_files_block, hash_inputs) for the given (name, content)."""
    lines = []
    names = []
    for i, (name, content) in enumerate(named_contents):
        eof = f'RBXEMBED{i}EOF'
        lines.append(f'read -r -d \'\' RBXEMBED{i} <<"{eof}"\n{content}\n{eof}\n')
        lines.append(f'printf "%s" "${{RBXEMBED{i}}}" >{name}\n')
        names.append(name)
    return ''.join(lines), ' '.join(names)
```

Rewrite `_get_checker`:

```python
def _get_checker(self) -> str:
    checker_path = get_default_app_path() / 'packagers' / 'boca' / 'checker.sh'
    if not checker_path.exists():
        console.console.print('[error]BOCA template checker script not found.[/error]')
        raise typer.Exit(1)

    checker = package.get_checker_or_builtin()
    reserved = {package.get_relative_source_path(checker): 'checker.cpp'}
    ns = flattening.build_flat_namespace([checker], reserved=reserved)

    named = [
        ('testlib.h', get_testlib().read_text()),
        ('rbx.h', header.get_header().read_text()),
    ]
    named += [(f.flat_name, f.content.decode('utf-8')) for f in ns.files]
    block, hash_inputs = self._embed_block(named)

    return (
        self._replace_common(checker_path.read_text(), 'cc')
        .replace('{{embedded_files}}', block)
        .replace('{{embedded_hash_inputs}}', hash_inputs)
    )
```

Mirror the same for `_get_interactor` (reserved name `interactor.cpp`, template `interactor_compile.sh`; the interactor reuses the checker's `testlib.h`/`rbx.h`, so embed only the interactor namespace files there, matching the template's original behavior — but DO embed the interactor's own deps).

**Step 4: Run** — `uv run pytest tests/rbx/box/packaging/test_boca_flatten.py -v`. Expected: PASS.

**Step 5: Commit** — `feat(boca): embed + rewrite checker/interactor deps inline (#525, #526)`.

---

### Task C3: MOJ inherits the generalization

**Files:** Modify: `rbx/box/packaging/moj/packager.py` (`_get_checker` ~67, `_get_interactor` ~70). Test: extend `test_boca_flatten.py` or add `test_moj_flatten.py`.

Confirm MOJ's overrides delegate to the BOCA helpers (or call `self._embed_block` + `build_flat_namespace` the same way). Add a test that a MOJ package for `flatten_checker` embeds the deps. Commit — `feat(moj): inherit flattened checker/interactor embedding`.

---

## Phase D — Polygon upload (+ #527)

### Task D1: Single upload namespace across all sources

**Files:** Modify: `rbx/box/packaging/polygon/upload.py`. Test: `tests/rbx/box/packaging/test_polygon_upload_flatten.py` (mock the `api.Problem` client — follow existing upload tests; assert on `save_file` calls).

**Step 1:** In `upload_problem()` (the orchestrator), build ONE namespace once:

```python
from rbx.box.packaging import flattening

upload_sources = (
    list(_collect_upload_generators())   # the generators gathered today (~lines 305-314)
    + package.get_solutions()
    + [package.get_checker_or_builtin()]
    + ([package.get_validator()] if package.get_validator() is not None else [])
    + ([package.get_interactor()] if pkg.interactor is not None else [])
)
reserved = {
    package.get_relative_source_path(package.get_checker_or_builtin()): _get_checker_name(),
}
# validator/interactor keep their special stem-based names too.
ns = flattening.build_flat_namespace(
    upload_sources, reserved=reserved, enforce_stem_unique=True
)
```

Thread `ns` into the upload helpers (`_update_checker`, `_update_interactor`, `_upload_validator`, `_upload_generator`, `_upload_solutions`). Each helper uploads `ns.content_for(code)` (rewritten bytes) under `ns.flat_name_for(code)` instead of `code.path.read_bytes()` / `code.path.name`. Upload every `ns.dep_files()` entry once as `api.FileType.RESOURCE` (name = `dep.flat_name`, `source_type=None`), alongside the existing `rbx.h`/`jngen.h`/`tgen.h` resource uploads.

**Step 2-4:** Test asserts: a generator under a subdir with `#include "../lib.h"` is uploaded under its flat name with rewritten content, and `lib.h` is uploaded as a RESOURCE. Run → green.

**Step 5: Commit** — `feat(polygon): upload flattened sources + deps on API upload (#525, #526)`.

---

### Task D2: Freemarker generator references use flat stems (#527)

**Files:** Modify: `rbx/box/packaging/polygon/upload.py` (`_get_freemarker_for_calls` ~242, the test-script generation ~334-346 that uses `generator.path.stem`).

**Step 1: Write the failing test** — fixture with two same-basename generators in different dirs (`gens/a/gen.cpp`, `gens/b/gen.cpp`) used by different testcases. Assert the produced freemarker script invokes the two distinct flat stems (`gens__a__gen`, `gens__b__gen`), each mapped to the correct testcase, and that two distinct SOURCE files are uploaded (no overwrite).

**Step 2: Run** — Expected: FAIL (today both collapse to `gen` and one overwrites the other).

**Step 3: Implement** — replace `generator.path.stem` with `pathlib.Path(ns.flat_name_for(generator)).stem` everywhere the script references a generator; replace `generator.path.name` in `_upload_generator` with `ns.flat_name_for(generator)`.

**Step 4: Run** — Expected: PASS.

**Step 5: Commit** — `fix(polygon): disambiguate same-basename generators on upload (#527)`.

---

## Phase E — Regression goldens + docs

### Task E1: Byte-identical regression for flat packages (#526)

**Files:** Test: `tests/rbx/box/packaging/test_flatten_regression.py` (or extend existing golden tests).

Add tests that a **flat** package with no `compilationFiles` and no cross-dir includes produces Polygon-offline `files/` and BOCA compile scripts byte-identical to the pre-change output. Use an existing flat fixture; capture the current output as the golden (generate once, commit the golden, or compare two runs). Assert `assign_flat_names` returns identity (basename) for that package and that no extra files appear. Commit — `test(packaging): assert flat packages stay byte-identical`.

### Task E2: Update module docs

**Files:** Modify: `rbx/box/packaging/CLAUDE.md`.

Document the new `flattening.py` seam: the shared `FlatNamespace`, the `__` collision scheme, and that Polygon (offline+upload) and BOCA now ship + rewrite each source's compilation closure. Note the guardrail for non-rewritable cross-dir sources. Commit — `docs(packaging): document source flattening for flat judges`.

---

## Final verification

Run the full non-CLI suite + the new files in parallel:

```bash
uv run pytest tests/rbx/box/packaging -v
uv run pytest --ignore=tests/rbx/box/cli -n auto
uv run ruff check . && uv run ruff format --check .
```

Expected: all green except the pre-existing environment-bound C++/sandbox compile failures on this machine (per project memory — verify those same tests are unrelated to this change, e.g. by confirming they fail on `main` too). The real-`g++` "the rewritten checker actually compiles flat" integration assertions should be marked `docker`/`slow` and verified in CI.

## Notes & risks
- **`expand` uses cwd as package root** — every `build_flat_namespace` call must run with the package directory as cwd (the packagers already run under `@package.within_problem`). Unit tests for `build_flat_namespace` need a package fixture (`pkg_from_testdata`/`cleandir_with_testdata`); the pure `assign_flat_names` tests do not.
- **Manual `compilationFiles` not reachable via includes** are shipped (bytes) and scanned for their own quoted includes, but if they are non-C++ resources with no includes they are simply copied — correct.
- **`href()`/generator accessors**: confirm `CodeItem.href()`, `package.get_generator`/`get_generator_or_nil`, and `package.get_solutions`/`get_validator` signatures against the source while implementing; the plan's names match current usage but verify before relying on them.
- **MOJ** shares BOCA templates; ensure the `{{embedded_files}}` template change doesn't break MOJ's other script paths (MOJ writes `scripts/` rather than `compile/{lang}` — confirm which template files it consumes).
