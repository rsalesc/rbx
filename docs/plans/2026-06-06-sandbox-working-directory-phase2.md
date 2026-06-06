# Sandbox Mirroring Phase 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `executionFiles` + default-on transitive auto-expansion of quoted
`#include`/relative imports, via a per-language dependency scanner + generic graph
engine, with a `rewrite` primitive baked for #525.

**Architecture:** New `rbx/box/dependencies/` package (mirrors `linters/`). A tiny
per-language `DependencyScanner` (C++ via tree-sitter-cpp, Python via `ast`) exposes
`references(file)` (resolved direct deps) and `rewrite(text, rename)` (C++ only). A
generic `expand(code) -> DependencyGraph` does the cycle-safe transitive walk and
exposes `files()` (by kind) and per-file edges. Compilation unions C++ deps into
compile inputs; execution unions Python deps + manual `executionFiles` into run inputs.

**Tech Stack:** Python 3.12, Pydantic v2, tree-sitter-cpp (already a dep), `ast`,
pytest (`uv run pytest`), ruff.

**Design doc:** `docs/plans/2026-06-06-sandbox-working-directory-phase2-design.md`

---

## Conventions for the executing engineer

- Single quotes; absolute imports only; run `uv run ruff format .` and
  `uv run ruff check --fix .` before each commit.
- Conventional Commits (commitizen). Append trailer
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Tests live under `tests/rbx/box/`. Reuse `testing_pkg` fixture (cwd = package root).
  `testing_pkg.add_file(path, src=None)` creates the file (empty unless `src` copies
  from `testdata/`); write content with `.write_text(...)`.
- `TestCompileItem` in `code_compile_test.py` has autouse `mock_steps_with_caching`
  (inspect `call_args[0][0]` = commands, `call_args.kwargs['artifacts']`).
- Real-compile/run integration tests go in `code_dependencies_integration_test.py`
  (no mock fixtures). Pre-existing C++/sandbox/docker failures on this machine are
  environmental — only new include/import-resolution failures are ours.

---

## Task 1: Scanner ABC + registry

**Files:**
- Create: `rbx/box/dependencies/__init__.py`
- Create: `rbx/box/dependencies/scanner.py`
- Test: `tests/rbx/box/dependencies_test.py`

**Step 1: Failing test** (`tests/rbx/box/dependencies_test.py`)
```python
import pathlib
from typing import List

from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, DependencyScanner, Reference


class _Dummy(DependencyScanner):
    kinds = {DependencyKind.COMPILATION}

    def handles(self, language: str) -> bool:
        return language == 'dummy'

    def references(self, file: pathlib.Path) -> List[Reference]:
        return []


def test_register_and_get_scanner():
    scanner.register(_Dummy)
    assert isinstance(scanner.get_scanner('dummy'), _Dummy)
    assert scanner.get_scanner('nope') is None


def test_rewrite_unsupported_by_default():
    import pytest

    with pytest.raises(NotImplementedError):
        _Dummy().rewrite('x', lambda s: None)
```

**Step 2:** `uv run pytest tests/rbx/box/dependencies_test.py -v` → FAIL (no module).

**Step 3: Implement** `rbx/box/dependencies/scanner.py`
```python
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
    spelling: str
    target: Optional[pathlib.Path] = None


class DependencyScanner(abc.ABC):
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
```
Create empty `rbx/box/dependencies/__init__.py` (Task 5 fills it).

**Step 4:** rerun → PASS. **Step 5:** commit `feat(dependencies): add scanner ABC + registry (#524)`.

---

## Task 2: C++ scanner — `references()` (tree-sitter-cpp)

**Files:**
- Create: `rbx/box/dependencies/cpp.py`
- Test: `tests/rbx/box/dependencies_test.py` (class `TestCppReferences`)

**Step 1: Failing tests**
```python
class TestCppReferences:
    def test_quoted_and_angle_and_builtin(self, testing_pkg):
        from rbx.box.dependencies import cpp

        testing_pkg.add_file('lib.h').write_text('#pragma once\n')
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include "../lib.h"\n'
            '#include <cstdio>\n'
            '#include "testlib.h"\n'
            'int main(){}\n'
        )
        refs = cpp.CppScanner().references(pathlib.Path('gens/gen.cpp'))
        by_spelling = {r.spelling: r.target for r in refs}
        # angle includes are not reported at all
        assert '../lib.h' in by_spelling
        assert by_spelling['../lib.h'] == pathlib.Path('lib.h')
        # builtin testlib.h is quoted but not a package file -> target None
        assert by_spelling['testlib.h'] is None
        assert 'cstdio' not in by_spelling

    def test_ignores_commented_include(self, testing_pkg):
        from rbx.box.dependencies import cpp

        testing_pkg.add_file('lib.h').write_text('#pragma once\n')
        src = testing_pkg.add_file('a.cpp')
        src.write_text('/* #include "lib.h" */\nint main(){}\n')
        refs = cpp.CppScanner().references(pathlib.Path('a.cpp'))
        assert refs == []
```

**Step 2:** run → FAIL (no `cpp` module).

**Step 3: Implement** `rbx/box/dependencies/cpp.py`
```python
import pathlib
from typing import Callable, Iterator, List, Optional

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from rbx import utils
from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, Reference

_LANGUAGE = Language(tree_sitter_cpp.language())


def _parser() -> Parser:
    return Parser(_LANGUAGE)


def _quoted_include_nodes(root: Node) -> Iterator[Node]:
    """Yield the string_literal path node of each quoted #include (skips <...>)."""
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == 'preproc_include':
            for child in node.children:
                if child.type == 'string_literal':
                    yield child
                    break
                if child.type == 'system_lib_string':
                    break
        stack.extend(node.children)


def _spelling(path_node: Node) -> str:
    text = path_node.text.decode('utf-8')
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def _resolve(including_file: pathlib.Path, spelling: str) -> Optional[pathlib.Path]:
    package_root = utils.abspath(pathlib.Path())
    candidate = utils.abspath(including_file.parent / spelling)
    if not candidate.is_file() or not candidate.is_relative_to(package_root):
        return None
    return candidate.relative_to(package_root)


@scanner.register
class CppScanner(scanner.DependencyScanner):
    kinds = {DependencyKind.COMPILATION}
    can_rewrite = True

    def handles(self, language: str) -> bool:
        return language in ('cpp', 'c')

    def references(self, file: pathlib.Path) -> List[Reference]:
        tree = _parser().parse(pathlib.Path(file).read_bytes())
        refs: List[Reference] = []
        for path_node in _quoted_include_nodes(tree.root_node):
            spelling = _spelling(path_node)
            refs.append(Reference(spelling=spelling, target=_resolve(file, spelling)))
        return refs

    def rewrite(self, text: str, rename: Callable[[str], Optional[str]]) -> str:
        tree = _parser().parse(text.encode('utf-8'))
        edits = []  # (start_byte, end_byte, replacement_text)
        for path_node in _quoted_include_nodes(tree.root_node):
            new = rename(_spelling(path_node))
            if new is not None:
                edits.append((path_node.start_byte, path_node.end_byte, f'"{new}"'))
        if not edits:
            return text
        data = bytearray(text.encode('utf-8'))
        for start, end, repl in sorted(edits, reverse=True):
            data[start:end] = repl.encode('utf-8')
        return data.decode('utf-8')
```

**Step 4:** run → PASS. **Step 5:** commit `feat(dependencies): C++ include scanner via tree-sitter (#524)`.

---

## Task 3: C++ `rewrite()` tests

**Files:** Test: `tests/rbx/box/dependencies_test.py` (class `TestCppRewrite`)

**Step 1: Tests**
```python
class TestCppRewrite:
    def test_rewrites_mapped_leaves_others(self):
        from rbx.box.dependencies import cpp

        text = (
            '#include "../lib.h"\n'
            '#include <cstdio>\n'
            '#include "keep.h"\n'
        )
        mapping = {'../lib.h': 'lib__x.h'}
        out = cpp.CppScanner().rewrite(text, mapping.get)
        assert '#include "lib__x.h"' in out
        assert '#include <cstdio>' in out      # angle untouched
        assert '#include "keep.h"' in out      # unmapped untouched

    def test_preserves_commented_include(self):
        from rbx.box.dependencies import cpp

        text = '/* #include "lib.h" */\n#include "lib.h"\n'
        out = cpp.CppScanner().rewrite(text, {'lib.h': 'flat.h'}.get)
        assert '/* #include "lib.h" */' in out   # comment untouched
        assert '#include "flat.h"' in out        # real directive rewritten
```

**Step 2:** run → PASS (rewrite implemented in Task 2). If FAIL, fix Task 2.
**Step 3:** commit `test(dependencies): C++ rewrite round-trip (#524)`.

---

## Task 4: Python scanner — `references()` (`ast`)

**Files:**
- Create: `rbx/box/dependencies/python.py`
- Test: `tests/rbx/box/dependencies_test.py` (class `TestPythonReferences`)

**Step 1: Tests**
```python
class TestPythonReferences:
    def test_relative_sibling_and_stdlib(self, testing_pkg):
        from rbx.box.dependencies import python

        testing_pkg.add_file('sols/helper.py').write_text('X = 1\n')
        main = testing_pkg.add_file('sols/main.py')
        main.write_text(
            'import os\n'
            'from . import helper\n'
            'import helper as h2\n'
            'print(helper.X, h2.X, os.getpid())\n'
        )
        refs = python.PythonScanner().references(pathlib.Path('sols/main.py'))
        targets = {r.target for r in refs if r.target is not None}
        assert pathlib.Path('sols/helper.py') in targets
        # stdlib os never resolves to a package file
        assert all(r.target != pathlib.Path('os.py') for r in refs)

    def test_parent_package_import(self, testing_pkg):
        from rbx.box.dependencies import python

        testing_pkg.add_file('common/util.py').write_text('Y = 2\n')
        src = testing_pkg.add_file('sols/sub/main.py')
        src.write_text('from ...common import util\n')
        refs = python.PythonScanner().references(pathlib.Path('sols/sub/main.py'))
        assert any(r.target == pathlib.Path('common/util.py') for r in refs)
```
> Note `from ...common import util` from `sols/sub/main.py`: level 3 → anchor ascends
> 2 from `sols/sub` → repo root, then `common/util.py`.

**Step 2:** run → FAIL.

**Step 3: Implement** `rbx/box/dependencies/python.py`
```python
import ast
import pathlib
from typing import List, Optional

from rbx import utils
from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, Reference


def _resolve_dotted(base: pathlib.Path, dotted: str) -> Optional[pathlib.Path]:
    parts = [p for p in dotted.split('.') if p]
    if not parts:
        return None
    package_root = utils.abspath(pathlib.Path())
    for candidate in (
        base.joinpath(*parts).with_suffix('.py'),
        base.joinpath(*parts, '__init__.py'),
    ):
        cand = utils.abspath(candidate)
        if cand.is_file() and cand.is_relative_to(package_root):
            return cand.relative_to(package_root)
    return None


@scanner.register
class PythonScanner(scanner.DependencyScanner):
    kinds = {DependencyKind.EXECUTION}
    can_rewrite = False

    def handles(self, language: str) -> bool:
        return language == 'py'

    def references(self, file: pathlib.Path) -> List[Reference]:
        file = pathlib.Path(file)
        try:
            tree = ast.parse(file.read_text())
        except SyntaxError:
            return []
        base_dir = file.parent
        refs: List[Reference] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # absolute imports: resolve as sibling under the importing file's dir
                for alias in node.names:
                    refs.append(
                        Reference(alias.name, _resolve_dotted(base_dir, alias.name))
                    )
            elif isinstance(node, ast.ImportFrom):
                anchor = base_dir
                for _ in range(max(node.level - 1, 0)):
                    anchor = anchor.parent
                dots = '.' * node.level
                if node.module:
                    refs.append(
                        Reference(
                            f'{dots}{node.module}',
                            _resolve_dotted(anchor, node.module),
                        )
                    )
                elif node.level > 0:
                    # from . import a, b  -> each name is a sibling submodule
                    for alias in node.names:
                        refs.append(
                            Reference(
                                f'{dots}{alias.name}',
                                _resolve_dotted(anchor, alias.name),
                            )
                        )
        return refs
```

**Step 4:** run → PASS. **Step 5:** commit `feat(dependencies): Python relative/sibling import scanner (#524)`.

---

## Task 5: Engine — `expand()` + `DependencyGraph` + self-registration

**Files:**
- Create: `rbx/box/dependencies/graph.py`
- Modify: `rbx/box/dependencies/__init__.py`
- Test: `tests/rbx/box/dependencies_test.py` (class `TestExpand`)

**Step 1: Tests**
```python
class TestExpand:
    def test_cpp_transitive_excludes_root(self, testing_pkg):
        from rbx.box.dependencies import graph
        from rbx.box.dependencies.scanner import DependencyKind
        from rbx.box.schema import CodeItem

        testing_pkg.add_file('lib.h').write_text('#include "extra.h"\n')
        testing_pkg.add_file('extra.h').write_text('#pragma once\n')
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text('#include "../lib.h"\nint main(){}\n')

        g = graph.expand(CodeItem(path=gen, language='cpp'))
        assert g is not None
        assert g.kinds == {DependencyKind.COMPILATION}
        assert g.files() == [pathlib.Path('extra.h'), pathlib.Path('lib.h')]

    def test_cycle_safe(self, testing_pkg):
        from rbx.box.dependencies import graph
        from rbx.box.schema import CodeItem

        testing_pkg.add_file('a.h').write_text('#include "b.h"\n')
        testing_pkg.add_file('b.h').write_text('#include "a.h"\n')
        src = testing_pkg.add_file('m.cpp')
        src.write_text('#include "a.h"\nint main(){}\n')
        g = graph.expand(CodeItem(path=src, language='cpp'))
        assert set(g.files()) == {pathlib.Path('a.h'), pathlib.Path('b.h')}

    def test_none_for_unhandled_language(self, testing_pkg):
        from rbx.box.dependencies import graph
        from rbx.box.schema import CodeItem

        j = testing_pkg.add_file('Main.java')
        j.write_text('class Main {}\n')
        assert graph.expand(CodeItem(path=j, language='java')) is None
```

**Step 2:** run → FAIL.

**Step 3: Implement** `rbx/box/dependencies/graph.py`
```python
import collections
import dataclasses
import pathlib
from typing import Dict, List, Optional, Set

from rbx import utils
from rbx.box import package
from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, Reference
from rbx.box.schema import CodeItem


@dataclasses.dataclass
class DependencyGraph:
    root: pathlib.Path
    nodes: Dict[pathlib.Path, List[Reference]]
    kinds: Set[DependencyKind]

    def files(self) -> List[pathlib.Path]:
        return sorted(p for p in self.nodes if p != self.root)


def expand(code: CodeItem) -> Optional[DependencyGraph]:
    from rbx.box.code import find_language_name

    instance = scanner.get_scanner(find_language_name(code))
    if instance is None:
        return None
    package_root = utils.abspath(pathlib.Path())
    abs_path = utils.abspath(code.path)
    if not abs_path.is_relative_to(package_root):
        return None  # remote/temporary files stay flat
    root = abs_path.relative_to(package_root)

    nodes: Dict[pathlib.Path, List[Reference]] = {}
    queue = collections.deque([root])
    while queue:
        current = queue.popleft()
        if current in nodes:
            continue
        refs = instance.references(current)
        nodes[current] = refs
        for ref in refs:
            if ref.target is not None and ref.target not in nodes:
                queue.append(ref.target)
    return DependencyGraph(root=root, nodes=nodes, kinds=set(instance.kinds))
```
> `find_language_name` is lazy-imported to avoid a `code` ↔ `dependencies` cycle.

Set `rbx/box/dependencies/__init__.py` to self-register the scanners:
```python
from rbx.box.dependencies import cpp, python  # noqa: F401  (self-register scanners)
```

**Step 4:** run → PASS. **Step 5:** commit `feat(dependencies): transitive expand() + DependencyGraph (#524)`.

---

## Task 6: `CodeItem.executionFiles` + `get_execution_files`

**Files:**
- Modify: `rbx/box/schema.py` (CodeItem, CodeItemWithDigest.create, OutputFromItemWithDigest.create)
- Modify: `rbx/box/package.py` (refactor `get_compilation_files`; add `get_execution_files`)
- Test: `tests/rbx/box/code_compile_test.py` (class `TestExecutionFiles`)

**Step 1: Tests** (add to `code_compile_test.py`)
```python
class TestExecutionFiles:
    def test_dest_is_package_relative(self, testing_pkg):
        testing_pkg.add_file('data.txt')
        sol = testing_pkg.add_file('sols/main.py')
        item = CodeItem(path=sol, language='py', executionFiles=['data.txt'])
        assert package.get_execution_files(item) == [
            (pathlib.Path('data.txt'), pathlib.Path('data.txt'))
        ]

    def test_rejects_missing(self, testing_pkg):
        sol = testing_pkg.add_file('m.py')
        item = CodeItem(path=sol, language='py', executionFiles=['nope.txt'])
        with pytest.raises(typer.Exit):
            package.get_execution_files(item)

    def test_with_digest_propagates_execution_files(self, testing_pkg):
        from rbx.box.schema import CodeItemWithDigest

        sol = testing_pkg.add_file('m.py')
        item = CodeItem(path=sol, language='py', executionFiles=['m.py'])
        wd = CodeItemWithDigest.create(item, 'deadbeef')
        assert wd.executionFiles == ['m.py']
```

**Step 2:** run → FAIL (`executionFiles` not a field / no `get_execution_files`).

**Step 3: Implement**
In `schema.py`, add to `CodeItem` after `compilationFiles`:
```python
    executionFiles: Optional[List[str]] = Field(
        default=[],
        description="""
Extra files that should be available at *execution* time, given relative to the
package directory and placed at the same package-relative path inside the sandbox
(the package directory structure is mirrored). Use for runtime companion files
(data files, sibling modules) a compiled binary or script needs at run time.
""",
    )
```
Add `executionFiles=code_item.executionFiles` to `CodeItemWithDigest.create` and
`executionFiles=output_from_item.executionFiles` to `OutputFromItemWithDigest.create`.

In `package.py`, refactor to share the body:
```python
def _get_declared_files(
    code: CodeItem, declared: Optional[List[str]], label: str
) -> List[Tuple[pathlib.Path, pathlib.Path]]:
    package_root = utils.abspath(pathlib.Path())
    res = []
    for entry in declared or []:
        entry_path = utils.abspath(pathlib.Path(entry))
        if not entry_path.is_file():
            console.console.print(
                f'[error]{label} [item]{entry}[/item] for code {code.href()} '
                f'does not exist.[/error]',
            )
            raise typer.Exit(1)
        if not entry_path.is_relative_to(package_root):
            console.console.print(
                f'[error]{label} [item]{entry}[/item] for code {code.href()} '
                f'is not under the package directory.[/error]',
            )
            raise typer.Exit(1)
        rel = entry_path.relative_to(package_root)
        res.append((rel, rel))
    return res


def get_compilation_files(code: CodeItem) -> List[Tuple[pathlib.Path, pathlib.Path]]:
    return _get_declared_files(code, code.compilationFiles, 'Compilation file')


def get_execution_files(code: CodeItem) -> List[Tuple[pathlib.Path, pathlib.Path]]:
    return _get_declared_files(code, code.executionFiles, 'Execution file')
```

**Step 4:** run → PASS (and existing `TestCompilationFiles` still green).
**Step 5:** commit `feat(schema): add executionFiles to CodeItem (#524)`.

---

## Task 7: Wire auto-expansion into compilation

**Files:**
- Modify: `rbx/box/code.py:compile_item` (after `get_compilation_files` extend, ~line 629)
- Test: `tests/rbx/box/code_compile_test.py` (`TestCompileItem`)

**Step 1: Test**
```python
    async def test_auto_expands_quoted_include(
        self, testing_pkg, mock_steps_with_caching
    ):
        testing_pkg.add_file('lib.h').write_text('#pragma once\n')
        gen = testing_pkg.add_file('gens/gen.cpp', src='compile_test/simple.cpp')
        # Overwrite with a parent-dir include and NO manual compilationFiles.
        gen.write_text('#include "../lib.h"\nint main(){}\n')
        await code.compile_item(CodeItem(path=gen, language='cpp'))

        artifacts = mock_steps_with_caching.call_args.kwargs['artifacts']
        dests = {i.dest for i in artifacts.inputs}
        assert pathlib.Path('lib.h') in dests
```

**Step 2:** run → FAIL (`lib.h` not auto-added).

**Step 3: Implement** — in `compile_item`, immediately after the
`artifacts.inputs.extend(... get_compilation_files ...)` block:
```python
        # Auto-expand transitive quoted #include "..." dependencies (default-on,
        # additive). Manual compilationFiles remain the escape hatch.
        from rbx.box.dependencies import graph as deps_graph
        from rbx.box.dependencies.scanner import DependencyKind

        dep_graph = deps_graph.expand(code)
        if dep_graph is not None and DependencyKind.COMPILATION in dep_graph.kinds:
            existing = {i.dest for i in artifacts.inputs}
            for dep in dep_graph.files():
                if dep not in existing:
                    artifacts.inputs.append(GradingFileInput(src=dep, dest=dep))
                    existing.add(dep)
```

**Step 4:** run → PASS; rerun full `TestCompileItem` (regressions).
**Step 5:** commit `feat(code): auto-expand quoted includes at compile time (#524)`.

---

## Task 8: Wire execution files into `_prepare_run`

**Files:**
- Modify: `rbx/box/code.py:_prepare_run` (after the `if inputs:` extension, ~line 418)
- Test: `tests/rbx/box/code_run_test.py` or new `code_prepare_run_test.py`

**Step 1: Test** — call `_prepare_run` directly and inspect `artifacts.inputs`.
```python
import pathlib

from rbx.box import code
from rbx.box.grading_utils import ...  # see code_run_test.py for DigestOrSource helper
from rbx.box.schema import CodeItem
from rbx.grading.steps import DigestHolder
from rbx.grading.steps_utils import DigestOrSource  # adapt import to actual location


class TestPrepareRunExecutionFiles:
    async def test_python_sibling_module_mirrored(self, testing_pkg):
        testing_pkg.add_file('sols/helper.py').write_text('X = 1\n')
        main = testing_pkg.add_file('sols/main.py')
        main.write_text('from . import helper\nprint(helper.X)\n')
        executable = DigestOrSource.create(DigestHolder(value='deadbeef'))
        prepared = await code._prepare_run(
            CodeItem(path=main, language='py'), executable
        )
        dests = {i.dest for i in prepared.artifacts.inputs}
        assert pathlib.Path('sols/helper.py') in dests

    async def test_manual_execution_file_mirrored(self, testing_pkg):
        testing_pkg.add_file('data.txt')
        main = testing_pkg.add_file('m.py')
        main.write_text('print(1)\n')
        executable = DigestOrSource.create(DigestHolder(value='deadbeef'))
        prepared = await code._prepare_run(
            CodeItem(path=main, language='py', executionFiles=['data.txt']),
            executable,
        )
        dests = {i.dest for i in prepared.artifacts.inputs}
        assert pathlib.Path('data.txt') in dests
```
> Confirm the exact `DigestOrSource` import/constructor from `code_run_test.py` before
> writing; adapt the two `executable = ...` lines accordingly.

**Step 2:** run → FAIL.

**Step 3: Implement** — in `_prepare_run`, after the `if inputs:`/`if outputs:` block
and before `return PreparedRun(...)`:
```python
    # Manual + auto-discovered execution files, mirrored at their package-relative
    # path. C++ contributes none here (its deps are compile-time); Python siblings
    # land via auto-expansion.
    from rbx.box.dependencies import graph as deps_graph
    from rbx.box.dependencies.scanner import DependencyKind

    exec_dests = {i.dest for i in artifacts.inputs}
    for src, dest in package.get_execution_files(code):
        if dest not in exec_dests:
            artifacts.inputs.append(GradingFileInput(src=src, dest=dest))
            exec_dests.add(dest)
    dep_graph = deps_graph.expand(code)
    if dep_graph is not None and DependencyKind.EXECUTION in dep_graph.kinds:
        for dep in dep_graph.files():
            if dep not in exec_dests:
                artifacts.inputs.append(GradingFileInput(src=dep, dest=dep))
                exec_dests.add(dep)
```

**Step 4:** run → PASS. **Step 5:** commit `feat(code): mirror execution files at run time (#524)`.

---

## Task 9: Real-compile / real-run integration

**Files:** Create `tests/rbx/box/code_dependencies_integration_test.py`

**Step 0:** baseline `uv run pytest tests/rbx/box/checkers_test.py -x -q` (env sanity).

**Step 1: Tests**
```python
import pathlib

from rbx.box import code
from rbx.box.schema import CodeItem


class TestAutoExpansionIntegration:
    async def test_subdir_cpp_autodiscovers_parent_include(self, testing_pkg):
        testing_pkg.add_file('lib.h').write_text(
            '#pragma once\ninline int answer(){ return 42; }\n'
        )
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include "../lib.h"\n#include <cstdio>\n'
            'int main(){ printf("%d\\n", answer()); }\n'
        )
        # No manual compilationFiles — must be auto-discovered.
        assert await code.compile_item(CodeItem(path=gen, language='cpp'))
```
Plus a Python end-to-end run test (subdir source importing a sibling), modeled on the
run helpers in `code_run_test.py` (compile_item → run_item with stdin/stdout; assert
the sibling's value reaches stdout), and a flat-package regression.

**Step 2:** run → PASS (modulo pre-existing environmental failures — verify any failure
is NOT an include/import-resolution error).
**Step 3:** commit `test(dependencies): integration for auto-expansion (#524)`.

---

## Task 10: Audit, full suite, lint, review

**Step 1: Audit** the new imports don't create cycles:
`uv run python -c "import rbx.box.code, rbx.box.dependencies.graph, rbx.box.package"`.
**Step 2:** focused suites:
```bash
uv run pytest tests/rbx/box/dependencies_test.py tests/rbx/box/code_compile_test.py -v
uv run pytest tests/rbx/box/code_dependencies_integration_test.py -v
uv run pytest tests/rbx/box/code_run_test.py -q
```
**Step 3:** `uv run ruff check . && uv run ruff format --check .` → clean.
**Step 4 (optional):** `uv run pytest --ignore=tests/rbx/box/cli -n auto -q`; triage only
new failures (pre-existing env failures per memory).
**Step 5:** Use superpowers:requesting-code-review against the design doc + this plan.
**Step 6:** final commit if the audit changed anything.

---

## Definition of done

- [ ] `rbx/box/dependencies/` (scanner/graph/cpp/python, registry, self-registration).
- [ ] `CodeItem.executionFiles` + `package.get_execution_files`; propagated in factories.
- [ ] C++ compilation auto-expands transitive quoted includes (additive).
- [ ] Execution mirrors manual + auto-discovered files via `_prepare_run`.
- [ ] C++ `rewrite` implemented + tested; Python `rewrite` raises (can_rewrite=False).
- [ ] Unit + integration green (modulo env failures); lint clean; conventional commits.
- [ ] No `packaging/` changes (that is #525).
```
