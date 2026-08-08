# Preset Problem Template Variants Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let a preset declare several named problem (and contest) templates — "variants" — so a setter can run `rbx create foo -v interactive` and get a real interactive problem package instead of a batch one they must rewrite.

**Architecture:** A variant is a complete sibling template directory inside the preset (`problem/`, `problem-interactive/`), declared explicitly in `preset.rbx.yml` with an id, description, and optional per-variant `tracking`/`libraries`/`expansion` that merge over the shared ones. All the code that currently reaches for `preset.problem` / `preset.contest` collapses into a single `resolve_template()` returning a `ResolvedTemplate`. The chosen variant is recorded in `.preset-lock.yml` so `rbx presets sync` diffs against the right directory. The bundled `default` preset gains an `interactive` variant.

**Tech Stack:** Python 3.12+, Pydantic v2, Typer, questionary, pytest, ruff. Package manager: `uv`.

**Design doc:** `docs/plans/2026-08-08-preset-problem-variants-design.md`. Read it before starting.

**Issue:** [#264](https://github.com/rsalesc/rbx/issues/264).

---

## Orientation (read this first)

You are working in `rbx`, a CLI for competitive-programming problem setters. Relevant vocabulary:

- **Package** — a problem or contest directory. A problem has `problem.rbx.yml`, a contest has `contest.rbx.yml`.
- **Preset** — a template repository with a `preset.rbx.yml`, holding a `problem/` template dir, a `contest/` template dir, and an `env.rbx.yml`. `rbx create` copies the problem template into a new directory.
- **Installed preset** — when a package is created, the whole preset is copied into the package's `.local.rbx/` so it can be re-consulted later.
- **Tracking** — `tracking.problem` in `preset.rbx.yml` lists assets the preset owns. `rbx presets sync` re-copies them from the installed preset when they changed upstream and the user has not modified them locally. `.preset-lock.yml` stores hashes to tell those apart.
- **Libraries** — third-party headers (testlib, jngen) fetched and materialized into each package.
- **Expansion** — install-time find/replace over template files, prompting the user for values.

Key files:

| File | Role |
|---|---|
| `rbx/box/presets/schema.py` | `Preset`, `TrackedAsset`, `Tracking`, `Library`, `Libraries`, `VariableExpansion`, `Expansion` |
| `rbx/box/presets/lock_schema.py` | `PresetLock`, `LockedAsset` |
| `rbx/box/presets/__init__.py` | All preset behavior + the `rbx presets` Typer app (~1530 lines) |
| `rbx/box/creation.py` | `create()` — used by `rbx create` and `rbx contest add` |
| `rbx/box/cli.py:845` | `rbx create` Typer command |
| `rbx/box/contest/main.py` | `rbx contest create` (~103-117), `rbx contest add` (~287) |
| `rbx/box/testing/testing_preset.py` | `TestingPreset` builder used by tests |
| `rbx/testdata/presets/simple-preset/` | The main preset fixture |
| `tests/rbx/box/presets/test_presets.py` | Main preset test suite (fixtures at lines ~99-200) |
| `rbx/resources/presets/default/` | The bundled preset |

Commands:

```bash
uv sync                                             # install deps
uv run pytest tests/rbx/box/presets -v              # the suite you will live in
uv run pytest --ignore=tests/rbx/box/cli            # full unit suite
uv run ruff check --fix . && uv run ruff format .   # lint + format, run before every commit
```

**Code style:** single quotes; absolute imports only (relative imports are banned by ruff `TID`); Pydantic v2 everywhere.

**Commits:** Conventional Commits, enforced by a commitizen pre-commit hook. Use the `/commit` skill's format: `<type>(<scope>): <lowercase imperative description>` under 72 chars, and always append the `Co-Authored-By: Claude <noreply@anthropic.com>` trailer. If the hook rejects a commit, fix and make a NEW commit — never amend.

**Known-noisy tests on this machine:** some checker/validator/sandbox/docker tests fail regardless of your change. If a failure is in a file you did not touch and mentions sandboxes or C++ compilation, verify it fails on `main` too before chasing it.

---

## Task 1: `PackageVariant` schema model

**Files:**
- Modify: `rbx/box/presets/schema.py` (add after `class Expansion`, before `class Preset`)
- Test: `tests/rbx/box/presets/test_preset_variants.py` (create)

**Step 1: Write the failing tests**

Create `tests/rbx/box/presets/test_preset_variants.py`:

```python
import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.presets.schema import PackageVariant


class TestPackageVariant:
    def test_minimal_variant(self):
        variant = PackageVariant(id='interactive', path=pathlib.Path('problem-interactive'))
        assert variant.id == 'interactive'
        assert variant.description == ''
        assert variant.tracking == []
        assert variant.libraries == []
        assert variant.expansion == []

    @pytest.mark.parametrize('bad_id', ['1abc', 'has space', 'has.dot', '', 'a/b'])
    def test_rejects_malformed_id(self, bad_id):
        with pytest.raises(ValidationError):
            PackageVariant(id=bad_id, path=pathlib.Path('p'))

    def test_rejects_reserved_default_id(self):
        with pytest.raises(ValidationError, match='reserved'):
            PackageVariant(id='default', path=pathlib.Path('p'))

    def test_accepts_dashes_and_underscores(self):
        assert PackageVariant(id='interactive-points_2', path=pathlib.Path('p')).id
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_preset_variants.py -v`
Expected: FAIL — `ImportError: cannot import name 'PackageVariant'`.

**Step 3: Implement**

In `rbx/box/presets/schema.py`, after `class Expansion`:

```python
class PackageVariant(BaseModel):
    # Identifier of the variant. Used in `--variant` and recorded in the
    # package's `.preset-lock.yml`.
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]*$', min_length=1, max_length=32)

    # Path of the variant's template directory, relative to the preset directory.
    path: pathlib.Path

    # Human-readable description, shown in the variant picker.
    description: str = Field(default='')

    # Assets tracked for this variant, merged over the shared tracking list
    # for this package kind (variant entries win, per path).
    tracking: List[TrackedAsset] = []

    # Libraries for this variant, merged over the shared library list for this
    # package kind (variant entries win, per library name).
    libraries: List[Library] = []

    # Variable expansions for this variant, merged over the shared expansion
    # list for this package kind (variant entries win, per needle).
    expansion: List[VariableExpansion] = []

    @field_validator('id')
    @classmethod
    def validate_id_not_reserved(cls, value: str) -> str:
        if value == 'default':
            raise ValueError(
                "'default' is a reserved variant id: it refers to the preset's "
                'canonical template'
            )
        return value
```

**Step 4: Verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_preset_variants.py -v`
Expected: PASS (4 tests / 8 with parametrize).

**Step 5: Lint and commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/presets/schema.py tests/rbx/box/presets/test_preset_variants.py
git commit -m "$(cat <<'EOF'
feat(presets): add PackageVariant schema model

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Declare variants on `Preset` and define merge semantics

**Files:**
- Modify: `rbx/box/presets/schema.py` (`class Preset`)
- Test: `tests/rbx/box/presets/test_preset_variants.py`

The merge helpers live on `Preset` so both `resolve_template` and any future consumer share one implementation.

**Step 1: Write the failing tests**

Append to `tests/rbx/box/presets/test_preset_variants.py`:

```python
from rbx.box.presets.schema import (
    Expansion,
    Libraries,
    Library,
    Preset,
    TrackedAsset,
    Tracking,
    VariableExpansion,
)


def _preset(**kwargs) -> Preset:
    base = dict(name='my-preset', uri='owner/repo')
    base.update(kwargs)
    return Preset(**base)


class TestPresetVariants:
    def test_defaults_to_no_variants(self):
        preset = _preset(problem=pathlib.Path('problem'))
        assert preset.problemVariants == []
        assert preset.contestVariants == []

    def test_rejects_duplicate_variant_ids(self):
        with pytest.raises(ValidationError, match='duplicate'):
            _preset(
                problem=pathlib.Path('problem'),
                problemVariants=[
                    PackageVariant(id='interactive', path=pathlib.Path('a')),
                    PackageVariant(id='interactive', path=pathlib.Path('b')),
                ],
            )

    def test_same_id_allowed_across_kinds(self):
        preset = _preset(
            problem=pathlib.Path('problem'),
            contest=pathlib.Path('contest'),
            problemVariants=[PackageVariant(id='div1', path=pathlib.Path('a'))],
            contestVariants=[PackageVariant(id='div1', path=pathlib.Path('b'))],
        )
        assert preset.problemVariants[0].path != preset.contestVariants[0].path

    def test_find_variant_returns_none_for_unknown(self):
        preset = _preset(problem=pathlib.Path('problem'))
        assert preset.find_variant('nope', is_contest=False) is None


class TestVariantMerging:
    def test_tracking_variant_entry_wins_over_shared(self):
        preset = _preset(
            problem=pathlib.Path('problem'),
            tracking=Tracking(
                problem=[
                    TrackedAsset(path=pathlib.Path('.gitignore')),
                    TrackedAsset(path=pathlib.Path('shared.h'), symlink=False),
                ]
            ),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('problem-interactive'),
                    tracking=[TrackedAsset(path=pathlib.Path('shared.h'), symlink=True)],
                )
            ],
        )
        merged = preset.merged_tracking('interactive', is_contest=False)
        by_path = {str(a.path): a for a in merged}
        assert set(by_path) == {'.gitignore', 'shared.h'}
        assert by_path['shared.h'].symlink is True

    def test_tracking_canonical_returns_shared_only(self):
        preset = _preset(
            problem=pathlib.Path('problem'),
            tracking=Tracking(problem=[TrackedAsset(path=pathlib.Path('.gitignore'))]),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('pi'),
                    tracking=[TrackedAsset(path=pathlib.Path('only-variant'))],
                )
            ],
        )
        merged = preset.merged_tracking(None, is_contest=False)
        assert [str(a.path) for a in merged] == ['.gitignore']

    def test_libraries_merge_by_name_variant_wins(self):
        shared = Library(name='testlib', source='a/b', dest=pathlib.Path('testlib.h'))
        override = Library(
            name='testlib', source='a/b', dest=pathlib.Path('testlib.h'), version='1.0'
        )
        extra = Library(name='interlib', source='c/d', dest=pathlib.Path('inter.h'))
        preset = _preset(
            problem=pathlib.Path('problem'),
            libraries=Libraries(problem=[shared]),
            problemVariants=[
                PackageVariant(
                    id='interactive', path=pathlib.Path('pi'), libraries=[override, extra]
                )
            ],
        )
        merged = preset.merged_libraries('interactive', is_contest=False)
        by_name = {lib.name: lib for lib in merged}
        assert set(by_name) == {'testlib', 'interlib'}
        assert by_name['testlib'].version == '1.0'

    def test_expansion_merges_by_needle(self):
        preset = _preset(
            problem=pathlib.Path('problem'),
            expansion=Expansion(
                problem=[VariableExpansion(needle='AUTHOR', prompt='Author?')]
            ),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('pi'),
                    expansion=[VariableExpansion(needle='AUTHOR', prompt='Who wrote it?')],
                )
            ],
        )
        merged = preset.merged_expansion('interactive', is_contest=False)
        assert len(merged) == 1
        assert merged[0].prompt == 'Who wrote it?'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_preset_variants.py -v`
Expected: FAIL — `Preset` has no `problemVariants` / `merged_tracking`.

**Step 3: Implement**

In `rbx/box/presets/schema.py`, add to `class Preset` after the `libraries` field:

```python
    # Additional problem templates ("variants") offered by this preset, beyond
    # the canonical `problem` template. Selected with `rbx create --variant`.
    problemVariants: List[PackageVariant] = Field(default_factory=list)

    # Additional contest templates, selected with `rbx contest create --variant`.
    contestVariants: List[PackageVariant] = Field(default_factory=list)
```

And these methods on `Preset`:

```python
    @model_validator(mode='after')
    def validate_unique_variant_ids(self) -> 'Preset':
        for kind, variants in (
            ('problemVariants', self.problemVariants),
            ('contestVariants', self.contestVariants),
        ):
            seen = set()
            for variant in variants:
                if variant.id in seen:
                    raise ValueError(f'duplicate variant id {variant.id} in {kind}')
                seen.add(variant.id)
        return self

    def variants(self, is_contest: bool) -> List[PackageVariant]:
        return self.contestVariants if is_contest else self.problemVariants

    def find_variant(
        self, variant_id: str, is_contest: bool
    ) -> Optional[PackageVariant]:
        for variant in self.variants(is_contest):
            if variant.id == variant_id:
                return variant
        return None

    def merged_tracking(
        self, variant_id: Optional[str], is_contest: bool
    ) -> List[TrackedAsset]:
        shared = self.tracking.contest if is_contest else self.tracking.problem
        return _merge_by(
            self._variant_tracking(variant_id, is_contest), shared, lambda a: a.path
        )

    def merged_libraries(
        self, variant_id: Optional[str], is_contest: bool
    ) -> List[Library]:
        shared = self.libraries.contest if is_contest else self.libraries.problem
        return _merge_by(
            self._variant_libraries(variant_id, is_contest), shared, lambda lib: lib.name
        )

    def merged_expansion(
        self, variant_id: Optional[str], is_contest: bool
    ) -> List[VariableExpansion]:
        shared = self.expansion.contest if is_contest else self.expansion.problem
        return _merge_by(
            self._variant_expansion(variant_id, is_contest), shared, lambda e: e.needle
        )
```

Add the three tiny private accessors (returning `[]` when `variant_id is None` or the id is unknown) and this module-level helper above `class Preset`:

```python
T = TypeVar('T')


def _merge_by(
    overrides: List[T], base: List[T], key: Callable[[T], Any]
) -> List[T]:
    """Merge `overrides` over `base`, keyed by `key`. Overrides win; base order
    is preserved and override-only entries are appended."""
    override_by_key = {key(item): item for item in overrides}
    res = [override_by_key.pop(key(item), item) for item in base]
    res.extend(override_by_key.values())
    return res
```

Import `Any`, `Callable`, `TypeVar` from `typing`.

**Step 4: Verify**

Run: `uv run pytest tests/rbx/box/presets/test_preset_variants.py -v`
Expected: PASS.

Then confirm nothing regressed: `uv run pytest tests/rbx/box/presets -v` — expected PASS.

**Step 5: Lint and commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/presets/schema.py tests/rbx/box/presets/test_preset_variants.py
git commit -m "$(cat <<'EOF'
feat(presets): declare problem and contest variants on Preset

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `resolve_template()`

This is the choke point. Every consumer goes through it after Task 4.

**Files:**
- Modify: `rbx/box/presets/__init__.py` (add near `_get_active_preset_package_path`, ~line 601)
- Test: `tests/rbx/box/presets/test_preset_variants.py`

**Step 1: Write the failing tests**

```python
from rbx.box import presets


def _write_preset(root: pathlib.Path, body: str) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'preset.rbx.yml').write_text(body)
    (root / 'problem').mkdir(exist_ok=True)
    (root / 'problem-interactive').mkdir(exist_ok=True)
    return root


PRESET_WITH_VARIANT = """---
name: "with-variant"
uri: "test/with-variant"
problem: "problem"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    description: "Interactive"
"""


class TestResolveTemplate:
    def test_canonical_when_no_variant_requested(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(preset, root, is_contest=False, variant=None)
        assert resolved.variant_id is None
        assert resolved.path == root / 'problem'

    def test_named_variant(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='interactive'
        )
        assert resolved.variant_id == 'interactive'
        assert resolved.path == root / 'problem-interactive'

    def test_default_keyword_means_canonical(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='default'
        )
        assert resolved.variant_id is None

    def test_unknown_variant_exits_and_lists_available(self, tmp_path, capsys):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=False, variant='nope')
        out = capsys.readouterr().out
        assert 'nope' in out
        assert 'interactive' in out

    def test_missing_canonical_without_variant_exits(self, tmp_path, capsys):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "variant-only"
uri: "test/variant-only"
problemVariants:
  - id: interactive
    path: "problem-interactive"
""",
        )
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=False, variant=None)

    def test_carries_merged_config(self, tmp_path):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
problem: "problem"
tracking:
  problem:
    - path: ".gitignore"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    tracking:
      - path: "interactor.cpp"
""",
        )
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='interactive'
        )
        assert {str(a.path) for a in resolved.tracking} == {'.gitignore', 'interactor.cpp'}
```

Also add a test for the nested-cwd mapping:

```python
    def test_variant_for_path_maps_nested_cwd(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        assert (
            presets.variant_for_path(preset, root, root / 'problem-interactive' / 'sols',
                                     is_contest=False)
            == 'interactive'
        )
        assert (
            presets.variant_for_path(preset, root, root / 'problem', is_contest=False)
            is None
        )
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_preset_variants.py -k Resolve -v`
Expected: FAIL — `resolve_template` does not exist.

**Step 3: Implement**

In `rbx/box/presets/__init__.py`:

```python
@dataclasses.dataclass(frozen=True)
class ResolvedTemplate:
    """A preset template directory plus the config that applies to it.

    `variant_id` is None for the preset's canonical template.
    """

    variant_id: Optional[str]
    path: pathlib.Path
    tracking: List[TrackedAsset]
    libraries: List[Library]
    expansion: List[VariableExpansion]


def resolve_template(
    preset: Preset,
    preset_path: pathlib.Path,
    *,
    is_contest: bool,
    variant: Optional[str],
) -> ResolvedTemplate:
    kind = 'contest' if is_contest else 'problem'
    if variant == 'default':
        variant = None

    if variant is None:
        canonical = preset.contest if is_contest else preset.problem
        if canonical is None:
            console.console.print(
                f'[error]Preset [item]{preset.name}[/item] does not have a canonical '
                f'{kind} template.[/error]'
            )
            _print_available_variants(preset, is_contest)
            raise typer.Exit(1)
        inner = canonical
    else:
        found = preset.find_variant(variant, is_contest)
        if found is None:
            console.console.print(
                f'[error]Preset [item]{preset.name}[/item] has no {kind} variant '
                f'[item]{variant}[/item].[/error]'
            )
            _print_available_variants(preset, is_contest)
            raise typer.Exit(1)
        inner = found.path

    path = preset_path / inner
    if not path.is_dir():
        console.console.print(
            f'[error]Preset [item]{preset.name}[/item] declares a {kind} template at '
            f'[item]{inner}[/item], but that directory does not exist.[/error]'
        )
        raise typer.Exit(1)

    return ResolvedTemplate(
        variant_id=variant,
        path=path,
        tracking=preset.merged_tracking(variant, is_contest),
        libraries=preset.merged_libraries(variant, is_contest),
        expansion=preset.merged_expansion(variant, is_contest),
    )
```

`_print_available_variants` prints `default` (when a canonical exists) plus each `id — description`.

`variant_for_path` maps a directory inside the preset to the variant that owns it, by longest matching declared path:

```python
def variant_for_path(
    preset: Preset,
    preset_path: pathlib.Path,
    target: pathlib.Path,
    *,
    is_contest: bool,
) -> Optional[str]:
    """Which variant's template directory contains `target`? None == canonical."""
    target = utils.abspath(target)
    best: Optional[Tuple[int, str]] = None
    for variant in preset.variants(is_contest):
        candidate = utils.abspath(preset_path / variant.path)
        if target == candidate or target.is_relative_to(candidate):
            depth = len(candidate.parts)
            if best is None or depth > best[0]:
                best = (depth, variant.id)
    return best[1] if best is not None else None
```

Import `dataclasses` at the top of the module.

**Step 4: Verify**

Run: `uv run pytest tests/rbx/box/presets/test_preset_variants.py -v`
Expected: PASS.

**Step 5: Lint and commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/presets/__init__.py tests/rbx/box/presets/test_preset_variants.py
git commit -m "$(cat <<'EOF'
feat(presets): resolve preset templates through one choke point

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Route every consumer through `ResolvedTemplate`

Pure refactor — **no behavior change**. The existing suite is the test: it must stay green without edits beyond signature updates.

**Files:**
- Modify: `rbx/box/presets/__init__.py` — `get_preset_tracked_assets` (~296), `_copy_updated_assets` (~480), `_get_active_preset_package_path` (~601), `_install_package_from_preset` (~944), `materialize_libraries` (~985), `install_contest` (~1003), `install_problem` (~1043)

**Step 1: Run the suite first to record the baseline**

Run: `uv run pytest tests/rbx/box/presets -v`
Expected: PASS. Note the count; it must not drop.

**Step 2: Refactor, one function at a time**

- `get_preset_tracked_assets(root, is_contest, add_symlinks=False)` → `get_template_tracked_assets(template: ResolvedTemplate, add_symlinks: bool = False)`. It globs `template.tracking` against `template.path` and appends symlinks found under `template.path`. This removes the current oddity where `_copy_updated_assets` passes the *template dir* back in as a package root, forcing a re-resolution of the preset from there.
- `_get_active_preset_package_path(root, is_contest)` → `get_active_template(root, *, is_contest, variant)`, returning a `ResolvedTemplate` via `resolve_template(get_active_preset(root), get_active_preset_path(root), ...)`.
- `materialize_libraries(preset, pkg_root, is_contest)` → `materialize_libraries(template: ResolvedTemplate, pkg_root)`, iterating `template.libraries`.
- `install_problem` / `install_contest` gain `variant: Optional[str] = None`, resolve once, and pass `template.path` (relative to the preset root), `template.tracking`, and `template.expansion` down to `_install_package_from_preset`.
- `_copy_updated_assets` takes the `ResolvedTemplate` instead of `is_contest`.

Keep the public names `install_problem` / `install_contest` — external callers depend on them, and `tests/rbx/box/test_creation.py` patches `presets.install_problem` by name.

**Step 3: Verify no regression**

```bash
uv run pytest tests/rbx/box/presets -v
uv run pytest tests/rbx/box/test_creation.py -v
uv run pytest --ignore=tests/rbx/box/cli -n auto
```
Expected: same pass count as the baseline.

**Step 4: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/presets/__init__.py
git commit -m "$(cat <<'EOF'
refactor(presets): thread ResolvedTemplate through install and sync

Removes the three independent lookups of preset.problem/preset.contest so
variant resolution cannot drift between install, tracking and sync.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Record the variant in the lock and honor it on sync

**Files:**
- Modify: `rbx/box/presets/lock_schema.py`, `rbx/box/presets/__init__.py` (`generate_lock` ~1202, `_sync` ~1215)
- Test: `tests/rbx/box/presets/test_preset_variants.py`

**Step 1: Write the failing tests**

```python
class TestLockVariant:
    def test_lock_defaults_to_none(self):
        from rbx.box.presets.lock_schema import PresetLock

        assert PresetLock(name='p').variant is None

    def test_existing_lock_without_variant_still_parses(self):
        from rbx.box.presets.lock_schema import PresetLock

        lock = PresetLock.model_validate({'name': 'default', 'assets': []})
        assert lock.variant is None

    def test_generate_lock_records_variant(self, tmp_path):
        # Build a package installed from the 'interactive' variant, then
        # generate its lock and assert `variant: interactive` round-trips.
        ...

    def test_sync_uses_the_locked_variant(self, tmp_path):
        # Track the same filename in both the canonical and the variant template
        # with DIFFERENT contents; sync a package locked to the variant and
        # assert it receives the variant's content, not the canonical's.
        ...

    def test_sync_errors_when_locked_variant_disappeared(self, tmp_path, capsys):
        # Remove the variant from preset.rbx.yml after creation; sync must exit
        # non-zero and name the missing variant, NOT silently fall back.
        ...
```

Flesh out the three stubs using the `simple_preset_testdata` + `install_preset_from_dir` pattern from `tests/rbx/box/presets/test_presets.py:151-190`.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_preset_variants.py -k Lock -v`
Expected: FAIL — `PresetLock` has no `variant`.

**Step 3: Implement**

`lock_schema.py`:

```python
class PresetLock(BaseModel):
    name: str

    # Which preset template this package was created from. None means the
    # preset's canonical template — which is what every pre-variants lock file
    # means, so old locks keep working untouched.
    variant: Optional[str] = None
```

`generate_lock(root, variant=None)` writes it through. `_sync` resolves with `variant=preset_lock.variant`; when `resolve_template` cannot find that variant it must fail with a message naming the variant and pointing at `.preset-lock.yml`, never fall back to canonical.

**Step 4: Verify**

Run: `uv run pytest tests/rbx/box/presets -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/presets/lock_schema.py rbx/box/presets/__init__.py tests/rbx/box/presets/test_preset_variants.py
git commit -m "$(cat <<'EOF'
feat(presets): record the template variant in the package lock

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Clean variant dirs when copying a preset

`install_preset_from_dir` (~line 692) cleans build cruft from `preset.problem` and `preset.contest` only. Without this fix, `rbx presets create -p <other>` copies `build/` and `.box/` junk out of every variant directory.

**Files:**
- Modify: `rbx/box/presets/__init__.py:692-745`
- Test: `tests/rbx/box/presets/test_preset_variants.py`

**Step 1: Failing test** — model it on `test_install_preset_from_dir` (`tests/rbx/box/presets/test_presets.py:556`), but put an `out/` (or `build/`) directory inside a declared variant dir and assert it is gone after the copy.

**Step 2:** Run it; expect FAIL (the junk survives).

**Step 3:** In `install_preset_from_dir`, after the existing `clean_copied_problem_dir` / `clean_copied_contest_dir` calls, loop over `preset.problemVariants` calling `clean_copied_problem_dir(dest / v.path, ...)` and over `preset.contestVariants` calling `clean_copied_contest_dir(dest / v.path, delete_local_rbx=False, ...)`.

**Step 4:** Run `uv run pytest tests/rbx/box/presets -v`; expect PASS.

**Step 5:** Commit as `fix(presets): clean build cruft from variant template dirs`.

---

## Task 7: CLI selection — flag plus picker

**Files:**
- Modify: `rbx/box/creation.py`, `rbx/box/cli.py:845`, `rbx/box/contest/main.py` (~103-117 create, ~287 add), `rbx/box/presets/__init__.py` (picker)
- Test: `tests/rbx/box/test_creation.py`, `tests/rbx/box/presets/test_preset_variants.py`

**Step 1: Write the failing tests**

```python
class TestVariantPicker:
    def test_no_variants_declared_never_prompts(self, tmp_path, monkeypatch):
        # questionary.select must not be called; result is the canonical.
        ...

    def test_non_tty_falls_back_to_canonical(self, tmp_path, monkeypatch):
        monkeypatch.setattr(presets.sys.stdin, 'isatty', lambda: False)
        ...

    def test_non_tty_without_canonical_exits(self, tmp_path, monkeypatch):
        ...

    def test_explicit_variant_skips_the_prompt(self, tmp_path, monkeypatch):
        ...
```

And in `tests/rbx/box/test_creation.py`, extend the existing stub-based tests to assert `creation.create('p', variant='interactive')` forwards `variant` to `presets.install_problem`.

**Step 2:** Run; expect FAIL.

**Step 3: Implement**

In `rbx/box/presets/__init__.py`, mirroring `registry.pick_preset` (`rbx/box/presets/registry.py:92-114`):

```python
def pick_variant(
    preset: Preset, *, is_contest: bool, variant: Optional[str]
) -> Optional[str]:
    """Resolve the variant to use, prompting when the preset offers a choice.

    Returns None for the canonical template. Never prompts when the preset
    declares no variants, or when stdin is not a TTY.
    """
    if variant is not None:
        return variant
    variants = preset.variants(is_contest)
    if not variants:
        return None

    canonical = preset.contest if is_contest else preset.problem
    if not sys.stdin.isatty():
        if canonical is None:
            console.console.print(
                f'[error]Preset [item]{preset.name}[/item] has no canonical template; '
                'pass --variant explicitly.[/error]'
            )
            raise typer.Exit(1)
        return None

    import questionary

    choices = []
    if canonical is not None:
        choices.append(questionary.Choice(title='default — canonical template', value='default'))
    for v in variants:
        title = f'{v.id} — {v.description}' if v.description else v.id
        choices.append(questionary.Choice(title=title, value=v.id))

    answer = questionary.select(
        'Which problem template do you want to use?'
        if not is_contest
        else 'Which contest template do you want to use?',
        choices=choices,
        default=choices[0].value,
    ).ask()
    if answer is None:
        raise typer.Exit(1)
    return None if answer == 'default' else answer
```

Call it from `install_problem` / `install_contest` — after the preset is installed and readable, before `resolve_template` — so both `rbx create` and `rbx contest add` get the prompt for free.

Thread `variant: Optional[str] = None` through `creation.create()` and add to each command:

```python
    variant: Annotated[
        Optional[str],
        typer.Option(
            '--variant',
            '-v',
            help='Which template variant of the preset to use. Omit to use the '
            'canonical template, or to be prompted when the preset offers variants.',
        ),
    ] = None,
```

Check `-v` is not already taken on those commands (`rbx create`, `rbx contest add`, `rbx contest create`); if it is, register `--variant` only and note it in the docs.

**Step 4:** Run `uv run pytest tests/rbx/box/presets tests/rbx/box/test_creation.py -v`; expect PASS.

**Step 5:** Commit as `feat(presets): select a template variant when creating packages`.

---

## Task 8: Surface variants in `rbx presets ls`

**Files:**
- Modify: `rbx/box/presets/__init__.py` (`ls` command, near the end of the file)
- Test: `tests/rbx/box/presets/test_preset_variants.py`

Print a Rich table of `id`, `description`, `path` for the active preset's problem and contest variants, marking the one recorded in `.preset-lock.yml` (fall back to `default`). Test by invoking the command in a package installed from a variant and asserting both the variant id and the marker appear in the captured output.

Commit as `feat(presets): list template variants in rbx presets ls`.

---

## Task 9: Test scaffolding — `TestingPreset` helpers and a fixture variant

**Files:**
- Modify: `rbx/box/testing/testing_preset.py`
- Create: `rbx/testdata/presets/simple-preset/problem-interactive/template.cpp`, `.../problem-interactive/.gitignore`, `.../problem-interactive/interactor.cpp`
- Modify: `rbx/testdata/presets/simple-preset/preset.rbx.yml`

Add to `TestingPreset`, next to `set_problem_path` / `create_problem_package`:

```python
    def add_problem_variant(self, id: str, path: PathOrStr, description: str = ''): ...
    def create_problem_variant_package(self, id: str): ...
```

Extend `simple-preset/preset.rbx.yml` with:

```yaml
problemVariants:
  - id: interactive
    path: "problem-interactive"
    description: "Interactive variant for tests"
    tracking:
      - path: "interactor.cpp"
```

Give `problem-interactive/template.cpp` **different** content from `problem/template.cpp` — several tests turn on distinguishing them.

Check whether any existing test asserts over the whole `simple-preset` tree (a recursive listing or an exact file-set assertion). If so, update it. Run `uv run pytest tests/rbx/box/presets -v` and expect PASS.

Commit as `test(presets): add a variant to the simple preset fixture`.

---

## Task 10: The bundled `interactive` variant

**Files:**
- Modify: `rbx/resources/presets/default/preset.rbx.yml`
- Create under `rbx/resources/presets/default/problem-interactive/`: `problem.rbx.yml`, `interactor.cpp`, `validator.cpp`, `rbx.h`, `.gitignore`, `sols/main.cpp`, `tests/gen.cpp`, `tests/testplan.txt`, `statement/statement.rbx.tex`, `statement/editorial.rbx.tex`, `statement/samples/000.in`, `statement/samples/000.rbx.tex`
- Test: `tests/rbx/box/presets/test_default_preset_variants.py` (create)

The task is the guessing game from `docs/setters/grading/interactors.md`: the input file holds `N S`; the solution asks `? X` (here, plain integers) and the interactor answers `<`, `>`, `=`; at most `Q.max` guesses.

`preset.rbx.yml` gains:

```yaml
problemVariants:
  - id: interactive
    path: "problem-interactive"
    description: "Communication task with a testlib interactor (guessing game)"
```

`problem-interactive/problem.rbx.yml` — copy the canonical and change: `type: communication`, add `interactor: {path: "interactor.cpp"}`, **remove `checker:`** (the schema rejects a checker on a communication problem), keep `validator`, and set `vars` to `N: {min: 2, max: 1000}` plus `Q: {max: 10}`.

`interactor.cpp` — the documented interactor verbatim (`registerInteraction`, `inf.readInt()` twice, `getVar<int>("Q.max")`, `ouf.readInt(1, N)`, `cout` responses, `tout` guess count, `quitf(_ok, ...)` / `quitf(_wa, "exceeded the maximum number of guesses")`).

`sols/main.cpp` — binary search over `[1, N]` reading the response character, flushing after every guess (`endl`).

`validator.cpp` — `registerValidation` + `prepareOpts`, read `N` in `[N.min, N.max]`, a space, `S` in `[1, N]`, eoln, eof.

`tests/gen.cpp` — `registerGen`, print `N` then `rnd.next(1, N)`. `tests/testplan.txt` — a couple of live (uncommented) `tests/gen` lines so the variant produces a real testset; verify against how the canonical testplan is consumed.

`rbx.h` and `.gitignore` — byte-identical copies of the canonical ones.

Statement — canonical structure plus an Interaction block describing the protocol; `statement/samples/000.in` is `10 7`; `000.rbx.tex` explains the interaction.

Do **not** create `build/` or `.box/` directories.

**Tests** in `tests/rbx/box/presets/test_default_preset_variants.py`:

```python
def test_default_preset_declares_interactive_variant():
    # Read the bundled preset.rbx.yml through the Preset model; assert the
    # variant exists and its path is a real directory.

def test_interactive_variant_package_is_valid_communication_task():
    # Validate problem-interactive/problem.rbx.yml through the Package model.
    # Assert type is COMMUNICATION, interactor is set, checker is None.

@pytest.mark.parametrize('shared', ['rbx.h', '.gitignore'])
def test_shared_files_match_the_canonical_template(shared):
    # Byte-compare against problem/<shared> so the copies cannot drift.
```

Run `uv run pytest tests/rbx/box/presets -v`; expect PASS. Commit as `feat(presets): ship an interactive variant in the default preset`.

---

## Task 11: End-to-end coverage

**Files:**
- Modify: `tests/e2e/spec.py` (`Scenario`), `tests/e2e/runner.py` (`seed_package_from_preset`, line 86)
- Create: `tests/e2e/testdata/default-preset-interactive/e2e.rbx.yml`
- Test: `tests/e2e/test_seed_from_preset.py`

`seed_package_from_preset` hardcodes `presets/<name>/problem`. Add an optional variant so a scenario can seed from one:

```yaml
scenarios:
  - name: works
    seed_from_preset: default
    seed_from_preset_variant: interactive
```

The runner resolves the directory by reading the preset's `preset.rbx.yml` through the `Preset` model and looking the variant up with `find_variant`, rather than guessing a directory name. Unknown variant → `FileNotFoundError` naming it, matching the existing unknown-preset behavior.

Scenario steps: `build` (assert the generated test groups), `run` (assert `sols/main.cpp: ac` — this exercises the interactor end to end), and `st b` (assert `build/statement-en.pdf`).

Add unit tests next to the existing ones in `tests/e2e/test_seed_from_preset.py`: the new field parses, defaults to `None`, seeds the interactive files (`interactor.cpp` present, `wcmp.cpp` absent), and raises on an unknown variant.

Run: `uv run pytest tests/e2e/test_seed_from_preset.py -v`, then `mise run test-e2e`. The e2e run compiles C++ — if it fails for sandbox/toolchain reasons unrelated to your change, confirm the same failure on `main` before chasing it. See `tests/e2e/README.md` for the DSL.

Commit as `test(e2e): cover the default preset's interactive variant`.

---

## Task 12: Documentation

**Files:**
- Modify: `docs/setters/presets/index.md`, `docs/setters/grading/interactors.md`

In `docs/setters/presets/index.md`, after "Setting up the problem template", add **Problem template variants**:

- What a variant is and when to add one (interactive, subtask-scored).
- The `problemVariants` YAML, with the `interactive` example.
- Selecting one: `rbx create foo -v interactive`, `rbx contest add ... -v interactive`, and the prompt when the flag is omitted.
- Per-variant `tracking` / `libraries` / `expansion` and the merge rule (variant wins).
- Sharing files: plain copies *or* in-preset symlinks (explaining that a symlink pointing elsewhere in the preset is rewritten at install time into a relative link into the package's `.local.rbx/`).
- That the variant is fixed at creation and recorded in `.preset-lock.yml`; changing it means recreating the problem (or hand-editing the lock).
- That `contestVariants` works identically.

In `docs/setters/grading/interactors.md`, add near the top that the default preset ships this exact problem as a variant: `rbx create guess -v interactive`.

Verify with a **non-strict** build — this repo has ~9 pre-existing `--strict` warnings unrelated to your change:

```bash
uv run mkdocs build
```

Commit as `docs(presets): document problem template variants`.

---

## Final verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest --ignore=tests/rbx/box/cli -n auto
uv run pytest tests/rbx/box/presets -v
uv run mkdocs build
```

Then, by hand, in a scratch directory outside the repo:

```bash
uv run rbx create guess -p default -v interactive
cd guess && uv run rbx build && uv run rbx run
grep variant .preset-lock.yml     # expect: variant: interactive
uv run rbx presets sync           # expect: syncs against problem-interactive
```

Backward-compatibility spot check, in the same scratch directory:

```bash
uv run rbx create plain -p default     # no prompt beyond today's; canonical template
grep variant plain/.preset-lock.yml    # expect: variant: null (or absent)
```

Do not report the feature complete until `rbx run` on the generated interactive problem judges `sols/main.cpp` as accepted — that is the single check proving the interactor, validator, generator, and schema all line up.
