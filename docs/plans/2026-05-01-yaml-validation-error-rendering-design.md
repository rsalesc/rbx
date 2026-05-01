# YAML validation error rendering

**Issue:** [#416](https://github.com/rsalesc/rbx/issues/416)

## Problem

When a user-authored YAML config file (`problem.rbx.yml`, `contest.rbx.yml`,
`env.rbx.yml`, `limits.*.rbx.yml`, `preset.rbx.yml`, `preset.lock.yml`) fails
validation, today's behavior is to print Pydantic's raw `ValidationError`
followed by a generic "Error parsing X" line. This gives the user the dotted
field path and the error message, but no source line, no surrounding YAML
context, and no caret pointing at the offending value. YAML syntax errors fall
through entirely as `ruyaml.YAMLError` tracebacks.

The user-facing problem: it is hard to tell *where* in a long config file the
error happened, and the dotted path (e.g. `solutions.2.path`) does not map
obviously to a list item in the source file.

## Goal

Render validation failures with rust/elm-style caret diagnostics that show:

- the file, line, and column;
- a small YAML snippet around the offending location with line numbers;
- a caret line underlining the bad key or value;
- a short, plain-English message;
- one block per distinct error, sorted in source order, with noisy
  Pydantic-internal duplicates folded.

Cover both Pydantic schema violations and YAML syntax errors with the same
visual format.

## Non-goals

- Rewriting the schema itself or changing any model definition.
- Touching the legacy `utils.model_from_yaml` callers that load
  internal/JSON-shaped data (these stay on the existing path).
- Adding a JSON Schema export, docs links, or "did-you-mean" suggestions.
  Those are useful follow-ups but out of scope.

## Architecture

One new module: **`rbx/box/yaml_validation.py`**.

### Public surface

```
load_yaml_model(path: pathlib.Path, model: Type[T]) -> T
class YamlSyntaxError(RbxException)
class YamlValidationError(RbxException)
```

`load_yaml_model` is the single entry point. It reads the file, parses with
`ruyaml` in round-trip mode, runs `model.model_validate`, and raises one of
the two typed exceptions on failure. Both subclass `RbxException`, which means
the existing top-level handler in `rbx/box/main.py:109` prints them with no
plumbing changes.

The exceptions build their full diagnostic in `__init__` using the
`RbxException.print` capture pattern, so `str(exc)` returns the rendered Rich
output.

### Private helpers

- `_locate(loc, root) -> (line, col, span)` — walks a Pydantic `loc` tuple
  against the ruyaml node tree.
- `_render_diagnostic(source, path, line, col, span, msg, header) -> Text` —
  builds the snippet + caret block.
- `_dedupe(errors) -> list[ErrorDetails]` — collapses duplicate and
  union-noise errors, sorts by `(line, col)`.
- `_format_loc(loc) -> str` — renders the loc tuple as
  `solutions[2].path`.

### Migrated call sites

| File | Line | Replaces |
|---|---|---|
| `rbx/box/package.py` | 73 | try/except around `model_from_yaml(Package, ...)` |
| `rbx/box/contest/contest_package.py` | 84 | try/except around `model_from_yaml(Contest, ...)` |
| `rbx/box/environment.py` | 327 | try/except around `model_from_yaml(Environment, ...)` |
| `rbx/box/limits_info.py` | 107 | direct `model_from_yaml(LimitsProfile, ...)` |
| `rbx/box/presets/__init__.py` | 119 | direct `model_from_yaml(Preset, ...)` |
| `rbx/box/presets/__init__.py` | 158 | direct `model_from_yaml(PresetLock, ...)` |

Each collapses from a 6-12 line try/except block to a single
`load_yaml_model(path, Model)` call. `utils.model_from_yaml` stays untouched
for any remaining internal callers.

## Data flow

```
caller -> load_yaml_model(path, Model)
            |
            +-- read_text()
            +-- ruyaml.YAML(typ='rt').load(text)
            |     |
            |     +-- on ruyaml.YAMLError -> YamlSyntaxError(...)
            |
            +-- Model.model_validate(parsed)
            |     |
            |     +-- on pydantic.ValidationError -> YamlValidationError(...)
            |
            +-- return model instance
```

`YamlValidationError.__init__` then:

1. calls `_dedupe(exc.errors())`;
2. for each surviving error, calls `_locate(loc, parsed_root)` to get
   `(line, col, span)`;
3. calls `_render_diagnostic(...)` and prints the result via the inherited
   `RbxException.print`;
4. prints the trailing "ensure latest rbx" hint.

`YamlSyntaxError.__init__` calls `_render_diagnostic` once with the line/col
from `ruyaml.YAMLError.problem_mark`.

## Locating the source line — algorithm

ruyaml's `CommentedMap` and `CommentedSeq` carry `.lc` with:

- `lc.key(name) -> (line, col)` — position of a map key
- `lc.value(name) -> (line, col)` — position of a map value
- `lc.item(i) -> (line, col)` — position of a list item

Pseudocode for `_locate(loc, root)`:

```
node = root
last_known = (root.lc.line, root.lc.col, 1)

for seg in loc:
    if isinstance(node, CommentedMap) and isinstance(seg, str) and seg in node:
        line, col = node.lc.key(seg)
        last_known = (line, col, len(seg))
        node = node[seg]
    elif isinstance(node, CommentedSeq) and isinstance(seg, int) and 0 <= seg < len(node):
        line, col = node.lc.item(seg)
        last_known = (line, col, 1)
        node = node[seg]
    elif seg in PYDANTIC_INTERNAL_SEGMENTS:  # 'union_tag', 'tagged-union'
        continue
    else:
        # cannot resolve further; keep last_known (parent location)
        break

# Widen span to scalar value length when possible
if not isinstance(node, (CommentedMap, CommentedSeq)) and node is not None:
    span = len(_yaml_repr(node))
    last_known = (last_known[0], last_known[1], span)

return last_known
```

Coverage:

- ✅ existing scalar field — exact key column
- ✅ existing list item — dash column for that item
- ✅ missing required field — falls back to parent map location, span =
  parent key length
- ✅ wrong type for a sub-map — points at the parent key
- ✅ discriminated-union mismatch — full path resolves; span widens to value
  length
- ✅ untagged-union mismatch — `union_tag` segments skipped; final location
  matches the value
- ✅ empty `loc=()` — returns `(1, 1, 1)`

## Rendering format

Per-error block:

```
error: solutions[2].path — file does not exist
  --> problem.rbx.yml:14:11
   |
12 |   - path: sols/main.cpp
13 |     outcome: ACCEPTED
14 |   - path: sols/typo.cpp
   |           ^^^^^^^^^^^^^ file does not exist
15 |     outcome: ACCEPTED
   |
```

Built from three Rich pieces:

1. Header `Text`: `"error: <dotted-loc> — <msg>"` — loc rendered as
   `solutions[2].path`, not the raw tuple.
2. Snippet via
   `rich.syntax.Syntax(window_text, "yaml", line_numbers=True,
   start_line=window_start, highlight_lines={offending_line})`. Window =
   ±2 lines, clipped to file bounds.
3. Caret line: a `Text` with `" " * (gutter_width + col)` then `"^" * span`,
   styled `error`, optionally followed by an inline note.

Multi-line block scalars (`|` / `>`): span clamped to the rest of the
offending line.

Top-level layout:

```
Failed to load problem.rbx.yml — 3 validation errors

[block 1]

[block 2]

[block 3]

If you believe this is a bug, ensure you are on the latest rbx.
```

YAML syntax errors share the renderer with `header="YAML syntax error"` and
a single block.

## Dedup

Applied to `ValidationError.errors()` before rendering:

1. Group by `(line, col)`.
2. Within each group, drop duplicate `msg` strings.
3. If a group has multiple distinct entries with `error['type']` starting
   with `union_`, fold into one synthetic message:
   `"value did not match any of: <type-A> | <type-B> | ..."`.
4. Sort by `(line, col)` ascending.

Discriminated-union errors are *not* folded — each branch produces a
distinct `loc` and is genuinely different information.

## Error-handling principles

- `FileNotFoundError` is **not** swallowed — it's the caller's responsibility
  (existing `find_problem_package` already handles missing files separately).
- Any exception type other than `ruyaml.YAMLError` and
  `pydantic.ValidationError` propagates unchanged — we don't want to mask
  programming bugs in a custom validator.
- The exception subclasses do not re-raise inside `__init__`; they store the
  rendered output and let `RbxException`'s top-level handler do the printing
  and exit.

## Testing strategy

All unit tests in **`tests/rbx/box/test_yaml_validation.py`** with small
inline YAML strings + tiny Pydantic models — no `testdata/` dependency.

### `_locate` (one test per branch)

1. Top-level scalar — `loc=('name',)`.
2. Nested map — `loc=('a', 'b', 'c')`.
3. List index — `loc=('items', 2)`.
4. List of maps — `loc=('items', 2, 'name')`.
5. Missing required field — falls back to parent.
6. Wrong type for sub-map — points at parent key.
7. Discriminated-union miss.
8. `union_tag` Pydantic segment skipped.
9. Empty `loc=()` → `(1, 1, 1)`.
10. Out-of-range list index — falls back.

### `_dedupe`

11. Identical `(loc, msg)` collapses.
12. Same `loc`, different union branches fold into one synthetic entry.
13. Different `loc` (discriminated union) stays separate.
14. Final order is ascending by `(line, col)`.

### `_render_diagnostic`

15. Snippet window ±2 lines, clipped at bounds.
16. Caret column matches scalar value column.
17. Span equals key length when value is missing.
18. Multi-line block scalar — span clamped to first line.
19. Output contains header, file:line:col, snippet, caret, message.

### `load_yaml_model`

20. Valid YAML + valid schema → returns instance.
21. Invalid YAML syntax → `YamlSyntaxError` with snippet + line.
22. Schema violation → `YamlValidationError` with all expected diagnostics.
23. Multiple errors — all rendered, sorted, deduped.
24. File not found → `FileNotFoundError` (not swallowed).

### Integration smoke tests

In existing test files, one per migrated call site:

25. `find_problem_package` with broken `problem.rbx.yml` → `YamlValidationError`.
26. `find_contest_package` analogous.
27. `get_environment` analogous.

Assertions on `str(exc)` use substrings/regex — resilient to minor Rich
formatting tweaks while still verifying every important piece appears.

## Documentation

Every public function and exception in `yaml_validation.py` gets a multi-line
docstring with `Args` / `Returns` / `Raises` and a worked example.
`_locate` carries its algorithm pseudocode in its docstring — it is the one
piece that is non-obvious to a future reader.

## Risks and mitigations

- **ruyaml round-trip mode is slower than `safe_load`.** Config files are
  small (kilobytes), and loading happens once per CLI invocation. Negligible.
- **Pydantic emits new `error['type']` strings between minor versions.** The
  union-folding heuristic checks for the `union_` prefix, which is stable
  across recent Pydantic v2 releases. If the prefix changes, the dedup
  degrades gracefully (errors render individually) — never wrong, just
  noisier.
- **`ruyaml` returns `CommentedMap` instead of `dict`.** Pydantic's
  `model_validate` accepts any mapping; we already use ruyaml-loaded data in
  parts of the codebase without issue.
