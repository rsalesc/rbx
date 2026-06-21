# `add-tests` & promotion for inherited `generatorScript` (issue #601)

## Goal

Make the script-editing commands aware of the **inherited** problem-level
`generatorScript` introduced in #599. Today both flows enumerate only explicit,
per-group `generatorScript` entries, so a (sub)group that relies on the inherited
default (`group.generatorScript is None`) is invisible:

- **`add-tests`** (stress findings → group, `rbx/box/cli.py`): the target list is
  built from `group.generatorScript is not None and …suffix == '.txt'`.
- **Promotion** (`rbx testcases promote`, `rbx/box/promotion.py`):
  `script_format_by_path()` and `remove_script_entries()` only register explicit
  group scripts, so `is_promotable()` rejects inherited-script tests (and removal
  would hit its `assert path in script_entry_by_path`).

This builds on #600/#604, where `@testgroup` annotations became **path-qualified**
(`@testgroup main/sub1`) and a line matches a run-key `K` iff its annotation is
`None`, equals `K`, or is a path-prefix of `K` (`_group_matches`). The run-key is
the full `group` or `group/subgroup` path. A leaf (sub)group with zero test
parameters inherits `pkg.generatorScript`; a group that *has* subgroups does not
(its subgroups do).

## Decisions

- **Semantics: operate on the shared script, scoped by `@testgroup` (Option A).**
  Given `@testgroup` scoping (#600), appending a line wrapped/placed so it matches
  only the chosen run-key keeps per-(sub)group edits isolated *without* duplicating
  the shared script into per-group files or mutating `problem.rbx.yml`. This is
  faithful to why a problem-level default is set in the first place (a single
  shared script). We do **not** materialize per-group copies (issue's Option B).
- **add-tests picker granularity: run-key (group *and* subgroup).** Each leaf
  (sub)group with an effective rbx `.txt` script is a candidate, labelled by its
  full path. For the common no-subgroup case this reads as `<group> @ script:line`.
- **No-block case: append at top level when the script is exclusive to the
  run-key, otherwise create a scoped `@testgroup <run-key>` block.** Exclusive =
  no other run-key shares that effective script, so a top-level append affects only
  that run-key.
- **Promotion safety rule (per #601 comment): a line is promotable iff removing it
  affects only its own run-key.** Formally, among the run-keys sharing the line's
  effective script, the set matched by the line's annotation must be exactly
  `{entry run-key}`. Applied uniformly (explicit and inherited scripts); a no-op
  for the common single-group explicit script.
- **Scope: rbx-format `.txt` scripts.** Box-format and manual-group paths are
  untouched (box already cannot be edited line-by-line / removed).

## Design

### 1. Shared effective-script resolution (`rbx/box/testcase_extractors.py`)

Extract the inline inheritance logic (currently `_explore_subgroup`, ~L288-297)
into one reusable helper, and a traversal over every leaf run-key:

```python
def effective_generator_script(
    subgroup: TestcaseSubgroup, pkg: Package
) -> Optional[GeneratorScript]:
    """Own ``generatorScript`` else the inherited problem-level default."""
    if subgroup.generatorScript is not None:
        return subgroup.generatorScript
    if subgroup.testcases or subgroup.testcaseGlob or subgroup.generators \
            or getattr(subgroup, 'subgroups', None):
        return None
    return pkg.generatorScript

def iter_effective_scripts() -> Iterable[Tuple[str, GeneratorScript]]:
    """(run_key, effective script) for each leaf (sub)group, mirroring the
    visitor's traversal (group itself, then each subgroup)."""
```

`_explore_subgroup` switches to `effective_generator_script(...)` (no behavior
change). Derived views used by the editing flows:

- `runkeys_by_script_path: Dict[Path, Set[str]]`
- format lookup over effective scripts (replaces the explicit-only
  `script_format_by_path`).

### 2. `@testgroup` block enumeration + insertion

**Parser (`rbx/box/stressing/generator_script_parser.py`).** Add:

```python
@dataclass
class TestgroupBlock:
    path: str        # full @testgroup path, e.g. 'main' or 'main/sub1'
    start_line: int  # line of the `@testgroup` keyword (1-indexed)
    end_line: int    # line of the matching closing `}`

def testgroup_blocks(script: str) -> List[TestgroupBlock]: ...
```

Walk `testgroup` tree nodes (positions via `propagate_positions`), threading the
nested-path prefix to build `path`; resolve `end_line` by a brace-depth text scan
from `start_line` (robust to lark filtering the `_RBRACE`).

**Handler (`rbx/box/generator_script_handlers.py`).** Add to
`RbxGeneratorScriptHandler` an insertion API that either inserts calls inside an
existing block (before its `}`, indented to match) or appends a new
`@testgroup <path> { … }` block, plus the existing top-level `append` for the
exclusive case. The optional leading `# comment` is preserved.

### 3. add-tests flow (`rbx/box/cli.py`)

Replace the explicit-only `groups_by_name` with candidates from
`iter_effective_scripts()` (rbx `.txt` only). For each run-key `K` / script `S`:

- one entry per existing `@testgroup` block whose **full path == `K`**:
  `K @ relpath(S):<start_line>` → insert into that block;
- one `K @ relpath(S) (new block)` / top-level entry → create a scoped block, or
  append top-level when `runkeys_by_script_path[S] == {K}` (exclusive).

Manual groups, `(create new script)`, `(create new manual group)`, `(skip)` are
unchanged.

### 4. Promotion flow (`rbx/box/promotion.py`, `rbx/box/testcases/main.py`)

- `script_format_by_path()` → format map over **effective** scripts (includes the
  inherited problem-level path).
- `remove_script_entries()` → build its path registry from effective scripts, so
  the inherited path is found; removal logic (path+line) is otherwise unchanged.
- `is_promotable(entry, …)` → keep existing gates (has `generator_script`, not
  `@copy`, `.txt`, format `rbx`) and add the **safety gate**:

  ```python
  S = entry.metadata.generator_script.path
  A = annotation_of_line(S, line)         # the line's @testgroup path or None
  affected = {k for k in runkeys_by_script_path[S] if _group_matches(A, k)}
  return affected == {entry.subgroup_entry.group}
  ```

- `_non_promotable_reason()` gains a "would also affect other test groups" message.

## Testing

- **Unit** — parser `testgroup_blocks` (flat, nested, path-qualified, empty block);
  handler insert-into-block / create-block / top-level append; `iter_effective_scripts`
  and `runkeys_by_script_path`; `is_promotable` safety matrix:
  named-block-scoped = safe, top-level-shared = unsafe, top-level-exclusive = safe,
  parent-tag into sibling subgroups = unsafe, subgroup-qualified block = safe.
- **Integration (CLI)** — add-tests inserts into an inherited script's block and
  creates a scoped block; promote removes the correct inherited line; promote is
  blocked with the reason when unsafe. Reuse `tests/rbx/box/promotion_test.py`,
  `tests/rbx/box/test_stress_promote.py`, `tests/rbx/box/testcases/test_promote.py`.
- **e2e** — new `tests/e2e/` fixture: problem-level `generatorScript` partitioned
  by `@testgroup`, exercising stress-add + promote.

## Out of scope

- Materialize-on-edit (Option B), per-group script forking.
- Box-format script editing/removal (unchanged).
- Editing inherited scripts that are compiled programs (non-`.txt`); already
  excluded by the `.txt` gate.
