# tgen Default Include Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Promote tgen to a first-class header in rbx with `rbx download tgen`, auto-include in C++ compilation, Polygon upload, and a new `--into PATH` flag for header downloads. Also fix the bug where `rbx download {jngen,testlib}` silently no-ops when the app cache exists.

**Architecture:** Three layers. (1) `rbx/config.py` grows a `download_<header>()` always-refresh sibling alongside each existing `get_<header>()` cache-on-miss function, plus a new tgen trio. (2) `rbx/box/download.py` exposes a `tgen` Typer command, `maybe_add_tgen()` for compile-time auto-include, and a shared `--into PATH` option resolved relative to the package root. (3) `rbx/box/code.py`, `rbx/grading/steps.py`, and `rbx/box/packaging/polygon/upload.py` wire tgen into compilation, precompile allowlist, and Polygon resource upload.

**Tech Stack:** Python 3, Typer CLI, Pydantic v2, pytest with `testing_package` fixtures, `requests` for downloads.

**Design doc:** `docs/plans/2026-05-12-tgen-default-include-design.md`. Issue: [#409](https://github.com/rsalesc/rbx/issues/409).

---

## Conventions

- Single quotes for strings; absolute imports only; `uv run ruff format .` before each commit.
- Commits follow Conventional Commits — use the `/commit` skill or write a message with a valid type (`feat`, `fix`, `test`, `docs`, `refactor`).
- Each task ends with a green-test commit. No squashing.
- For ruff trailing-whitespace issues run `uv run ruff check --fix .`.

---

## Task 1: Add `download_*` always-refresh siblings in `rbx/config.py`

**Files:**
- Modify: `rbx/config.py:146-222` (testlib/jngen download helpers and getters)
- Test: covered indirectly by Task 4 (download CLI tests)

**Step 1: Refactor existing downloaders to extract a reusable always-refresh function**

In `rbx/config.py`, after `_download_jngen()` (line 175), and after the existing `get_testlib()` / `get_jngen()` functions, add:

```python
def download_testlib() -> pathlib.Path:
    """Always re-fetch testlib.h from upstream and return the cached path."""
    app_file = get_app_file(pathlib.Path('testlib.h'))
    try:
        _download_testlib(app_file)
    except DownloadError:
        if not app_file.exists():
            raise
    return app_file


def download_jngen() -> pathlib.Path:
    """Always re-fetch jngen.h from upstream and return the cached path."""
    app_file = get_app_file(pathlib.Path('jngen.h'))
    try:
        _download_jngen(app_file)
    except DownloadError:
        if not app_file.exists():
            raise
    return app_file
```

`get_app_file()` ensures the parent dir exists; `_download_*` overwrites the file on success. On failure with no cache, re-raise so the CLI surfaces an error.

**Step 2: Run linter to verify**

Run: `uv run ruff check rbx/config.py`
Expected: PASS (no new diagnostics).

**Step 3: Commit**

```bash
git add rbx/config.py
git commit -m "refactor(config): add always-refresh download_* siblings for headers"
```

---

## Task 2: Add tgen download helper + getter in `rbx/config.py`

**Files:**
- Modify: `rbx/config.py` (add `_download_tgen`, `get_tgen`, `download_tgen`)

**Step 1: Add `_download_tgen` after `_download_jngen` (~line 175)**

```python
def _download_tgen(save_at: pathlib.Path):
    import requests

    console.print('Downloading tgen.h...')
    r = requests.get(
        'https://raw.githubusercontent.com/brunomaletta/tgen/main/single_include/tgen.h'
    )

    if r.ok:
        save_at.parent.mkdir(parents=True, exist_ok=True)
        with save_at.open('wb') as f:
            f.write(r.content)
    else:
        console.print('[error]Failed to download tgen.h.[/error]')
        raise DownloadError()
```

**Step 2: Add `get_tgen()` and `download_tgen()` after the jngen counterparts (~line 222)**

```python
def get_tgen() -> pathlib.Path:
    app_file = get_app_file(pathlib.Path('tgen.h'))
    if not app_file.exists():
        try:
            _download_tgen(app_file)
        except DownloadError:
            app_file = get_app_file(pathlib.Path('tgen.h'), predownloaded=True)
    return app_file


def download_tgen() -> pathlib.Path:
    app_file = get_app_file(pathlib.Path('tgen.h'))
    try:
        _download_tgen(app_file)
    except DownloadError:
        if not app_file.exists():
            raise
    return app_file
```

**Step 3: Run linter**

Run: `uv run ruff check rbx/config.py`
Expected: PASS.

**Step 4: Commit**

```bash
git add rbx/config.py
git commit -m "feat(config): add tgen.h download helpers"
```

---

## Task 3: Add `tgen_grading_input()` and warning-ignore in `rbx/grading/steps.py`

**Files:**
- Modify: `rbx/grading/steps.py:20` (import)
- Modify: `rbx/grading/steps.py:405-407` (add `tgen_grading_input`)
- Modify: `rbx/grading/steps.py:648` (warning-ignore branch)

**Step 1: Update import**

Change line 20 from:
```python
from rbx.config import get_bits_stdcpp, get_jngen, get_testlib
```
to:
```python
from rbx.config import get_bits_stdcpp, get_jngen, get_testlib, get_tgen
```

**Step 2: Add `tgen_grading_input` after `jngen_grading_input`**

After line 407 add:
```python
def tgen_grading_input() -> GradingFileInput:
    return GradingFileInput(src=get_tgen(), dest=pathlib.Path('tgen.h'))
```

**Step 3: Extend the warning-ignore branch on line 648**

Change:
```python
if 'testlib' in file or 'jngen' in file or 'stresslib' in file:
```
to:
```python
if 'testlib' in file or 'jngen' in file or 'tgen' in file or 'stresslib' in file:
```

**Step 4: Run linter**

Run: `uv run ruff check rbx/grading/steps.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/grading/steps.py
git commit -m "feat(grading): expose tgen.h as a grading input header"
```

---

## Task 4: Failing test for tgen auto-include + precompile

**Files:**
- Modify: `tests/rbx/box/code_compile_test.py:281-297` (add jngen-style tgen test)
- Modify: `tests/rbx/box/code_compile_test.py:380-395` (extend expected header set)

**Step 1: Add `test_compile_artifacts_with_tgen` right after `test_compile_artifacts_with_jngen`**

```python
async def test_compile_artifacts_with_tgen(
    self, testing_pkg: testing_package.TestingPackage, mock_steps_with_caching
):
    """Test that tgen.h is included in artifacts when available."""
    cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
    code_item = CodeItem(path=cpp_file, language='cpp')

    await code.compile_item(code_item)

    call_args = mock_steps_with_caching.call_args
    artifacts = call_args.kwargs['artifacts']

    tgen_input = next(
        (inp for inp in artifacts.inputs if inp.dest.name == 'tgen.h'), None
    )
    assert tgen_input is not None
```

**Step 2: Extend the expected_header_files set on line 381**

Change:
```python
expected_header_files = {'testlib.h', 'jngen.h', 'rbx.h', 'stdc++.h'}
```
to:
```python
expected_header_files = {'testlib.h', 'jngen.h', 'tgen.h', 'rbx.h', 'stdc++.h'}
```

And on line 395 change:
```python
processed_header_files = {'testlib.h', 'jngen.h', 'rbx.h'}
```
to:
```python
processed_header_files = {'testlib.h', 'jngen.h', 'tgen.h', 'rbx.h'}
```

**Step 3: Run tests, expect failure**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestCompileItem::test_compile_artifacts_with_tgen -v`
Expected: FAIL — `tgen_input` is `None` because nothing wires tgen yet.

**Step 4: Do NOT commit yet — implementation in Task 5.**

---

## Task 5: Wire `maybe_add_tgen` into compilation

**Files:**
- Modify: `rbx/box/download.py:10` (import)
- Modify: `rbx/box/download.py:42-48` (add `maybe_add_tgen`)
- Modify: `rbx/box/code.py:620` (call it)
- Modify: `rbx/box/code.py:660` (precompile allowlist)

**Step 1: Extend the `rbx.config` import in `rbx/box/download.py`**

Change line 10 from:
```python
from rbx.config import get_builtin_checker, get_jngen, get_testlib
```
to:
```python
from rbx.config import (
    download_jngen,
    download_testlib,
    download_tgen,
    get_builtin_checker,
    get_jngen,
    get_testlib,
    get_tgen,
)
```

(`download_*` symbols are used in Task 6; importing here keeps a single import block.)

**Step 2: Add `maybe_add_tgen` right after `maybe_add_jngen` (after line 48)**

```python
def maybe_add_tgen(code: CodeItem, artifacts: steps.GradingArtifacts):
    # Try to get from compilation files, then from package folder, then from tool.
    artifact = get_local_artifact('tgen.h') or steps.tgen_grading_input()
    compilation_files = package.get_compilation_files(code)
    if any(dest == artifact.dest for _, dest in compilation_files):
        return
    artifacts.inputs.append(artifact)
```

**Step 3: Call it in `rbx/box/code.py` after line 620**

Insert after `download.maybe_add_jngen(code, artifacts)`:
```python
        download.maybe_add_tgen(code, artifacts)
```

**Step 4: Extend the precompile allowlist on line 660**

Change:
```python
and input.dest.name in ['stdc++.h', 'jngen.h', 'testlib.h']
```
to:
```python
and input.dest.name in ['stdc++.h', 'jngen.h', 'tgen.h', 'testlib.h']
```

**Step 5: Run the tests added in Task 4**

Run: `uv run pytest tests/rbx/box/code_compile_test.py::TestCompileItem -v`
Expected: PASS (both the new `test_compile_artifacts_with_tgen` and the updated `test_compile_precompilation_enabled_by_default`).

**Step 6: Run lint + format**

Run: `uv run ruff check --fix . && uv run ruff format .`
Expected: PASS, no diff after second run.

**Step 7: Commit**

```bash
git add rbx/box/download.py rbx/box/code.py tests/rbx/box/code_compile_test.py
git commit -m "feat(box): auto-include tgen.h in C++ compilation"
```

---

## Task 6: `rbx download tgen` CLI + always-refresh testlib/jngen + `--into PATH`

**Files:**
- Modify: `rbx/box/download.py:51-62` (refactor testlib + jngen commands, add tgen)

**Step 1: Add the helper at the top of `rbx/box/download.py` (after `get_local_artifact`)**

```python
def _resolve_download_target(name: str, into: Optional[str]) -> pathlib.Path:
    if into is None:
        return pathlib.Path(name)
    target = package.get_problem_package_dir() / into
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
```

**Step 2: Replace the existing `testlib` and `jngen` commands and add `tgen`**

Replace lines 51-62 with:

```python
_INTO_HELP = (
    'Path (relative to the package root) where the file should be placed. '
    'Parent directories are created. If omitted, the file is written to the '
    'current directory.'
)


@app.command('testlib', help='Download the latest testlib.h')
@package.within_problem
def testlib(
    into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP),
):
    target = _resolve_download_target('testlib.h', into)
    shutil.copyfile(download_testlib(), target)
    console.console.print(
        f'Downloaded [item]testlib.h[/item] into [item]{target}[/item].'
    )


@app.command('jngen', help='Download the latest jngen.h')
@package.within_problem
def jngen(
    into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP),
):
    target = _resolve_download_target('jngen.h', into)
    shutil.copyfile(download_jngen(), target)
    console.console.print(
        f'Downloaded [item]jngen.h[/item] into [item]{target}[/item].'
    )


@app.command('tgen', help='Download the latest tgen.h')
@package.within_problem
def tgen(
    into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP),
):
    target = _resolve_download_target('tgen.h', into)
    shutil.copyfile(download_tgen(), target)
    console.console.print(
        f'Downloaded [item]tgen.h[/item] into [item]{target}[/item].'
    )
```

(`Optional` is already imported; `package.get_problem_package_dir` is the existing accessor — confirm by `grep -n "def get_problem_package_dir" rbx/box/package.py` before writing.)

**Step 3: Run linter and formatter**

Run: `uv run ruff check --fix rbx/box/download.py && uv run ruff format rbx/box/download.py`
Expected: PASS.

**Step 4: Smoke-test the help text**

Run: `uv run rbx download --help`
Expected: shows `testlib`, `jngen`, `tgen` subcommands; each has `--into PATH`.

**Step 5: Commit**

```bash
git add rbx/box/download.py
git commit -m "feat(download): add tgen command and --into flag, refresh on every invocation"
```

---

## Task 7: Tests for download CLI behavior

**Files:**
- Create: `tests/rbx/box/download_test.py`

**Step 1: Write the failing tests**

```python
import pathlib
from unittest import mock

import pytest

from rbx.box import download, package
from rbx.box.testing import testing_package


class _FakeResponse:
    def __init__(self, content: bytes, ok: bool = True):
        self.content = content
        self.ok = ok


@pytest.fixture
def fake_requests_get():
    with mock.patch('requests.get') as m:
        m.return_value = _FakeResponse(b'// fake header\n')
        yield m


@pytest.fixture(autouse=True)
def clear_app_cache(tmp_path, monkeypatch):
    monkeypatch.setattr('rbx.config.get_app_path', lambda: tmp_path / 'app')
    yield


class TestDownloadTgen:
    def test_writes_tgen_to_cwd_by_default(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.tgen(into=None)
        target = pathlib.Path.cwd() / 'tgen.h'
        assert target.read_bytes() == b'// fake header\n'

    def test_into_resolves_relative_to_package_root(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.tgen(into='libs/headers/tgen.h')
        target = package.get_problem_package_dir() / 'libs' / 'headers' / 'tgen.h'
        assert target.read_bytes() == b'// fake header\n'

    def test_refetches_on_every_invocation(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.tgen(into=None)
        download.tgen(into=None)
        assert fake_requests_get.call_count == 2


class TestDownloadJngenRefresh:
    def test_jngen_refetches_even_when_cached(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.jngen(into=None)
        download.jngen(into=None)
        assert fake_requests_get.call_count == 2


class TestDownloadTestlibRefresh:
    def test_testlib_refetches_even_when_cached(
        self, testing_pkg: testing_package.TestingPackage, fake_requests_get
    ):
        download.testlib(into=None)
        download.testlib(into=None)
        assert fake_requests_get.call_count == 2
```

**Notes for the implementing engineer:**
- `testing_pkg` is the standard fixture from `tests/rbx/box/conftest.py`; it `chdir`s into a fresh problem package, so `pathlib.Path.cwd()` equals the package root.
- `package.get_problem_package_dir()` returns the same dir; the two `target` paths intentionally test both surfaces.
- `clear_app_cache` redirects the app dir so the file cache is empty per-test.
- The Typer commands are decorated with `@package.within_problem` but the underlying functions accept the `into` kwarg directly — call them as Python functions, not via the Typer CLI.

**Step 2: Run tests**

Run: `uv run pytest tests/rbx/box/download_test.py -v`
Expected: PASS (4 tests).

If `get_problem_package_dir` requires anything beyond `testing_pkg`, debug with @superpowers:systematic-debugging before patching the test — the production code is what we care about.

**Step 3: Lint**

Run: `uv run ruff check --fix tests/rbx/box/download_test.py && uv run ruff format tests/rbx/box/download_test.py`

**Step 4: Commit**

```bash
git add tests/rbx/box/download_test.py
git commit -m "test(download): cover tgen, --into, and always-refresh behavior"
```

---

## Task 8: Polygon upload + fixture for tgen

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py:127-135` (add `_update_tgen`)
- Modify: `rbx/box/packaging/polygon/upload.py:305` (call `_update_tgen`)
- Modify: `rbx/box/packaging/polygon/test.py:45-49` (add resource line)

**Step 1: Add `_update_tgen` after `_update_jngen`**

```python
def _update_tgen(problem: api.Problem):
    tgen = download.get_tgen()
    console.console.print('Uploading tgen.h...')
    problem.save_file(
        type=api.FileType.RESOURCE,
        name='tgen.h',
        file=tgen.read_bytes(),
        source_type=None,
    )
```

**Step 2: Call it next to `_update_jngen(problem)` on line 305**

Add:
```python
        _update_tgen(problem)  # TODO: only upload if necessary
```

**Step 3: Update the resource list in `rbx/box/packaging/polygon/test.py`**

Change line 45-49 from:
```xml
      <file path="files/jngen.h" type="h.g++"/>
      <file path="files/olymp.sty"/>
      <file path="files/problem.tex"/>
      <file path="files/statements.ftl"/>
      <file path="files/testlib.h" type="h.g++"/>
```
to:
```xml
      <file path="files/jngen.h" type="h.g++"/>
      <file path="files/olymp.sty"/>
      <file path="files/problem.tex"/>
      <file path="files/statements.ftl"/>
      <file path="files/testlib.h" type="h.g++"/>
      <file path="files/tgen.h" type="h.g++"/>
```

**Step 4: Verify `polygon/test.py` still parses cleanly**

Run: `uv run python rbx/box/packaging/polygon/test.py`
Expected: prints a parsed `Problem` and `Contest` without exception. (If this file is excluded from CI / has side effects, the engineer should at least import it without error.)

**Step 5: Run lint + format**

Run: `uv run ruff check --fix . && uv run ruff format .`

**Step 6: Commit**

```bash
git add rbx/box/packaging/polygon/upload.py rbx/box/packaging/polygon/test.py
git commit -m "feat(packaging): upload tgen.h as a Polygon resource"
```

---

## Task 9: Schema comment + docs

**Files:**
- Modify: `rbx/box/schema.py:288,293` (comment update)
- Modify: `docs/setters/cheatsheet.md:34` (add row)
- Modify: `docs/setters/testset/generators.md:130-138` (add Tgen section)
- Modify: `docs/setters/reference/cli.md` (after the `### jngen` section ~line 545)

**Step 1: Update `rbx/box/schema.py`**

Read lines 285-295 and adjust the comment so both occurrences of "testlib.h, jngen.h" mention tgen.h as well. Specifically replace `Testlib and jngen are already included by default.` with `Testlib, jngen and tgen are already included by default.` and the file-list example `such as testlib.h, jngen.h, etc.` to `such as testlib.h, jngen.h, tgen.h, etc.`.

**Step 2: Update `docs/setters/cheatsheet.md` line 34**

After the jngen row add:
```
| Download tgen to the current folder                | `rbx download tgen`                                            |
```

(Match the column widths of neighboring rows.)

**Step 3: Append a Tgen section to `docs/setters/testset/generators.md`**

After line 137 (just before the existing `!!! danger "Under development"` block, or after it — keep parallel placement to the Jngen section), add:

```markdown
## Tgen, the modern alternative

{{rbx}} also has a built-in integration with [tgen](https://github.com/brunomaletta/tgen),
a C++ header for writing random testcase generators quickly and safely, by Bruno Maletta.

To implement a Tgen-based generator, it suffices to include the `tgen.h` header — {{rbx}}
makes it available to every C++ compilation, just like {{testlib}} and {{jngen}}.

You can grab a local copy of the latest `tgen.h` with:

```bash
rbx download tgen
```

Or place it at an arbitrary path relative to the package root with `--into`:

```bash
rbx download tgen --into libs/tgen.h
```

The same `--into` flag is available for `rbx download testlib` and
`rbx download jngen`.
```

**Step 4: Update `docs/setters/reference/cli.md`**

Read the existing `### jngen` block (line 545+) and:
1. Mention `--into PATH` in the testlib and jngen sections.
2. Add a parallel `### tgen` section directly after `### jngen` with the same shape (Download tgen.h, signature, `--into`).

**Step 5: Spot-check the docs build does not break**

If a docs build is wired up (`mise run docs` or similar — check `mise.toml`), run it. If not, just verify the Markdown files render correctly in a viewer.

**Step 6: Commit**

```bash
git add rbx/box/schema.py docs/setters/cheatsheet.md docs/setters/testset/generators.md docs/setters/reference/cli.md
git commit -m "docs: document tgen default include and --into flag"
```

---

## Task 10: Full test pass + smoke check

**Files:** none.

**Step 1: Run the full default test suite**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: PASS. Pay attention to:
- `tests/rbx/box/code_compile_test.py` — the precompile allowlist test.
- `tests/rbx/box/download_test.py` — the new tests.
- Any test that asserts on the Polygon resource list.

**Step 2: Smoke test the CLI**

Run: `uv run rbx download --help`
Expected: shows `tgen` with `--into PATH`.

If you have a sandbox problem package handy:
```bash
cd <some-problem-package>
uv run rbx download tgen --into vendor/tgen.h
ls vendor/tgen.h
```
Expected: file exists, ~tens of KB, starts with copyright/header guard from upstream.

**Step 3: Run lint + format once more**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS.

**Step 4: No code commit. Open the PR.**

```bash
gh pr create --title "feat: add tgen as a default include" --body "Closes #409"
```
(Filling in the body via the `/commit` PR template, or by hand if you prefer.)

---

## Notes for the implementing engineer

- **`get_problem_package_dir()`** is the canonical "package root" accessor used elsewhere in `rbx/box/download.py` (see how `remote_cmd` resolves paths, and how `package.within_problem` `chdir`s). Don't reinvent.
- **Don't add a separate `download_bits_stdcpp()`.** Out of scope per design doc.
- **Don't add a `--refresh` flag.** Always-refresh on `rbx download` is the explicit refresh path.
- **Single quotes** in Python sources; ruff will catch deviations.
- **Cache invalidation:** `tgen.h` joins the precompile allowlist. The grading cache keys off file content, so adding it won't invalidate existing solutions' caches; it will only show up on the next recompile.
- **If the docs build fails** on the new Markdown, prefer fixing the Markdown over disabling the build. The pattern from the Jngen section is the safe template.
- **Watch out for `@functools.cache`** — none of the new functions (`download_tgen`, `_resolve_download_target`, `maybe_add_tgen`) should be cached. If you reach for a cache, re-read `rbx/box/CLAUDE.md`'s "Test isolation rule" first.

---

## Done criteria

- `rbx download tgen` writes `tgen.h` to the current dir and re-fetches every time.
- `rbx download tgen --into libs/tgen.h` writes to `<pkg>/libs/tgen.h`.
- `rbx download jngen` and `rbx download testlib` also refresh on every invocation (bugfix).
- C++ compilations include `tgen.h` and precompile it.
- Polygon packaging uploads `tgen.h` as a resource.
- Docs mention tgen alongside jngen.
- `uv run pytest --ignore=tests/rbx/box/cli` is green.
