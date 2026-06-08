# Preset Registry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the silent `default`-preset fallback with a registry-backed interactive picker, fed by a merged built-in + user-local registry, where every preset carries a description.

**Architecture:** A `PresetRegistry` (list of `RegistryPreset` entries with `name`/`uri`/`description`) is loaded from a built-in YAML shipped in `rbx/resources/presets/registry.yml` and merged with a user-local `<app_dir>/presets/registry.yml` (user entries win on name collision). The creation commands resolve a preset via `get_preset_fetch_info_with_fallback`, which now: uses an explicit `--preset`, else the active `.local.rbx` preset, else (interactive) shows a `questionary.select` over the merged registry, else (non-interactive) errors. `rbx presets registry {ls,add,rm}` manages the user file; using a new `--preset` interactively offers to register it.

**Tech Stack:** Python 3, Pydantic v2, Typer, questionary, ruyaml, pytest.

**Design doc:** `docs/plans/2026-06-08-preset-registry-design.md`

**Conventions:** Single quotes, absolute imports, ruff. Commit with the `/commit` skill (conventional commits). Run tests with `uv run pytest`. Default test command excludes CLI tests: append `--ignore=tests/rbx/box/cli` for full runs.

---

## Task 1: Add `description` to the `Preset` schema

**Files:**
- Modify: `rbx/box/presets/schema.py` (the `Preset` class, ~line 115)
- Modify: `rbx/resources/presets/default/preset.rbx.yml`
- Test: `tests/rbx/box/presets/test_presets_additions_test.py`

**Step 1: Write the failing test**

Add to `tests/rbx/box/presets/test_presets_additions_test.py`:

```python
class TestPresetDescription:
    def test_preset_description_defaults_to_empty(self):
        from rbx.box.presets.schema import Preset

        p = Preset(name='abc', uri='owner/repo')
        assert p.description == ''

    def test_preset_description_roundtrips(self):
        from rbx.box.presets.schema import Preset

        p = Preset(name='abc', uri='owner/repo', description='Hello')
        assert p.description == 'Hello'

    def test_default_preset_has_description(self):
        from rbx.box.presets import get_preset_yaml
        from rbx.config import get_default_app_path

        preset = get_preset_yaml(get_default_app_path() / 'presets' / 'default')
        assert preset.description.strip() != ''
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_presets_additions_test.py::TestPresetDescription -v`
Expected: FAIL (`description` attribute does not exist / default preset has no description).

**Step 3: Implement**

In `rbx/box/presets/schema.py`, add to `Preset` right after the `name` field (keep the existing `NameField`/`Field` import already present):

```python
    # Human-readable description of the preset, shown in the preset registry
    # picker. This is the canonical home of the description; the registry keeps
    # a denormalized copy for display.
    description: str = Field(default='')
```

In `rbx/resources/presets/default/preset.rbx.yml`, add a `description` line just under `name`:

```yaml
name: "default"
description: "rbx's default preset: ICPC-style problem/contest with testlib, jngen and tgen."
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_presets_additions_test.py::TestPresetDescription -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/presets/schema.py rbx/resources/presets/default/preset.rbx.yml tests/rbx/box/presets/test_presets_additions_test.py
git commit -m "feat(presets): add description field to preset schema"
```

> Note: the published JSON schema (`schemas/Preset.json`) is generated at docs build time by `rbx/box/dump_schemas.py` via `mkdocs_gen_files`; it is not committed, so no regeneration step is needed here.

---

## Task 2: Registry schema (`RegistryPreset`, `PresetRegistry`)

**Files:**
- Create: `rbx/box/presets/registry_schema.py`
- Test: `tests/rbx/box/presets/test_registry.py`

**Step 1: Write the failing test**

Create `tests/rbx/box/presets/test_registry.py`:

```python
import pytest

from rbx.box.presets.registry_schema import PresetRegistry, RegistryPreset


class TestRegistrySchema:
    def test_entry_requires_name_and_uri(self):
        e = RegistryPreset(name='default', uri='default')
        assert e.name == 'default'
        assert e.uri == 'default'
        assert e.description == ''

    def test_registry_defaults_to_empty(self):
        assert PresetRegistry().presets == []

    def test_name_pattern_enforced(self):
        with pytest.raises(Exception):
            RegistryPreset(name='a', uri='x')  # too short for NameField
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_registry.py -v`
Expected: FAIL (module does not exist).

**Step 3: Implement**

Create `rbx/box/presets/registry_schema.py`:

```python
from typing import List

from pydantic import BaseModel

from rbx.box.presets.schema import NameField


class RegistryPreset(BaseModel):
    # Logical name of the preset (must be unique within the registry).
    name: str = NameField()

    # URI used to fetch the preset. Uses the same grammar as Preset.uri and is
    # resolved by get_preset_fetch_info (owner/repo, @gh/..., full URL, a local
    # path, or a bundled tool-preset name such as 'default').
    uri: str

    # Denormalized copy of the preset's description, captured at registration
    # time so the picker can display it without resolving the preset.
    description: str = ''


class PresetRegistry(BaseModel):
    presets: List[RegistryPreset] = []
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_registry.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/presets/registry_schema.py tests/rbx/box/presets/test_registry.py
git commit -m "feat(presets): add registry schema models"
```

---

## Task 3: Ship the built-in registry resource

**Files:**
- Create: `rbx/resources/presets/registry.yml`
- Test: `tests/rbx/box/presets/test_registry.py`

**Step 1: Write the failing test**

Append to `tests/rbx/box/presets/test_registry.py`:

```python
class TestBuiltinRegistry:
    def test_builtin_registry_loads_and_has_default(self):
        from rbx.box.presets import registry

        reg = registry.get_builtin_registry()
        names = {p.name for p in reg.presets}
        assert 'default' in names

    def test_builtin_default_entry_has_description(self):
        from rbx.box.presets import registry

        reg = registry.get_builtin_registry()
        default = next(p for p in reg.presets if p.name == 'default')
        assert default.uri == 'default'
        assert default.description.strip() != ''
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_registry.py::TestBuiltinRegistry -v`
Expected: FAIL (`registry` module / resource missing).

**Step 3: Implement**

Create `rbx/resources/presets/registry.yml`:

```yaml
# yaml-language-server: $schema=https://rsalesc.github.io/rbx/schemas/PresetRegistry.json
presets:
  - name: "default"
    uri: "default"
    description: "rbx's default preset: ICPC-style problem/contest with testlib, jngen and tgen."
```

(The `registry` module itself is implemented in Task 4; this task only adds the
resource + tests that Task 4 will satisfy. If executing strictly task-by-task,
the Task 3 tests fail until Task 4 lands — acceptable since they are committed
together conceptually. To keep each task green, implement Task 4's
`get_builtin_registry` in this step too, OR run Task 3 and Task 4 tests together
after Task 4. Recommended: do Task 3 resource + Task 4 code, then run both test
classes.)

**Step 4 & 5:** Defer the green run + commit to the end of Task 4 (they share the `registry` module).

---

## Task 4: Registry load / merge / mutate API

**Files:**
- Create: `rbx/box/presets/registry.py`
- Test: `tests/rbx/box/presets/test_registry.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/box/presets/test_registry.py`:

```python
class TestRegistryMergeAndMutate:
    def test_user_registry_path_under_app_dir(self, monkeypatch, tmp_path):
        from rbx.box.presets import registry
        from rbx import utils

        monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
        assert registry.user_registry_path() == tmp_path / 'presets' / 'registry.yml'

    def test_user_registry_empty_when_missing(self, monkeypatch, tmp_path):
        from rbx.box.presets import registry
        from rbx import utils

        monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
        assert registry.get_user_registry().presets == []

    def test_merge_unions_builtin_and_user(self, monkeypatch, tmp_path):
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import RegistryPreset

        monkeypatch.setattr(
            registry,
            'get_user_registry',
            lambda: registry.PresetRegistry(
                presets=[RegistryPreset(name='mine', uri='me/repo', description='d')]
            ),
        )
        merged = registry.get_merged_registry()
        names = [p.name for p in merged.presets]
        assert 'default' in names and 'mine' in names
        # built-ins first
        assert names.index('default') < names.index('mine')

    def test_user_entry_wins_on_name_collision(self, monkeypatch):
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import RegistryPreset

        monkeypatch.setattr(
            registry,
            'get_user_registry',
            lambda: registry.PresetRegistry(
                presets=[RegistryPreset(name='default', uri='custom/uri', description='x')]
            ),
        )
        merged = registry.get_merged_registry()
        default = next(p for p in merged.presets if p.name == 'default')
        assert default.uri == 'custom/uri'

    def test_add_and_remove_user_entry(self, monkeypatch, tmp_path):
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import RegistryPreset
        from rbx import utils

        monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
        registry.add_to_user_registry(
            RegistryPreset(name='foo', uri='o/r', description='bar')
        )
        assert any(p.name == 'foo' for p in registry.get_user_registry().presets)
        removed = registry.remove_from_user_registry('foo')
        assert removed is True
        assert not any(p.name == 'foo' for p in registry.get_user_registry().presets)

    def test_add_replaces_existing_user_entry(self, monkeypatch, tmp_path):
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import RegistryPreset
        from rbx import utils

        monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
        registry.add_to_user_registry(RegistryPreset(name='foo', uri='a', description='1'))
        registry.add_to_user_registry(RegistryPreset(name='foo', uri='b', description='2'))
        entries = [p for p in registry.get_user_registry().presets if p.name == 'foo']
        assert len(entries) == 1
        assert entries[0].uri == 'b'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_registry.py -v`
Expected: FAIL (module / functions missing).

**Step 3: Implement**

Create `rbx/box/presets/registry.py`:

```python
import pathlib
from typing import Optional

import ruyaml

from rbx import utils
from rbx.box.presets.registry_schema import PresetRegistry, RegistryPreset
from rbx.box.yaml_validation import load_yaml_model
from rbx.config import get_default_app_path


def builtin_registry_path() -> pathlib.Path:
    return get_default_app_path() / 'presets' / 'registry.yml'


def user_registry_path() -> pathlib.Path:
    return utils.get_app_path() / 'presets' / 'registry.yml'


def get_builtin_registry() -> PresetRegistry:
    path = builtin_registry_path()
    if not path.is_file():
        return PresetRegistry()
    return load_yaml_model(path, PresetRegistry)


def get_user_registry() -> PresetRegistry:
    path = user_registry_path()
    if not path.is_file():
        return PresetRegistry()
    return load_yaml_model(path, PresetRegistry)


def get_merged_registry() -> PresetRegistry:
    builtin = get_builtin_registry()
    user = get_user_registry()
    user_by_name = {p.name: p for p in user.presets}

    merged = []
    seen = set()
    # Built-ins first; a user entry with the same name overrides it.
    for p in builtin.presets:
        merged.append(user_by_name.get(p.name, p))
        seen.add(p.name)
    # Then user-only entries, in their declared order.
    for p in user.presets:
        if p.name not in seen:
            merged.append(p)
            seen.add(p.name)
    return PresetRegistry(presets=merged)


def _save_user_registry(reg: PresetRegistry) -> None:
    path = user_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = ruyaml.YAML(typ='rt')
    with path.open('w') as f:
        yaml.dump(reg.model_dump(mode='python'), f)


def add_to_user_registry(entry: RegistryPreset) -> None:
    reg = get_user_registry()
    reg.presets = [p for p in reg.presets if p.name != entry.name]
    reg.presets.append(entry)
    _save_user_registry(reg)


def remove_from_user_registry(name: str) -> bool:
    reg = get_user_registry()
    before = len(reg.presets)
    reg.presets = [p for p in reg.presets if p.name != name]
    if len(reg.presets) == before:
        return False
    _save_user_registry(reg)
    return True


def find_in_registry(uri_or_name: str) -> Optional[RegistryPreset]:
    for p in get_merged_registry().presets:
        if p.name == uri_or_name or p.uri == uri_or_name:
            return p
    return None
```

Re-export the schema names for convenience at the top of the module body if a
test imports `registry.PresetRegistry` (the test above uses
`registry.PresetRegistry`); the `from ... import PresetRegistry, RegistryPreset`
line already binds them into the module namespace.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_registry.py -v`
Expected: PASS (Task 3 + Task 4 classes all green).

**Step 5: Commit**

```bash
git add rbx/box/presets/registry.py rbx/resources/presets/registry.yml tests/rbx/box/presets/test_registry.py
git commit -m "feat(presets): add merged preset registry (builtin + user)"
```

---

## Task 5: Interactivity check + interactive picker

**Files:**
- Create/Modify: `rbx/box/presets/registry.py` (add `is_interactive`, `pick_preset`)
- Test: `tests/rbx/box/presets/test_registry.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/box/presets/test_registry.py`:

```python
class TestPicker:
    def test_pick_returns_selected_entry(self, monkeypatch):
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import PresetRegistry, RegistryPreset

        entry = RegistryPreset(name='default', uri='default', description='d')
        monkeypatch.setattr(
            registry,
            'get_merged_registry',
            lambda: PresetRegistry(presets=[entry]),
        )

        class FakeSelect:
            def ask(self_inner):
                return 'default'

        monkeypatch.setattr(
            registry.questionary, 'select', lambda *a, **k: FakeSelect()
        )
        chosen = registry.pick_preset()
        assert chosen is entry

    def test_pick_raises_exit_on_cancel(self, monkeypatch):
        import click

        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import PresetRegistry, RegistryPreset

        monkeypatch.setattr(
            registry,
            'get_merged_registry',
            lambda: PresetRegistry(
                presets=[RegistryPreset(name='default', uri='default')]
            ),
        )

        class FakeSelect:
            def ask(self_inner):
                return None  # user hit Ctrl-C

        monkeypatch.setattr(
            registry.questionary, 'select', lambda *a, **k: FakeSelect()
        )
        with pytest.raises(click.exceptions.Exit):
            registry.pick_preset()
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_registry.py::TestPicker -v`
Expected: FAIL (`questionary` / `pick_preset` not present).

**Step 3: Implement**

Add to `rbx/box/presets/registry.py` (add imports `import sys`, `import questionary`, `import typer`, `from rbx import console`):

```python
def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def pick_preset() -> RegistryPreset:
    reg = get_merged_registry()
    if not reg.presets:
        console.console.print('[error]No presets available in the registry.[/error]')
        raise typer.Exit(1)

    by_name = {p.name: p for p in reg.presets}
    choices = [
        questionary.Choice(
            title=f'{p.name} — {p.description}' if p.description else p.name,
            value=p.name,
        )
        for p in reg.presets
    ]
    default_value = 'default' if 'default' in by_name else reg.presets[0].name
    answer = questionary.select(
        'Which preset do you want to use?',
        choices=choices,
        default=default_value,
    ).ask()
    if answer is None:
        raise typer.Exit(1)
    return by_name[answer]
```

> `questionary.Choice` `default` matches by `value`; passing the name string is
> correct. If a future questionary version rejects a string default, pass the
> matching `Choice` object instead.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_registry.py::TestPicker -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/presets/registry.py tests/rbx/box/presets/test_registry.py
git commit -m "feat(presets): add interactive registry picker"
```

---

## Task 6: Rewire `get_preset_fetch_info_with_fallback`

**Files:**
- Modify: `rbx/box/presets/__init__.py` (`get_preset_fetch_info_with_fallback`, ~line 600)
- Test: `tests/rbx/box/presets/test_presets_additions_test.py`

**Step 1: Update the failing tests**

Replace `TestGetPresetFetchInfoWithFallback` in
`tests/rbx/box/presets/test_presets_additions_test.py` with:

```python
class TestGetPresetFetchInfoWithFallback:
    def test_explicit_uri_resolves(self, monkeypatch):
        dummy = SimpleNamespace(name='p', uri='o/r')
        monkeypatch.setattr(
            presets, 'get_preset_fetch_info', lambda uri, local=False: dummy
        )
        assert presets.get_preset_fetch_info_with_fallback('o/r') is dummy

    def test_none_uri_returns_none_when_active_preset_exists(self, monkeypatch):
        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): SimpleNamespace()
        )
        assert presets.get_preset_fetch_info_with_fallback(None) is None

    def test_none_uri_interactive_uses_picker(self, monkeypatch):
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import RegistryPreset

        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): None
        )
        monkeypatch.setattr(registry, 'is_interactive', lambda: True)
        monkeypatch.setattr(
            registry, 'pick_preset', lambda: RegistryPreset(name='default', uri='default')
        )
        dummy = SimpleNamespace(name='default', uri='default')
        monkeypatch.setattr(
            presets, 'get_preset_fetch_info', lambda uri, local=False: dummy
        )
        assert presets.get_preset_fetch_info_with_fallback(None) is dummy

    def test_none_uri_non_interactive_errors(self, monkeypatch):
        import click
        from rbx.box.presets import registry

        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): None
        )
        monkeypatch.setattr(registry, 'is_interactive', lambda: False)
        with pytest.raises(click.exceptions.Exit):
            presets.get_preset_fetch_info_with_fallback(None)
```

(Delete the old `test_none_uri_uses_default_when_no_active_preset` and
`test_missing_default_preset_errors` — the silent-default behavior is gone.)

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_presets_additions_test.py::TestGetPresetFetchInfoWithFallback -v`
Expected: FAIL (current implementation still falls back to default).

**Step 3: Implement**

In `rbx/box/presets/__init__.py`, add an import near the other preset imports:

```python
from rbx.box.presets import registry as preset_registry
```

Replace the body of `get_preset_fetch_info_with_fallback`:

```python
def get_preset_fetch_info_with_fallback(
    uri: Optional[str],
    local: bool = False,
) -> Optional[PresetFetchInfo]:
    if uri is not None:
        return get_preset_fetch_info(uri, local=local)

    # No explicit preset: prefer the active preset in the cwd.
    if get_active_preset_or_null() is not None:
        return None

    # No active preset: choose from the registry.
    if not preset_registry.is_interactive():
        console.console.print(
            '[error]No preset selected and no active preset found.[/error]'
        )
        console.console.print(
            'Pass [item]--preset <name-or-uri>[/item] (e.g. [item]--preset default[/item]) '
            'or run interactively to pick from the registry.'
        )
        raise typer.Exit(1)

    chosen = preset_registry.pick_preset()
    return get_preset_fetch_info(chosen.uri, local=local)
```

Remove the now-unused `_FALLBACK_PRESET_NAME` constant only if nothing else
references it — grep first: `grep -rn "_FALLBACK_PRESET_NAME" rbx/`. If unused,
delete its definition (line ~35); if referenced, leave it.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_presets_additions_test.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/presets/__init__.py tests/rbx/box/presets/test_presets_additions_test.py
git commit -m "feat(presets): pick preset from registry instead of silent default"
```

---

## Task 7: `presets registry` CLI sub-commands (ls / add / rm)

**Files:**
- Modify: `rbx/box/presets/__init__.py` (register a `registry` sub-Typer)
- Test: `tests/rbx/box/presets/test_registry_cli.py`

**Step 1: Write the failing tests**

Create `tests/rbx/box/presets/test_registry_cli.py`:

```python
import pathlib

import pytest
from typer.testing import CliRunner

from rbx.box import presets
from rbx.box.presets import registry
from rbx.box.presets.registry_schema import RegistryPreset

runner = CliRunner()


@pytest.fixture
def isolated_app_dir(monkeypatch, tmp_path):
    from rbx import utils

    monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
    return tmp_path


class TestRegistryLs:
    def test_ls_lists_default(self, isolated_app_dir):
        result = runner.invoke(presets.app, ['registry', 'ls'])
        assert result.exit_code == 0
        assert 'default' in result.stdout


class TestRegistryAdd:
    def test_add_writes_user_entry(self, isolated_app_dir, monkeypatch):
        # Stub the metadata peek so no network/clone happens.
        monkeypatch.setattr(
            presets,
            '_peek_preset_metadata',
            lambda uri, local=False: RegistryPreset(
                name='myp', uri=uri, description='desc'
            ),
        )
        result = runner.invoke(presets.app, ['registry', 'add', 'owner/repo'])
        assert result.exit_code == 0, result.stdout
        names = {p.name for p in registry.get_user_registry().presets}
        assert 'myp' in names


class TestRegistryRm:
    def test_rm_removes_user_entry(self, isolated_app_dir):
        registry.add_to_user_registry(
            RegistryPreset(name='myp', uri='o/r', description='d')
        )
        result = runner.invoke(presets.app, ['registry', 'rm', 'myp'])
        assert result.exit_code == 0
        names = {p.name for p in registry.get_user_registry().presets}
        assert 'myp' not in names

    def test_rm_unknown_errors(self, isolated_app_dir):
        result = runner.invoke(presets.app, ['registry', 'rm', 'nope'])
        assert result.exit_code != 0
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_registry_cli.py -v`
Expected: FAIL (`registry` sub-command and `_peek_preset_metadata` missing).

**Step 3: Implement**

In `rbx/box/presets/__init__.py`:

1. Add a `_peek_preset_metadata` helper that installs the preset into a temp dir
   and reads its `preset.rbx.yml`:

```python
def _peek_preset_metadata(uri: str, local: bool = False) -> 'RegistryPreset':
    from rbx.box.presets.registry_schema import RegistryPreset

    fetch_info = get_preset_fetch_info(uri, local=local)
    if fetch_info is None:
        console.console.print(
            f'[error]Could not resolve preset URI [item]{uri}[/item].[/error]'
        )
        raise typer.Exit(1)
    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp) / 'preset'
        _install_preset_from_fetch_info(fetch_info, scratch)
        preset = get_preset_yaml(scratch)
    return RegistryPreset(
        name=preset.name, uri=uri, description=preset.description
    )
```

2. Create a `registry` sub-Typer and register it on `app`:

```python
registry_app = typer.Typer(no_args_is_help=True)
app.add_typer(registry_app, name='registry', help='Manage the preset registry.')


@registry_app.command('ls', help='List presets available in the registry.')
def registry_ls():
    from rbx.box.presets import registry as preset_registry

    merged = preset_registry.get_merged_registry()
    user_names = {p.name for p in preset_registry.get_user_registry().presets}
    if not merged.presets:
        console.console.print('No presets in the registry.')
        return
    from rich.table import Table

    table = Table('Name', 'Description', 'URI', 'Source')
    for p in merged.presets:
        source = 'user' if p.name in user_names else 'built-in'
        table.add_row(p.name, p.description, p.uri, source)
    console.console.print(table)


@registry_app.command('add', help='Add a preset to the user registry.')
def registry_add(
    uri: Annotated[
        str,
        typer.Argument(help='URI of the preset to register (owner/repo, URL, or path).'),
    ],
    local: Annotated[
        bool,
        typer.Option('--local', help='Resolve the preset from the local rbx version.'),
    ] = False,
):
    from rbx.box.presets import registry as preset_registry

    entry = _peek_preset_metadata(uri, local=local)
    preset_registry.add_to_user_registry(entry)
    console.console.print(
        f'[success]Registered preset [item]{entry.name}[/item] '
        f'([item]{entry.uri}[/item]).[/success]'
    )


@registry_app.command('rm', help='Remove a preset from the user registry.')
def registry_rm(
    name: Annotated[str, typer.Argument(help='Name of the preset to remove.')],
):
    from rbx.box.presets import registry as preset_registry

    if preset_registry.remove_from_user_registry(name):
        console.console.print(
            f'[success]Removed preset [item]{name}[/item] from the registry.[/success]'
        )
        return
    console.console.print(
        f'[error]Preset [item]{name}[/item] is not in the user registry '
        f'(built-in presets cannot be removed).[/error]'
    )
    raise typer.Exit(1)
```

Ensure `tempfile`, `pathlib`, `Annotated` are imported (they already are at the
top of the module).

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_registry_cli.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/presets/__init__.py tests/rbx/box/presets/test_registry_cli.py
git commit -m "feat(presets): add 'presets registry' ls/add/rm commands"
```

---

## Task 8: Auto-offer to register a newly used preset

**Files:**
- Modify: `rbx/box/presets/__init__.py` (add `maybe_offer_to_register`)
- Modify: `rbx/box/creation.py`
- Modify: `rbx/box/contest/main.py` (contest `create` and `init`)
- Test: `tests/rbx/box/presets/test_registry_cli.py`

**Step 1: Write the failing test**

Append to `tests/rbx/box/presets/test_registry_cli.py`:

```python
class TestOfferToRegister:
    def test_offers_and_registers_when_confirmed(self, isolated_app_dir, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(presets.registry, 'is_interactive', lambda: True)
        # Confirm "yes".
        monkeypatch.setattr(
            presets.questionary, 'confirm',
            lambda *a, **k: SimpleNamespace(ask=lambda: True),
        )
        meta = RegistryPreset(name='newp', uri='o/r', description='d')
        monkeypatch.setattr(presets, '_peek_preset_metadata', lambda uri, local=False: meta)

        fetch_info = SimpleNamespace(uri='o/r')
        presets.maybe_offer_to_register(fetch_info)
        assert any(p.name == 'newp' for p in presets.registry.get_user_registry().presets)

    def test_skips_when_already_registered(self, isolated_app_dir, monkeypatch):
        from types import SimpleNamespace

        presets.registry.add_to_user_registry(
            RegistryPreset(name='newp', uri='o/r', description='d')
        )
        monkeypatch.setattr(presets.registry, 'is_interactive', lambda: True)

        called = {'confirm': False}

        def _confirm(*a, **k):
            called['confirm'] = True
            return SimpleNamespace(ask=lambda: True)

        monkeypatch.setattr(presets.questionary, 'confirm', _confirm)
        presets.maybe_offer_to_register(SimpleNamespace(uri='o/r'))
        assert called['confirm'] is False  # already known → no prompt

    def test_skips_when_non_interactive(self, isolated_app_dir, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(presets.registry, 'is_interactive', lambda: False)
        presets.maybe_offer_to_register(SimpleNamespace(uri='o/r'))
        assert presets.registry.get_user_registry().presets == []
```

> Note: this test references `presets.registry`. Add
> `from rbx.box.presets import registry` (bound as `registry`) at module scope of
> `rbx/box/presets/__init__.py`, OR keep the `preset_registry` alias from Task 6
> and update the test to use `presets.preset_registry`. Pick one alias and stay
> consistent across Tasks 6–8.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_registry_cli.py::TestOfferToRegister -v`
Expected: FAIL (`maybe_offer_to_register` missing).

**Step 3: Implement**

In `rbx/box/presets/__init__.py`:

```python
def maybe_offer_to_register(fetch_info: Optional[PresetFetchInfo]) -> None:
    """After a user installs from an explicit --preset URI, offer to add it to
    the user registry (interactive only, and only if not already known)."""
    if fetch_info is None or not getattr(fetch_info, 'uri', None):
        return
    if not preset_registry.is_interactive():
        return
    if preset_registry.find_in_registry(fetch_info.uri) is not None:
        return
    if not questionary.confirm(
        f'Register preset "{fetch_info.uri}" so it shows up in the picker next time?',
        default=False,
    ).ask():
        return
    entry = _peek_preset_metadata(fetch_info.uri)
    preset_registry.add_to_user_registry(entry)
    console.console.print(
        f'[success]Registered preset [item]{entry.name}[/item].[/success]'
    )
```

Wire it into the creation commands, only when the user passed an explicit
`--preset` (i.e. `preset is not None`):

- `rbx/box/creation.py` `create()`, after `presets.install_problem(...)`:

```python
    if preset is not None:
        presets.maybe_offer_to_register(fetch_info)
```

- `rbx/box/contest/main.py` `create()`, after `presets.install_contest(...)` (inside or after the `with cd...` block):

```python
    if preset is not None:
        presets.maybe_offer_to_register(fetch_info)
```

- `rbx/box/contest/main.py` `init()`, after `presets.install_contest(...)`:

```python
    if preset is not None:
        presets.maybe_offer_to_register(fetch_info)
```

(Do NOT wire `add_variant` or `presets update`/scratch flows — those intentionally
do not auto-offer; see design doc.)

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_registry_cli.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/presets/__init__.py rbx/box/creation.py rbx/box/contest/main.py tests/rbx/box/presets/test_registry_cli.py
git commit -m "feat(presets): offer to register a newly used preset"
```

---

## Task 9: Documentation

**Files:**
- Modify: the presets docs page (find with `grep -rl "preset" docs/`; likely `docs/presets.md` or similar)
- Modify: `rbx/box/dump_schemas.py` (add `PresetRegistry` so its schema is published, matching the `# yaml-language-server` URL in `registry.yml`)

**Step 1: Add `PresetRegistry` to the published schemas**

In `rbx/box/dump_schemas.py`:

```python
from rbx.box.presets.registry_schema import PresetRegistry
...
models = [Package, Environment, Contest, Preset, PresetLock, PresetRegistry, Statement, LimitsProfile]
```

**Step 2: Update the presets docs**

Document:
- the new `description` field on a preset,
- the registry concept (built-in + user files, merge precedence),
- the picker behavior (interactive selection, `--preset` to skip it, non-interactive requires `--preset`),
- the `rbx presets registry ls|add|rm` commands.

**Step 3: Verify docs build**

Run: `uv run mkdocs build` (non-strict). Expected: builds; ignore the
~9 pre-existing unrelated strict warnings (see project memory). Confirm the
`PresetRegistry.json` schema is generated.

**Step 4: Commit**

```bash
git add docs rbx/box/dump_schemas.py
git commit -m "docs(presets): document preset registry and description field"
```

---

## Task 10: Full verification sweep

**Step 1: Lint & format**

```bash
uv run ruff check --fix .
uv run ruff format .
```

**Step 2: Targeted preset test run**

```bash
uv run pytest tests/rbx/box/presets -v
```
Expected: PASS.

**Step 3: Broader run (catch fallout from the behavior change)**

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto
```
Expected: PASS, except the pre-existing local C++/checker/validator/sandbox/docker
failures noted in project memory (verify any failures are unrelated to presets;
in particular check no test relied on the silent `default` fallback — if one does,
update it to pass `--preset default` or run interactively-stubbed).

**Step 4: CLI smoke (optional, manual)**

```bash
uv run rbx presets registry ls
uv run rbx presets registry add rsalesc/rbx/rbx/resources/presets/default
uv run rbx presets registry rm <name>
```

**Step 5: Final commit (only if lint/format changed files)**

```bash
git add -A
git commit -m "chore(presets): lint and format pass"
```

---

## Open follow-ups (not in scope)

- Pinning a preset version in the registry entry.
- A curated multi-preset built-in catalog (only `default` ships now).
- `--yes`/`--default` non-interactive convenience flag to opt back into the old
  silent-default behavior, if scripts need it.
