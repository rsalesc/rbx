# YAML validation error rendering — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace raw Pydantic validation tracebacks for user-authored YAML configs with rust-style caret diagnostics that show file, line, snippet, caret, and a clean message.

**Architecture:** One new module `rbx/box/yaml_validation.py` exposes `load_yaml_model(path, model)` plus two `RbxException` subclasses (`YamlSyntaxError`, `YamlValidationError`). It loads with `ruyaml` (round-trip mode preserves line/column on every node), validates with Pydantic, and on failure walks the error `loc` against the ruyaml tree to render a Rich diagnostic. Six existing call sites collapse to one-line calls.

**Tech Stack:** Pydantic v2, ruyaml (already a dep), Rich (already a dep), pytest.

**Design doc:** `docs/plans/2026-05-01-yaml-validation-error-rendering-design.md`

---

## Pre-flight

This plan assumes you are working in an isolated worktree created by `superpowers:using-git-worktrees`. The worktree at `.worktrees/yaml-validation/` (or wherever) is already on a feature branch. If not, stop and create one before starting.

Read `docs/plans/2026-05-01-yaml-validation-error-rendering-design.md` end-to-end first. Every section here references decisions made there.

Test runner cheat-sheet:

```bash
# Single file
uv run pytest tests/rbx/box/test_yaml_validation.py -v

# Single test
uv run pytest tests/rbx/box/test_yaml_validation.py::test_locate_top_level_scalar -v

# Lint + format (run before each commit)
uv run ruff check --fix rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
uv run ruff format rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
```

Commit after every task. Follow the project's `commit` skill (conventional commits, no `git add -A`, named files only).

---

## Task 1: Bootstrap the module skeleton

**Files:**
- Create: `rbx/box/yaml_validation.py`
- Create: `tests/rbx/box/test_yaml_validation.py`

**Step 1: Create the module with imports and stubs**

```python
# rbx/box/yaml_validation.py
"""Pretty-rendered YAML loading and validation for user-authored configs.

Loads a YAML file with ruyaml (round-trip mode, so every node carries its
source line/column) and validates it against a Pydantic model. On either a
YAML syntax error or a Pydantic validation error, raises a typed
RbxException whose ``str(exc)`` is a rust-style caret diagnostic showing
file, line, snippet, caret, and message.

The single public entry point is :func:`load_yaml_model`.
"""

from __future__ import annotations

import pathlib
from typing import Any, List, Tuple, Type, TypeVar

import pydantic
import ruyaml
from ruyaml.comments import CommentedMap, CommentedSeq

from rbx.box.exception import RbxException

T = TypeVar('T', bound=pydantic.BaseModel)

PYDANTIC_INTERNAL_LOC_SEGMENTS = frozenset({'union_tag', 'tagged-union'})


class YamlSyntaxError(RbxException):
    """Raised when a YAML file cannot be parsed."""


class YamlValidationError(RbxException):
    """Raised when a YAML file parses but fails Pydantic schema validation."""


def load_yaml_model(path: pathlib.Path, model: Type[T]) -> T:
    """Load a YAML file and validate it against a Pydantic model.

    Args:
        path: Path to a YAML file. Must exist; ``FileNotFoundError`` from
            ``read_text`` propagates unchanged.
        model: A ``pydantic.BaseModel`` subclass to validate the loaded
            data against.

    Returns:
        An instance of ``model`` populated from the YAML file.

    Raises:
        YamlSyntaxError: The file is not valid YAML.
        YamlValidationError: The file parses but does not match ``model``.
        FileNotFoundError: The file does not exist.
    """
    raise NotImplementedError
```

**Step 2: Create the test file with imports**

```python
# tests/rbx/box/test_yaml_validation.py
"""Unit tests for rbx.box.yaml_validation."""

from __future__ import annotations

import pathlib
from typing import List, Optional

import pydantic
import pytest
import ruyaml

from rbx.box.yaml_validation import (
    YamlSyntaxError,
    YamlValidationError,
    load_yaml_model,
)


def _parse(text: str) -> ruyaml.comments.CommentedBase:
    """Parse YAML text with ruyaml in round-trip mode for tests."""
    return ruyaml.YAML(typ='rt').load(text)
```

**Step 3: Verify both files import cleanly**

Run: `uv run python -c "from rbx.box.yaml_validation import load_yaml_model, YamlSyntaxError, YamlValidationError"`
Expected: no output, no error.

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py -v`
Expected: "no tests ran" but no collection error.

**Step 4: Lint + commit**

```bash
uv run ruff check --fix rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
uv run ruff format rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git add rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git commit -m "feat(yaml): bootstrap yaml_validation module skeleton

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Implement `_locate` — top-level scalar field

**Files:**
- Modify: `rbx/box/yaml_validation.py`
- Modify: `tests/rbx/box/test_yaml_validation.py`

**Step 1: Write the failing test**

Append to `tests/rbx/box/test_yaml_validation.py`:

```python
def test_locate_top_level_scalar():
    from rbx.box.yaml_validation import _locate

    text = 'name: my-problem\ntimeLimit: 1000\n'
    root = _parse(text)

    line, col, span = _locate(('timeLimit',), root)

    assert line == 2  # 1-based line of `timeLimit:`
    assert col == 1   # 1-based column of `t` in `timeLimit`
    assert span == len('timeLimit')
```

> Note on indexing: ruyaml's `.lc.line` is 0-based; `_locate` MUST normalize
> to 1-based since the renderer prints `file:line:col` for users. Bake the
> +1 conversion inside `_locate`.

**Step 2: Run, verify it fails**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py::test_locate_top_level_scalar -v`
Expected: FAIL with `ImportError: cannot import name '_locate'`.

**Step 3: Implement minimal `_locate`**

Add to `rbx/box/yaml_validation.py` (above `load_yaml_model`):

```python
def _locate(
    loc: Tuple[Any, ...],
    root: Any,
) -> Tuple[int, int, int]:
    """Walk a Pydantic ``loc`` tuple against a ruyaml-parsed tree.

    ruyaml's ``CommentedMap`` and ``CommentedSeq`` carry source positions
    via ``.lc``: ``lc.key(name)``, ``lc.value(name)``, and ``lc.item(i)``
    each return ``(line, col)`` 0-based. This function normalises to
    1-based line/column for display and computes a caret span.

    Algorithm (see design doc, "Locating the source line"):

    - Walk each segment. If the current node is a CommentedMap and the
      segment is a string key that exists, record its key position and
      descend.
    - If the current node is a CommentedSeq and the segment is an int
      index in range, record its item position and descend.
    - If the segment is a Pydantic-internal marker (``union_tag``,
      ``tagged-union``), skip it and continue.
    - Otherwise, stop walking and return the last known position
      (the deepest resolvable ancestor).

    The caret span widens to the length of the final node's scalar
    representation when applicable; otherwise it stays at the length of
    the last walked key.

    Args:
        loc: Pydantic error ``loc`` tuple; segments are ``str`` (map
            keys), ``int`` (sequence indices), or internal markers.
        root: ruyaml-parsed root node (CommentedMap or CommentedSeq).

    Returns:
        ``(line, col, span)``, all 1-based for line/col.
    """
    # ruyaml uses 0-based line/col; we convert to 1-based on return.
    if hasattr(root, 'lc'):
        last_line, last_col = root.lc.line, root.lc.col
    else:
        last_line, last_col = 0, 0
    last_span = 1

    node: Any = root
    for seg in loc:
        if isinstance(node, CommentedMap) and isinstance(seg, str) and seg in node:
            line, col = node.lc.key(seg)
            last_line, last_col = line, col
            last_span = len(seg)
            node = node[seg]
            continue
        if isinstance(node, CommentedSeq) and isinstance(seg, int) and 0 <= seg < len(node):
            line, col = node.lc.item(seg)
            last_line, last_col = line, col
            last_span = 1
            node = node[seg]
            continue
        if seg in PYDANTIC_INTERNAL_LOC_SEGMENTS:
            continue
        break

    return last_line + 1, last_col + 1, last_span
```

**Step 4: Run the test**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py::test_locate_top_level_scalar -v`
Expected: PASS.

**Step 5: Lint + commit**

```bash
uv run ruff check --fix rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
uv run ruff format rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git add rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git commit -m "feat(yaml): locate top-level scalar fields in source

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: `_locate` — nested map field

**Step 1: Write failing test**

```python
def test_locate_nested_map():
    from rbx.box.yaml_validation import _locate

    text = 'a:\n  b:\n    c: hello\n'
    root = _parse(text)

    line, col, span = _locate(('a', 'b', 'c'), root)

    assert line == 3
    assert col == 5
    assert span == len('c')
```

**Step 2: Run** — should already PASS (Task 2 covered the recursion case). If FAIL, debug `_locate` before continuing.

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py::test_locate_nested_map -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/rbx/box/test_yaml_validation.py
git commit -m "test(yaml): cover nested map locate

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: `_locate` — list index and list-of-maps

**Step 1: Write failing tests**

```python
def test_locate_list_index():
    from rbx.box.yaml_validation import _locate

    text = 'items:\n  - a\n  - b\n  - c\n'
    root = _parse(text)

    line, col, span = _locate(('items', 2), root)

    assert line == 4   # third item is on line 4
    assert col == 5    # column of the scalar after "- "
    # span = 1 by default for list items (no scalar widen yet)


def test_locate_list_of_maps():
    from rbx.box.yaml_validation import _locate

    text = 'items:\n  - name: alice\n  - name: bob\n  - name: carol\n'
    root = _parse(text)

    line, col, span = _locate(('items', 2, 'name'), root)

    assert line == 4
    assert col == 5
    assert span == len('name')
```

**Step 2: Run**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py -v -k locate_list`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/rbx/box/test_yaml_validation.py
git commit -m "test(yaml): cover list-index and list-of-maps locate

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: `_locate` — fallback cases

**Step 1: Write failing tests**

```python
def test_locate_missing_key_falls_back_to_parent():
    from rbx.box.yaml_validation import _locate

    text = 'items:\n  - name: alice\n  - name: bob\n'
    root = _parse(text)

    # 'absent' is missing from items[1]; walk should stop at items[1]
    line, col, span = _locate(('items', 1, 'absent'), root)

    assert line == 3   # items[1] starts on line 3
    assert col == 5    # column of 'name' key inside items[1]
    # span should still be the last walked key length (== len('name'))
    assert span == len('name')


def test_locate_out_of_range_index_falls_back():
    from rbx.box.yaml_validation import _locate

    text = 'items:\n  - a\n  - b\n'
    root = _parse(text)

    line, col, span = _locate(('items', 99), root)

    # falls back to the 'items' key location
    assert line == 1
    assert col == 1
    assert span == len('items')


def test_locate_skips_pydantic_internal_segments():
    from rbx.box.yaml_validation import _locate

    text = 'step:\n  type: foo\n  arg: bar\n'
    root = _parse(text)

    # 'union_tag' is not a real key; walker should skip and resolve 'type'
    line, col, span = _locate(('step', 'union_tag', 'type'), root)

    assert line == 2
    assert col == 3
    assert span == len('type')


def test_locate_empty_loc():
    from rbx.box.yaml_validation import _locate

    text = 'name: x\n'
    root = _parse(text)

    line, col, span = _locate((), root)

    assert (line, col, span) == (1, 1, 1)
```

> Note: the fallback test for `missing_key` uses `items[1]` (line 3) rather
> than `items[2]` to guarantee the index is in-range and the only failing
> segment is `'absent'`. This isolates the missing-key branch from the
> out-of-range branch.

**Step 2: Run**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py -v -k locate`
Expected: all PASS.

**Step 3: Commit**

```bash
git add tests/rbx/box/test_yaml_validation.py
git commit -m "test(yaml): cover locate fallback and skip cases

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: `_locate` — widen span for scalar values

**Step 1: Write failing test**

```python
def test_locate_widens_span_to_scalar_value():
    from rbx.box.yaml_validation import _locate

    # The error is "value of timeLimit is wrong"; we want the caret under
    # the value '1234567', not just under the key.
    text = 'timeLimit: 1234567\n'
    root = _parse(text)

    # When the loc walks all the way TO the scalar value we want the
    # span to match the value's printed length.  We model this by
    # treating the loc as ending on the scalar; _locate walks 'timeLimit'
    # and then since the last node is a scalar, widens span.
    line, col, span = _locate(('timeLimit',), root)

    # By design, locate currently returns the KEY position with span=len(key).
    # Widening to the value happens only when the value is the offender.
    # We expose this via an extra param.
    assert line == 1
    assert col == 1
    assert span == len('timeLimit')
```

> Wait — re-read the design doc. The widen-to-scalar behaviour is described
> as: when the deepest resolved node is itself a scalar (after walking),
> widen the span to its value length. But Pydantic's loc for a scalar field
> is `('timeLimit',)`, and we resolve INTO `node = root['timeLimit'] = 1234567`.
> So after the walk, `node` is a scalar — widen the span there.

Replace the test with the correct assertion:

```python
def test_locate_widens_span_to_scalar_value():
    from rbx.box.yaml_validation import _locate

    text = 'timeLimit: 1234567\n'
    root = _parse(text)

    line, col, span = _locate(('timeLimit',), root)

    # After widening: caret column moves to where the value starts,
    # span equals value length.
    assert line == 1
    # column of '1' in '1234567' (after 'timeLimit: ')
    assert col == len('timeLimit: ') + 1
    assert span == len('1234567')
```

**Step 2: Run, verify FAIL**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py::test_locate_widens_span_to_scalar_value -v`
Expected: FAIL — current `_locate` returns the KEY position, not the value position.

**Step 3: Update `_locate` to widen for scalar values**

Replace `_locate` with the version that, after the walk, checks whether the final `node` is a scalar (not a Commented* container) AND we made at least one successful descent. If so, query the parent map's `.lc.value(last_seg)` for the value position and use the scalar's repr length as span.

```python
def _locate(
    loc: Tuple[Any, ...],
    root: Any,
) -> Tuple[int, int, int]:
    """[unchanged docstring above]"""
    if hasattr(root, 'lc'):
        last_line, last_col = root.lc.line, root.lc.col
    else:
        last_line, last_col = 0, 0
    last_span = 1

    node: Any = root
    parent: Any = None
    last_seg: Any = None
    walked_any = False

    for seg in loc:
        if isinstance(node, CommentedMap) and isinstance(seg, str) and seg in node:
            line, col = node.lc.key(seg)
            last_line, last_col = line, col
            last_span = len(seg)
            parent, last_seg = node, seg
            node = node[seg]
            walked_any = True
            continue
        if isinstance(node, CommentedSeq) and isinstance(seg, int) and 0 <= seg < len(node):
            line, col = node.lc.item(seg)
            last_line, last_col = line, col
            last_span = 1
            parent, last_seg = node, seg
            node = node[seg]
            walked_any = True
            continue
        if seg in PYDANTIC_INTERNAL_LOC_SEGMENTS:
            continue
        break

    # If we descended fully into a scalar, widen the caret to the value.
    if (
        walked_any
        and not isinstance(node, (CommentedMap, CommentedSeq))
        and node is not None
        and isinstance(parent, CommentedMap)
        and isinstance(last_seg, str)
    ):
        try:
            v_line, v_col = parent.lc.value(last_seg)
            last_line, last_col = v_line, v_col
            last_span = max(1, len(str(node)))
        except (KeyError, AttributeError):
            pass

    return last_line + 1, last_col + 1, last_span
```

**Step 4: Run the new test AND the prior `top_level_scalar` test**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py -v -k locate`
Expected: the new test PASS. The `top_level_scalar` test now FAILS because we changed behaviour.

**Step 5: Update the prior test to match the new (correct) behaviour**

In `test_locate_top_level_scalar`, the intent of the original test was "find the field". With scalar widening, when the value is what's wrong, the caret should land on the value. Update:

```python
def test_locate_top_level_scalar():
    from rbx.box.yaml_validation import _locate

    text = 'name: my-problem\ntimeLimit: 1000\n'
    root = _parse(text)

    line, col, span = _locate(('timeLimit',), root)

    assert line == 2
    # caret on the value, not the key
    assert col == len('timeLimit: ') + 1
    assert span == len('1000')
```

Likewise update `test_locate_nested_map` to expect the value column for `c: hello`:

```python
def test_locate_nested_map():
    from rbx.box.yaml_validation import _locate

    text = 'a:\n  b:\n    c: hello\n'
    root = _parse(text)

    line, col, span = _locate(('a', 'b', 'c'), root)

    assert line == 3
    assert col == len('    c: ') + 1
    assert span == len('hello')
```

And `test_locate_list_of_maps`:

```python
def test_locate_list_of_maps():
    from rbx.box.yaml_validation import _locate

    text = 'items:\n  - name: alice\n  - name: bob\n  - name: carol\n'
    root = _parse(text)

    line, col, span = _locate(('items', 2, 'name'), root)

    assert line == 4
    assert col == len('  - name: ') + 1
    assert span == len('carol')
```

> The list-index test (`test_locate_list_index`) is unaffected — its loc
> ends at an int index, not a string key, so the parent-is-CommentedMap
> guard prevents widening.

**Step 6: Run all locate tests**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py -v -k locate`
Expected: all PASS.

**Step 7: Commit**

```bash
git add rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git commit -m "feat(yaml): widen caret span to scalar values in locate

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Implement `_format_loc` for human-readable error paths

**Step 1: Write failing test**

```python
def test_format_loc_renders_path_human_readably():
    from rbx.box.yaml_validation import _format_loc

    assert _format_loc(()) == '<root>'
    assert _format_loc(('name',)) == 'name'
    assert _format_loc(('a', 'b', 'c')) == 'a.b.c'
    assert _format_loc(('items', 2)) == 'items[2]'
    assert _format_loc(('items', 2, 'name')) == 'items[2].name'
    assert _format_loc(('a', 'union_tag', 'b')) == 'a.b'
```

**Step 2: Run** — FAIL (function not defined).

**Step 3: Implement**

Add to `rbx/box/yaml_validation.py`:

```python
def _format_loc(loc: Tuple[Any, ...]) -> str:
    """Render a Pydantic loc tuple as ``a.b[2].c``.

    Empty tuples render as ``<root>``. Pydantic-internal segments
    (``union_tag`` etc.) are skipped so users do not see them.
    """
    if not loc:
        return '<root>'
    parts: List[str] = []
    for seg in loc:
        if seg in PYDANTIC_INTERNAL_LOC_SEGMENTS:
            continue
        if isinstance(seg, int):
            parts.append(f'[{seg}]')
        else:
            parts.append(f'.{seg}' if parts else str(seg))
    return ''.join(parts) or '<root>'
```

**Step 4: Run + commit**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py::test_format_loc_renders_path_human_readably -v`
Expected: PASS.

```bash
uv run ruff check --fix rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
uv run ruff format rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git add rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git commit -m "feat(yaml): format loc tuples as readable dotted paths

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: Implement `_dedupe`

**Step 1: Write failing tests**

```python
def test_dedupe_collapses_identical_errors():
    from rbx.box.yaml_validation import _dedupe

    errors = [
        {'loc': ('a',), 'msg': 'oops', 'type': 'value_error'},
        {'loc': ('a',), 'msg': 'oops', 'type': 'value_error'},
        {'loc': ('b',), 'msg': 'bad',  'type': 'value_error'},
    ]

    out = _dedupe(errors)

    assert len(out) == 2
    assert {e['loc'] for e in out} == {('a',), ('b',)}


def test_dedupe_folds_union_branches_at_same_loc():
    from rbx.box.yaml_validation import _dedupe

    errors = [
        {'loc': ('score',), 'msg': 'expected int',   'type': 'union_int_expected'},
        {'loc': ('score',), 'msg': 'expected tuple', 'type': 'union_tuple_expected'},
    ]

    out = _dedupe(errors)

    assert len(out) == 1
    msg = out[0]['msg']
    assert 'union' in msg.lower() or 'any of' in msg.lower()
    assert 'int' in msg and 'tuple' in msg


def test_dedupe_keeps_discriminated_union_errors_separate():
    from rbx.box.yaml_validation import _dedupe

    errors = [
        {'loc': ('step', 'foo'), 'msg': 'foo bad', 'type': 'value_error'},
        {'loc': ('step', 'bar'), 'msg': 'bar bad', 'type': 'value_error'},
    ]

    out = _dedupe(errors)

    assert len(out) == 2
```

> Note: `_dedupe` operates purely on Pydantic's error dicts (no source
> location) — sort-by-(line,col) happens later in `YamlValidationError`
> after we've called `_locate`.

**Step 2: Run** — FAIL.

**Step 3: Implement**

```python
def _dedupe(errors: List[dict]) -> List[dict]:
    """Collapse Pydantic ``ValidationError.errors()`` for cleaner output.

    - Identical ``(loc, msg)`` pairs are deduplicated.
    - Multiple errors at the same ``loc`` whose ``type`` starts with
      ``union_`` are folded into a single synthetic message of the form
      ``"value did not match any of the allowed types (... | ...)"``.
    - Errors at distinct ``loc`` values stay distinct (covers
      discriminated unions where each branch lives at a different path).

    Output order matches first appearance per ``loc``; final
    line/column ordering is applied later by the renderer.
    """
    by_loc: 'dict[tuple, list[dict]]' = {}
    order: List[tuple] = []
    for e in errors:
        key = tuple(e['loc'])
        if key not in by_loc:
            by_loc[key] = []
            order.append(key)
        by_loc[key].append(e)

    out: List[dict] = []
    for key in order:
        group = by_loc[key]
        # Drop identical (loc, msg) duplicates.
        seen_msgs = set()
        unique = []
        for e in group:
            if e['msg'] in seen_msgs:
                continue
            seen_msgs.add(e['msg'])
            unique.append(e)

        union_branches = [e for e in unique if str(e.get('type', '')).startswith('union_')]
        if len(union_branches) >= 2 and len(union_branches) == len(unique):
            joined = ' | '.join(e['msg'] for e in union_branches)
            out.append({
                'loc': key,
                'msg': f'value did not match any of the allowed types ({joined})',
                'type': 'union_folded',
            })
        else:
            out.extend(unique)

    return out
```

**Step 4: Run + commit**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py -v -k dedupe`
Expected: all PASS.

```bash
uv run ruff check --fix rbx/box/yaml_validation.py
uv run ruff format rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git add rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git commit -m "feat(yaml): dedupe and fold union noise in pydantic errors

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: Implement `_render_diagnostic`

**Files:**
- Modify: `rbx/box/yaml_validation.py`
- Modify: `tests/rbx/box/test_yaml_validation.py`

**Step 1: Write failing tests**

```python
def _render(*args, **kwargs):
    """Helper: render a diagnostic to plain text."""
    from rich.console import Console
    from rbx.box.yaml_validation import _render_diagnostic

    out = _render_diagnostic(*args, **kwargs)
    console = Console(width=120, record=True, color_system=None)
    console.print(out)
    return console.export_text()


def test_render_diagnostic_includes_header_and_location():
    text = 'name: x\ntimeLimit: 1000\n'
    rendered = _render(
        source=text,
        path=pathlib.Path('problem.rbx.yml'),
        line=2, col=12, span=4,
        msg='input should be a valid integer',
        loc_label='timeLimit',
        header='error',
    )

    assert 'error' in rendered
    assert 'timeLimit' in rendered
    assert 'problem.rbx.yml:2:12' in rendered
    assert 'input should be a valid integer' in rendered
    # snippet contains the offending line
    assert 'timeLimit: 1000' in rendered


def test_render_diagnostic_window_clipped_at_file_start():
    text = 'a: 1\nb: 2\n'
    rendered = _render(
        source=text,
        path=pathlib.Path('x.yml'),
        line=1, col=1, span=1,
        msg='bad', loc_label='a', header='error',
    )

    # No phantom line numbers below 1
    assert '\n 0 ' not in rendered
    assert '\n-1 ' not in rendered


def test_render_diagnostic_caret_under_correct_column():
    text = 'name: my-problem\n'
    rendered = _render(
        source=text,
        path=pathlib.Path('p.yml'),
        line=1, col=7, span=10,
        msg='bad name', loc_label='name', header='error',
    )

    # Find the caret line (contains ^^^^^)
    caret_line = next(line for line in rendered.splitlines() if '^^^' in line)
    # Caret start position must align with column 7 of 'name: my-problem'
    # (allow gutter offset; we just verify the leading ^ count and run).
    assert '^' * 10 in caret_line
```

**Step 2: Run** — FAIL.

**Step 3: Implement**

Add to `rbx/box/yaml_validation.py`:

```python
import rich.text
from rich.console import Group
from rich.syntax import Syntax

WINDOW = 2  # lines of context before and after the offending line


def _render_diagnostic(
    *,
    source: str,
    path: pathlib.Path,
    line: int,
    col: int,
    span: int,
    msg: str,
    loc_label: str,
    header: str,
) -> Group:
    """Build a single caret diagnostic block.

    Layout::

        <header>: <loc_label> — <msg>
          --> <path>:<line>:<col>
          [snippet via rich.syntax.Syntax with line numbers]
          [caret line aligned under the offending column]

    Args:
        source: Full source text of the file (for the snippet window).
        path: Path used in the ``--> path:line:col`` header.
        line: 1-based line of the offending token.
        col: 1-based column of the offending token (within ``line``).
        span: Number of caret characters to emit.
        msg: Short, plain-English error message.
        loc_label: Human-readable dotted path (from ``_format_loc``).
        header: ``"error"`` or ``"YAML syntax error"``.

    Returns:
        A ``rich.console.Group`` ready to ``console.print``.
    """
    lines = source.splitlines()
    total = len(lines)
    start = max(1, line - WINDOW)
    end = min(total, line + WINDOW)
    snippet_text = '\n'.join(lines[start - 1:end])

    syntax = Syntax(
        snippet_text,
        'yaml',
        line_numbers=True,
        start_line=start,
        highlight_lines={line},
        theme='ansi_dark',
    )

    # Caret line: align under the correct column.
    # Syntax renders a gutter of ``len(str(end)) + 2`` chars before the source
    # (line number + space + pipe + space). We replicate that offset.
    gutter = len(str(end)) + 3
    caret = rich.text.Text(' ' * (gutter + col - 1) + '^' * max(1, span), style='bold red')

    header_text = rich.text.Text.from_markup(
        f'[error]{header}[/error]: [item]{loc_label}[/item] — {msg}'
    )
    location_text = rich.text.Text.from_markup(f'  [info]-->[/info] {path}:{line}:{col}')

    return Group(header_text, location_text, syntax, caret)
```

**Step 4: Run** — verify the three render tests PASS.

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py -v -k render`
Expected: PASS.

> If `test_render_diagnostic_caret_under_correct_column` fails because the
> gutter width assumption is off, print the rendered text and adjust the
> ``gutter`` formula. Rich's `Syntax` gutter is "right-aligned line number"
> + " " + "│" + " " — for windows under 100 lines that's 2 + 1 + 1 + 1 = 5.
> Use `len(str(end)) + 3` only if Rich's vertical bar is one char.

**Step 5: Commit**

```bash
uv run ruff check --fix rbx/box/yaml_validation.py
uv run ruff format rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git add rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git commit -m "feat(yaml): render caret diagnostic blocks for validation errors

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: Implement `YamlSyntaxError`

**Step 1: Write failing test**

```python
def test_yaml_syntax_error_renders_diagnostic(tmp_path):
    bad_yaml = 'a: 1\nb: [unterminated\n'
    p = tmp_path / 'bad.yml'
    p.write_text(bad_yaml)

    class M(pydantic.BaseModel):
        a: int = 0

    with pytest.raises(YamlSyntaxError) as exc_info:
        load_yaml_model(p, M)

    rendered = str(exc_info.value)
    assert 'YAML syntax error' in rendered
    assert 'bad.yml' in rendered
    assert ':2' in rendered  # line 2 contains the unterminated bracket
```

> This test exercises both `YamlSyntaxError.__init__` and `load_yaml_model`'s
> exception-mapping branch. We implement the syntax-error path in this task
> and the validation-error path in the next.

**Step 2: Run** — FAIL (`load_yaml_model` is `NotImplementedError`).

**Step 3: Implement `YamlSyntaxError` and the syntax-error half of `load_yaml_model`**

Replace the `YamlSyntaxError` stub:

```python
class YamlSyntaxError(RbxException):
    """Raised when a YAML file cannot be parsed.

    Wraps a ``ruyaml.YAMLError`` and renders a single caret diagnostic
    pointing at ``problem_mark.line / .column``.
    """

    def __init__(
        self,
        path: pathlib.Path,
        source: str,
        cause: ruyaml.YAMLError,
    ):
        super().__init__()
        mark = getattr(cause, 'problem_mark', None) or getattr(cause, 'context_mark', None)
        if mark is not None:
            line = mark.line + 1
            col = mark.column + 1
        else:
            line, col = 1, 1
        msg = getattr(cause, 'problem', None) or str(cause)

        with self.possibly_capture():
            self.console.print(_render_diagnostic(
                source=source,
                path=path,
                line=line,
                col=col,
                span=1,
                msg=str(msg),
                loc_label='<root>',
                header='YAML syntax error',
            ))
```

Replace `load_yaml_model` body:

```python
def load_yaml_model(path: pathlib.Path, model: Type[T]) -> T:
    """[docstring unchanged]"""
    source = path.read_text()
    try:
        data = ruyaml.YAML(typ='rt').load(source)
    except ruyaml.YAMLError as exc:
        raise YamlSyntaxError(path, source, exc) from exc

    # Validation path implemented in the next task.
    return model.model_validate(data)
```

**Step 4: Run + commit**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py::test_yaml_syntax_error_renders_diagnostic -v`
Expected: PASS.

```bash
uv run ruff check --fix rbx/box/yaml_validation.py
uv run ruff format rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git add rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git commit -m "feat(yaml): wrap YAML syntax errors with caret diagnostic

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: Implement `YamlValidationError`

**Step 1: Write failing tests**

```python
class _NestedModel(pydantic.BaseModel):
    name: str
    score: int


class _RootModel(pydantic.BaseModel):
    title: str
    items: List[_NestedModel]


def test_validation_error_renders_one_block_per_error(tmp_path):
    text = 'title: hello\nitems:\n  - name: a\n    score: oops\n  - name: b\n    score: 5\n'
    p = tmp_path / 'p.yml'
    p.write_text(text)

    with pytest.raises(YamlValidationError) as exc_info:
        load_yaml_model(p, _RootModel)

    rendered = str(exc_info.value)
    assert 'p.yml' in rendered
    assert 'items[0].score' in rendered
    assert 'oops' in rendered or 'integer' in rendered.lower()


def test_validation_error_collects_multiple_errors_sorted_by_line(tmp_path):
    text = 'items:\n  - name: a\n    score: bad\n  - name: 123\n    score: 5\n'
    # title is missing; items[0].score is a string; items[1].name is an int
    p = tmp_path / 'p.yml'
    p.write_text(text)

    with pytest.raises(YamlValidationError) as exc_info:
        load_yaml_model(p, _RootModel)

    rendered = str(exc_info.value)
    # Find the lines that contain ':3:' and ':4:' style location markers.
    locs = [
        seg
        for line in rendered.splitlines()
        for seg in [line.split('p.yml:')[1].split(' ')[0]] if 'p.yml:' in line
    ]
    # Multiple errors → multiple --> lines.
    assert len(locs) >= 2
```

**Step 2: Run** — FAIL (`YamlValidationError` is still a stub).

**Step 3: Implement `YamlValidationError`**

```python
class YamlValidationError(RbxException):
    """Raised when a YAML file parses but does not match a Pydantic model.

    Wraps a ``pydantic.ValidationError``. On construction, every error
    (after deduplication) is rendered as its own caret diagnostic block,
    sorted by source line/column. A trailing hint reminds the user to
    check they are running the latest ``rbx``.
    """

    def __init__(
        self,
        path: pathlib.Path,
        source: str,
        root: Any,
        cause: pydantic.ValidationError,
    ):
        super().__init__()
        deduped = _dedupe(list(cause.errors()))

        # Resolve every error's source position.
        rendered_blocks: List[Tuple[int, int, Group]] = []
        for err in deduped:
            line, col, span = _locate(tuple(err['loc']), root)
            block = _render_diagnostic(
                source=source,
                path=path,
                line=line,
                col=col,
                span=span,
                msg=str(err['msg']),
                loc_label=_format_loc(tuple(err['loc'])),
                header='error',
            )
            rendered_blocks.append((line, col, block))

        rendered_blocks.sort(key=lambda t: (t[0], t[1]))

        n = len(rendered_blocks)
        self.print(rich.text.Text.from_markup(
            f'[error]Failed to load[/error] [item]{path}[/item] '
            f'— {n} validation error{"s" if n != 1 else ""}'
        ))
        self.print('')
        for _, _, block in rendered_blocks:
            self.print(block)
            self.print('')
        self.print(rich.text.Text.from_markup(
            '[error]If you believe this is a bug, ensure you are on the latest rbx.[/error]'
        ))
```

Update `load_yaml_model`:

```python
def load_yaml_model(path: pathlib.Path, model: Type[T]) -> T:
    """[docstring unchanged]"""
    source = path.read_text()
    try:
        data = ruyaml.YAML(typ='rt').load(source)
    except ruyaml.YAMLError as exc:
        raise YamlSyntaxError(path, source, exc) from exc

    try:
        return model.model_validate(data)
    except pydantic.ValidationError as exc:
        raise YamlValidationError(path, source, data, exc) from exc
```

**Step 4: Run + commit**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py -v`
Expected: all PASS.

```bash
uv run ruff check --fix rbx/box/yaml_validation.py
uv run ruff format rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git add rbx/box/yaml_validation.py tests/rbx/box/test_yaml_validation.py
git commit -m "feat(yaml): wrap pydantic validation errors with caret diagnostics

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 12: End-to-end happy-path and FileNotFoundError tests

**Step 1: Write tests**

```python
def test_load_yaml_model_returns_instance_on_success(tmp_path):
    text = 'title: ok\nitems:\n  - name: a\n    score: 1\n'
    p = tmp_path / 'p.yml'
    p.write_text(text)

    out = load_yaml_model(p, _RootModel)

    assert isinstance(out, _RootModel)
    assert out.title == 'ok'
    assert out.items[0].score == 1


def test_load_yaml_model_propagates_file_not_found(tmp_path):
    p = tmp_path / 'missing.yml'

    with pytest.raises(FileNotFoundError):
        load_yaml_model(p, _RootModel)
```

**Step 2: Run + commit**

Run: `uv run pytest tests/rbx/box/test_yaml_validation.py -v`
Expected: all PASS.

```bash
git add tests/rbx/box/test_yaml_validation.py
git commit -m "test(yaml): cover happy path and missing-file behaviour

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 13: Migrate `rbx/box/package.py`

**Files:**
- Modify: `rbx/box/package.py:71-83`

**Step 1: Replace the try/except**

Before (lines 71-83):

```python
@functools.cache
def find_problem_package(root: pathlib.Path = pathlib.Path()) -> Optional[Package]:
    problem_yaml_path = find_problem_yaml(root)
    if not problem_yaml_path:
        return None
    try:
        return utils.model_from_yaml(Package, problem_yaml_path.read_text())
    except ValidationError as e:
        console.console.print(e)
        console.console.print(
            '[error]Error parsing [item]problem.rbx.yml[/item].[/error]'
        )
        console.console.print(
            '[error]If you are sure the file is correct, ensure you are '
            'in the latest version of [item]rbx[/item].[/error]'
        )
        raise typer.Exit(1) from e
```

After:

```python
@functools.cache
def find_problem_package(root: pathlib.Path = pathlib.Path()) -> Optional[Package]:
    problem_yaml_path = find_problem_yaml(root)
    if not problem_yaml_path:
        return None
    return load_yaml_model(problem_yaml_path, Package)
```

Add the import near the other `rbx.box` imports:

```python
from rbx.box.yaml_validation import load_yaml_model
```

Remove now-unused imports if `ValidationError`, `typer`, or `utils` are not used elsewhere in the file (run `uv run ruff check rbx/box/package.py` after editing to confirm).

> Note: dropping `typer.Exit(1)` is intentional — `RbxException` is caught
> at the top of `box/main.py` and exits the process. Behaviour is preserved.

**Step 2: Run package + smoke tests**

Run: `uv run pytest tests/rbx/box/ -v -k "package or schema" --ignore=tests/rbx/box/cli`
Expected: all PASS, no regressions.

**Step 3: Commit**

```bash
git add rbx/box/package.py
git commit -m "refactor(package): use load_yaml_model for problem.rbx.yml

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 14: Migrate `rbx/box/contest/contest_package.py`

**Files:**
- Modify: `rbx/box/contest/contest_package.py:82-92`

**Step 1: Replace the try/except**

Before:

```python
    try:
        contest = utils.model_from_yaml(Contest, contest_yaml_path.read_text())
    except ValidationError as e:
        console.console.print(e)
        console.console.print('[error]Error parsing contest.rbx.yml.[/error]')
        console.console.print(
            '[error]If you are sure the file is correct, ensure you are '
            'in the latest version of [item]rbx[/item].[/error]'
        )
        raise typer.Exit(1) from e
```

After:

```python
    contest = load_yaml_model(contest_yaml_path, Contest)
```

Add import: `from rbx.box.yaml_validation import load_yaml_model`. Remove unused imports per ruff.

**Step 2: Run contest tests**

Run: `uv run pytest tests/rbx/box/contest -v --ignore=tests/rbx/box/cli`
Expected: PASS.

**Step 3: Commit**

```bash
git add rbx/box/contest/contest_package.py
git commit -m "refactor(contest): use load_yaml_model for contest.rbx.yml

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 15: Migrate `rbx/box/environment.py`

**Files:**
- Modify: `rbx/box/environment.py:325-337`

**Step 1: Replace the try/except**

Before:

```python
    try:
        return utils.model_from_yaml(Environment, env_path.read_text())
    except ValidationError as e:
        console.console.print(e)
        console.console.print(
            f'[error]Error parsing environment file [item]{env_path}[/item][/error]'
        )
        console.console.print(
            '[error]If you are sure the file is correct, ensure you are '
            'in the latest version of [item]rbx[/item].[/error]'
        )
        raise typer.Exit(1) from e
```

After:

```python
    return load_yaml_model(env_path, Environment)
```

Add the import; remove unused.

**Step 2: Run env tests**

Run: `uv run pytest tests/rbx/box -v -k "env or environment" --ignore=tests/rbx/box/cli`
Expected: PASS.

**Step 3: Commit**

```bash
git add rbx/box/environment.py
git commit -m "refactor(env): use load_yaml_model for env.rbx.yml

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 16: Migrate `rbx/box/limits_info.py`

**Files:**
- Modify: `rbx/box/limits_info.py:100-107`

**Step 1: Swap the bare `model_from_yaml` for `load_yaml_model`**

Before:

```python
    return utils.model_from_yaml(LimitsProfile, limits_path.read_text())
```

After:

```python
    return load_yaml_model(limits_path, LimitsProfile)
```

Add `from rbx.box.yaml_validation import load_yaml_model` near other rbx.box imports. The existence check above remains as-is.

**Step 2: Run limits tests**

Run: `uv run pytest tests/rbx/box/limits_info_test.py -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add rbx/box/limits_info.py
git commit -m "refactor(limits): use load_yaml_model for limits profiles

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 17: Migrate `rbx/box/presets/__init__.py`

**Files:**
- Modify: `rbx/box/presets/__init__.py:119` (Preset)
- Modify: `rbx/box/presets/__init__.py:158` (PresetLock)

**Step 1: Replace both load sites**

Line 119 (in `get_preset_yaml`):

Before:
```python
    preset = utils.model_from_yaml(Preset, found.read_text())
```
After:
```python
    preset = load_yaml_model(found, Preset)
```

Line 158 (in `get_preset_lock`):

Before:
```python
    return utils.model_from_yaml(PresetLock, found.read_text())
```
After:
```python
    return load_yaml_model(found, PresetLock)
```

> Leave the `yaml.safe_load` call in `get_preset_yaml_metadata` (line 132)
> alone — it deliberately reads only two raw fields without a model. Out of
> scope.

Add `from rbx.box.yaml_validation import load_yaml_model`.

**Step 2: Run preset tests**

Run: `uv run pytest tests/rbx/box/presets -v --ignore=tests/rbx/box/cli`
Expected: PASS.

**Step 3: Commit**

```bash
git add rbx/box/presets/__init__.py
git commit -m "refactor(presets): use load_yaml_model for preset configs

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 18: Integration smoke test for problem.rbx.yml

**Files:**
- Modify: `tests/rbx/box/test_path_resolution.py` OR add a new `tests/rbx/box/test_package_loading.py`

Pick `tests/rbx/box/test_package_loading.py` (new, focused) so the test colocates with what it covers.

**Step 1: Write the test**

```python
# tests/rbx/box/test_package_loading.py
"""Smoke test: load_yaml_model surfaces YamlValidationError end-to-end."""

from __future__ import annotations

import pathlib

import pytest

from rbx.box.package import find_problem_package
from rbx.box.yaml_validation import YamlValidationError


def test_find_problem_package_raises_yaml_validation_error_on_bad_yml(
    cleandir: pathlib.Path,
):
    # Minimal broken problem.rbx.yml: timeLimit must be int, given a string.
    (cleandir / 'problem.rbx.yml').write_text(
        'name: bad-problem\ntimeLimit: "not a number"\nmemoryLimit: 256\n'
    )

    with pytest.raises(YamlValidationError) as exc_info:
        find_problem_package(cleandir)

    rendered = str(exc_info.value)
    assert 'problem.rbx.yml' in rendered
    assert 'timeLimit' in rendered
```

> The `cleandir` fixture is defined in `tests/rbx/conftest.py:39` and yields
> a clean tmp directory it has `cd`-ed into.
> `find_problem_package` is `@functools.cache`-d; if other tests in the
> same module collide, call `find_problem_package.cache_clear()` in a
> fixture or use `monkeypatch.setattr` to bypass the cache.

**Step 2: Run**

Run: `uv run pytest tests/rbx/box/test_package_loading.py -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/rbx/box/test_package_loading.py
git commit -m "test(package): smoke-test yaml validation error rendering

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 19: Integration smoke test for contest.rbx.yml

**Files:**
- Modify: `tests/rbx/box/contest/` — add `tests/rbx/box/contest/test_contest_loading.py`

**Step 1: Write the test**

```python
# tests/rbx/box/contest/test_contest_loading.py
from __future__ import annotations

import pathlib

import pytest

from rbx.box.contest.contest_package import find_contest_package
from rbx.box.yaml_validation import YamlValidationError


def test_find_contest_package_raises_yaml_validation_error_on_bad_yml(
    cleandir: pathlib.Path,
):
    (cleandir / 'contest.rbx.yml').write_text(
        'name: my-contest\nproblems: "not-a-list"\n'
    )

    with pytest.raises(YamlValidationError) as exc_info:
        find_contest_package(cleandir)

    rendered = str(exc_info.value)
    assert 'contest.rbx.yml' in rendered
    assert 'problems' in rendered
```

> If `find_contest_package` raises a different `RbxException` shape than
> `YamlValidationError` (e.g. from one of the post-load validators that
> run after the YAML is loaded), debug — the YAML must fail Pydantic
> first since `problems` is a structural field. If the test fails because
> the YAML is *too* broken (some other path runs first), use a different
> trigger: `problems: [{name: "x"}]` (missing required `path` field on
> the entry).

**Step 2: Run + commit**

Run: `uv run pytest tests/rbx/box/contest/test_contest_loading.py -v`
Expected: PASS.

```bash
git add tests/rbx/box/contest/test_contest_loading.py
git commit -m "test(contest): smoke-test yaml validation error rendering

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 20: Full test sweep

**Step 1: Run the project test suite**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: green. If any test fails, debug — the migration should be behaviour-preserving except for the rendered output of validation errors.

> If a test elsewhere in the suite was asserting on the OLD raw-Pydantic
> output text (`grep -rn "validation error for"` in `tests/`), update its
> assertion to check the new diagnostic format. Likely candidates: any
> test that loads a deliberately broken `problem.rbx.yml`, `env.rbx.yml`,
> or preset and asserts on the captured stderr.

**Step 2: Lint sweep**

Run: `uv run ruff check rbx tests` — should be clean.
Run: `uv run ruff format --check rbx tests` — should be clean.

**Step 3: Manual smoke check**

```bash
mkdir -p /tmp/rbx-smoke && cd /tmp/rbx-smoke
cat > problem.rbx.yml <<'EOF'
name: smoke
timeLimit: "not a number"
memoryLimit: 256
EOF
cd -
uv run rbx --help  # sanity
( cd /tmp/rbx-smoke && uv run rbx build || true )
```

Expected: a caret diagnostic identifying `timeLimit` on line 2 with a snippet, not a Pydantic traceback.

**Step 4: If any test failed in step 1, fix and recommit using a `test:` or `fix:` type as appropriate.**

---

## Task 21: Final commit and PR prep

**Step 1: Verify branch state**

Run: `git log --oneline main..HEAD`
Expected: ~17 commits, each conventional, each scoped.

**Step 2: Run the full default test command one more time**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: green.

**Step 3: Update the design doc with any deviations**

If anything about the implementation diverged from the design doc (e.g. the gutter formula in `_render_diagnostic`, an extra dedup edge case, a fixture you had to add), append a short "## Implementation notes" section to
`docs/plans/2026-05-01-yaml-validation-error-rendering-design.md` listing
the deviations. Commit that under `docs(yaml): record implementation notes`.

**Step 4: Stop here**

Plan is complete. Hand back to the user for review and PR.
