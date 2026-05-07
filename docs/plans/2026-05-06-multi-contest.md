# Multi-Contest Packages Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow a single contest directory to host multiple `Contest` configurations (variants), selectable via `-C <id>` / `RBX_CONTEST`, sharing the same filesystem (statements, problems, assets).

**Architecture:** `contest.rbx.yml` is always required and either (a) is itself the single contest (today's behavior, default) or (b) sets `use_variants: true` and acts as a sentinel — variants live in sibling `contest.<id>.rbx.yml` files. A contextvar holds the current selection set by Typer callbacks. `find_contest_yaml` is variant-aware. Implicit consumers (naming, packaging, BOCA, statement-extends) auto-pick when a problem belongs to exactly one variant; otherwise they error with a picker message.

**Tech Stack:** Pydantic v2, Typer, contextvars, `@functools.cache`, ruyaml.

**Reference:** [`docs/plans/2026-05-06-multi-contest-design.md`](2026-05-06-multi-contest-design.md).

---

## Pre-flight

- Worktree: `.worktrees/multi-contest`, branch `feature/multi-contest`.
- Use `/commit` skill conventions (`feat`, `fix`, `docs`, `test`, `refactor`).
- Run `uv run pytest --ignore=tests/rbx/box/cli -n auto` after each task; commit only when green.
- After every task that adds a `@functools.cache`, register it in `rbx/testing_utils.py:clear_all_functools_cache`.

---

## Task 1: Add `use_variants` to `Contest` schema

**Files:**
- Modify: `rbx/box/contest/schema.py:258-309`
- Test: `tests/rbx/box/contest/test_contest_schema.py`

**Step 1: Write the failing tests**

Add to `tests/rbx/box/contest/test_contest_schema.py`:

```python
def test_contest_default_is_not_dispatcher():
    contest = Contest(name='c')
    assert contest.use_variants is False
    assert contest.is_dispatcher is False


def test_contest_dispatcher_skips_required_validation():
    contest = Contest.model_validate({'use_variants': True})
    assert contest.is_dispatcher is True
    assert contest.problems == []
    assert contest.statements == []


def test_contest_dispatcher_rejects_problems_field():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        Contest.model_validate({
            'use_variants': True,
            'problems': [{'short_name': 'A'}],
        })
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_schema.py -v -k 'dispatcher or default_is_not'`
Expected: FAIL (no `use_variants`/`is_dispatcher` attribute).

**Step 3: Implementation**

In `rbx/box/contest/schema.py`, modify `Contest`:

```python
class Contest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    use_variants: bool = Field(
        default=False,
        description=(
            'When true, this file is a sentinel marking the directory as a '
            'multi-contest dispatcher. The actual contests live in sibling '
            'files matching contest.<id>.rbx.yml. When set, no other Contest '
            'fields may be specified.'
        ),
    )

    name: str = Field(
        default='', description='Name of this contest.'
    )  # Was NameField; relaxed to allow empty for dispatcher mode.

    # ... rest of fields stay (titles, problems, statements, vars), all already have defaults ...

    @model_validator(mode='after')
    def _validate_dispatcher_or_real(self):
        if self.use_variants:
            for field in ('name', 'titles', 'problems', 'statements', 'vars'):
                value = getattr(self, field)
                if value:
                    raise ValueError(
                        f'Field {field!r} cannot be set when use_variants is true.'
                    )
        else:
            if not self.name:
                raise ValueError('Field "name" is required for a contest.')
        return self

    @property
    def is_dispatcher(self) -> bool:
        return self.use_variants
```

Keep `check_problem_identifiers_unique` as-is. Note: `name` field constraints from `NameField` are moved into the conditional validator so dispatcher mode can omit it. If `NameField` provides a regex, port that check into `_validate_dispatcher_or_real` for the non-dispatcher branch (keep the regex tight; reuse the same one).

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/rbx/box/contest/test_contest_schema.py -v`
Expected: All pass. Existing schema tests must still pass.

**Step 5: Commit**

```bash
git add rbx/box/contest/schema.py tests/rbx/box/contest/test_contest_schema.py
git commit -m "feat(contest): add use_variants dispatcher mode to Contest schema"
```

---

## Task 2: Variant id constants and selection state module

**Files:**
- Create: `rbx/box/contest/contest_state.py`
- Test: `tests/rbx/box/contest/test_contest_state.py`

**Step 1: Write the failing tests**

```python
import re
import pytest

from rbx.box.contest import contest_state


def test_variant_id_pattern_accepts_typical_ids():
    assert contest_state.is_valid_variant_id('div1')
    assert contest_state.is_valid_variant_id('warmup')
    assert contest_state.is_valid_variant_id('A1')
    assert contest_state.is_valid_variant_id('ioi-2024_main')


def test_variant_id_pattern_rejects_invalid():
    assert not contest_state.is_valid_variant_id('')
    assert not contest_state.is_valid_variant_id('1div')
    assert not contest_state.is_valid_variant_id('div 1')
    assert not contest_state.is_valid_variant_id('div.1')


def test_selection_default_is_none():
    assert contest_state.get_selected_variant_id() is None


def test_set_selected_variant_id_round_trip():
    token = contest_state.selected_variant_id_var.set('div1')
    try:
        assert contest_state.get_selected_variant_id() == 'div1'
    finally:
        contest_state.selected_variant_id_var.reset(token)
    assert contest_state.get_selected_variant_id() is None


def test_resolve_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('RBX_CONTEST', 'envdiv')
    assert contest_state.resolve_explicit_selection() == 'envdiv'


def test_resolve_prefers_var_over_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('RBX_CONTEST', 'envdiv')
    token = contest_state.selected_variant_id_var.set('flagdiv')
    try:
        assert contest_state.resolve_explicit_selection() == 'flagdiv'
    finally:
        contest_state.selected_variant_id_var.reset(token)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_state.py -v`
Expected: FAIL (module doesn't exist).

**Step 3: Implementation**

Create `rbx/box/contest/contest_state.py`:

```python
import contextvars
import os
import re
from typing import Optional

VARIANT_ID_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*$')
ENV_VAR = 'RBX_CONTEST'

selected_variant_id_var: contextvars.ContextVar[Optional[str]] = (
    contextvars.ContextVar('rbx_selected_variant_id', default=None)
)


def is_valid_variant_id(value: str) -> bool:
    return bool(VARIANT_ID_PATTERN.match(value))


def get_selected_variant_id() -> Optional[str]:
    return selected_variant_id_var.get()


def resolve_explicit_selection() -> Optional[str]:
    """Returns the selected variant id, preferring contextvar over env var."""
    explicit = selected_variant_id_var.get()
    if explicit is not None:
        return explicit
    env_value = os.environ.get(ENV_VAR)
    if env_value:
        return env_value
    return None
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/rbx/box/contest/test_contest_state.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add rbx/box/contest/contest_state.py tests/rbx/box/contest/test_contest_state.py
git commit -m "feat(contest): add variant id selection state and helpers"
```

---

## Task 3: Variant discovery helper

**Files:**
- Modify: `rbx/box/contest/contest_package.py` (top of file)
- Test: `tests/rbx/box/contest/test_contest_package.py` (new test class)

**Step 1: Write the failing tests**

Add `class TestDiscoverVariants` to the existing test file:

```python
def test_discover_variants_single_mode_returns_default(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text('name: c\n')
    variants = cp_module.discover_contest_variants(tmp_path)
    assert variants == {None: tmp_path / 'contest.rbx.yml'}


def test_discover_variants_dispatcher_mode_lists_siblings(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
    (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1\n')
    (tmp_path / 'contest.div2.rbx.yml').write_text('name: div2\n')
    variants = cp_module.discover_contest_variants(tmp_path)
    assert set(variants.keys()) == {'div1', 'div2'}
    assert variants['div1'].name == 'contest.div1.rbx.yml'


def test_discover_variants_dispatcher_with_invalid_id(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
    (tmp_path / 'contest.bad name.rbx.yml').write_text('name: bad\n')
    variants = cp_module.discover_contest_variants(tmp_path)
    # Files with invalid ids are silently skipped (logged elsewhere).
    assert variants == {}


def test_discover_variants_no_yaml_returns_empty(tmp_path):
    assert cp_module.discover_contest_variants(tmp_path) == {}


def test_discover_variants_real_contest_with_siblings_errors(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text('name: c\n')
    (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1\n')
    with pytest.raises(typer.Exit):
        cp_module.discover_contest_variants(tmp_path)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py::TestDiscoverVariants -v`
Expected: FAIL (function doesn't exist).

**Step 3: Implementation**

In `rbx/box/contest/contest_package.py`, add (after existing imports, before `find_contest_yaml`):

```python
from typing import Dict
from rbx.box.contest.contest_state import is_valid_variant_id

VARIANT_GLOB = 'contest.*.rbx.yml'


def discover_contest_variants(
    contest_root: pathlib.Path,
) -> Dict[Optional[str], pathlib.Path]:
    """Returns variant_id -> yaml path. Single-contest mode uses key None.

    Errors via typer.Exit if contest.rbx.yml is a real contest AND there are
    sibling contest.<id>.rbx.yml files (ambiguous).
    """
    canonical = contest_root / YAML_NAME
    if not canonical.is_file():
        return {}

    canonical_contest = load_yaml_model(canonical, Contest)
    sibling_paths = sorted(contest_root.glob(VARIANT_GLOB))
    siblings: Dict[str, pathlib.Path] = {}
    for path in sibling_paths:
        # path.name is e.g. 'contest.div1.rbx.yml' -> id 'div1'
        # Strip leading 'contest.' and trailing '.rbx.yml'.
        name = path.name[len('contest.'):-len('.rbx.yml')]
        if not is_valid_variant_id(name):
            continue
        siblings[name] = path

    if canonical_contest.is_dispatcher:
        return {vid: p for vid, p in siblings.items()}

    if siblings:
        console.console.print(
            f'[error]{canonical} is a real contest but sibling variant files '
            f'exist: {[p.name for p in siblings.values()]}. Set '
            f'use_variants: true on contest.rbx.yml to enable dispatcher '
            f'mode.[/error]'
        )
        raise typer.Exit(1)

    return {None: canonical}
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py::TestDiscoverVariants -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py
git commit -m "feat(contest): add discover_contest_variants helper"
```

---

## Task 4: Variant-aware `find_contest_yaml` / `find_contest_package`

**Files:**
- Modify: `rbx/box/contest/contest_package.py:66-96`
- Modify: `rbx/testing_utils.py` (no change expected — already covers `contest_package`).
- Test: `tests/rbx/box/contest/test_contest_package.py` (new test class).

**Step 1: Write the failing tests**

```python
class TestFindContestYamlVariantAware:
    def test_single_mode_returns_canonical(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('name: c\n')
        cp_module.find_contest_yaml.cache_clear()
        assert cp_module.find_contest_yaml(tmp_path) == tmp_path / 'contest.rbx.yml'

    def test_dispatcher_with_explicit_selection(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1\n')
        cp_module.find_contest_yaml.cache_clear()
        assert (
            cp_module.find_contest_yaml(tmp_path, contest_id='div1')
            == tmp_path / 'contest.div1.rbx.yml'
        )

    def test_dispatcher_unknown_id_errors(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        cp_module.find_contest_yaml.cache_clear()
        with pytest.raises(typer.Exit):
            cp_module.find_contest_yaml(tmp_path, contest_id='ghost')

    def test_dispatcher_no_selection_returns_none(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1\n')
        cp_module.find_contest_yaml.cache_clear()
        assert cp_module.find_contest_yaml(tmp_path) is None

    def test_single_mode_with_id_errors(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('name: c\n')
        cp_module.find_contest_yaml.cache_clear()
        with pytest.raises(typer.Exit):
            cp_module.find_contest_yaml(tmp_path, contest_id='div1')

    def test_uses_contextvar_when_no_arg(self, tmp_path):
        from rbx.box.contest.contest_state import selected_variant_id_var
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div2.rbx.yml').write_text('name: div2\n')
        cp_module.find_contest_yaml.cache_clear()
        token = selected_variant_id_var.set('div2')
        try:
            assert (
                cp_module.find_contest_yaml(tmp_path)
                == tmp_path / 'contest.div2.rbx.yml'
            )
        finally:
            selected_variant_id_var.reset(token)
            cp_module.find_contest_yaml.cache_clear()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py::TestFindContestYamlVariantAware -v`
Expected: FAIL (signature doesn't accept `contest_id`).

**Step 3: Implementation**

Replace `find_contest_yaml` and `find_contest_package` in `rbx/box/contest/contest_package.py`:

```python
@functools.cache
def find_contest_yaml(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> Optional[pathlib.Path]:
    from rbx.box.contest.contest_state import resolve_explicit_selection

    root = utils.abspath(root)
    contest_yaml_path = root / YAML_NAME
    while root != pathlib.PosixPath('/') and not contest_yaml_path.is_file():
        root = root.parent
        contest_yaml_path = root / YAML_NAME
    if not contest_yaml_path.is_file():
        return None

    contest_root = contest_yaml_path.parent
    canonical_contest = load_yaml_model(contest_yaml_path, Contest)

    effective_id = contest_id if contest_id is not None else resolve_explicit_selection()

    if not canonical_contest.is_dispatcher:
        if effective_id is not None:
            console.console.print(
                f'[error]Contest at {contest_root} is not a dispatcher (no '
                f'use_variants). Cannot select variant {effective_id!r}.[/error]'
            )
            raise typer.Exit(1)
        return contest_yaml_path

    # Dispatcher mode.
    variants = discover_contest_variants(contest_root)
    if effective_id is None:
        return None
    if effective_id not in variants:
        console.console.print(
            f'[error]Contest variant {effective_id!r} not found. '
            f'Available: {sorted(variants.keys())}.[/error]'
        )
        raise typer.Exit(1)
    return variants[effective_id]


@functools.cache
def find_contest_package(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> Optional[Contest]:
    contest_yaml_path = find_contest_yaml(root, contest_id=contest_id)
    if not contest_yaml_path:
        return None
    contest = load_yaml_model(contest_yaml_path, Contest)

    contest_root = contest_yaml_path.parent
    validate_problem_folders_exist(contest, contest_root)
    validate_problem_folders_are_packages(contest, contest_root)
    return contest
```

Update `find_contest_package_or_die` and `find_contest` to forward `contest_id`:

```python
def find_contest_package_or_die(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> Contest:
    package = find_contest_package(root, contest_id=contest_id)
    if package is None:
        from rbx.box.contest.contest_state import resolve_explicit_selection
        # Distinguish "no contest at all" from "dispatcher with no selection".
        if find_contest_yaml.__wrapped__(root, contest_id=contest_id) is None and \
                resolve_explicit_selection() is None and contest_id is None:
            # We need a clearer message. Try to detect dispatcher case.
            ...
        console.console.print(...)  # Use the picker message here.
        raise typer.Exit(1)
    return package
```

Cleaner alternative: split the error reporting into a helper:

```python
def _die_no_contest(root: pathlib.Path) -> 'NoReturn':
    contest_yaml_path = root / YAML_NAME
    while root != pathlib.PosixPath('/') and not contest_yaml_path.is_file():
        root = root.parent
        contest_yaml_path = root / YAML_NAME
    if contest_yaml_path.is_file():
        canonical = load_yaml_model(contest_yaml_path, Contest)
        if canonical.is_dispatcher:
            variants = discover_contest_variants(contest_yaml_path.parent)
            console.console.print(
                f'[error]Multiple contests are defined in this directory. '
                f'Pass -C <id> or set RBX_CONTEST=<id>. '
                f'Available contests: {sorted(variants.keys())}.[/error]'
            )
            raise typer.Exit(1)
    console.console.print(f'Contest not found in {root.absolute()}', style='error')
    raise typer.Exit(1)


def find_contest_package_or_die(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> Contest:
    package = find_contest_package(root, contest_id=contest_id)
    if package is None:
        _die_no_contest(utils.abspath(root))
    return package


def find_contest(
    root: pathlib.Path = pathlib.Path(),
    contest_id: Optional[str] = None,
) -> pathlib.Path:
    found = find_contest_yaml(root, contest_id=contest_id)
    if found is None:
        _die_no_contest(utils.abspath(root))
    return found.parent
```

Update `within_contest`, `save_contest`, and `get_ruyaml` to forward `contest_id` (or accept it). For `within_contest`, no change to signature is needed because the contextvar is already set by the caller; just call `find_contest()` which honors the contextvar.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/rbx/box/contest/ -v -n auto`
Expected: All pass (existing tests must still pass under new signatures with default `contest_id=None`).

**Step 5: Commit**

```bash
git add rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py
git commit -m "feat(contest): make find_contest_yaml variant-aware"
```

---

## Task 5: Naming auto-pick when problem is in exactly one variant

**Files:**
- Modify: `rbx/box/naming.py`
- Test: `tests/rbx/box/test_naming.py` (create if absent).

**Step 1: Write the failing tests**

Tests should cover:

1. `get_problem_entry_in_contest()` when the canonical `contest.rbx.yml` is a real contest containing the current problem → returns the entry. (Existing behavior.)
2. Dispatcher mode with two variants, problem in exactly one variant, no `-C` selection → returns the entry from the containing variant.
3. Dispatcher mode, problem in two variants, no selection → returns `None`.
4. Dispatcher mode, problem in two variants, `-C div1` set → returns the div1 entry.
5. New helper `naming.require_problem_in_contest()` — errors via `typer.Exit` if the entry can't be uniquely determined.

Use `cleandir` and `pkg_from_testdata` patterns from `tests/rbx/box/conftest.py`. Mock `package.find_problem` and `find_contest_yaml`/`find_contest_package` if needed; prefer real fixtures.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_naming.py -v`
Expected: FAIL.

**Step 3: Implementation**

In `rbx/box/naming.py`, change `get_problem_entry_in_contest`:

```python
def get_problem_entry_in_contest() -> Optional[Tuple[int, ContestProblem]]:
    from rbx.box.contest import contest_state
    from rbx.box.contest.contest_package import (
        discover_contest_variants,
        find_contest,
        find_contest_yaml,
    )

    # Fast path: explicit selection or single-contest mode.
    contest = contest_package.find_contest_package()
    if contest is not None:
        return _entry_in_contest(contest)

    # Dispatcher mode with no selection: walk all variants.
    if contest_state.resolve_explicit_selection() is not None:
        return None  # User selected an id but contest still didn't load -> upstream error.

    # Find the dispatcher root (without selection it's None, so re-walk).
    try:
        contest_root = find_contest()
    except typer.Exit:
        return None
    variants = discover_contest_variants(contest_root)
    matches = []
    for vid, _ in variants.items():
        if vid is None:
            continue
        candidate = contest_package.find_contest_package(contest_id=vid)
        if candidate is None:
            continue
        entry = _entry_in_contest(candidate)
        if entry is not None:
            matches.append((vid, entry))

    if len(matches) == 1:
        return matches[0][1]
    return None


def _entry_in_contest(contest) -> Optional[Tuple[int, ContestProblem]]:
    problem_path = package.find_problem()
    contest_path = contest_package.find_contest()
    for i, problem in enumerate(contest.problems):
        if problem.path is None:
            continue
        if (problem_path / 'problem.rbx.yml').samefile(
            contest_path / problem.path / 'problem.rbx.yml'
        ):
            return i, problem
    return None
```

Add the new `require_problem_in_contest` helper:

```python
def require_problem_in_contest() -> Tuple[int, ContestProblem]:
    """Like get_problem_entry_in_contest but errors if not uniquely resolvable."""
    entry = get_problem_entry_in_contest()
    if entry is not None:
        return entry
    from rbx.box.contest import contest_state
    from rbx.box.contest.contest_package import discover_contest_variants, find_contest
    try:
        contest_root = find_contest()
    except typer.Exit:
        console.print('[error]No contest found for the current problem.[/error]')
        raise typer.Exit(1) from None
    variants = discover_contest_variants(contest_root)
    if len(variants) > 1 and contest_state.resolve_explicit_selection() is None:
        console.print(
            f'[error]This problem is part of multiple contests. '
            f'Pass -C <id> or set RBX_CONTEST=<id>. '
            f'Available contests: {sorted(k for k in variants if k is not None)}.[/error]'
        )
        raise typer.Exit(1)
    console.print('[error]Problem is not registered in the active contest.[/error]')
    raise typer.Exit(1)
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/rbx/box/test_naming.py tests/rbx/box/contest/ -v -n auto`
Expected: All pass.

**Step 5: Commit**

```bash
git add rbx/box/naming.py tests/rbx/box/test_naming.py
git commit -m "feat(contest): auto-pick variant when problem is in exactly one"
```

---

## Task 6: Statement-extends ambiguity error

**Files:**
- Modify: `rbx/box/contest/statement_overriding.py:65-89`
- Test: `tests/rbx/box/contest/test_statement_overriding.py`

**Step 1: Write the failing test**

Add a test where:
- Dispatcher mode, two variants, both define a matching `ContestStatement`.
- Problem statement uses `extends: contest`.
- No `-C` selection.
- `get_inheritance_overrides()` raises `StatementInheritanceError` with a message mentioning `-C` and listing variants.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/contest/test_statement_overriding.py -v`
Expected: FAIL.

**Step 3: Implementation**

In `get_inheritance_overrides`, before the existing single-contest path:

```python
def get_inheritance_overrides(statement: Statement) -> StatementOverrideData:
    from rbx.box.contest import contest_state
    from rbx.box.contest.contest_package import discover_contest_variants, find_contest

    contest = contest_package.find_contest_package()
    if contest is None:
        # Dispatcher mode without selection: surface a precise error.
        try:
            contest_root = find_contest()
        except typer.Exit:
            contest_root = None
        if contest_root is not None:
            variants = discover_contest_variants(contest_root)
            if len(variants) > 1 and contest_state.resolve_explicit_selection() is None:
                with StatementInheritanceError() as e:
                    e.print(
                        f'[error]Statement [item]{statement.name}[/item] extends '
                        f'a contest statement, but multiple contests are defined. '
                        f'Pass -C <id> or set RBX_CONTEST=<id>. '
                        f'Available: {sorted(k for k in variants if k is not None)}.[/error]'
                    )
                raise e
        with StatementInheritanceError() as e:
            e.print(
                f'[error][item]{statement.name}[/item] inherits its configuration '
                f'from the contest, but no contest was found.[/error]'
            )
        raise e

    # ... existing matching code ...
```

**Step 4: Run test to verify pass**

Run: `uv run pytest tests/rbx/box/contest/test_statement_overriding.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/contest/statement_overriding.py tests/rbx/box/contest/test_statement_overriding.py
git commit -m "feat(contest): raise picker error for statement extends in dispatcher mode"
```

---

## Task 7: Wire `-C/--contest` flag in CLI callbacks

**Files:**
- Modify: `rbx/box/cli.py:125-200` (root callback).
- Modify: `rbx/box/contest/main.py:26-40` (contest sub-app, add a callback).
- Test: `tests/rbx/box/cli/` (CLI tests, slow). Plus a unit-level test.

**Step 1: Write the failing test**

Unit-level test in `tests/rbx/box/contest/test_contest_state.py`:

```python
def test_root_callback_sets_contextvar_from_flag(monkeypatch):
    """Smoke: invoking the root callback with --contest sets the contextvar."""
    from typer.testing import CliRunner
    from rbx.box import cli
    from rbx.box.contest.contest_state import selected_variant_id_var

    captured = {}

    @cli.app.command('probe-contest')
    def probe():
        captured['value'] = selected_variant_id_var.get()

    runner = CliRunner()
    result = runner.invoke(cli.app, ['-C', 'div1', 'probe-contest'])
    assert result.exit_code == 0, result.output
    assert captured['value'] == 'div1'
```

**Step 2: Run tests to verify it fails**

Run: `uv run pytest tests/rbx/box/contest/test_contest_state.py::test_root_callback_sets_contextvar_from_flag -v`
Expected: FAIL.

**Step 3: Implementation**

In `rbx/box/cli.py:main`, add new option after `version` (before the body):

```python
contest_id: Annotated[
    Optional[str],
    typer.Option(
        '-C',
        '--contest',
        help='Select a contest variant by id (when contest.rbx.yml has '
        'use_variants: true). Defaults to the RBX_CONTEST env var.',
        envvar='RBX_CONTEST',
    ),
] = None,
```

At the start of the body:

```python
from rbx.box.contest import contest_state as _contest_state
if contest_id is not None and not _contest_state.is_valid_variant_id(contest_id):
    console.console.print(f'[error]Invalid contest id: {contest_id!r}[/error]')
    raise typer.Exit(1)
if contest_id is not None:
    _contest_state.selected_variant_id_var.set(contest_id)
```

In `rbx/box/contest/main.py`, add a callback right after `app = typer.Typer(...)`:

```python
@app.callback()
def contest_main(
    contest_id: Annotated[
        Optional[str],
        typer.Option(
            '-C', '--contest',
            help='Select a contest variant by id.',
            envvar='RBX_CONTEST',
        ),
    ] = None,
):
    if contest_id is not None:
        if not contest_state.is_valid_variant_id(contest_id):
            console.console.print(f'[error]Invalid contest id: {contest_id!r}[/error]')
            raise typer.Exit(1)
        contest_state.selected_variant_id_var.set(contest_id)
```

(Imports: `from rbx.box.contest import contest_state`, `Optional`, `Annotated`.)

Note: typer envvar handling means `RBX_CONTEST=foo rbx ...` works without the flag.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/rbx/box/contest/test_contest_state.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/cli.py rbx/box/contest/main.py tests/rbx/box/contest/test_contest_state.py
git commit -m "feat(contest): add -C/--contest flag to root and contest CLI"
```

---

## Task 8: Switch packaging consumers to `require_problem_in_contest`

**Files:**
- Modify: `rbx/box/packaging/packager.py:81` (and the `find_contest_package_or_die` calls at 146, 157).
- Modify: `rbx/box/packaging/pkg/packager.py:29, 103`.
- Modify: `rbx/box/packaging/boca/packager.py:85`.
- Modify: `rbx/box/tooling/boca/submitter.py:45-48`.
- Modify: `rbx/box/tooling/boca/scraper.py:385, 392, 400`.
- Test: existing tests under `tests/rbx/box/packaging/`, `tests/rbx/box/tooling/`.

**Step 1: Write the failing tests**

Add tests for each consumer that exercise dispatcher mode without `-C`:

1. `rbx package build` for a problem in 2 variants → exits with picker message.
2. `rbx package build` with `-C div1` → succeeds, output uses div1's letter.

Likely best handled at the unit level by mocking `naming.get_problem_shortname` is **not** allowed (we want to test the new `require_problem_in_contest`). Instead, set up a fixture with two variants and call the packager directly.

**Step 2: Run tests to verify they fail**

Run targeted tests; expect new behavior to error.

**Step 3: Implementation**

In each call site that previously did:

```python
shortname = naming.get_problem_shortname()
```

and assumed it could be `None`, switch to `_, problem_entry = naming.require_problem_in_contest(); shortname = problem_entry.short_name` **only** when the call site cannot tolerate a `None` (packaging always uses the letter for naming). Sites that already handle `None` (e.g., `get_problem_name_with_contest_info`) stay as-is.

Concretely:

- `rbx/box/packaging/packager.py:81` — uses `shortname` to compute output filename. Switch to `require_problem_in_contest`.
- `pkg/packager.py:29` — same.
- `boca/packager.py:85` — same.
- `tooling/boca/submitter.py:45` — uses `get_problem_shortname() or ''` to look up in a dict; if `None`, the next line errors with a message that doesn't mention contest variants. Replace with `require_problem_in_contest()` so the error is clearer.
- `tooling/boca/scraper.py` — three lookups. Replace with `require_problem_in_contest()` and use the entry's `short_name`/index.

For `find_contest_package_or_die()` calls at `packager.py:146, 157` and `pkg/packager.py:103`: the new error path inside `find_contest_package_or_die` already produces the right message, so these need no further change.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/rbx/box/packaging/ tests/rbx/box/tooling/ -v -n auto`
Expected: PASS, including new dispatcher-mode tests.

**Step 5: Commit**

```bash
git add rbx/box/packaging/ rbx/box/tooling/ tests/rbx/box/packaging/ tests/rbx/box/tooling/
git commit -m "feat(contest): require explicit variant for packaging and BOCA tooling"
```

---

## Task 9: `rbx contest list` command

**Files:**
- Modify: `rbx/box/contest/main.py`
- Test: `tests/rbx/box/contest/test_contest_main.py` (create if absent) or e2e.

**Step 1: Write the failing test**

Use Typer's `CliRunner` to exercise:

1. Single-contest dir → `rbx contest list` prints the canonical contest name.
2. Dispatcher dir with two variants → prints both ids, marks active selection if `-C div1` is set.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/contest/test_contest_main.py -v`
Expected: FAIL (command doesn't exist).

**Step 3: Implementation**

Add to `rbx/box/contest/main.py`:

```python
@app.command('list, ls', help='List all contests in the current directory.')
def list_contests():
    contest_root = find_contest()
    variants = contest_package.discover_contest_variants(contest_root)
    active = contest_state.resolve_explicit_selection()
    if not variants:
        console.console.print('[warning]No contests found.[/warning]')
        return
    if list(variants.keys()) == [None]:
        console.console.print('[item]contest.rbx.yml[/item] (single contest)')
        return
    for vid in sorted(k for k in variants if k is not None):
        marker = ' [active]' if vid == active else ''
        console.console.print(f'[item]{vid}[/item]{marker}')
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/rbx/box/contest/test_contest_main.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/contest/main.py tests/rbx/box/contest/test_contest_main.py
git commit -m "feat(contest): add rbx contest list command"
```

---

## Task 10: E2E fixture for multi-contest

**Files:**
- Create: `tests/e2e/testdata/multi-contest/contest.rbx.yml` (`use_variants: true`).
- Create: `tests/e2e/testdata/multi-contest/contest.div1.rbx.yml`.
- Create: `tests/e2e/testdata/multi-contest/contest.div2.rbx.yml`.
- Create: `tests/e2e/testdata/multi-contest/A/problem.rbx.yml` (shared, in both variants).
- Create: `tests/e2e/testdata/multi-contest/B/problem.rbx.yml` (only in div1).
- Create: `tests/e2e/testdata/multi-contest/e2e.rbx.yml`.

**Step 1: Author the e2e scenarios**

`e2e.rbx.yml` should cover:

1. `rbx -C div1 contest each rbx run` succeeds.
2. `rbx contest list` lists `div1` and `div2`.
3. `rbx contest each rbx run` (no `-C`) errors with picker message.
4. Inside `A/`: `rbx package build` (no `-C`) errors (A is in both contests).
5. Inside `A/`: `rbx -C div1 package build` succeeds.
6. Inside `B/`: `rbx package build` (no `-C`) succeeds — auto-pick because B is only in div1.

Refer to `tests/e2e/README.md` for the schema.

**Step 2: Run the e2e suite**

Run: `mise run test-e2e` (or `uv run pytest tests/e2e/testdata/multi-contest/ -v`).
Expected: all scenarios pass.

**Step 3: Commit**

```bash
git add tests/e2e/testdata/multi-contest/
git commit -m "test(contest): add e2e fixture for multi-contest dispatcher mode"
```

---

## Task 11: Update CLAUDE.md docs

**Files:**
- Modify: `rbx/box/CLAUDE.md` (Package Discovery section).
- Modify: `CLAUDE.md` (Configuration Files section).

**Step 1: Document changes**

- Note that `contest.rbx.yml` may be a dispatcher (`use_variants: true`) and that variants live in `contest.<id>.rbx.yml`.
- Document `-C/--contest` and `RBX_CONTEST` env var.
- Note that `find_contest_yaml(root, contest_id=None)` consults the contextvar from `rbx.box.contest.contest_state`.

**Step 2: Commit**

```bash
git add CLAUDE.md rbx/box/CLAUDE.md
git commit -m "docs(contest): document multi-contest dispatcher mode"
```

---

## Task 12: Open follow-up issue

After merge, open a GitHub issue tracking `rbx contest add_variant <id>` scaffolding command (decision deferred during design — see design doc "Follow-ups").

---

## Verification

After all tasks land:

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest --ignore=tests/rbx/box/cli -n auto
mise run test-e2e
```

All must pass. The pre-existing failure in `tests/rbx/box/testcase_utils_test.py::TestClearBuiltTestcases::test_clear_built_testcases_nonexistent` is unrelated and already fails on `main`; do not block on it.
