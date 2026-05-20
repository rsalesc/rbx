# BOCA multi-language mapping (cc/cpp aliasing) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let one rbx language target multiple BOCA languages (forward `cc`+`cpp` from rbx `cpp`) via new `languages` + `template` fields, and migrate the default preset to the future shape. Legacy fields (`bocaLanguage`, env-level `languages`, `template` fallback) remain working for back-compat; their removal is tracked in issue #471.

**Architecture:** Add a plural `languages: List[str]` and a `template: Optional[str]` to `BocaLanguageExtension`, with computed accessors that fall back to the singular `bocaLanguage`. The forward map uses the first (primary) resolved BOCA language; the reverse map matches by membership. The packager iterates a **union** of `BocaExtension.languages` (default now `[]`) + resolved `languages` across every rbx language + a name-fallback safety net for zero-config users, and sources per-language compile/run/interactive templates from `resolved_template` rather than from the emitted BOCA name. The default preset declares `languages` + `template` on every language and drops the env-level `languages` list.

**Tech Stack:** Python 3.10+, Pydantic v2, Typer, pytest. Code lives under `rbx/box/packaging/boca/`; preset under `rbx/resources/presets/default/`.

**Design doc:** `docs/plans/2026-05-19-boca-multi-language-mapping-design.md`. **Follow-up issue:** #471 (full deprecation).

**Conventions:**
- Single quotes; absolute imports only; ruff `E4 E7 E9 F B I TID SLF`.
- Conventional Commits (commitizen) — use `/commit` skill or write compliant messages.
- Run `uv run pytest <path>` for tests; `uv run ruff check . && uv run ruff format .` before committing.

---

### Task 1: Add `languages` + `template` to `BocaLanguageExtension`

**Files:**
- Modify: `rbx/box/packaging/boca/extension.py:27-29`
- Create: `tests/rbx/box/packaging/boca/__init__.py` (empty, if not already present)
- Create: `tests/rbx/box/packaging/boca/test_extension.py`

**Step 1: Write failing tests**

```python
# tests/rbx/box/packaging/boca/test_extension.py
from rbx.box.packaging.boca.extension import BocaLanguageExtension


def test_resolved_languages_uses_plural_when_set():
    ext = BocaLanguageExtension(languages=['cc', 'cpp'])
    assert ext.resolved_languages == ['cc', 'cpp']
    assert ext.primary_language == 'cc'


def test_resolved_languages_falls_back_to_singular():
    ext = BocaLanguageExtension(bocaLanguage='cc')
    assert ext.resolved_languages == ['cc']
    assert ext.primary_language == 'cc'


def test_resolved_languages_empty_when_unset():
    ext = BocaLanguageExtension()
    assert ext.resolved_languages == []
    assert ext.primary_language is None


def test_resolved_template_uses_explicit_when_set():
    ext = BocaLanguageExtension(languages=['cc', 'cpp'], template='cc')
    assert ext.resolved_template == 'cc'


def test_resolved_template_falls_back_to_primary():
    ext = BocaLanguageExtension(languages=['cc', 'cpp'])
    assert ext.resolved_template == 'cc'


def test_resolved_template_falls_back_through_singular():
    ext = BocaLanguageExtension(bocaLanguage='py3')
    assert ext.resolved_template == 'py3'


def test_resolved_template_none_when_unset():
    ext = BocaLanguageExtension()
    assert ext.resolved_template is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_extension.py -v`
Expected: ALL FAIL (`AttributeError` / `ValidationError` for unknown fields).

**Step 3: Implement on `BocaLanguageExtension`**

Replace lines 27-29 of `rbx/box/packaging/boca/extension.py` with:

```python
class BocaLanguageExtension(BaseModel):
    # Deprecated: use `languages` instead. Kept for back-compat (see issue #471).
    bocaLanguage: typing.Optional[str] = Field(
        default=None,
        deprecated='Use `languages` instead.',
    )
    # BOCA languages this rbx language maps to. First entry is the canonical/primary,
    # used as the forward (rbx -> BOCA) mapping. All entries are emitted as separate
    # per-language script dirs in the BOCA package (e.g. ['cc', 'cpp'] emits both).
    languages: typing.Optional[typing.List[str]] = None
    # On-disk BOCA template dir (under rbx/resources/packagers/boca/{compile,run,
    # interactive}/) to source per-language scripts from. Falls back to
    # primary_language for back-compat (see issue #471).
    template: typing.Optional[str] = None

    @property
    def resolved_languages(self) -> typing.List[str]:
        if self.languages:
            return self.languages
        if self.bocaLanguage:
            return [self.bocaLanguage]
        return []

    @property
    def primary_language(self) -> typing.Optional[str]:
        langs = self.resolved_languages
        return langs[0] if langs else None

    @property
    def resolved_template(self) -> typing.Optional[str]:
        return self.template or self.primary_language
```

Add `Field` to the pydantic import at the top: `from pydantic import BaseModel, Field`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_extension.py -v`
Expected: 7 PASSED.

**Step 5: Commit**

```bash
git add rbx/box/packaging/boca/extension.py tests/rbx/box/packaging/boca/
git commit -m "feat(boca): add languages and template to language extension"
```

---

### Task 2: Update forward map to use `primary_language`

**Files:**
- Modify: `rbx/box/packaging/boca/boca_language_utils.py:27-43`
- Create: `tests/rbx/box/packaging/boca/test_language_utils.py`

**Step 1: Write failing test**

Create `tests/rbx/box/packaging/boca/test_language_utils.py`. The unit under test only depends on `get_environment`/`get_language`, so patch those directly.

```python
# tests/rbx/box/packaging/boca/test_language_utils.py
from unittest import mock

import pytest

from rbx.box.packaging.boca import boca_language_utils
from rbx.box.packaging.boca.extension import BocaLanguageExtension


def _mk_language(name: str, ext: BocaLanguageExtension | None = None):
    lang = mock.MagicMock()
    lang.name = name
    lang.get_extension_or_default.return_value = ext or BocaLanguageExtension()
    return lang


def test_forward_map_uses_primary_from_languages(monkeypatch):
    cpp_lang = _mk_language(
        'cpp', BocaLanguageExtension(languages=['cc', 'cpp'])
    )
    monkeypatch.setattr(boca_language_utils, 'get_language', lambda n: cpp_lang)
    env = mock.MagicMock()
    env.extensions = None
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_boca_language_from_rbx_language('cpp') == 'cc'
```

**Step 2: Run test, expect failure**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_language_utils.py::test_forward_map_uses_primary_from_languages -v`
Expected: FAIL (current code reads `bocaLanguage`, which is None, so it falls through and raises `ValueError`).

**Step 3: Implement**

In `rbx/box/packaging/boca/boca_language_utils.py`, replace lines 27-43 (`get_boca_language_from_rbx_language`) so the first branch uses the new accessor:

```python
def get_boca_language_from_rbx_language(rbx_language: str) -> BocaLanguage:
    language = get_language(rbx_language)
    language_extension = language.get_extension_or_default(
        'boca', BocaLanguageExtension
    )
    primary = language_extension.primary_language
    if primary:
        return typing.cast(BocaLanguage, primary)
    env = get_environment()
    if (
        env.extensions is not None
        and env.extensions.boca is not None
        and rbx_language.lower() in env.extensions.boca.languages
    ):
        return typing.cast(BocaLanguage, rbx_language.lower())
    if rbx_language.lower() in typing.get_args(BocaLanguage):
        return typing.cast(BocaLanguage, rbx_language.lower())
    raise ValueError(f'No Boca language found for Rbx language {rbx_language}')
```

**Step 4: Run test, expect pass**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_language_utils.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/packaging/boca/boca_language_utils.py tests/rbx/box/packaging/boca/test_language_utils.py
git commit -m "feat(boca): forward map reads primary_language"
```

---

### Task 3: Update reverse map to membership in `resolved_languages`

**Files:**
- Modify: `rbx/box/packaging/boca/boca_language_utils.py:11-24`
- Extend: `tests/rbx/box/packaging/boca/test_language_utils.py`

**Step 1: Add failing tests**

Append to `tests/rbx/box/packaging/boca/test_language_utils.py`:

```python
def test_reverse_map_resolves_alias_via_membership(monkeypatch):
    cpp_lang = _mk_language(
        'cpp', BocaLanguageExtension(languages=['cc', 'cpp'])
    )
    env = mock.MagicMock()
    env.languages = [cpp_lang]
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)
    monkeypatch.setattr(
        boca_language_utils, 'get_language_by_extension_or_nil', lambda _: None
    )

    assert boca_language_utils.get_rbx_language_from_boca_language('cc') == 'cpp'
    assert boca_language_utils.get_rbx_language_from_boca_language('cpp') == 'cpp'


def test_reverse_map_back_compat_with_singular(monkeypatch):
    py_lang = _mk_language('py', BocaLanguageExtension(bocaLanguage='py3'))
    env = mock.MagicMock()
    env.languages = [py_lang]
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)
    monkeypatch.setattr(
        boca_language_utils, 'get_language_by_extension_or_nil', lambda _: None
    )

    assert boca_language_utils.get_rbx_language_from_boca_language('py3') == 'py'
```

**Step 2: Run, expect failure**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_language_utils.py -v`
Expected: the alias test FAILS for `cpp` (current code only checks equality on the singular).

**Step 3: Implement membership check**

Replace lines 11-24 of `rbx/box/packaging/boca/boca_language_utils.py`:

```python
def get_rbx_language_from_boca_language(boca_language: BocaLanguage) -> str:
    # First by BOCA language membership in the rbx language's resolved targets.
    for language in get_environment().languages:
        language_extension = language.get_extension_or_default(
            'boca', BocaLanguageExtension
        )
        if boca_language in language_extension.resolved_languages:
            return language.name
    # Then by rbx language extension.
    language_by_extension = get_language_by_extension_or_nil(boca_language)
    if language_by_extension is not None:
        return language_by_extension.name
    # Then by rbx language name.
    return boca_language
```

**Step 4: Run, expect pass**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_language_utils.py -v`
Expected: ALL PASS.

**Step 5: Commit**

```bash
git add rbx/box/packaging/boca/boca_language_utils.py tests/rbx/box/packaging/boca/test_language_utils.py
git commit -m "feat(boca): reverse map matches by membership in resolved_languages"
```

---

### Task 4: Default `BocaExtension.languages` to `[]`

**Files:**
- Modify: `rbx/box/packaging/boca/extension.py:11`
- Extend: `tests/rbx/box/packaging/boca/test_extension.py`

**Step 1: Add failing test**

Append to `tests/rbx/box/packaging/boca/test_extension.py`:

```python
from rbx.box.packaging.boca.extension import BocaExtension


def test_boca_extension_languages_defaults_to_empty():
    assert BocaExtension().languages == []
```

**Step 2: Run, expect failure**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_extension.py::test_boca_extension_languages_defaults_to_empty -v`
Expected: FAIL (current default is `list(typing.get_args(BocaLanguage))`).

**Step 3: Implement**

In `rbx/box/packaging/boca/extension.py:11`, change:

```python
    languages: typing.List[BocaLanguage] = list(typing.get_args(BocaLanguage))
```

to:

```python
    languages: typing.List[BocaLanguage] = []
```

**Step 4: Run, expect pass**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_extension.py -v`
Expected: ALL PASS (8 total).

**Step 5: Commit**

```bash
git add rbx/box/packaging/boca/extension.py tests/rbx/box/packaging/boca/test_extension.py
git commit -m "feat(boca): default BocaExtension.languages to empty list"
```

---

### Task 5: Add emitted-set helper (union + name-fallback)

**Files:**
- Modify: `rbx/box/packaging/boca/boca_language_utils.py` (append helper)
- Extend: `tests/rbx/box/packaging/boca/test_language_utils.py`

This helper is what `packager.py` will iterate in place of `BocaExtension.languages` directly.

**Step 1: Add failing tests**

Append to `tests/rbx/box/packaging/boca/test_language_utils.py`:

```python
from rbx.box.packaging.boca.extension import BocaExtension


def _mk_env(languages, boca_ext_languages=None):
    env = mock.MagicMock()
    env.languages = languages
    if boca_ext_languages is None:
        env.extensions = None
    else:
        env.extensions = mock.MagicMock()
        env.extensions.boca = BocaExtension(languages=boca_ext_languages)
    return env


def test_emitted_set_union_from_languages(monkeypatch):
    env = _mk_env(
        [
            _mk_language('cpp', BocaLanguageExtension(languages=['cc', 'cpp'])),
            _mk_language('py', BocaLanguageExtension(bocaLanguage='py3')),
        ]
    )
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_emitted_boca_languages() == ['cc', 'cpp', 'py3']


def test_emitted_set_includes_env_level_languages(monkeypatch):
    env = _mk_env(
        [_mk_language('cpp', BocaLanguageExtension(languages=['cc']))],
        boca_ext_languages=['java'],
    )
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_emitted_boca_languages() == ['cc', 'java']


def test_emitted_set_name_fallback_for_zero_config(monkeypatch):
    # rbx language named 'c' with NO boca extension -> contributes 'c'.
    c_lang = _mk_language('c', BocaLanguageExtension())  # empty boca ext
    env = _mk_env([c_lang])
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_emitted_boca_languages() == ['c']


def test_emitted_set_deduplicates_and_preserves_order(monkeypatch):
    env = _mk_env(
        [
            _mk_language('cpp', BocaLanguageExtension(languages=['cc', 'cpp'])),
            _mk_language('cc', BocaLanguageExtension(languages=['cc'])),
        ]
    )
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_emitted_boca_languages() == ['cc', 'cpp']
```

**Step 2: Run, expect failure**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_language_utils.py -v`
Expected: 4 new tests FAIL (`AttributeError: module ... has no attribute 'get_emitted_boca_languages'`).

**Step 3: Implement**

Append to `rbx/box/packaging/boca/boca_language_utils.py`:

```python
def get_emitted_boca_languages() -> typing.List[BocaLanguage]:
    """Return the ordered, deduplicated set of BOCA languages to emit per-language
    script dirs for. Union of:
      1. Resolved languages across every enabled rbx language.
      2. Env-level extensions.boca.languages (back-compat).
      3. Name fallback: rbx language whose name is itself a valid BocaLanguage and
         which declared no explicit boca extension.
    """
    seen: typing.Dict[str, None] = {}
    env = get_environment()
    boca_literals = set(typing.get_args(BocaLanguage))

    for language in env.languages:
        language_extension = language.get_extension_or_default(
            'boca', BocaLanguageExtension
        )
        resolved = language_extension.resolved_languages
        if resolved:
            for boca_lang in resolved:
                seen.setdefault(boca_lang, None)
        elif language.name in boca_literals:
            # Name-fallback safety net for zero-config users.
            seen.setdefault(language.name, None)

    if env.extensions is not None and env.extensions.boca is not None:
        for boca_lang in env.extensions.boca.languages:
            seen.setdefault(boca_lang, None)

    return typing.cast(typing.List[BocaLanguage], list(seen.keys()))
```

**Step 4: Run, expect pass**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_language_utils.py -v`
Expected: ALL PASS.

**Step 5: Commit**

```bash
git add rbx/box/packaging/boca/boca_language_utils.py tests/rbx/box/packaging/boca/test_language_utils.py
git commit -m "feat(boca): add get_emitted_boca_languages helper (union + name fallback)"
```

---

### Task 6: Packager uses emitted-set helper and `resolved_template`

**Files:**
- Modify: `rbx/box/packaging/boca/packager.py:262-405`

**Step 1: Audit current usage**

Read `rbx/box/packaging/boca/packager.py:340-410`. The five emission loops (`limits`, `compare`, `run`, `compile`, `tests`) all iterate `extension.languages`. The `run` loop sources its template from `… / 'run' / language` or `… / 'interactive' / language` — i.e. by emitted BOCA name. `_get_compile(language)` (line 271) does the same for the compile template. These two are the ones that must be redirected through `resolved_template`.

**Step 2: Write a regression-pinning test first**

Create `tests/rbx/box/packaging/boca/test_packager_emitted_set.py`. This test pins the wiring: the packager imports and uses `get_emitted_boca_languages` and `resolved_template`. Because the full packager is heavy to spin up end-to-end, these are import-level pins; Task 8 is the behavioral integration test.

```python
# tests/rbx/box/packaging/boca/test_packager_emitted_set.py
import inspect


def test_packager_iterates_emitted_set():
    """The BOCA packager must use get_emitted_boca_languages() rather than reading
    BocaExtension.languages directly, so that languages aliases are honored."""
    from rbx.box.packaging.boca import packager as pkgr

    src = inspect.getsource(pkgr)
    assert 'get_emitted_boca_languages' in src, (
        'packager.py must import and call get_emitted_boca_languages'
    )


def test_packager_sources_compile_template_via_resolved_template():
    """The compile/run template source dir must come from resolved_template,
    not from the emitted BOCA language name directly."""
    from rbx.box.packaging.boca import packager as pkgr

    src = inspect.getsource(pkgr)
    assert 'resolved_template' in src, (
        'packager.py must use resolved_template for compile/run template sourcing'
    )
```

**Step 3: Run, expect failure**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_packager_emitted_set.py -v`
Expected: 2 FAIL (symbols not yet referenced).

**Step 4: Implement packager changes**

In `rbx/box/packaging/boca/packager.py`:

1. Add to the imports at the top:
   ```python
   from rbx.box.environment import get_language
   from rbx.box.packaging.boca.boca_language_utils import (
       get_emitted_boca_languages,
       get_rbx_language_from_boca_language,
   )
   from rbx.box.packaging.boca.extension import BocaLanguageExtension
   ```
   (Adjust to merge with any existing imports from those modules; don't duplicate.)

2. Replace each of the five `for language in extension.languages:` loops (around lines 362, 368, 374, 397, 403) with `for language in emitted_languages:`. Just before the first such loop (right after `extension = …` is fetched, ~line 360), bind:
   ```python
   emitted_languages = get_emitted_boca_languages()
   ```

3. In the `run`-emission loop (lines 374-392), source the template from the rbx language's `resolved_template` instead of the emitted BOCA name:

   ```python
   for language in emitted_languages:
       rbx_language_name = get_rbx_language_from_boca_language(language)
       rbx_language = get_language(rbx_language_name)
       template_name = (
           rbx_language.get_extension_or_default('boca', BocaLanguageExtension)
           .resolved_template
           or language
       )
       sub = 'interactive' if pkg.type == TaskType.COMMUNICATION else 'run'
       run_orig_path = (
           get_default_app_path() / 'packagers' / 'boca' / sub / template_name
       )
       if not run_orig_path.is_file():
           console.console.print(
               f'[error]Run script for template [item]{template_name}[/item] not found for task of type [item]{pkg.type}[/item].[/error]'
           )
           raise typer.Exit(1)
       shutil.copyfile(run_orig_path, run_path / language)
       self._expand_run_script(run_path / language, language)
   ```

4. In `_get_compile(self, language)` (lines 267-297), source the template from `resolved_template`:

   ```python
   def _get_compile(self, language: BocaLanguage) -> str:
       pkg = package.find_problem_package_or_die()

       rbx_language_name = get_rbx_language_from_boca_language(language)
       rbx_language = get_language(rbx_language_name)
       template_name = (
           rbx_language.get_extension_or_default('boca', BocaLanguageExtension)
           .resolved_template
           or language
       )
       compile_path = (
           get_default_app_path()
           / 'packagers'
           / 'boca'
           / 'compile'
           / template_name
       )
       if not compile_path.is_file():
           console.console.print(
               f'[error]Compile script for template [item]{template_name}[/item] not found.[/error]'
           )
           raise typer.Exit(1)
       # ... rest of body unchanged (compile_text = compile_path.read_text() onward) ...
   ```

   Keep `_replace_common(compile_text, language)` keyed by the emitted BOCA language so per-emit flag overrides still apply.

**Step 5: Run new tests + existing packager tests**

```bash
uv run pytest tests/rbx/box/packaging/boca/test_packager_emitted_set.py -v
uv run pytest tests/rbx/box/packaging --ignore=tests/rbx/box/packaging/e2e -v
```

Expected: PASS. (e2e tests are docker-bound and intentionally skipped here.)

**Step 6: Commit**

```bash
git add rbx/box/packaging/boca/packager.py tests/rbx/box/packaging/boca/test_packager_emitted_set.py
git commit -m "feat(boca): packager iterates emitted set and sources templates via resolved_template"
```

---

### Task 7: Migrate the default preset

**Files:**
- Modify: `rbx/resources/presets/default/env.rbx.yml`

**Step 1: Update each language block**

In `rbx/resources/presets/default/env.rbx.yml`:

- Lines 16-27 (`cpp`): replace the `extensions.boca` block with:
  ```yaml
      extensions:
        boca:
          languages: ["cc", "cpp"]
          template: "cc"
        polygon:
          polygonLanguage: "cpp.gcc13-64-winlibs-g++20"
  ```

- Lines 28-34 (`c`): add an `extensions` block:
  ```yaml
      extensions:
        boca:
          languages: ["c"]
          template: "c"
  ```

- Lines 35-44 (`py`): replace the `extensions.boca` block with:
  ```yaml
      extensions:
        boca:
          languages: ["py3"]
          template: "py3"
  ```

- Lines 45-59 (`java`): add a boca sub-block under existing `extensions`:
  ```yaml
      extensions:
        boca:
          languages: ["java"]
          template: "java"
        polygon:
          polygonLanguage: "java21"
  ```

- Lines 60-73 (`kt`): replace the `extensions.boca` block with:
  ```yaml
      extensions:
        boca:
          languages: ["kt"]
          template: "kt"
  ```

- Lines 74-82 (env-level `extensions.boca`): **remove the `languages:` line**; keep `flags`, `preferContestLetter`, `usePypy` as-is.

**Step 2: Sanity-load the preset**

Run:
```bash
uv run python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('rbx/resources/presets/default/env.rbx.yml').read_text()); print('ok')"
```
Expected: `ok`.

**Step 3: Run the existing test suite (non-CLI, non-e2e)**

```bash
uv run pytest --ignore=tests/rbx/box/cli --ignore=tests/rbx/box/packaging/e2e -x
```
Expected: PASS.

**Step 4: Commit**

```bash
git add rbx/resources/presets/default/env.rbx.yml
git commit -m "feat(boca): migrate default preset to languages and template"
```

---

### Task 8: Integration check — cc/cpp aliasing produces identical scripts

**Files:**
- Create: `tests/rbx/box/packaging/boca/test_packager_integration.py`
- Possibly create: `tests/rbx/box/packaging/boca/testdata/aliased-cc-cpp/` (minimal fixture)

**Step 1: Locate (or minimize) a BOCA-buildable fixture**

Run `git grep -l "test_pkg" tests/rbx/box/packaging` and inspect existing packaging tests for the fixture pattern. If a BOCA-buildable testdata pkg already exists for non-e2e packager tests, reuse it. Otherwise minimize a copy of `tests/e2e/testdata/pkg-boca/` (problem.rbx.yml + a trivial cpp solution + a trivial generator) into `tests/rbx/box/packaging/boca/testdata/aliased-cc-cpp/`. Keep it tiny.

**Step 2: Write the integration test**

```python
# tests/rbx/box/packaging/boca/test_packager_integration.py
import pathlib
import zipfile

import pytest
from typer.testing import CliRunner

from rbx.box.cli import app


@pytest.mark.test_pkg('boca/testdata/aliased-cc-cpp')
def test_default_preset_emits_aliased_cc_and_cpp(cleandir_with_testdata):
    runner = CliRunner()
    # If the packager requires the 'boca' time profile, generate it first.
    runner.invoke(app, ['time', '-p', 'boca'])
    result = runner.invoke(app, ['package', 'build', '--packager', 'boca'])
    assert result.exit_code == 0, result.output

    builds = list(pathlib.Path('build').rglob('*.zip'))
    assert builds, 'no BOCA zip was produced'
    zip_path = builds[0]

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert any(n.endswith('compile/cc') for n in names)
        assert any(n.endswith('compile/cpp') for n in names)
        cc = zf.read(next(n for n in names if n.endswith('compile/cc')))
        cpp = zf.read(next(n for n in names if n.endswith('compile/cpp')))
    assert cc == cpp, 'compile/cc and compile/cpp must be identical (template aliasing)'
```

Match the conftest conventions for `test_pkg` fixture-path resolution. If `package build` output path differs from `build/`, adapt the rglob to wherever rbx writes the BOCA zip on the test fixture. Consult `rbx/box/packaging/main.py` and an existing packager test for the actual output location.

**Step 3: Run, expect pass**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_packager_integration.py -v`
Expected: PASS.

If failure exposes a missing piece in the testdata, iterate minimally (smallest possible self-contained BOCA-buildable package). If the test is too heavy for default CI, mark it `@pytest.mark.slow` so it stays runnable locally and in e2e jobs.

**Step 4: Commit**

```bash
git add tests/rbx/box/packaging/boca/test_packager_integration.py tests/rbx/box/packaging/boca/testdata/
git commit -m "test(boca): assert default preset emits aliased cc/cpp with identical scripts"
```

---

### Task 9: Final verification + lint + format

**Step 1: Run targeted suites**

```bash
uv run pytest tests/rbx/box/packaging/boca -v
uv run pytest --ignore=tests/rbx/box/cli --ignore=tests/rbx/box/packaging/e2e -n auto
```
Expected: ALL PASS.

**Step 2: Lint and format**

```bash
uv run ruff check --fix .
uv run ruff format .
```
Expected: no diagnostics; formatter reports unchanged or only the new files reformatted.

**Step 3: Commit any formatting drift**

```bash
git diff --quiet || (git add -A && git commit -m "style: ruff format")
```

**Step 4: Final smoke**

```bash
git log --oneline main..HEAD
```
Expected: a small linear series of focused commits matching tasks 1-8 (plus optional style commit).

---

## Sequencing notes

- Tasks 1-5 are pure schema/utility changes covered by unit tests; safe to run sequentially without integration.
- Task 6 is the only consumer-side change in the packager; it depends on tasks 1, 3, and 5.
- Task 7 (preset migration) is independent of tasks 1-6 at the code level but must land **after** task 4 (since dropping the env-level `languages` list relies on the new empty default).
- Task 8 validates the whole chain.

## Out of scope (tracked in #471)

- Removing `bocaLanguage`, env-level `languages`, and the `template` fallback.
- Adding load-time deprecation warnings for those fields.
- Migrating non-default presets/fixtures/docs to the new shape.
