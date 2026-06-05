# Sandbox Working Directory Mirroring — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Mirror the package directory structure inside the sandbox so a program at
`gens/gen.cpp` can `#include "../lib.h"` (a header at the package root), while
leaving flat packages byte-for-byte identical.

**Architecture:** The whole mirroring effect is driven by one variable. Today
`_get_code_variables` sets `source = code.path.name` (basename), which flows through
`file_mapping.compilable` into the compile command and (for Python) the run command.
Changing `source` to the **package-relative path** mirrors C/C++/Python sources
(Java/Kotlin use `{javaClass}`/`Main.kt`, so they stay at the root, untouched). We
also (a) repurpose `compilationFiles` to land files at their package-relative path
and lift the "must be under the code's folder" restriction, and (b) place
auto-injected builtin headers (testlib/jngen/tgen/rbx) in the **source's own
directory** so quoted `#include "testlib.h"` keeps resolving with no `-I.`.
Precompiled headers (`.gch`) then land beside the header automatically. The sandbox
already creates nested dirs (`create_file`/`create_symlink` call `mkdir(parents=True)`),
so no sandbox-layer change is needed.

**Tech Stack:** Python 3.12, Pydantic v2, Typer, pytest (`uv run pytest`), ruff.

**Design doc:** `docs/plans/2026-06-05-sandbox-working-directory-design.md`

**Scope:** Phase 1 only (mirroring + `compilationFiles` repurpose + builtin
placement). `executionFiles` and auto-expansion are Phase 2 (separate plan).

---

## Conventions for the executing engineer

- Single quotes for strings; absolute imports only; run `uv run ruff format .` and
  `uv run ruff check --fix .` before each commit.
- Commits MUST be Conventional Commits (commitizen). Append the trailer
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Wiring/unit tests live in `tests/rbx/box/code_compile_test.py` — that file
  **mocks** `steps_with_caching.compile` and `_precompile_header`, so they run
  locally without invoking g++. Inspect captured calls via
  `mock_steps_with_caching.call_args` (`call_args[0][0]` = commands list;
  `call_args.kwargs['artifacts']` = the `GradingArtifacts`).
- Real-compile integration tests go in a NEW file (`code_compile_integration_test.py`)
  so they do not pick up the mock fixtures.
- Pre-existing failures on this machine: some checker/validator/sandbox/docker tests
  fail regardless of this change. Before trusting a real-compile failure, run an
  existing real-compile test (e.g. `tests/rbx/box/checkers_test.py`) to establish a
  baseline; only a *new* failure mode (e.g. an include-resolution error) is ours.

---

## Background: exact current code

`rbx/box/code.py:219-224`
```python
def _get_code_variables(code: CodeItem, language: str) -> dict[str, Any]:
    res = {'source': code.path.name, 'language': language}
    java_klass = _get_java_class_name(code.path)
    if java_klass is not None:
        res['javaClass'] = java_klass
    return res
```

`rbx/box/package.py:541-566`
```python
def get_compilation_files(code: CodeItem) -> List[Tuple[pathlib.Path, pathlib.Path]]:
    code_dir = utils.abspath(code.path.parent)

    res = []
    for compilation_file in code.compilationFiles or []:
        compilation_file_path = utils.abspath(pathlib.Path(compilation_file))
        if not compilation_file_path.is_file():
            console.console.print(...does not exist...)
            raise typer.Exit(1)
        if not compilation_file_path.is_relative_to(code_dir):
            console.console.print(...not under the code's folder...)
            raise typer.Exit(1)
        res.append((
            pathlib.Path(compilation_file),
            compilation_file_path.relative_to(code_dir),
        ))
    return res
```

`rbx/box/download.py:47-53` (the four `maybe_add_*` are identical in shape)
```python
def maybe_add_testlib(code: CodeItem, artifacts: steps.GradingArtifacts):
    artifact = get_local_artifact('testlib.h') or steps.testlib_grading_input()
    compilation_files = package.get_compilation_files(code)
    if any(dest == artifact.dest for _, dest in compilation_files):
        return
    artifacts.inputs.append(artifact)
```

`rbx/utils.py:215-222` (the relativizer we will reuse)
```python
def relcwd(path: pathlib.Path) -> pathlib.Path:
    cwd = abspath(pathlib.Path())
    path = abspath(path)
    if not path.is_relative_to(cwd):
        raise ValueError(f'relcwd: {path} is not relative to {cwd}')
    return path.relative_to(cwd)
```

---

## Task 1: Package-relative source resolver

A single helper that maps `code.path` to the package-relative path used for mirroring,
falling back to the bare basename for paths outside the package root (remote/temp
files) — preserving today's flat placement for those.

**Files:**
- Modify: `rbx/box/package.py` (add function near `get_compilation_files`, ~line 538)
- Test: `tests/rbx/box/code_compile_test.py` (new class `TestRelativeSourcePath`)

**Step 1: Write the failing tests**

Add to `tests/rbx/box/code_compile_test.py`:
```python
class TestRelativeSourcePath:
    def test_nested_source_is_package_relative(
        self, testing_pkg: testing_package.TestingPackage
    ):
        gen = testing_pkg.add_file('gens/gen.cpp')
        assert package.get_relative_source_path(
            CodeItem(path=gen)
        ) == pathlib.Path('gens/gen.cpp')

    def test_flat_source_is_basename(
        self, testing_pkg: testing_package.TestingPackage
    ):
        sol = testing_pkg.add_file('solution.cpp')
        assert package.get_relative_source_path(
            CodeItem(path=sol)
        ) == pathlib.Path('solution.cpp')

    def test_external_source_falls_back_to_basename(
        self, testing_pkg: testing_package.TestingPackage, tmp_path: pathlib.Path
    ):
        # A path outside the package root keeps the legacy flat basename.
        external = tmp_path / 'somewhere' / 'remote.cpp'
        assert package.get_relative_source_path(
            CodeItem(path=external)
        ) == pathlib.Path('remote.cpp')
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestRelativeSourcePath -v`
Expected: FAIL — `AttributeError: module 'rbx.box.package' has no attribute 'get_relative_source_path'`.

**Step 3: Implement**

In `rbx/box/package.py`, just above `get_compilation_files` (line 539), add:
```python
def get_relative_source_path(code: CodeItem) -> pathlib.Path:
    """Package-relative path where ``code.path`` is mirrored inside the sandbox.

    Falls back to the bare basename for paths outside the package root (e.g.
    remote/temporary files), which preserves the legacy flat placement.
    """
    try:
        return utils.relcwd(code.path)
    except ValueError:
        return pathlib.Path(code.path.name)
```
(`utils` and `CodeItem` are already imported in `package.py`.)

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestRelativeSourcePath -v`
Expected: PASS (3 passed).

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/package.py tests/rbx/box/code_compile_test.py
git commit -m "$(cat <<'EOF'
feat(package): add package-relative source path resolver (#522)

Maps a CodeItem's path to its package-relative form for sandbox
mirroring, with a basename fallback for paths outside the package
root (remote/temporary files) to preserve legacy flat placement.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Mirror the source via `_get_code_variables`

Drive the compilable's sandbox location off the package-relative path.

**Files:**
- Modify: `rbx/box/code.py:219-224`
- Test: `tests/rbx/box/code_compile_test.py` (add to `TestCompileItem`)

**Step 1: Write the failing tests**

Add to `class TestCompileItem`:
```python
    async def test_compile_nested_source_mirrors_path(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        gen = testing_pkg.add_file('gens/gen.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=gen, language='cpp'))

        call_args = mock_steps_with_caching.call_args
        commands = call_args[0][0]
        artifacts = call_args.kwargs['artifacts']

        # Compile command references the mirrored, package-relative source.
        assert commands[0].split()[-1] == 'gens/gen.cpp'
        # The compilable artifact is placed at its package-relative path.
        compilable = next(
            (i for i in artifacts.inputs if i.dest == pathlib.Path('gens/gen.cpp')),
            None,
        )
        assert compilable is not None

    async def test_compile_flat_source_unchanged(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        sol = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=sol, language='cpp'))

        commands = mock_steps_with_caching.call_args[0][0]
        # Flat package: package-relative path == basename, so command is unchanged.
        assert commands[0].split()[-1] == 'solution.cpp'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestCompileItem::test_compile_nested_source_mirrors_path -v`
Expected: FAIL — last command token is `gen.cpp` (basename), not `gens/gen.cpp`.

**Step 3: Implement**

Change `rbx/box/code.py:220`:
```python
def _get_code_variables(code: CodeItem, language: str) -> dict[str, Any]:
    res = {'source': package.get_relative_source_path(code).as_posix(), 'language': language}
    java_klass = _get_java_class_name(code.path)
    if java_klass is not None:
        res['javaClass'] = java_klass
    return res
```
(`package` is already imported in `code.py`.)

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestCompileItem -v`
Expected: PASS — both new tests and all existing `TestCompileItem` tests (the
flat-package command/dest tests still assert basenames, which equal the relative
paths at the root).

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/code.py tests/rbx/box/code_compile_test.py
git commit -m "$(cat <<'EOF'
feat(code): mirror source to its package-relative path in sandbox (#522)

Drive the compilable's sandbox location off the package-relative
path so a source in gens/ is compiled as gens/gen.cpp. Flat
packages are unchanged (relative path equals basename at root);
Java/Kotlin are unaffected (they map via javaClass/Main.kt).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Repurpose `compilationFiles` (package-relative dest, lift restriction)

**Files:**
- Modify: `rbx/box/package.py:541-566`
- Test: `tests/rbx/box/code_compile_test.py` (new class `TestCompilationFiles`)

**Step 1: Write the failing tests**

```python
class TestCompilationFiles:
    def test_dest_is_package_relative(
        self, testing_pkg: testing_package.TestingPackage
    ):
        testing_pkg.add_file('lib.h')
        gen = testing_pkg.add_file('gens/gen.cpp')
        code_item = CodeItem(
            path=gen, language='cpp', compilationFiles=['lib.h']
        )
        assert package.get_compilation_files(code_item) == [
            (pathlib.Path('lib.h'), pathlib.Path('lib.h'))
        ]

    def test_accepts_file_outside_code_dir(
        self, testing_pkg: testing_package.TestingPackage
    ):
        # lib.h at root, source in gens/: rejected before, allowed now.
        testing_pkg.add_file('lib.h')
        gen = testing_pkg.add_file('gens/gen.cpp')
        code_item = CodeItem(
            path=gen, language='cpp', compilationFiles=['lib.h']
        )
        # Must not raise.
        package.get_compilation_files(code_item)

    def test_rejects_missing_file(
        self, testing_pkg: testing_package.TestingPackage
    ):
        gen = testing_pkg.add_file('gen.cpp')
        code_item = CodeItem(
            path=gen, language='cpp', compilationFiles=['nope.h']
        )
        with pytest.raises(typer.Exit):
            package.get_compilation_files(code_item)

    def test_rejects_file_outside_package(
        self, testing_pkg: testing_package.TestingPackage, tmp_path: pathlib.Path
    ):
        outside = tmp_path / 'outside.h'
        outside.write_text('')
        gen = testing_pkg.add_file('gen.cpp')
        code_item = CodeItem(
            path=gen, language='cpp', compilationFiles=[str(outside)]
        )
        with pytest.raises(typer.Exit):
            package.get_compilation_files(code_item)
```
(`typer` is already imported in this test file.)

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestCompilationFiles -v`
Expected: FAIL — `test_dest_is_package_relative` returns
`(lib.h, ../lib.h)`-style or raises "not under the code's folder";
`test_accepts_file_outside_code_dir` raises `typer.Exit`.

**Step 3: Implement**

Replace `get_compilation_files` body in `rbx/box/package.py`:
```python
def get_compilation_files(code: CodeItem) -> List[Tuple[pathlib.Path, pathlib.Path]]:
    package_root = utils.abspath(pathlib.Path())

    res = []
    for compilation_file in code.compilationFiles or []:
        compilation_file_path = utils.abspath(pathlib.Path(compilation_file))
        if not compilation_file_path.is_file():
            console.console.print(
                f'[error]Compilation file [item]{compilation_file}[/item] for '
                f'code {code.href()} does not exist.[/error]',
            )
            raise typer.Exit(1)
        if not compilation_file_path.is_relative_to(package_root):
            console.console.print(
                f'[error]Compilation file [item]{compilation_file}[/item] for '
                f'code {code.href()} is not under the package directory.[/error]',
            )
            raise typer.Exit(1)

        rel = compilation_file_path.relative_to(package_root)
        res.append((rel, rel))
    return res
```
Note: `src` and `dest` are now the same package-relative path; both resolve correctly
because `cwd` is the package root and `GradingArtifacts.root` defaults to `.`.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestCompilationFiles -v`
Expected: PASS (4 passed).

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/package.py tests/rbx/box/code_compile_test.py
git commit -m "$(cat <<'EOF'
feat(package): place compilation files at package-relative paths (#522)

compilationFiles now land at their package-relative path and may
live anywhere under the package root (the under-code-folder
restriction is lifted), enabling ../lib.h-style includes. Files
under the code dir keep the same source-relative offset, so
existing includes resolve unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Place builtin headers in the source's directory

**Files:**
- Modify: `rbx/box/download.py` (`maybe_add_rbx_header`, `maybe_add_testlib`,
  `maybe_add_jngen`, `maybe_add_tgen` — lines 37-71)
- Test: `tests/rbx/box/code_compile_test.py` (add to `TestCompileItem`)

**Step 1: Write the failing tests**

```python
    async def test_builtin_headers_placed_in_source_dir(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        gen = testing_pkg.add_file('gens/gen.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=gen, language='cpp'))

        artifacts = mock_steps_with_caching.call_args.kwargs['artifacts']
        testlib = next(
            (i for i in artifacts.inputs if i.dest.name == 'testlib.h'), None
        )
        assert testlib is not None
        assert testlib.dest == pathlib.Path('gens/testlib.h')

    async def test_builtin_headers_flat_unchanged(
        self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
    ):
        sol = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=sol, language='cpp'))

        artifacts = mock_steps_with_caching.call_args.kwargs['artifacts']
        testlib = next(
            (i for i in artifacts.inputs if i.dest.name == 'testlib.h'), None
        )
        assert testlib is not None
        assert testlib.dest == pathlib.Path('testlib.h')
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestCompileItem::test_builtin_headers_placed_in_source_dir -v`
Expected: FAIL — testlib dest is `testlib.h` (root), not `gens/testlib.h`.

**Step 3: Implement**

In `rbx/box/download.py`, in each of the four `maybe_add_*` functions, insert one
line right after the `artifact = ...` assignment and before
`compilation_files = package.get_compilation_files(code)`:
```python
    artifact.dest = package.get_relative_source_path(code).parent / artifact.dest
```
For example `maybe_add_testlib` becomes:
```python
def maybe_add_testlib(code: CodeItem, artifacts: steps.GradingArtifacts):
    # Try to get from compilation files, then from package folder, then from tool.
    artifact = get_local_artifact('testlib.h') or steps.testlib_grading_input()
    artifact.dest = package.get_relative_source_path(code).parent / artifact.dest
    compilation_files = package.get_compilation_files(code)
    if any(dest == artifact.dest for _, dest in compilation_files):
        return
    artifacts.inputs.append(artifact)
```
Apply the identical one-line insertion to `maybe_add_rbx_header`, `maybe_add_jngen`,
and `maybe_add_tgen`. For a flat source `parent == .`, so the dest collapses to the
root name (`./testlib.h` == `testlib.h`), and the dedup against
`get_compilation_files` (now also package-relative) stays consistent.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestCompileItem -v`
Expected: PASS — new tests pass; existing `test_compile_artifacts_with_testlib` /
`_with_jngen` (which assert on `dest.name`) still pass.

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/download.py tests/rbx/box/code_compile_test.py
git commit -m "$(cat <<'EOF'
feat(download): place builtin headers in the source's directory (#522)

testlib/jngen/tgen/rbx headers are injected beside the source so
quoted includes resolve for mirrored (subdir) sources without -I..
Flat packages are unaffected (the dest collapses to the root).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Verify precompiled headers target the source dir (no logic change expected)

`_precompile_header` sets the produced `.gch` dest to
`input_artifact.dest.with_suffix('.h.gch')` (`code.py:553`). With the builtin header
now at `gens/testlib.h`, the `.gch` lands at `gens/testlib.h.gch` — beside it — for
free. This task adds a guard test. If it fails, fix the precompile path derivation
(do NOT special-case; keep deriving from the header's dest).

**Files:**
- Test: `tests/rbx/box/code_compile_test.py` (add to `TestCompileItem`)

**Step 1: Write the test**

```python
    async def test_precompile_targets_source_dir_header(
        self,
        testing_pkg: testing_package.TestingPackage,
        mock_steps_with_caching,
        mock_precompile_header,
    ):
        gen = testing_pkg.add_file('gens/gen.cpp', src='compile_test/simple.cpp')
        await code.compile_item(CodeItem(path=gen, language='cpp'))

        # _precompile_header is called positionally: (..., artifacts, input, ...)
        # i.e. the candidate header is the 5th positional arg (index 4).
        precompiled_dests = [
            call.args[4].dest for call in mock_precompile_header.call_args_list
        ]
        assert pathlib.Path('gens/testlib.h') in precompiled_dests
```

**Step 2: Run**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestCompileItem::test_precompile_targets_source_dir_header -v`
Expected: PASS (the builtin header dest is already source-dir from Task 4).
If FAIL: confirm the precompile loop (`code.py:662-685`) selects inputs by
`input.dest.name in ['stdc++.h','jngen.h','tgen.h','testlib.h']` and that the
candidate is the source-dir header; adjust only if a real bug surfaces.

**Step 3: Commit**

```bash
git add tests/rbx/box/code_compile_test.py
git commit -m "$(cat <<'EOF'
test(code): assert precompiled header targets the source dir (#522)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Real-compile integration tests

Prove actual include resolution end-to-end with a real toolchain.

**Files:**
- Create: `tests/rbx/box/code_compile_integration_test.py`

**Step 0: Baseline the toolchain**

Run an existing real-compile test to confirm the sandbox/g++ path works on this
machine:
Run: `uv run pytest tests/rbx/box/checkers_test.py -x -q`
If this is already broken (pre-existing, per the conventions note), record that and
treat only *new* failure modes below (e.g. `fatal error: '../lib.h' file not found`)
as ours.

**Step 1: Write the tests**

```python
import pathlib

from rbx.box import code
from rbx.box.schema import CodeItem
from rbx.box.testing import testing_package


class TestSandboxMirroringIntegration:
    async def test_parent_dir_include_compiles(
        self, testing_pkg: testing_package.TestingPackage
    ):
        lib = testing_pkg.add_file('lib.h')
        lib.write_text('#pragma once\ninline int answer() { return 42; }\n')
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include "../lib.h"\n'
            '#include <cstdio>\n'
            'int main() { printf("%d\\n", answer()); return 0; }\n'
        )
        code_item = CodeItem(
            path=gen, language='cpp', compilationFiles=['lib.h']
        )
        digest = await code.compile_item(code_item)
        assert digest

    async def test_subdir_source_finds_testlib(
        self, testing_pkg: testing_package.TestingPackage
    ):
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include "testlib.h"\n'
            'int main(int argc, char* argv[]) {\n'
            '  registerGen(argc, argv, 1);\n'
            '  printf("%d\\n", (int)rnd.next(1, 10));\n'
            '  return 0;\n'
            '}\n'
        )
        digest = await code.compile_item(CodeItem(path=gen, language='cpp'))
        assert digest

    async def test_flat_source_still_compiles(
        self, testing_pkg: testing_package.TestingPackage
    ):
        sol = testing_pkg.add_file('sol.cpp')
        sol.write_text('#include <cstdio>\nint main(){ printf("ok\\n"); }\n')
        digest = await code.compile_item(CodeItem(path=sol, language='cpp'))
        assert digest
```

**Step 2: Run**

Run: `uv run pytest tests/rbx/box/code_compile_integration_test.py -v`
Expected: PASS. If the baseline in Step 0 was broken environmentally, these may
share that failure — in that case confirm via the error message that it is the SAME
environmental failure, not an include-resolution error, and note it for CI.

**Step 3: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add tests/rbx/box/code_compile_integration_test.py
git commit -m "$(cat <<'EOF'
test(code): integration tests for sandbox dir mirroring (#522)

Real-compile coverage: ../lib.h parent-dir include, subdir source
resolving testlib from its own dir, and a flat source regression.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Audit for flat-layout assumptions, full suite, final review

**Files:** none expected (audit + verification); fix any site the audit surfaces.

**Step 1: Audit**

Run and review each hit for code that assumes the flat basename layout (constructs a
sandbox dest from `code.path.name`, or expects the compilable at a fixed flat name):
```bash
grep -rn "\.path\.name" rbx/box | grep -vi test
grep -rn "code\.path\.name\|compilable\b" rbx/box/code.py
```
Pay attention to `_prepare_run` (execution artifact construction) and the Polygon
importer (`rbx/box/packaging/polygon/importer.py:190`, which assigns
`compilationFiles`). For execution: the run path reuses `_get_code_variables` →
`file_mapping`, so C++ binaries stay generic at the root and Python sources mirror
automatically — no change expected, but confirm by reading.

**Step 2: Run the focused suites**

```bash
uv run pytest tests/rbx/box/code_compile_test.py -v
uv run pytest tests/rbx/box/code_compile_integration_test.py -v
uv run pytest tests/rbx/box/code_run_test.py tests/rbx/box/code_java_rename_test.py -q
```
Expected: PASS (modulo any pre-existing environmental failures established in Task 6
Step 0).

**Step 3: Lint**

```bash
uv run ruff check . && uv run ruff format --check .
```
Expected: clean.

**Step 4: Broad regression (optional but recommended)**

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto -q
```
Triage failures: anything failing on `main` before this branch is pre-existing
(see the local-failures memory). Investigate only newly-introduced failures.

**Step 5: Request code review**

Use superpowers:requesting-code-review against the design doc and this plan, then
address findings.

**Step 6: Final commit (if the audit changed anything)**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(box): remove residual flat-layout assumptions (#522)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Definition of done

- [ ] `source` is the package-relative path; nested C/C++/Python sources mirror,
      flat packages are byte-identical, Java/Kotlin untouched.
- [ ] `compilationFiles` land at package-relative paths; `../lib.h` (root header)
      is declarable and resolves; files outside the package root are rejected.
- [ ] Builtin headers sit in the source's directory; flat placement unchanged.
- [ ] Precompiled `.gch` lands beside the header for nested sources.
- [ ] Wiring tests pass locally; integration tests pass with a working toolchain.
- [ ] No remaining flat-layout assumptions in non-test code.
- [ ] Lint clean; conventional commits throughout.

## Out of scope (Phase 2 — separate plan)

`executionFiles` on every `CodeItem`, and default-on, recursive, quoted-only
auto-expansion of `#include "..."` (C++) and relative/sibling imports (Python).
