# YAML `!include` Fragments Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let a contest variant share statement/document/vars configuration with the canonical contest by splicing fragment files in with a `!include` YAML tag, instead of duplicating ~110 lines.

**Architecture:** All user-authored configs load through one function, `yaml_validation.load_yaml_model(path, model)`, which parses with ruyaml round-trip and hands the tree to pydantic. Include resolution is a transformation on that round-trip tree, inserted between those two steps. Because the spliced subtrees are real `CommentedMap`/`CommentedSeq` nodes, they carry their own source positions; stamping each with its origin path is what keeps error diagnostics pointing at the right file. The same round-trip representation lets writers navigate into fragments and edit them in place.

**Tech Stack:** Python 3.9+, ruyaml (round-trip YAML), pydantic v2, pytest, typer.

**Design doc:** [`2026-08-31-yaml-include-fragments-design.md`](2026-08-31-yaml-include-fragments-design.md)

---

## Phase 1 — Resolver core

### Task 1: Include-tolerant round-trip constructor

ruyaml rejects `<<: !include x.yml` during construction because its `flatten_mapping` demands a mapping node. Teach it to pass merge-key includes through untouched.

**Files:**
- Create: `rbx/box/yaml_include.py`
- Test: `tests/rbx/box/yaml_include_test.py`

**Step 1: Write the failing test**

```python
import io
import ruyaml
from rbx.box.yaml_include import make_yaml


def test_merge_key_include_loads_without_error():
    doc = 'vars:\n  <<: !include shared/vars.yml\n  warmup: true\n'
    data = make_yaml().load(doc)
    assert 'warmup' in data['vars']


def test_merge_key_include_round_trips_byte_identically():
    doc = 'vars:\n  <<: !include shared/vars.yml\n  warmup: true\nname: x\n'
    y = make_yaml()
    buf = io.StringIO()
    y.dump(y.load(doc), buf)
    assert buf.getvalue() == doc


def test_plain_include_is_a_tagged_scalar():
    data = make_yaml().load('statements: !include shared/st.yml\n')
    node = data['statements']
    assert str(node.tag) == '!include'
    assert node.value == 'shared/st.yml'
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/yaml_include_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rbx.box.yaml_include'`

**Step 3: Write minimal implementation**

```python
"""Resolution of the `!include` YAML tag for user-authored configs."""

from __future__ import annotations

import ruyaml
from ruyaml.constructor import RoundTripConstructor
from ruyaml.nodes import ScalarNode

INCLUDE_TAG = '!include'
MERGE_TAG = 'tag:yaml.org,2002:merge'


def _is_include(node) -> bool:
    return isinstance(node, ScalarNode) and str(node.tag) == INCLUDE_TAG


class IncludeTolerantConstructor(RoundTripConstructor):
    """A round-trip constructor that tolerates `<<: !include ...`.

    ruyaml's `flatten_mapping` resolves merge keys at construction time and
    raises on a value node that is not already a mapping. An `!include` is a
    scalar at that point -- the fragment has not been read yet -- so the pairs
    are lifted out before delegating and reinserted afterwards. Resolution
    performs the actual merge later, in `resolve_includes`.
    """

    def flatten_mapping(self, node):
        includes = []
        kept = []
        for key, value in node.value:
            if (
                isinstance(key, ScalarNode)
                and str(key.tag) == MERGE_TAG
                and _is_include(value)
            ):
                includes.append((key, value))
            else:
                kept.append((key, value))
        node.value = kept
        merge = super().flatten_mapping(node)
        node.value = includes + node.value
        return merge


def make_yaml() -> ruyaml.YAML:
    """A round-trip YAML instance that can parse `!include`."""
    yaml = ruyaml.YAML(typ='rt')
    yaml.Constructor = IncludeTolerantConstructor
    return yaml
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/yaml_include_test.py -v`
Expected: PASS (3 passed)

**Step 5: Commit**

```bash
git add rbx/box/yaml_include.py tests/rbx/box/yaml_include_test.py
git commit -m "feat(yaml): tolerate merge-key !include in round-trip parsing"
```

---

### Task 2: Resolve whole-node includes

**Files:**
- Modify: `rbx/box/yaml_include.py`
- Test: `tests/rbx/box/yaml_include_test.py`

**Step 1: Write the failing test**

```python
def test_resolves_mapping_include(tmp_path):
    (tmp_path / 'frag.yml').write_text('a: 1\nb: 2\n')
    (tmp_path / 'main.yml').write_text('top: !include frag.yml\n')
    data, sources = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['top']) == {'a': 1, 'b': 2}
    assert sources == {tmp_path / 'main.yml', tmp_path / 'frag.yml'}


def test_resolves_sequence_include(tmp_path):
    (tmp_path / 'list.yml').write_text('- x\n- y\n')
    (tmp_path / 'main.yml').write_text('items: !include list.yml\n')
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert list(data['items']) == ['x', 'y']


def test_resolves_include_at_document_root(tmp_path):
    (tmp_path / 'frag.yml').write_text('a: 1\n')
    (tmp_path / 'main.yml').write_text('!include frag.yml\n')
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data) == {'a': 1}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/yaml_include_test.py -k resolves -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_yaml_file'`

**Step 3: Write minimal implementation**

Add to `rbx/box/yaml_include.py`. Note the recursion carries each fragment's *own* directory, so a fragment's includes resolve relative to itself.

```python
import pathlib
from typing import Any, Set, Tuple

from ruyaml.comments import CommentedMap, CommentedSeq

# Attribute stamped on a spliced fragment root, naming the file it came from.
SOURCE_ATTR = '_rbx_include_source'


def _load_tree(path: pathlib.Path):
    return make_yaml().load(path.read_text())


def _resolve_node(node: Any, base_dir: pathlib.Path, stack, sources: Set[pathlib.Path]):
    if _is_tagged_include(node):
        return _splice(node, base_dir, stack, sources)
    if isinstance(node, CommentedMap):
        for key in list(node.keys()):
            node[key] = _resolve_node(node[key], base_dir, stack, sources)
        return node
    if isinstance(node, CommentedSeq):
        for i in range(len(node)):
            node[i] = _resolve_node(node[i], base_dir, stack, sources)
        return node
    return node


def _splice(node, base_dir, stack, sources):
    target = _resolve_path(node.value, base_dir, stack)
    sources.add(target)
    sub = _load_tree(target)
    sub = _resolve_node(sub, target.parent, stack + (target,), sources)
    _stamp(sub, target)
    return sub


def _stamp(tree, path):
    if isinstance(tree, (CommentedMap, CommentedSeq)):
        try:
            setattr(tree, SOURCE_ATTR, path)
        except AttributeError:
            pass


def resolve_yaml_file(
    path: pathlib.Path,
) -> Tuple[Any, Set[pathlib.Path]]:
    """Load `path` and splice in every transitive `!include`.

    Returns the resolved round-trip tree and the set of every file read,
    so callers can invalidate caches on any of them.
    """
    path = path.resolve()
    sources = {path}
    tree = _load_tree(path)
    tree = _resolve_node(tree, path.parent, (path,), sources)
    return tree, sources
```

`_is_tagged_include` checks for a ruyaml `TaggedScalar` whose `.tag` is `!include`; `_resolve_path` is written in Task 4.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/yaml_include_test.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rbx/box/yaml_include.py tests/rbx/box/yaml_include_test.py
git commit -m "feat(yaml): resolve whole-node !include fragments"
```

---

### Task 3: Resolve merge-key includes

The `<<: !include` pair survived construction as a raw pair (Task 1). Resolution must now read the fragment and merge it *under* the sibling keys — the explicit keys win.

**Files:**
- Modify: `rbx/box/yaml_include.py`
- Test: `tests/rbx/box/yaml_include_test.py`

**Step 1: Write the failing test**

```python
def test_merge_key_include_merges_under_explicit_keys(tmp_path):
    (tmp_path / 'frag.yml').write_text('a: 1\nb: 2\n')
    (tmp_path / 'main.yml').write_text(
        'vars:\n  <<: !include frag.yml\n  b: 99\n  c: 3\n'
    )
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['vars']) == {'a': 1, 'b': 99, 'c': 3}


def test_merge_key_include_is_shallow(tmp_path):
    """Documented limitation: `<<` replaces a sibling map wholesale."""
    (tmp_path / 'frag.yml').write_text('m:\n  x: 1\n  y: 2\n')
    (tmp_path / 'main.yml').write_text('v:\n  <<: !include frag.yml\n  m:\n    x: 9\n')
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['v']['m']) == {'x': 9}


def test_merge_key_include_nested_one_level(tmp_path):
    (tmp_path / 'st.yml').write_text('pt: a\nen: b\n')
    (tmp_path / 'main.yml').write_text(
        'vars:\n  titles:\n    <<: !include st.yml\n    pt: override\n'
    )
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['vars']['titles']) == {'pt': 'override', 'en': 'b'}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/yaml_include_test.py -k merge_key_include_merges -v`
Expected: FAIL — the `<<` key is still present / values not merged.

**Step 3: Write minimal implementation**

In `_resolve_node`'s `CommentedMap` branch, before descending, pull out any merge-key include, resolve it, and set missing keys:

```python
def _apply_merge_includes(node: CommentedMap, base_dir, stack, sources) -> None:
    merge_keys = [k for k in list(node.keys()) if _is_merge_key(k)]
    for key in merge_keys:
        fragment = _splice(node[key], base_dir, stack, sources)
        del node[key]
        if not isinstance(fragment, CommentedMap):
            raise IncludeError(
                f'`<<: !include` expects the fragment to be a mapping, '
                f'but it is a {type(fragment).__name__}.'
            )
        for fkey, fvalue in fragment.items():
            if fkey not in node:
                node[fkey] = fvalue
```

`_is_merge_key` recognises the key ruyaml leaves behind for a `<<` pair (a `TaggedScalar`/merge marker, per Task 1's reinsertion).

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/yaml_include_test.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rbx/box/yaml_include.py tests/rbx/box/yaml_include_test.py
git commit -m "feat(yaml): resolve merge-key !include fragments"
```

---

### Task 4: Path resolution rules and errors

**Files:**
- Modify: `rbx/box/yaml_include.py`
- Test: `tests/rbx/box/yaml_include_test.py`

**Step 1: Write the failing test**

```python
import pytest
from rbx.box.yaml_include import IncludeError, resolve_yaml_file


def test_nested_include_resolves_relative_to_its_own_directory(tmp_path):
    sub = tmp_path / 'shared'
    sub.mkdir()
    (sub / 'inner.yml').write_text('v: 1\n')
    (sub / 'outer.yml').write_text('nested: !include inner.yml\n')
    (tmp_path / 'main.yml').write_text('top: !include shared/outer.yml\n')
    data, sources = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['top']['nested']) == {'v': 1}
    assert sub / 'inner.yml' in sources


def test_cycle_is_reported_with_the_chain(tmp_path):
    (tmp_path / 'a.yml').write_text('x: !include b.yml\n')
    (tmp_path / 'b.yml').write_text('y: !include a.yml\n')
    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(tmp_path / 'a.yml')
    assert 'cycle' in str(exc.value).lower()
    assert 'a.yml' in str(exc.value)


def test_missing_fragment_names_the_path_and_the_includer(tmp_path):
    (tmp_path / 'main.yml').write_text('x: !include nope.yml\n')
    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(tmp_path / 'main.yml')
    assert 'nope.yml' in str(exc.value)
    assert 'main.yml' in str(exc.value)


def test_absolute_path_is_rejected(tmp_path):
    (tmp_path / 'main.yml').write_text('x: !include /etc/passwd\n')
    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(tmp_path / 'main.yml')
    assert 'absolute' in str(exc.value).lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/yaml_include_test.py -k "nested or cycle or missing or absolute" -v`
Expected: FAIL — `IncludeError` not defined.

**Step 3: Write minimal implementation**

```python
from rbx.box.exception import RbxException


class IncludeError(RbxException):
    pass


def _resolve_path(raw: str, base_dir: pathlib.Path, stack) -> pathlib.Path:
    includer = stack[-1]
    candidate = pathlib.Path(raw)
    if candidate.is_absolute():
        with IncludeError() as err:
            err.print(
                f'[error]`!include {raw}` in [item]{includer}[/item] is an absolute '
                f'path. Includes must be relative to the including file.[/error]'
            )
    target = (base_dir / candidate).resolve()
    if target in stack:
        chain = ' -> '.join(str(p) for p in stack + (target,))
        with IncludeError() as err:
            err.print(f'[error]`!include` cycle detected: {chain}[/error]')
    if not target.is_file():
        with IncludeError() as err:
            err.print(
                f'[error]`!include {raw}` in [item]{includer}[/item] points at '
                f'[item]{target}[/item], which does not exist.[/error]'
            )
    return target
```

Follow the `RbxException` context-manager idiom already used in `rbx/box/statements/expander.py`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/yaml_include_test.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rbx/box/yaml_include.py tests/rbx/box/yaml_include_test.py
git commit -m "feat(yaml): validate !include paths and report cycles"
```

---

## Phase 2 — Wire into config loading

### Task 5: Resolve includes in `load_yaml_model`

**Files:**
- Modify: `rbx/box/yaml_validation.py:373-399`
- Test: `tests/rbx/box/yaml_validation_test.py`

**Step 1: Write the failing test**

```python
def test_load_yaml_model_resolves_includes(tmp_path):
    (tmp_path / 'frag.yml').write_text('- short_name: A\n')
    (tmp_path / 'contest.rbx.yml').write_text(
        'name: c\nproblems: !include frag.yml\n'
    )
    contest = load_yaml_model(tmp_path / 'contest.rbx.yml', Contest)
    assert [p.short_name for p in contest.problems] == ['A']
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/yaml_validation_test.py -k includes -v`
Expected: FAIL — pydantic rejects a `TaggedScalar` where a list is expected.

**Step 3: Write minimal implementation**

Replace the `ruyaml.YAML(typ='rt').load(source)` call with `resolve_yaml_file(path)`, keeping the `YamlSyntaxError` wrapping and letting `IncludeError` propagate:

```python
    try:
        data, sources = resolve_yaml_file(path)
    except ruyaml.YAMLError as exc:
        raise YamlSyntaxError(path, source, exc) from exc
```

Store `sources` on the returned model via a module-level side table keyed by path (Task 8 consumes it), or return it from a new `load_yaml_model_with_sources`; prefer the explicit second function and leave `load_yaml_model` delegating to it.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/yaml_validation_test.py -v`
Expected: PASS

**Step 5: Run the existing suites that load configs**

Run: `uv run pytest tests/rbx/box/yaml_validation_test.py tests/rbx/box/contest -v`
Expected: PASS — no regressions for files without includes.

**Step 6: Commit**

```bash
git add rbx/box/yaml_validation.py tests/rbx/box/yaml_validation_test.py
git commit -m "feat(yaml): resolve !include when loading user configs"
```

---

### Task 6: Point diagnostics at the fragment that owns the error

**Files:**
- Modify: `rbx/box/yaml_validation.py:129` (`_locate`), `:306` (`_render_diagnostic`), `:74` (`YamlValidationError`)
- Test: `tests/rbx/box/yaml_validation_test.py`

**Step 1: Write the failing test**

```python
def test_validation_error_inside_a_fragment_names_the_fragment(tmp_path):
    (tmp_path / 'frag.yml').write_text('- short_name: not-a-valid-short-name\n')
    (tmp_path / 'contest.rbx.yml').write_text(
        'name: c\nproblems: !include frag.yml\n'
    )
    with pytest.raises(YamlValidationError) as exc:
        load_yaml_model(tmp_path / 'contest.rbx.yml', Contest)
    rendered = str(exc.value)
    assert 'frag.yml' in rendered
    assert 'contest.rbx.yml' not in rendered.split('\n')[0]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/yaml_validation_test.py -k fragment_names -v`
Expected: FAIL — the diagnostic names `contest.rbx.yml` and shows a line from the wrong file.

**Step 3: Write minimal implementation**

Have `_locate` return a fourth element: the path stamped on the nearest enclosing spliced fragment root (`SOURCE_ATTR`), or `None` for the parent file. `YamlValidationError` then reads that file's text for the snippet and prints its name. Keep the signature change internal — `_locate` is private.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/yaml_validation_test.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rbx/box/yaml_validation.py tests/rbx/box/yaml_validation_test.py
git commit -m "fix(yaml): point validation errors at the including fragment"
```

---

### Task 7: Reject `!include` in `model_from_yaml`

`rbx/utils.py:419` serves non-user-authored files and has no base directory. It must fail loudly rather than mysteriously.

**Files:**
- Modify: `rbx/utils.py:419`
- Test: `tests/rbx/utils_test.py`

**Step 1: Write the failing test**

```python
def test_model_from_yaml_rejects_include():
    with pytest.raises(Exception) as exc:
        utils.model_from_yaml(SomeModel, 'x: !include frag.yml\n')
    assert 'load_yaml_model' in str(exc.value)
```

**Step 2–5:** implement, verify, commit as `fix(yaml): reject !include in the path-less loader`.

---

### Task 8: Invalidate the build cache on fragment edits

**Files:**
- Modify: whichever fingerprint feeds `rbx/box/package.py:150` `get_cache_fingerprint`
- Test: `tests/rbx/box/package_test.py`

Hash the transitive `sources` set from Task 5 rather than the single config file, so touching `shared/statements.yml` rebuilds. **Investigate first** — confirm what currently contributes `contest.rbx.yml` to the fingerprint before changing it.

---

## Phase 3 — Writers

### Task 9: Navigate into fragments when saving

**Files:**
- Modify: `rbx/box/contest/contest_package.py:310` (`save_contest`), `:330` (`get_ruyaml`)
- Test: `tests/rbx/box/contest/contest_package_test.py`

`save_contest` currently does `write_text(model_to_yaml(package))`, which re-serialises from the model and would inline every fragment. Replace with a round-trip edit that walks to the target key, and when its value is an `!include` `TaggedScalar`, opens that fragment and recurses.

**Test first:** `rbx contest add` against a contest whose `problems` is an include must append to the *fragment*, leave the parent file byte-identical, and preserve the fragment's comments.

### Task 10: Warn when a fragment is shared

Build the reverse map by globbing `contest*.rbx.yml` in the contest root and expanding each closure; if more than one contest reaches the fragment, print the blast radius and confirm unless `--yes`.

---

## Phase 4 — Ergonomics

### Task 11: `rbx contest add_variant` scaffolds the thin form

Emit `name`, `problems`, and includes pointing at the canonical's fragments instead of a full copy. Update `tests/rbx/box/lazy_cli_test.py` if help text changes.

### Task 12: `rbx contest extract <field> <path>`

Lift a node out of a contest file into a fragment, replacing it with an `!include`, preserving comments. Needs a row in `ENTRIES` in `rbx/box/cli/__init__.py` carrying the same `help=`/`rich_help_panel=`/`hidden=` as the module (see the lazy-CLI contract in `CLAUDE.md`).

### Task 13: Docs and E2E

- Document the tag, path rules, and the shallow-`<<` limitation, following [`docs/plans/docs-writing-style-guide.md`](docs-writing-style-guide.md). Introduce fragments before using them.
- Hand-insert any new CLI flag rows into the checked-in CLI reference rather than regenerating (it has drifted).
- E2E fixture under `tests/e2e/` mirroring `subreg-2026`: canonical plus one variant sharing `statements`, `documents` and `vars` fragments; assert both build and that the variant's `vars` override applies.

---

## Notes for the implementer

- **Run only the test files you touch.** A full run is slow and produces spurious sandbox wall-clock timeouts.
- Single quotes; absolute imports only; `uv run ruff check --fix .` and `uv run ruff format .` before each commit.
- Commits must be Conventional Commits — use the `/commit` skill.
- Phases 1–2 are the feature's spine and are independently shippable: with them, a variant can share config, it validates correctly, and errors point at the right file. Phase 3 prevents `rbx contest add` from silently undoing the sharing, so **do not ship Phase 1–2 to users without at least a guard** that refuses to write a file containing includes.
