# Subgroup-level `@testgroup` filtering in generator scripts

**Issue:** [#600](https://github.com/rsalesc/rbx/issues/600) — follow-up from #599 (problem-level `generatorScript`).
**Date:** 2026-06-21

## Background

With #599, a problem-level `generatorScript` is inherited by every group and
subgroup that does not declare its own test parameters. When a script runs for a
group/subgroup, `@testgroup <name> { ... }` blocks let it emit only the
testcases tagged with that name (plus untagged lines).

Today the `@testgroup` filter can only target a **group**, never a **subgroup**,
for two independent reasons:

1. **Parser** (`rbx/box/stressing/generator_script_parser.py`): `GROUP_NAME` is a
   flat token with no `/` path syntax, and `GenerationInput.group` holds a single
   string. Nested `@testgroup` just lets the innermost name win, so there is no
   way to express `@testgroup group/subgroup`.
2. **Extractor** (`rbx/box/testcase_extractors.py`, `run_testcase_visitor.
   _explore_subgroup`): when running a script for a subgroup, the filter key
   passed to `_extract_script_lines` is `group_path = prefix[0]` — the *parent
   group's* name. All subgroups of a group therefore share one filter key.

### Impact

Because #599 inherits the problem-level script into subgroups, sibling subgroups
that inherit a shared script all receive the **same** filtered lines (untagged
lines + `@testgroup <parent-group>` lines). There is no way to route distinct
testcases to distinct subgroups from one shared script.

## Approach

Represent the `@testgroup` annotation as a `/`-joined **path** on
`GenerationInput.group` (the field stays `Optional[str]`), and replace the
string-equality filter with a **prefix-path predicate**:

> annotation `A` matches run-key `K` ⟺ `A is None` **or** `K == A` **or**
> `K.startswith(A + '/')`

The extractor passes the **full** `subgroup_path` (e.g. `main/sub1`) as `K`
instead of the parent group name. This single predicate change simultaneously:

- keeps untagged and parent-group-tagged lines flowing to every subgroup
  (back-compat, exactly as the issue requests), and
- routes `@testgroup main/sub1` lines to that one subgroup only.

### Why the prefix rule is correct

| run-key `K`            | `A=None` | `A=g` | `A=g/s1`     | `A=g/s2` |
| ---------------------- | -------- | ----- | ------------ | -------- |
| `g` (group, no subs)   | match    | match | drop         | drop     |
| `g/s1` (subgroup)      | match    | match | match        | drop     |
| `g/s2` (subgroup)      | match    | match | drop         | match    |

- Existing scripts (no path annotations) are unaffected: at the group level
  `K == group_path`, so the predicate reduces to today's behavior.
- Path-qualified lines targeting a non-existent subgroup simply match nothing
  (silent no-op), consistent with how filtered-out lines behave today.

### Alternative considered

Make `GenerationInput.group` a `List[str]` and match segment-wise. Rejected:
more invasive (Pydantic model, serialization, every consumer) for no added
expressiveness over the string-path + prefix rule.

## Design — change sites

### 1. Parser (`generator_script_parser.py`)

- Broaden the `GROUP_NAME` token to capture path-like tokens (start with an
  alphanumeric, then alphanumerics / `-` / `_` / `/`). This lets
  trailing/double-slash cases reach the transformer so it can raise a *clear*
  error instead of a cryptic lark failure. (A leading `/` is still rejected at
  tokenize time, which is acceptable.)
- In the `testgroup` transformer:
  - **Validate** each `/`-separated segment: non-empty and matching
    `[a-zA-Z0-9][a-zA-Z0-9\-_]*`; raise a clear `ValueError` otherwise. This
    rejects `main/`, `main//sub`, etc. Arbitrary depth (`a/b/c`) is accepted
    syntactically and simply never matches rbx's 2-level model.
  - **Concatenate** for nesting:
    `child.group = name if child.group is None else f'{name}/{child.group}'`.
    Both inline `@testgroup a/b { ... }` and nested
    `@testgroup a { @testgroup b { ... } }` yield path `a/b`.
- Update the `ScriptGeneratedInput.group` docstring to note it is now a
  `/`-joined path.

### 2. Handler (`generator_script_handlers.py`)

Replace the equality filter in `RbxGeneratorScriptHandler.parse()` with the
prefix-path predicate via a small helper:

```python
def _group_matches(annotation: Optional[str], key: str) -> bool:
    if annotation is None:
        return True
    return key == annotation or key.startswith(annotation + '/')
```

### 3. Extractor (`testcase_extractors.py`)

In `_explore_subgroup`, pass `subgroup_path` (already computed as
`'/'.join(prefix)`) instead of `group_path` as the filter key when running the
script. At the group level the two are identical, so existing group-level
scripts are unaffected.

## Testing

- **Parser tests** (`tests/rbx/box/stressing/test_generator_script_parser.py`):
  inline `main/sub1`; nested concat → `main/sub1` (update/rename the existing
  `..._inner_takes_precedence` test, whose behavior changes); deep `a/b/c`
  accepted; malformed (`/sub`, `main/`, `main//sub`) rejected.
- **Handler tests** (`tests/rbx/box/test_generator_script_handlers.py`):
  prefix-match filtering — key `g/s1` returns untagged + `@testgroup g` +
  `@testgroup g/s1` and excludes `g/s2`; key `g` returns untagged + `g` only.
- **Extractor test** (`tests/rbx/box/testcase_extractors_test.py`): a shared
  problem-level script routing distinct testcases to distinct subgroups via
  path-qualified `@testgroup`, asserting no overlap across siblings.
- **e2e fixture** (`tests/e2e/`): a problem-level `generatorScript` partitioned
  across groups **and** subgroups, asserting no duplicate testcases across
  siblings.
- **Round-trip / stress coverage**: confirm `statement_spans` / `append` /
  `remove` still work with path-qualified `@testgroup`, and generators
  referenced inside `@testgroup g/s { ... }` resolve through the normal stress
  flow.
