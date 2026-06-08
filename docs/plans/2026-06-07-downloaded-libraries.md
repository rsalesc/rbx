# Downloaded Libraries Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the hardcoded `testlib`/`jngen`/`tgen` download logic with preset-declared, versioned, cached, and package-materialized libraries (issue #392).

**Architecture:** A new `libraries:` block in `preset.rbx.yml` declares each library's `source` (preset URI grammar) + `path` + `version` + `dest` + `symlink` + `always_include`. A fetch layer caches files once under `~/.rbx/libs/`; a materialize layer writes them into the package (copy, or symlink via `.local.rbx/libs/`). `rbx presets sync` and package creation drive fetch+materialize. At compile, default libraries are pulled in by the existing quoted-`#include` auto-expansion; `always_include` libraries are additionally injected into `__internal__/`. `rbx.h` + `bits/stdc++.h` stay tool built-ins; `testlib`/`jngen`/`tgen` leave `config.py`.

**Tech Stack:** Python 3, Pydantic v2, Typer, pytest, GitPython (`rbx/box/git_utils.py`), `requests`, tree-sitter-cpp (existing dependency scanner).

**Design doc:** `docs/plans/2026-06-07-downloaded-libraries-design.md`

---

## Ordering principle

The clean cut (removing `maybe_add_testlib/jngen/tgen`) would break the whole
suite if done first. So we build everything **additively** first, make the
default preset provide `testlib` via `always_include`, and only **then** remove
the hardcoded injection. The suite stays green at every commit.

## ⚠️ Open decision — confirm before Task 9

Today `testlib`, `jngen`, **and** `tgen` are auto-injected into every C++ compile.
After the clean cut, only libraries the default preset declares are available by
default. **Plan assumes:** the default preset declares **`testlib` only**
(`always_include: true`); `jngen`/`tgen` become opt-in (a setter adds them to
the local preset snapshot). This avoids committing the very large `jngen.h`/
`tgen.h` into every package. Task 8 greps the test suite for `jngen`/`tgen`
usage and adds explicit declarations to those fixtures. **If you'd rather keep
all three always-on, declare all three in Task 9 instead and skip the fixture
patches.**

Run all commands from the worktree root. Default test command:
`uv run pytest <path> -v`. Use the `/commit` skill for every commit
(conventional commits enforced by commitizen).

---

## Task 1: `Library` / `Libraries` schema models

**Files:**
- Modify: `rbx/box/presets/schema.py`
- Test: `tests/rbx/box/presets/test_presets.py`

**Step 1: Write the failing test**

Add to `tests/rbx/box/presets/test_presets.py`:

```python
def test_preset_parses_libraries_block():
    from rbx.box.presets.schema import Preset

    preset = Preset.model_validate(
        {
            'name': 'sample',
            'uri': 'owner/repo',
            'libraries': {
                'problem': [
                    {
                        'name': 'testlib',
                        'source': 'MikeMirzayanov/testlib',
                        'path': 'testlib.h',
                        'version': 'master',
                        'dest': 'testlib.h',
                        'always_include': True,
                    }
                ]
            },
        }
    )

    lib = preset.libraries.problem[0]
    assert lib.name == 'testlib'
    assert lib.source == 'MikeMirzayanov/testlib'
    assert str(lib.path) == 'testlib.h'
    assert lib.version == 'master'
    assert str(lib.dest) == 'testlib.h'
    assert lib.always_include is True
    assert lib.symlink is False
    assert lib.include_as is None
    # Defaults: no libraries block => empty lists.
    assert Preset(name='x', uri='owner/repo').libraries.problem == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_presets.py::test_preset_parses_libraries_block -v`
Expected: FAIL — `Preset` has no `libraries` attribute (extra field forbidden or AttributeError).

**Step 3: Write minimal implementation**

In `rbx/box/presets/schema.py`, add after the `Tracking` class (around line 36):

```python
class Library(BaseModel):
    # Logical name of the library. Used as the cache key and as the argument to
    # `rbx download <name>`.
    name: str = NameField()

    # Source of the library, using the same URI grammar as preset `uri`
    # (owner/repo, @gh/owner/repo, a full GitHub/git URL, a raw download URL, or
    # a local path). Resolved by `get_library_fetch_info`.
    source: str

    # Path of the file or directory to take from the source repo. Omit for a
    # raw-URL source (the URL already points at the file).
    path: Optional[pathlib.Path] = None

    # Version to fetch: a commit prefix, a tag/release/branch, or 'latest'.
    version: str = 'latest'

    # Where the library is materialized inside the problem/contest package.
    dest: pathlib.Path

    # When true, the materialized file lives in .local.rbx/libs/<name>/ and
    # `dest` is a relative symlink into it; otherwise `dest` is a real copy.
    symlink: bool = False

    # When true, the library is also injected into the reserved __internal__/
    # dir at compile time (exposed via -I__internal__), so any source can
    # include it without it resolving relative to the includer.
    always_include: bool = False

    # How the library is spelled in an #include when always_include is set.
    # Defaults to the basename of `path` (or `dest`). Use for nested names like
    # `bits/stdc++.h`.
    include_as: Optional[pathlib.Path] = None


class Libraries(BaseModel):
    # Problem libraries, materialized into every problem package.
    problem: List[Library] = []

    # Contest libraries, materialized into every contest package.
    contest: List[Library] = []
```

Then add the field to `Preset` (after `expansion`, around line 99):

```python
    # Configures third-party libraries (testlib, jngen, etc.) that should be
    # fetched, cached, and materialized into the package.
    libraries: Libraries = Field(default_factory=Libraries)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_presets.py::test_preset_parses_libraries_block -v`
Expected: PASS

**Step 5: Commit** (use `/commit`)

```
feat(presets): add Library/Libraries schema models to preset config
```

---

## Task 2: Library source resolution (extend the URI grammar)

Reuse the preset URI extractors and add raw-URL + arbitrary-git extractors, then
expose `get_library_fetch_info(source)`.

**Files:**
- Modify: `rbx/box/presets/fetch.py`
- Test: `tests/rbx/box/presets/test_fetch.py`

**Step 1: Write the failing tests**

Add to `tests/rbx/box/presets/test_fetch.py`:

```python
from rbx.box.presets.fetch import get_library_fetch_info


def test_library_fetch_info_github_short():
    info = get_library_fetch_info('MikeMirzayanov/testlib')
    assert info is not None
    assert info.fetch_uri == 'https://github.com/MikeMirzayanov/testlib'
    assert info.is_github()
    assert not info.is_raw_url()


def test_library_fetch_info_raw_url():
    info = get_library_fetch_info('https://example.com/headers/foo.h')
    assert info is not None
    assert info.is_raw_url()
    assert info.fetch_uri == 'https://example.com/headers/foo.h'


def test_library_fetch_info_git_url():
    info = get_library_fetch_info('https://gitlab.com/u/r.git')
    assert info is not None
    assert info.is_git_url()
    assert info.fetch_uri == 'https://gitlab.com/u/r.git'


def test_library_fetch_info_local(tmp_path):
    (tmp_path / 'lib.h').write_text('x')
    info = get_library_fetch_info(str(tmp_path / 'lib.h'))
    assert info is not None
    assert info.is_local()
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/presets/test_fetch.py -k library_fetch_info -v`
Expected: FAIL — `get_library_fetch_info` does not exist.

**Step 3: Implement**

In `rbx/box/presets/fetch.py`, add a sibling model + resolver. Note GitHub raw
URLs (`raw.githubusercontent.com`) must NOT be treated as generic raw URLs when
we can derive owner/repo — but for simplicity here, only non-GitHub `https://`
URLs ending in a file extension are raw URLs; GitHub URLs keep going through the
GitHub extractor.

```python
class LibraryFetchInfo(BaseModel):
    # 'github' | 'git' | 'raw' | 'local'
    kind: str
    # For github/git/raw: the URL to fetch from. For local: the filesystem path.
    fetch_uri: str

    def is_github(self) -> bool:
        return self.kind == 'github'

    def is_git_url(self) -> bool:
        return self.kind == 'git'

    def is_raw_url(self) -> bool:
        return self.kind == 'raw'

    def is_local(self) -> bool:
        return self.kind == 'local'


def get_library_fetch_info(source: str) -> Optional['LibraryFetchInfo']:
    # 1) GitHub (full or short), reusing the existing preset extractors.
    github = get_preset_fetch_info(source)
    if github is not None and github.is_remote() and 'github.com' in (
        github.fetch_uri or ''
    ):
        return LibraryFetchInfo(kind='github', fetch_uri=github.fetch_uri)

    # 2) Arbitrary git URL (ends in .git).
    if re.match(r'^https?://', source) and source.endswith('.git'):
        return LibraryFetchInfo(kind='git', fetch_uri=source)

    # 3) Raw download URL (any other http(s) URL).
    if re.match(r'^https?://', source):
        return LibraryFetchInfo(kind='raw', fetch_uri=source)

    # 4) Local path.
    try:
        if pathlib.Path(source).exists():
            return LibraryFetchInfo(kind='local', fetch_uri=source)
    except OSError:
        pass

    # 5) Short github fallback (owner/repo without a scheme).
    if github is not None and github.is_remote():
        return LibraryFetchInfo(kind='github', fetch_uri=github.fetch_uri)

    return None
```

**Step 4: Run to verify they pass**

Run: `uv run pytest tests/rbx/box/presets/test_fetch.py -k library_fetch_info -v`
Expected: PASS

**Step 5: Commit**

```
feat(presets): resolve library sources via extended URI grammar
```

---

## Task 3: Fetch + cache layer

Fetch a (source, path, version) into `~/.rbx/libs/<source-hash>/<ref>/<path>` once.

**Files:**
- Create: `rbx/box/presets/library_fetch.py`
- Test: `tests/rbx/box/presets/test_library_fetch.py`

**Step 1: Write the failing test** (local source = deterministic, offline)

```python
import pathlib
from rbx.box.presets.schema import Library
from rbx.box.presets import library_fetch


def test_fetch_library_local_source_caches(tmp_path, monkeypatch):
    # Point the app cache at a temp dir.
    app = tmp_path / 'app'
    monkeypatch.setattr(library_fetch, 'get_app_path', lambda: app)

    src_repo = tmp_path / 'src'
    src_repo.mkdir()
    (src_repo / 'lib.h').write_text('#pragma once\n// lib')

    lib = Library(
        name='lib',
        source=str(src_repo),
        path='lib.h',
        version='latest',
        dest='lib.h',
    )

    cached = library_fetch.fetch_library(lib)
    assert cached.is_file()
    assert cached.read_text() == '#pragma once\n// lib'
    assert app in cached.parents  # cached under the app libs dir
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_library_fetch.py -v`
Expected: FAIL — module/function missing.

**Step 3: Implement**

```python
import hashlib
import pathlib
import shutil
import tempfile
from typing import Optional

import typer

from rbx import console
from rbx.box import git_utils
from rbx.box.presets.fetch import get_library_fetch_info
from rbx.box.presets.schema import Library
from rbx.utils import get_app_path


def _cache_root() -> pathlib.Path:
    return get_app_path() / 'libs'


def _source_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def _cache_path(library: Library, ref: str) -> pathlib.Path:
    path_part = str(library.path) if library.path is not None else 'file'
    return _cache_root() / _source_hash(library.source) / ref / path_part


def fetch_library(library: Library) -> pathlib.Path:
    """Fetch the library into the global cache and return the cached file path.

    First fetch requires network for remote sources; afterwards the cache is
    reused. Raises typer.Exit on failure (no offline fallback by design).
    """
    info = get_library_fetch_info(library.source)
    if info is None:
        console.console.print(
            f'[error]Library [item]{library.name}[/item] has an invalid source '
            f'[item]{library.source}[/item].[/error]'
        )
        raise typer.Exit(1)

    if info.is_local():
        src = pathlib.Path(info.fetch_uri)
        if library.path is not None and src.is_dir():
            src = src / library.path
        ref = 'local'
        dst = _cache_path(library, ref)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        return dst

    if info.is_raw_url():
        ref = 'url'
        dst = _cache_path(library, ref)
        if not dst.exists():
            _download_url(info.fetch_uri, dst)
        return dst

    if info.is_github():
        ref = _resolve_ref(info.fetch_uri, library.version)
        dst = _cache_path(library, ref)
        if not dst.exists():
            owner_repo = info.fetch_uri.removeprefix('https://github.com/')
            raw = (
                f'https://raw.githubusercontent.com/{owner_repo}/{ref}/'
                f'{library.path}'
            )
            _download_url(raw, dst)
        return dst

    # Arbitrary git: clone + checkout + copy path.
    ref = library.version if library.version != 'latest' else None
    dst = _cache_path(library, ref or 'latest')
    if not dst.exists():
        _clone_and_copy(info.fetch_uri, ref, library.path, dst)
    return dst


def _resolve_ref(github_uri: str, version: str) -> str:
    if version != 'latest':
        return version
    # 'latest' on GitHub: use the default branch HEAD via ls-remote HEAD.
    return git_utils.resolve_remote_head(github_uri)


def _download_url(url: str, dst: pathlib.Path) -> None:
    import requests

    console.console.print(f'Downloading [item]{url}[/item]...')
    r = requests.get(url)
    if not r.ok:
        console.console.print(f'[error]Failed to download [item]{url}[/item].[/error]')
        raise typer.Exit(1)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.content)


def _clone_and_copy(
    uri: str, ref: Optional[str], path: Optional[pathlib.Path], dst: pathlib.Path
) -> None:
    import git

    with tempfile.TemporaryDirectory() as td:
        repo = git.Repo.clone_from(uri, td)
        if ref is not None:
            repo.git.checkout(ref)
        src = pathlib.Path(td) / (path or '')
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copyfile(src, dst)
```

Add `resolve_remote_head` to `rbx/box/git_utils.py` (mirrors `ls_remote_tags`):

```python
def resolve_remote_head(uri: str) -> str:
    """Return the commit SHA the remote's default branch (HEAD) points at."""
    out = subprocess.check_output(['git', 'ls-remote', uri, 'HEAD'], text=True)
    return out.split()[0]
```

> ⚠️ Per `rbx/box/CLAUDE.md`, if `fetch_library` (or any new module-level
> `@functools.cache`) caches resolved state, register it in
> `rbx.testing_utils.clear_all_functools_cache`. The version above is cache-free.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_library_fetch.py -v`
Expected: PASS

**Step 5: Commit**

```
feat(presets): add library fetch + global cache layer
```

---

## Task 4: Materialize into the package (copy + symlink)

**Files:**
- Modify: `rbx/box/presets/library_fetch.py`
- Test: `tests/rbx/box/presets/test_library_fetch.py`

**Step 1: Write the failing tests**

```python
def test_materialize_copy(tmp_path):
    cache = tmp_path / 'cache.h'
    cache.write_text('content')
    lib = Library(name='lib', source='x', path='lib.h', dest='sub/lib.h')
    pkg = tmp_path / 'pkg'
    pkg.mkdir()

    library_fetch.materialize_library(lib, cache, pkg)

    out = pkg / 'sub' / 'lib.h'
    assert out.is_file() and not out.is_symlink()
    assert out.read_text() == 'content'


def test_materialize_symlink(tmp_path):
    cache = tmp_path / 'cache.h'
    cache.write_text('content')
    lib = Library(name='lib', source='x', path='lib.h', dest='sub/lib.h', symlink=True)
    pkg = tmp_path / 'pkg'
    pkg.mkdir()

    library_fetch.materialize_library(lib, cache, pkg)

    out = pkg / 'sub' / 'lib.h'
    stored = pkg / '.local.rbx' / 'libs' / 'lib' / 'lib.h'
    assert stored.is_file()
    assert out.is_symlink()
    assert out.resolve() == stored.resolve()
    assert out.read_text() == 'content'
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/presets/test_library_fetch.py -k materialize -v`
Expected: FAIL — `materialize_library` missing.

**Step 3: Implement**

```python
from rbx import utils


def materialize_library(
    library: Library, cache_path: pathlib.Path, pkg_root: pathlib.Path
) -> None:
    dest = pkg_root / library.dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.is_file():
        dest.unlink()

    if not library.symlink:
        shutil.copyfile(cache_path, dest)
        return

    stored = pkg_root / '.local.rbx' / 'libs' / library.name / (
        library.path.name if library.path else cache_path.name
    )
    stored.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cache_path, stored)
    rel = utils.relpath(utils.abspath(stored), utils.abspath(dest).parent)
    dest.symlink_to(rel)
```

(Directory `path` support: when `cache_path` is a directory, mirror it with
`shutil.copytree`. Defer until a test needs it — YAGNI.)

**Step 4: Run to verify they pass**

Run: `uv run pytest tests/rbx/box/presets/test_library_fetch.py -k materialize -v`
Expected: PASS

**Step 5: Commit**

```
feat(presets): materialize libraries into the package (copy/symlink)
```

---

## Task 5: Wire fetch+materialize into create + `presets sync`

**Files:**
- Modify: `rbx/box/presets/__init__.py`
- Test: `tests/rbx/box/presets/test_presets.py`

**Step 1: Write the failing test** (preset with a local-source library)

Use the existing preset-fixture helpers. Build a preset whose `preset.rbx.yml`
declares a `libraries.problem` entry from a local source, install it into a
package, then assert the file is materialized.

```python
def test_sync_materializes_libraries(tmp_path, ...):
    # Arrange: a local "library source" file.
    src = tmp_path / 'src' / 'lib.h'
    src.parent.mkdir(parents=True)
    src.write_text('// lib')

    # Build a preset that declares the library, install it into a package
    # (reuse the TestingPreset / preset_with_problem_package helpers in this file).
    # ... preset.libraries.problem = [Library(name='lib', source=str(src),
    #         path='lib.h', dest='lib.h')]
    # Install -> package root P.

    # Act
    presets.sync()  # within the package

    # Assert
    assert (P / 'lib.h').read_text() == '// lib'
```

> Mirror the construction style of the existing
> `preset_with_problem_package`/`problem_package_with_preset` fixtures in
> `test_presets.py` (read them first). Keep the library source LOCAL so the test
> needs no network.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_presets.py -k sync_materializes_libraries -v`
Expected: FAIL — libraries are not materialized.

**Step 3: Implement**

Add a helper and call it from `_sync` (after `_copy_updated_assets`,
`presets/__init__.py:461`) and from the install/create path
(`install_preset_at_package`, line 881):

```python
def materialize_libraries(preset: Preset, pkg_root: pathlib.Path, is_contest: bool):
    from rbx.box.presets import library_fetch

    libs = preset.libraries.contest if is_contest else preset.libraries.problem
    for library in libs:
        cached = library_fetch.fetch_library(library)
        library_fetch.materialize_library(library, cached, pkg_root)
```

In `_sync`, load the active preset (it is already available via the lock /
`find_local_preset`; reuse whatever `_copy_updated_assets` uses to read the
preset) and call `materialize_libraries(preset, root, is_contest())` before
`generate_lock()`. Ensure materialized files are picked up by `generate_lock()`
so a later hand-edit is detected (they live at real package paths, so the
existing `build_package_locked_assets` snapshot covers them only if tracked — if
not, register them as additional `TrackedAsset(path=dest, symlink=...)` entries
when generating the lock).

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_presets.py -k sync_materializes_libraries -v`
Expected: PASS

Then the full presets suite: `uv run pytest tests/rbx/box/presets -v` — Expected: PASS.

**Step 5: Commit**

```
feat(presets): materialize declared libraries on create and sync
```

---

## Task 6: `always_include` compile injection

Add an injection path in `compile_item` that drops `always_include` libraries
into `__internal__/`, mirroring the bits injection. This is **additive** — it
runs alongside the still-present `maybe_add_testlib/jngen/tgen` (Task 7 removes
those). Dedup by `dest` so no double injection.

**Files:**
- Modify: `rbx/box/code.py`
- Create: `rbx/box/libraries.py` (small helper to load always_include libs)
- Test: `tests/rbx/box/test_code.py` (or the closest existing compile test file)

**Step 1: Write the failing test**

A C++ source in one directory that includes an `always_include` library declared
with a source in a different directory must compile. Build a package whose local
preset snapshot declares the library `always_include: true`, place a `.cpp` that
`#include`s it from a non-adjacent dir, compile, assert success.

> Read an existing compile test (e.g. how `compile_item` is exercised) and copy
> its harness. Keep the library source local.

**Step 2: Run to verify it fails**

Expected: FAIL — the include does not resolve (header not injected).

**Step 3: Implement**

`rbx/box/libraries.py`:

```python
import functools
import pathlib
from typing import List

from rbx.box import package
from rbx.box.presets.schema import Library


@functools.cache
def get_always_include_libraries() -> List[Library]:
    """Active preset libraries flagged always_include, for the current package."""
    preset = package.get_local_preset_or_none()  # add if missing; else read .local.rbx
    if preset is None:
        return []
    is_contest = package.is_contest_package()  # use the existing predicate
    libs = preset.libraries.contest if is_contest else preset.libraries.problem
    return [lib for lib in libs if lib.always_include]
```

> Register `get_always_include_libraries.cache_clear` in
> `rbx.testing_utils.clear_all_functools_cache` (per `rbx/box/CLAUDE.md`).

In `rbx/box/code.py`, after the `maybe_add_*` calls (around line 677), inject:

```python
from rbx.box import libraries as _libraries

existing = {input.dest for input in artifacts.inputs}
for lib in _libraries.get_always_include_libraries():
    include_as = lib.include_as or pathlib.Path(
        (lib.path or lib.dest).name
    )
    dest = steps.INTERNAL_DIR / include_as
    if dest in existing:
        continue
    src = package.get_root_dir() / lib.dest  # the materialized file
    artifacts.inputs.append(steps.GradingFileInput(src=src, dest=dest))
    existing.add(dest)
```

The existing bits block (lines 698-709) already adds `-I__internal__` only when
bits is present. Ensure `-I__internal__` is also added when any always_include
library was injected: extend that block's condition to also fire when the loop
above appended at least one internal input. (Simplest: set a
`needs_internal_include` flag and OR it with `bits_artifact is not None`.)

**Step 4: Run to verify it passes**

Run the new compile test — Expected: PASS.

**Step 5: Commit**

```
feat(code): inject always_include libraries into __internal__
```

---

## Task 7: Default preset declares `testlib`; drop committed `testlib.h`

Make the default preset provide `testlib` via the new mechanism BEFORE removing
the hardcoded injection.

**Files:**
- Modify: `rbx/resources/presets/default/preset.rbx.yml`
- Delete: `rbx/resources/presets/default/problem/testlib.h`
- Modify (if needed): `rbx/resources/presets/default/problem/problem.rbx.yml`
- Test: an e2e/create smoke test

**Step 1: Write/extend the failing test**

A test that creates a problem from the default preset and builds it must still
find `testlib.h`. Reuse existing create/build smoke tests if present; otherwise
add one that runs `rbx problem create` from the default preset and asserts
`testlib.h` is materialized at its `dest` and the validator/generator compiles.

**Step 2: Run to verify it fails** (after deleting the committed `testlib.h`)

Expected: FAIL — `testlib.h` missing until declared.

**Step 3: Implement**

In `rbx/resources/presets/default/preset.rbx.yml` add:

```yaml
libraries:
  problem:
    - name: testlib
      source: MikeMirzayanov/testlib
      path: testlib.h
      version: latest          # pin to a tag/commit to freeze the view
      dest: testlib.h
      always_include: true
```

Confirm `dest` matches where `gen.cpp`/`validator.cpp` include `testlib.h` from
(today: `#include "testlib.h"` with the file beside them or via always_include).
With `always_include: true`, location-independence is preserved.

Delete the committed `rbx/resources/presets/default/problem/testlib.h`.

> NOTE: this test will hit the network on first run (no offline fallback, by
> design). Mark it `@pytest.mark.slow`/`docker` as appropriate, or pin
> `version` to a tag and seed the cache in a fixture. Prefer a **local-source**
> variant in unit tests and keep the real-network test in e2e.

**Step 4: Run to verify it passes**

Expected: PASS.

**Step 5: Commit**

```
feat(presets): declare testlib as a default-preset library
```

---

## Task 8: Patch test fixtures that rely on jngen/tgen

**Files:**
- Test fixtures under `tests/` and `rbx/resources/presets/` (discover first)

**Step 1: Discover**

Run: `grep -rIl "jngen\|tgen" tests rbx/resources | sort`
Read each hit; identify which compile sources `#include "jngen.h"`/`"tgen.h"`.

**Step 2: For each affected fixture**

Add a `libraries` declaration (local source or pinned remote, `always_include:
true`) to that fixture's preset, OR commit the header next to the source so
auto-expansion resolves it. Prefer a local-source library to stay offline.

**Step 3: Run the affected suites** — Expected: PASS.

**Step 4: Commit**

```
test: declare jngen/tgen libraries in fixtures that use them
```

---

## Task 9: Clean cut — remove hardcoded testlib/jngen/tgen

Now that `testlib` (and any fixtures' jngen/tgen) come from presets, remove the
hardcoded injection and downloaders.

**Files:**
- Modify: `rbx/box/code.py:674-676` (remove the three `maybe_add_*` calls)
- Modify: `rbx/box/download.py` (remove `maybe_add_testlib/jngen/tgen`, `get_local_artifact` testlib/jngen/tgen usage; keep `maybe_add_rbx_header`)
- Modify: `rbx/grading/steps.py` (remove `testlib_grading_input/jngen_grading_input/tgen_grading_input`)
- Modify: `rbx/config.py` (remove `_download_testlib/_download_jngen/_download_tgen`, `get_testlib/get_jngen/get_tgen`, `download_testlib/download_jngen/download_tgen`)
- Delete: `rbx/resources/predownloaded/{testlib.h,jngen.h,tgen.h}` if present (keep `bits/stdc++.h`)

**Step 1: Make the edits.** Keep `bits/stdc++.h` and `rbx.h` paths intact
(`maybe_get_bits_stdcpp_for_commands`, `maybe_add_rbx_header`,
`get_bits_stdcpp`).

**Step 2: Fix references.** `grep -rn "maybe_add_testlib\|get_testlib\|download_testlib\|testlib_grading_input\|maybe_add_jngen\|maybe_add_tgen" rbx tests` and update/remove each.

**Step 3: Run the full suite**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: PASS (local C++/sandbox/docker failures noted in memory are
pre-existing and unrelated — verify any failures are in that known set).

**Step 4: Commit**

```
refactor: remove hardcoded testlib/jngen/tgen, sourced from presets now
```

---

## Task 10: Rework `rbx download`

**Files:**
- Modify: `rbx/box/download.py`
- Test: `tests/rbx/box/test_download.py` (create if absent)

**Step 1: Write the failing test**

`rbx download <name>` resolves `<name>` against the active preset's libraries and
materializes it (local source). `rbx download` (no name) materializes all.

**Step 2: Run to verify it fails.**

**Step 3: Implement**

Replace the hardcoded `testlib`/`jngen`/`tgen` subcommands with:

```python
@app.command('library, lib', help='Download a preset-declared library by name.')
@package.within_problem
def library(
    name: Optional[str] = typer.Argument(None),
    into: Optional[str] = typer.Option(None, '--into', help=_INTO_HELP),
):
    from rbx.box import libraries as _libraries
    from rbx.box.presets import library_fetch

    libs = _libraries.get_declared_libraries()  # all, for current pkg kind
    targets = libs if name is None else [l for l in libs if l.name == name]
    if name is not None and not targets:
        console.console.print(f'[error]No library named [item]{name}[/item].[/error]')
        raise typer.Exit(1)
    for lib in targets:
        cached = library_fetch.fetch_library(lib)
        if into is not None and name is not None:
            shutil.copyfile(cached, _resolve_download_target(lib.dest.name, into))
        else:
            library_fetch.materialize_library(lib, cached, package.get_root_dir())
```

Keep `rbx download checker` and `rbx download remote` unchanged. For backward
compat, keep `testlib`/`jngen`/`tgen` as thin aliases that call `library('testlib')`
etc. (they now resolve via the preset; if undeclared, the clear error above
fires). Add `get_declared_libraries()` to `rbx/box/libraries.py` (all libs for
the current package kind, not just always_include).

**Step 4: Run to verify it passes.**

**Step 5: Commit**

```
feat(download): resolve `rbx download` against preset libraries
```

---

## Task 11: Docs

**Files:**
- Modify: `docs/setters/presets/index.md`
- Modify: the `compilationFiles` field description in `rbx/box/schema.py:296`
  (remove "Testlib, jngen and tgen are already included by default" — no longer
  true; point to the `libraries` mechanism + `always_include`).

**Step 1:** Document the `libraries` block, source grammar, `version` semantics
(latest drifts, pin to freeze), copy vs symlink, `always_include`, and `rbx
download <name>`.

**Step 2:** Verify docs build (non-strict, per memory):
Run: `uv run mkdocs build` (ignore the ~9 known pre-existing strict warnings).

**Step 3: Commit**

```
docs: document preset libraries and update compilationFiles note
```

---

## Final verification

1. `uv run ruff check . && uv run ruff format --check .`
2. `uv run pytest --ignore=tests/rbx/box/cli -n auto` — green modulo the known
   pre-existing local failures (checker/validator/sandbox/docker).
3. Manually: `uv run rbx problem create` from the default preset, then
   `uv run rbx build` — `testlib.h` is materialized and the package builds.
4. Re-read the design doc; confirm every decision (1–8) is honored.
