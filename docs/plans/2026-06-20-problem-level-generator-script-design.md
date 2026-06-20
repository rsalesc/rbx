# Problem-level `generatorScript` default (issue #599)

## Goal

Add a problem-level `generatorScript` field to `problem.rbx.yml`. When set, any test
group **or subgroup** that does not specify its own test parameters
(`testcases`, `testcaseGlob`, `generators`, `generatorScript`) inherits this script as a
default. This removes the need to repeat `generatorScript` on every group when a single
shared script (typically partitioned with `@testgroup` blocks) drives all generation.

## Decisions

- **Inheritance scope:** all groups *and* subgroups with zero test parameters inherit the
  package default (uniform rule in the extractor).
- **Validation:** keep the current permissive behavior. `_check_oneof` already allows zero
  test parameters per (sub)group; the package default does not conflict, so no new
  hard-error validation is added. A group with no source and no package default remains a
  silent no-op, as today.

## Design

### 1. Schema (`rbx/box/schema.py`, `Package`)

Add an optional field, mirroring the existing problem-level defaults (`validator`,
`visualizer`):

```python
generatorScript: Optional[GeneratorScript] = Field(
    default=None,
    description='A generator script used as the default for any test group or subgroup '
    'that does not specify its own test parameters.',
)
```

No change to `_check_oneof` (it only forbids setting more than one source on a single
(sub)group; the package default is orthogonal).

### 2. Inheritance (`rbx/box/testcase_extractors.py`)

In `run_testcase_visitor._explore_subgroup`, resolve an *effective* script before the
existing generator-script block:

```python
effective_gs = subgroup.generatorScript
if effective_gs is None and not (
    subgroup.testcases or subgroup.testcaseGlob
    or subgroup.generators or subgroup.generatorScript
):
    effective_gs = pkg.generatorScript  # closure over pkg; may be None
```

The existing block then uses `effective_gs` instead of `subgroup.generatorScript`.
`run_generator_script` is refactored to accept a `GeneratorScript` entry plus a name (its
only caller is internal). The `@testgroup` filter key stays `group_path` (unchanged).

This follows the existing precedent in the same function, where `pkg.validator` and
`pkg.visualizer` are inherited into groups.

### 3. Known limitations (tracked as follow-ups)

- **#600** — `@testgroup` cannot target subgroups (parser uses a flat group name; extractor
  filters subgroup runs by the parent group name). Sibling subgroups inheriting a shared
  script therefore receive identical filtered lines.
- **#601** — `rbx add-tests` and promotion operate on explicit per-group scripts only, not
  inherited ones.

## Testing

- `tests/rbx/box/testcase_extractors_test.py`: group inherits the package script; subgroup
  inherits; group/subgroup with its own params overrides (no inheritance); no package
  script means no inheritance (silent).
- Schema round-trip test for the new field.

## Out of scope

Subgroup-targeted `@testgroup` filtering (#600) and edit/promotion of inherited scripts
(#601).
