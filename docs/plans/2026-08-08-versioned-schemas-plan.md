# Versioned Schemas Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Publish versioned JSON Schemas to a dedicated GitHub Pages repo, and make `rbx` write a `# yaml-language-server` URL pinned to the active preset's `min_version`.

**Architecture:** A release-tag CI job generates the 8 schemas and pushes them into `rsalesc/rbx-schemas` under `<major>.<minor>/`. In the CLI, a new `rbx/box/schema_urls.py` resolves the pin from the nearest `.local.rbx/preset.rbx.yml` (falling back to the installed version, and to today's unversioned URL below a floor), and three write paths stamp it: `model_to_yaml`, `rbx lint`, and package creation from a preset.

**Tech Stack:** Python 3.9+/Pydantic v2 JSON Schema generation, Typer CLI, mkdocs `gen-files`, pytest, GitHub Actions.

**Design doc:** `docs/plans/2026-08-08-versioned-schemas-design.md`

**Branch:** continue on `docs/versioned-schemas-design`, or branch from it.

---

## Background the executor needs

- Schemas are generated from Pydantic models listed in `rbx/box/dump_schemas.py`. That file is an *mkdocs `gen-files` script* (see `mkdocs.yml:96`) — it runs at docs-build time and writes into the site via `mkdocs_gen_files.open`. It cannot be imported outside a mkdocs build.
- Today's URL comes from `rbx/utils.py:329` `uploaded_schema_path`, used by `model_to_yaml` (`rbx/utils.py:333`) and `rbx/box/linting.py:28`.
- Every config model sets `ConfigDict(extra='forbid')`, so generated schemas contain `"additionalProperties": false`.
- `rbx/box/presets/__init__.py:192` `find_local_preset` walks *up* from a root looking for `.local.rbx/preset.rbx.yml`, then falls back to `find_nested_preset`.
- **Do not** call `get_preset_yaml` / `get_active_preset` from the URL helper: they call `_check_preset_compatibility` (`rbx/box/presets/__init__.py:106`) which prints errors and raises `typer.Exit(1)`. Stamping a comment must never abort a command.
- `rbx/utils.py` is imported by `rbx.box.presets`, so `rbx/utils.py` must not import `rbx.box.*` at module level. Use a function-local import (that file already does this in `_ensure_json_serializable`).
- Run tests with `uv run pytest`. Lint with `uv run ruff check .` and `uv run ruff format .`. Single quotes, absolute imports only.
- Commit with the `/commit` skill conventions (conventional commits; the pre-commit hook enforces them).

---

## Task 1: Relax `additionalProperties` in generated schemas

**Files:**
- Modify: `rbx/utils.py:309` (`dump_schema_str`)
- Test: `tests/rbx/test_utils.py`

**Step 1: Write the failing test**

Add to `tests/rbx/test_utils.py`:

```python
class TestSchemaRelaxation:
    def test_dump_schema_str_drops_additional_properties_false(self):
        from pydantic import BaseModel, ConfigDict

        from rbx.utils import dump_schema_str

        class Inner(BaseModel):
            model_config = ConfigDict(extra='forbid')
            x: int = 0

        class Outer(BaseModel):
            model_config = ConfigDict(extra='forbid')
            inner: Inner = Inner()

        dumped = json.loads(dump_schema_str(Outer))

        assert 'additionalProperties' not in dumped
        assert 'additionalProperties' not in dumped['$defs']['Inner']

    def test_dump_schema_str_keeps_required_and_types(self):
        from pydantic import BaseModel, ConfigDict

        from rbx.utils import dump_schema_str

        class Model(BaseModel):
            model_config = ConfigDict(extra='forbid')
            name: str

        dumped = json.loads(dump_schema_str(Model))

        assert dumped['required'] == ['name']
        assert dumped['properties']['name']['type'] == 'string'
```

**Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/rbx/test_utils.py::TestSchemaRelaxation -v`
Expected: FAIL — `additionalProperties` is present.

**Step 3: Implement**

In `rbx/utils.py`, above `dump_schema_str`:

```python
def _relax_schema(node):
    """Drop `additionalProperties: false` so a pinned schema tolerates keys
    added by newer rbx versions. rbx itself still rejects unknown keys at load
    time (models are `extra='forbid'`), so typos are caught by the tool."""
    if isinstance(node, dict):
        return {
            k: _relax_schema(v)
            for k, v in node.items()
            if not (k == 'additionalProperties' and v is False)
        }
    if isinstance(node, list):
        return [_relax_schema(item) for item in node]
    return node
```

and change `dump_schema_str` to:

```python
def dump_schema_str(model: Type[BaseModel]) -> str:
    return json.dumps(_relax_schema(model.model_json_schema()), indent=4)
```

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/test_utils.py -v`
Expected: PASS (all of them — `dump_schema_str` is otherwise unchanged).

**Step 5: Commit**

```bash
git add rbx/utils.py tests/rbx/test_utils.py
git commit -m "feat(schemas): publish forward-tolerant schemas"
```

---

## Task 2: `schema_urls` module — floor, minor, and the tolerant preset read

**Files:**
- Create: `rbx/box/schema_urls.py`
- Test: `tests/rbx/box/test_schema_urls.py`

**Step 1: Write the failing test**

```python
import pathlib
import textwrap

import pytest
from pydantic import BaseModel

from rbx.box import schema_urls


class Package(BaseModel):
    pass


def _write_preset(root: pathlib.Path, min_version: str) -> None:
    local = root / '.local.rbx'
    local.mkdir(parents=True, exist_ok=True)
    (local / 'preset.rbx.yml').write_text(
        textwrap.dedent(f"""
        name: "test-preset"
        uri: "rsalesc/rbx"
        min_version: "{min_version}"
        """)
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    schema_urls.preset_min_version.cache_clear()
    yield
    schema_urls.preset_min_version.cache_clear()


class TestSchemaUrl:
    def test_pins_to_preset_minor(self, tmp_path):
        _write_preset(tmp_path, '1.4.2')

        assert schema_urls.schema_url(Package, tmp_path) == (
            'https://rsalesc.github.io/rbx-schemas/1.4/Package.json'
        )

    def test_pins_from_nested_problem_dir(self, tmp_path):
        _write_preset(tmp_path, '1.4.2')
        nested = tmp_path / 'problems' / 'A'
        nested.mkdir(parents=True)

        assert schema_urls.schema_url(Package, nested) == (
            'https://rsalesc.github.io/rbx-schemas/1.4/Package.json'
        )

    def test_falls_back_to_unversioned_below_floor(self, tmp_path):
        _write_preset(tmp_path, '0.14.0')

        assert schema_urls.schema_url(Package, tmp_path) == (
            'https://rsalesc.github.io/rbx/schemas/Package.json'
        )

    def test_uses_installed_version_without_preset(self, tmp_path, mocker):
        mocker.patch('rbx.utils.get_version', return_value='2.7.3')

        assert schema_urls.schema_url(Package, tmp_path) == (
            'https://rsalesc.github.io/rbx-schemas/2.7/Package.json'
        )

    def test_malformed_preset_is_tolerated_silently(self, tmp_path, capsys):
        local = tmp_path / '.local.rbx'
        local.mkdir()
        (local / 'preset.rbx.yml').write_text('this: [is, not, valid\n')

        url = schema_urls.schema_url(Package, tmp_path)

        assert url.endswith('Package.json')
        assert capsys.readouterr().out == ''

    def test_incompatible_preset_does_not_raise(self, tmp_path):
        # min_version far above the installed version would make
        # _check_preset_compatibility exit; stamping a comment must not.
        _write_preset(tmp_path, '999.0.0')

        assert schema_urls.schema_url(Package, tmp_path).endswith('Package.json')

    def test_preset_read_is_cached(self, tmp_path):
        _write_preset(tmp_path, '1.4.2')

        schema_urls.schema_url(Package, tmp_path)
        (tmp_path / '.local.rbx' / 'preset.rbx.yml').unlink()

        assert schema_urls.schema_url(Package, tmp_path) == (
            'https://rsalesc.github.io/rbx-schemas/1.4/Package.json'
        )
```

**Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/rbx/box/test_schema_urls.py -v`
Expected: FAIL — `ModuleNotFoundError: rbx.box.schema_urls`.

**Step 3: Implement `rbx/box/schema_urls.py`**

```python
import functools
import pathlib
from typing import Optional, Tuple, Type

import yaml
from pydantic import BaseModel

from rbx import utils

# Base URL of the versioned schema site. Kept in one place so adopting a
# custom domain later is a one-line change (github.io then redirects, so pins
# already written into users' files keep resolving).
VERSIONED_BASE_URL = 'https://rsalesc.github.io/rbx-schemas'

# First minor whose schemas are published. Older floors -- including the
# historical `min_version` default of 0.14.0 -- fall back to the unversioned
# URL, because pointing at a nonexistent file makes editors show a hard
# "unable to load schema" error.
SCHEMA_PIN_FLOOR: Tuple[int, int] = (1, 1)


@functools.cache
def preset_min_version(root: pathlib.Path) -> Optional[str]:
    """`min_version` of the preset governing `root`, or None.

    Deliberately tolerant: never raises, never prints. Unlike
    `presets.get_preset_yaml`, this does not run compatibility checks -- writing
    a schema comment must never abort a command. Cached because
    `model_to_yaml` is called once per test evaluation.
    """
    from rbx.box.presets import find_local_preset

    try:
        preset_path = find_local_preset(root)
        if preset_path is None:
            return None
        loaded = yaml.safe_load((preset_path / 'preset.rbx.yml').read_text())
        if not isinstance(loaded, dict):
            return None
        version = loaded.get('min_version')
        if not isinstance(version, str) or not utils.is_valid_semver(version):
            return None
        return version
    except Exception:
        return None


def _minor(version: str) -> Tuple[int, int]:
    semver = utils.get_semver(version)
    return (semver.major, semver.minor)


def schema_url(
    model_cls: Type[BaseModel], root: pathlib.Path = pathlib.Path()
) -> str:
    """URL of the schema for `model_cls`, pinned to the compatibility floor of
    the preset governing `root` (or to the installed version if there is
    none)."""
    version = preset_min_version(utils.abspath(root)) or utils.get_version()
    try:
        major, minor = _minor(version)
    except Exception:
        return utils.uploaded_schema_path(model_cls)
    if (major, minor) < SCHEMA_PIN_FLOOR:
        return utils.uploaded_schema_path(model_cls)
    return f'{VERSIONED_BASE_URL}/{major}.{minor}/{model_cls.__name__}.json'
```

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/box/test_schema_urls.py -v`
Expected: PASS. If `mocker` is unavailable, use `unittest.mock.patch` instead (the project uses stdlib `mock`) — patch `rbx.utils.get_version`.

**Step 5: Commit**

```bash
git add rbx/box/schema_urls.py tests/rbx/box/test_schema_urls.py
git commit -m "feat(schemas): resolve version-pinned schema URLs"
```

---

## Task 3: Stamp the pin from `model_to_yaml`

**Files:**
- Modify: `rbx/utils.py:333` (`model_to_yaml`)
- Modify: `rbx/box/packaging/polygon/importer.py:247`
- Test: `tests/rbx/test_utils.py`

**Step 1: Write the failing test**

```python
    def test_model_to_yaml_pins_schema_to_preset_min_version(self, tmp_path):
        (tmp_path / '.local.rbx').mkdir()
        (tmp_path / '.local.rbx' / 'preset.rbx.yml').write_text(
            'name: "p"\nuri: "u"\nmin_version: "1.4.0"\n'
        )

        from rbx.box import schema_urls

        schema_urls.preset_min_version.cache_clear()
        output = model_to_yaml(SampleModel(...), root=tmp_path)
        schema_urls.preset_min_version.cache_clear()

        assert output.startswith(
            '# yaml-language-server: '
            '$schema=https://rsalesc.github.io/rbx-schemas/1.4/SampleModel.json'
        )
```

Also update the existing `test_schema_path_generation` (`tests/rbx/test_utils.py:239`), which asserts the unversioned URL: outside a preset it now pins to the installed version's minor. Assert against `schema_urls.schema_url(SampleModel)` rather than a literal.

**Step 2: Run and confirm failure**

Run: `uv run pytest tests/rbx/test_utils.py -k schema -v`
Expected: FAIL — `model_to_yaml() got an unexpected keyword argument 'root'`.

**Step 3: Implement**

In `rbx/utils.py`:

```python
def model_to_yaml(
    model: BaseModel, root: Optional[pathlib.Path] = None, **kwargs
) -> str:
    ...
    # Function-local import: rbx.box.presets imports this module.
    from rbx.box.schema_urls import schema_url

    path = schema_url(model.__class__, root or pathlib.Path())
    schema_comment = f'# yaml-language-server: $schema={path}\n\n'
```

Then pass the destination package root where a call site writes outside the cwd — `rbx/box/packaging/polygon/importer.py:247`:

```python
        (into_path / 'problem.rbx.yml').write_text(
            utils.model_to_yaml(pkg, root=into_path)
        )
```

Leave the other call sites on the default (they write inside the current package).

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/test_utils.py tests/rbx/box/test_schema_urls.py -v`
Expected: PASS.

Then the broader suite, since many fixtures compare written YAML:
Run: `uv run pytest --ignore=tests/rbx/box/cli -x -q`
Expected: PASS. Fix any snapshot/fixture that hardcodes the unversioned URL by pointing it at `schema_urls.schema_url(...)`.

**Step 5: Commit**

```bash
git add rbx/utils.py rbx/box/packaging/polygon/importer.py tests/rbx/test_utils.py
git commit -m "feat(schemas): pin schema header written by model_to_yaml"
```

---

## Task 4: Enable header normalization in `rbx lint`

`fix_language_server` (`rbx/box/linting.py:19`) has been commented out of `fix_yaml` since it was added. It also has a latent bug: it re-inserts the header only after a line starting with `---`, so a file without a document marker would *lose* its header. Fix that, make it idempotent, and leave foreign schema URLs alone.

**Files:**
- Modify: `rbx/box/linting.py:19-56`
- Test: `tests/rbx/box/linters/test_language_server_header.py`

**Step 1: Write the failing tests**

```python
import pathlib

from rbx.box import linting
from rbx.box.schema import Package

VERSIONED = 'https://rsalesc.github.io/rbx-schemas'


def _preset(root: pathlib.Path, min_version: str = '1.4.0') -> None:
    (root / '.local.rbx').mkdir(parents=True, exist_ok=True)
    (root / '.local.rbx' / 'preset.rbx.yml').write_text(
        f'name: "p"\nuri: "u"\nmin_version: "{min_version}"\n'
    )


class TestFixLanguageServer:
    def test_replaces_unversioned_header_with_pin(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        path.write_text(
            '---\n'
            '# yaml-language-server: $schema='
            'https://rsalesc.github.io/rbx/schemas/Package.json\n'
            'name: "problem"\n'
        )

        assert linting.fix_language_server(path, Package, tmp_path) is True
        assert f'$schema={VERSIONED}/1.4/Package.json' in path.read_text()

    def test_is_idempotent(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        path.write_text(
            f'---\n# yaml-language-server: $schema={VERSIONED}/1.4/Package.json\n'
            'name: "problem"\n'
        )

        assert linting.fix_language_server(path, Package, tmp_path) is False

    def test_adds_header_to_file_without_document_marker(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        path.write_text('name: "problem"\n')

        assert linting.fix_language_server(path, Package, tmp_path) is True
        lines = path.read_text().splitlines()
        assert lines[0].startswith('# yaml-language-server:')
        assert 'name: "problem"' in path.read_text()

    def test_leaves_foreign_schema_url_untouched(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        original = (
            '---\n'
            '# yaml-language-server: $schema=./my-local-schema.json\n'
            'name: "problem"\n'
        )
        path.write_text(original)

        assert linting.fix_language_server(path, Package, tmp_path) is False
        assert path.read_text() == original
```

Remember to clear `schema_urls.preset_min_version.cache_clear()` between tests (autouse fixture, as in Task 2).

**Step 2: Run and confirm failure**

Run: `uv run pytest tests/rbx/box/linters/test_language_server_header.py -v`
Expected: FAIL — signature takes no `root`, and the no-marker case drops the header.

**Step 3: Implement**

Replace `fix_language_server` in `rbx/box/linting.py`:

```python
# Hosts whose schema headers rbx owns and may rewrite. A user pointing at a
# local or third-party schema is left alone.
_OWNED_SCHEMA_PREFIXES = (
    'https://rsalesc.github.io/rbx/schemas/',
    f'{schema_urls.VERSIONED_BASE_URL}/',
)


def _is_owned_schema_header(line: str) -> bool:
    return any(prefix in line for prefix in _OWNED_SCHEMA_PREFIXES)


def fix_language_server(
    path: pathlib.Path,
    model_cls: Type[BaseModel],
    root: pathlib.Path = pathlib.Path(),
) -> bool:
    orig_text = path.read_text()
    header = (
        f'# yaml-language-server: $schema={schema_urls.schema_url(model_cls, root)}\n'
    )

    lines = orig_text.splitlines(keepends=True)
    existing = [
        i
        for i, line in enumerate(lines)
        if line.strip().startswith('# yaml-language-server:')
    ]
    if existing and not all(_is_owned_schema_header(lines[i]) for i in existing):
        # The file points at a schema rbx does not own; do not touch it.
        return False

    kept = [line for i, line in enumerate(lines) if i not in set(existing)]
    insert_at = 1 if kept and kept[0].startswith('---') else 0
    content = ''.join(kept[:insert_at] + [header] + kept[insert_at:])

    if content == orig_text:
        return False
    path.write_text(content)
    return True
```

Add `from rbx.box import schema_urls` to the imports and drop the now-unused `uploaded_schema_path` import. Then re-enable it inside `fix_yaml` (replacing the commented block at `rbx/box/linting.py:54`):

```python
    if model_cls is not None:
        if fix_language_server(path, model_cls, path.parent):
            changed = True
```

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/box/linters -v && uv run pytest tests/rbx/box/presets -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/linting.py tests/rbx/box/linters/test_language_server_header.py
git commit -m "feat(lint): normalize yaml-language-server schema headers"
```

---

## Task 5: Stamp headers when a package is created from a preset

Preset templates (including third-party ones) hardcode a schema URL. Normalize after copying — the local preset already exists at that point, so the pin resolves.

**Files:**
- Modify: `rbx/box/presets/__init__.py` (`install_problem` ~line 1043, `install_contest` ~line 1003)
- Test: `tests/rbx/box/presets/test_presets_create.py`

**Step 1: Write the failing test**

Follow the existing style in `tests/rbx/box/presets/test_presets_create.py`; assert that after creating a problem (and a contest) from the default preset, the first non-`---` line of `problem.rbx.yml` / `contest.rbx.yml` carries the pinned URL for the preset's `min_version`, not the unversioned one.

**Step 2: Run and confirm failure**

Run: `uv run pytest tests/rbx/box/presets/test_presets_create.py -v`
Expected: FAIL — the copied template still carries the unversioned URL.

**Step 3: Implement**

At the end of `install_problem`, after `clean_copied_problem_dir(...)`:

```python
    from rbx.box.linting import fix_language_server

    fix_language_server(dest_pkg / 'problem.rbx.yml', Package, dest_pkg)
```

and in `install_contest`, after `clean_copied_contest_dir(...)`:

```python
    from rbx.box.linting import fix_language_server

    fix_language_server(dest_pkg / 'contest.rbx.yml', Contest, dest_pkg)
```

Use function-local imports: `rbx.box.linting` imports `rbx.box.presets`. Guard on `.is_file()` if the template may be absent.

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/box/presets -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/presets/__init__.py tests/rbx/box/presets/test_presets_create.py
git commit -m "feat(presets): pin schema header on package creation"
```

---

## Task 6: Extract the schema list and a directory dumper

`dump_schemas.py` can only run inside mkdocs. CI needs the same list and content without mkdocs.

**Files:**
- Create: `rbx/box/schema_export.py`
- Modify: `rbx/box/dump_schemas.py`
- Test: `tests/rbx/box/test_schema_export.py`

**Step 1: Write the failing test**

```python
import json

from rbx.box import schema_export


def test_exports_every_documented_model(tmp_path):
    schema_export.export_schemas(tmp_path)

    names = {p.stem for p in tmp_path.glob('*.json')}

    assert names == {m.__name__ for m in schema_export.MODELS}
    assert 'Package' in names


def test_exported_schema_is_valid_json_and_relaxed(tmp_path):
    schema_export.export_schemas(tmp_path)

    schema = json.loads((tmp_path / 'Package.json').read_text())

    assert schema['title'] == 'Package'
    assert 'additionalProperties' not in json.dumps(schema)
```

**Step 2: Run and confirm failure**

Run: `uv run pytest tests/rbx/box/test_schema_export.py -v`
Expected: FAIL — module missing.

**Step 3: Implement `rbx/box/schema_export.py`**

Move the model list out of `dump_schemas.py`:

```python
import pathlib
from typing import List, Type

from pydantic import BaseModel

from rbx.box.contest.schema import Contest
from rbx.box.environment import Environment
from rbx.box.package import Package
from rbx.box.presets.lock_schema import PresetLock
from rbx.box.presets.registry_schema import PresetRegistry
from rbx.box.presets.schema import Preset
from rbx.box.schema import LimitsProfile
from rbx.box.statements.schema import Statement
from rbx.utils import dump_schema_str

MODELS: List[Type[BaseModel]] = [
    Package,
    Environment,
    Contest,
    Preset,
    PresetLock,
    PresetRegistry,
    Statement,
    LimitsProfile,
]


def export_schemas(into: pathlib.Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        (into / f'{model.__name__}.json').write_text(dump_schema_str(model))
```

Rewrite `rbx/box/dump_schemas.py` to consume it (unversioned URLs keep working exactly as before):

```python
import pathlib

import mkdocs_gen_files

from rbx.box.schema_export import MODELS
from rbx.utils import dump_schema_str

for model in MODELS:
    path = pathlib.Path('schemas') / f'{model.__name__}.json'
    with mkdocs_gen_files.open(str(path), 'w') as f:
        f.write(dump_schema_str(model))
```

**Step 4: Run tests and the docs build**

Run: `uv run pytest tests/rbx/box/test_schema_export.py -v`
Expected: PASS.
Run: `uv run mkdocs build 2>&1 | tail -20`
Expected: builds; `site/schemas/Package.json` exists. (Per project notes, `--strict` fails on ~9 pre-existing unrelated warnings — use a non-strict build.)

**Step 5: Commit**

```bash
git add rbx/box/schema_export.py rbx/box/dump_schemas.py tests/rbx/box/test_schema_export.py
git commit -m "refactor(schemas): extract reusable schema exporter"
```

---

## Task 7: CLI entry point for the exporter

CI needs one command to produce a publishable tree. Add a hidden command so the workflow does not depend on `python -c` incantations.

**Files:**
- Create: `rbx/box/schema_publish.py` (small `__main__` shim)
- Test: `tests/rbx/box/test_schema_export.py`

**Step 1: Write the failing test**

```python
def test_publish_layout(tmp_path):
    from rbx.box import schema_publish

    schema_publish.build_site(tmp_path, version='1.4.2')

    assert (tmp_path / '1.4' / 'Package.json').is_file()
    assert (tmp_path / 'latest' / 'Package.json').is_file()

    index = json.loads((tmp_path / 'index.json').read_text())
    assert index['latest'] == '1.4'
    assert '1.4' in index['versions']
    assert 'Package' in index['models']


def test_publish_merges_with_existing_versions(tmp_path):
    from rbx.box import schema_publish

    schema_publish.build_site(tmp_path, version='1.3.0')
    schema_publish.build_site(tmp_path, version='1.4.0')

    index = json.loads((tmp_path / 'index.json').read_text())

    assert index['versions'] == ['1.3', '1.4']
    assert index['latest'] == '1.4'
    assert (tmp_path / '1.3' / 'Package.json').is_file()
```

**Step 2: Run and confirm failure**

Run: `uv run pytest tests/rbx/box/test_schema_export.py -v`
Expected: FAIL — module missing.

**Step 3: Implement `rbx/box/schema_publish.py`**

```python
"""Builds the publishable tree for the versioned schema site.

Run from CI against a checkout at a release tag:

    uv run python -m rbx.box.schema_publish <out-dir> <version>

`out-dir` is a checkout of the schemas repo, so existing version directories
are preserved and the index is recomputed from what is on disk.
"""

import json
import pathlib
import shutil
import sys

from rbx.box.schema_export import MODELS, export_schemas
from rbx.utils import get_semver


def build_site(out: pathlib.Path, version: str) -> None:
    semver = get_semver(version)
    minor = f'{semver.major}.{semver.minor}'

    target = out / minor
    if target.exists():
        shutil.rmtree(target)
    export_schemas(target)

    versions = sorted(
        (p.name for p in out.iterdir() if p.is_dir() and p.name != 'latest'),
        key=lambda name: tuple(int(part) for part in name.split('.')),
    )
    latest = versions[-1]

    latest_dir = out / 'latest'
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    shutil.copytree(out / latest, latest_dir)

    (out / 'index.json').write_text(
        json.dumps(
            {
                'latest': latest,
                'versions': versions,
                'models': [model.__name__ for model in MODELS],
            },
            indent=4,
        )
    )


if __name__ == '__main__':
    build_site(pathlib.Path(sys.argv[1]), sys.argv[2])
```

Note the `latest` alias tracks the greatest published minor on disk, so re-publishing an old patch does not demote `latest`.

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/box/test_schema_export.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/schema_publish.py tests/rbx/box/test_schema_export.py
git commit -m "feat(schemas): build versioned schema site tree"
```

---

## Task 8: Release workflow job

**Files:**
- Modify: `.github/workflows/release.yml`

**Prerequisites (manual, by the repo owner):**
1. Create `rsalesc/rbx-schemas`, empty, with a `main` branch and Pages enabled ("Deploy from a branch" → `main` → `/`). Add a `.nojekyll` file so directories starting with `_` are served.
2. Create a fine-grained PAT (or deploy key) with write access to `rbx-schemas`; store it as the secret `SCHEMAS_DEPLOY_TOKEN` in `rsalesc/rbx`. `GITHUB_TOKEN` cannot write to another repo.

**Step 1: Add the job**

{% raw %}
```yaml
  publish-schemas:
    name: Publish versioned JSON schemas
    runs-on: ubuntu-latest
    needs: pypi-publish
    if: ${{ !contains(github.ref_name, 'rc') }}
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
          python-version: "3.14"
      - run: uv sync --locked --all-groups
      - name: Checkout schemas repo
        uses: actions/checkout@v4
        with:
          repository: rsalesc/rbx-schemas
          token: ${{ secrets.SCHEMAS_DEPLOY_TOKEN }}
          path: .schemas-site
      - name: Build schema site
        run: uv run python -m rbx.box.schema_publish .schemas-site "${{ github.ref_name }}"
      - name: Push
        working-directory: .schemas-site
        run: |
          git config user.name github-actions[bot]
          git config user.email 41898282+github-actions[bot]@users.noreply.github.com
          git add -A
          git diff --staged --quiet && echo "no schema changes" && exit 0
          git commit -m "chore: publish schemas for ${{ github.ref_name }}"
          git push
```
{% endraw %}

`needs: pypi-publish` keeps schemas from appearing for a version that failed to publish. The `rc` guard prevents `1.5.0rc1` from exposing a `1.5` schema before `1.5.0` is installable.

**Step 2: Validate the workflow file**

Run: `uv run python -c "import yaml,pathlib;yaml.safe_load(pathlib.Path('.github/workflows/release.yml').read_text());print('ok')"`
Expected: `ok`.

**Step 3: Dry-run the publish step locally**

```bash
mkdir -p /tmp/schemas-site && uv run python -m rbx.box.schema_publish /tmp/schemas-site 1.1.0 && find /tmp/schemas-site -maxdepth 2 | sort | head -20
```
Expected: `1.1/`, `latest/`, `index.json` with 8 models each.

**Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci(schemas): publish versioned schemas on release"
```

---

## Task 9: Raise the default preset floor to the pinning floor

`SCHEMA_PIN_FLOOR` is `1.1`, and `rbx/resources/presets/default/preset.rbx.yml` declares `min_version: "1.0.0"` — which would keep the bundled preset on the unversioned URL. Bump it in the same release that ships this feature.

**Files:**
- Modify: `rbx/resources/presets/default/preset.rbx.yml:5`
- Modify: `rbx/resources/presets/default/{problem/problem.rbx.yml,contest/contest.rbx.yml}`, `rbx/resources/presets/default/preset.rbx.yml:2`, `rbx/resources/presets/registry.yml:1` — point the committed headers at `https://rsalesc.github.io/rbx-schemas/1.1/<Model>.json`
- Test: `tests/rbx/box/presets/test_presets_create.py`

**Steps:**
1. Set `min_version: "1.1.0"` in the default preset.
2. Update the four committed header lines to the pinned URLs. This is what a user sees before ever running `rbx lint`, so it must already be correct.
3. Do **not** touch `tests/e2e/testdata/**` presets (`min_version: "0.14.0"`) — they are below the floor and correctly keep the unversioned URL. That is deliberate coverage of the fallback.
4. Run: `uv run pytest tests/rbx/box/presets -q` and `uv run pytest --ignore=tests/rbx/box/cli -q`.
5. Commit: `feat(presets): pin default preset to versioned schemas`.

**Caveat to confirm before merging:** bumping the bundled preset's `min_version` to `1.1.0` means packages created by this release refuse to load on rbx < 1.1.0. That is the intended contract, but it must land in a minor release, not a patch.

---

## Task 10: Document it

**Files:**
- Modify: `docs/setters/presets/index.md` (or a new `docs/setters/reference/schemas.md`, added to `mkdocs.yml` nav under Reference)

**Content to cover:**
- Where schemas live: `https://rsalesc.github.io/rbx-schemas/<major>.<minor>/<Model>.json`, plus `latest/` and `index.json`.
- The pin comes from the active preset's `min_version` — the compatibility floor the package promises — so the editor validates against the oldest rbx the package claims to support.
- Published schemas tolerate unknown keys, but *not* enum values added after the pinned minor; if the editor rejects a value your rbx accepts, raise the preset's `min_version`.
- `rbx lint` normalizes the header; a custom or local `$schema` is left untouched.
- Floors below 1.1 fall back to the unversioned URL, which stays published indefinitely.

Verify: `uv run mkdocs build 2>&1 | tail -5` (non-strict, per the pre-existing warnings), then commit `docs(schemas): document versioned schema URLs`.

---

## Task 11: Full verification

1. `uv run ruff check . && uv run ruff format --check .`
2. `uv run pytest --ignore=tests/rbx/box/cli -q -n auto`
3. `uv run pytest tests/rbx/box/cli -q` (slow)
4. `mise run test-e2e`
5. Manual: create a problem from the default preset in a scratch dir, confirm `problem.rbx.yml`'s header is `.../rbx-schemas/1.1/Package.json`, run `rbx lint` twice and confirm the second run reports no change.

**Known pre-existing failures on this machine** (not caused by this work): checker/validator/sandbox/docker tests, `test_compute_walltime_uses_active_environment`, and the completion spec drift test. Confirm any failure reproduces on the base commit before investigating.

**Post-release verification** (after the first tagged release with this job):
```bash
curl -sSI https://rsalesc.github.io/rbx-schemas/1.1/Package.json | head -3
curl -sS https://rsalesc.github.io/rbx-schemas/index.json
```
Then open a generated `problem.rbx.yml` in VS Code with the YAML extension and confirm completion works and no "unable to load schema" error appears.
