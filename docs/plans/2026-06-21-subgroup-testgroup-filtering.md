# Subgroup-level `@testgroup` filtering — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let a single (often problem-level / inherited) generator script route distinct testcases to distinct *subgroups* via path-qualified `@testgroup group/subgroup { ... }`.

**Architecture:** Carry the `@testgroup` annotation as a `/`-joined path on `GenerationInput.group` (type unchanged, `Optional[str]`). The script parser gains path syntax (inline `a/b` and nested-concatenation) plus segment validation. The handler's group filter changes from string-equality to a **prefix-path predicate** (`A` matches key `K` ⟺ `A is None or K == A or K.startswith(A + '/')`). The extractor passes the full `subgroup_path` (e.g. `main/sub1`) as the filter key instead of the parent group name. Group-level behavior is byte-for-byte unchanged.

**Tech Stack:** Python 3.12, Lark grammar, Pydantic v2, pytest (`uv run pytest`), ruff, e2e YAML DSL under `tests/e2e/`.

**Design doc:** `docs/plans/2026-06-21-subgroup-testgroup-filtering-design.md`

**Conventions:** single quotes; absolute imports; commit via the `/commit` workflow in `.claude/skills/commit.md` (conventional commits; co-author trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`). Run tests with `uv run pytest`.

---

## Task 1: Parser — path-qualified `@testgroup` (inline + nested concat + validation)

**Files:**
- Modify: `rbx/box/stressing/generator_script_parser.py`
- Test: `tests/rbx/box/stressing/test_generator_script_parser.py`

### Step 1: Update the two existing nested tests and add new ones (failing)

In `tests/rbx/box/stressing/test_generator_script_parser.py`:

**(a) Update** `test_parse_and_transform_nested_testgroups` (≈ line 496). The inner statement's group must now be the **concatenated path**:

```python
    def test_parse_and_transform_nested_testgroups(self):
        """Nested testgroups concatenate into a path (outer/inner)."""
        script = """
@testgroup outer {
    gens/gen1 --X=1
    @testgroup inner {
        gens/gen2 --Y=2
    }
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2
        assert result[0].group == 'outer'
        assert result[0].generator_call is not None
        assert result[0].generator_call.name == 'gens/gen1'
        assert result[1].group == 'outer/inner'
        assert result[1].generator_call is not None
        assert result[1].generator_call.name == 'gens/gen2'
```

**(b) Replace** `test_parse_and_transform_nested_testgroups_inner_takes_precedence` (≈ line 520) with a concat assertion (rename it):

```python
    def test_parse_and_transform_nested_testgroups_build_path(self):
        """A nested testgroup builds a full path from outer to inner."""
        script = """
@testgroup outer {
    @testgroup inner {
        gens/gen1 --X=1
    }
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].group == 'outer/inner'
```

**(c) Add** these new tests (anywhere alongside the testgroup tests):

```python
    def test_parse_and_transform_inline_subgroup_path(self):
        """An inline `group/subgroup` path is carried verbatim on .group."""
        script = """
@testgroup main/sub1 {
    gens/gen1 --X=1
}
"""
        result = parse_and_transform(script, pathlib.Path('s.txt'))
        assert len(result) == 1
        assert result[0].group == 'main/sub1'

    def test_parse_and_transform_inline_path_then_nested_concats(self):
        """An inline path nested under another group concatenates fully."""
        script = """
@testgroup a {
    @testgroup b/c {
        gens/gen1 1
    }
}
"""
        result = parse_and_transform(script, pathlib.Path('s.txt'))
        assert len(result) == 1
        assert result[0].group == 'a/b/c'

    def test_parse_and_transform_deep_path_allowed_syntactically(self):
        """Paths deeper than rbx's 2-level model parse fine (they just match nothing)."""
        script = '@testgroup a/b/c {\n    gens/gen1 1\n}\n'
        result = parse_and_transform(script, pathlib.Path('s.txt'))
        assert len(result) == 1
        assert result[0].group == 'a/b/c'

    def test_parse_and_transform_untagged_lines_have_no_group(self):
        """Top-level (untagged) statements keep group == None."""
        script = 'gens/gen1 1\n@testgroup main/sub1 {\n    gens/gen2 2\n}\n'
        result = parse_and_transform(script, pathlib.Path('s.txt'))
        assert result[0].group is None
        assert result[1].group == 'main/sub1'

    @pytest.mark.parametrize('bad', ['main/', 'main//sub', 'a/b/'])
    def test_parse_and_transform_rejects_malformed_path(self, bad):
        """Empty path segments are rejected with a clear error."""
        script = f'@testgroup {bad} {{\n    gens/gen1 1\n}}\n'
        with pytest.raises(ValueError, match='Invalid @testgroup path'):
            parse_and_transform(script, pathlib.Path('s.txt'))

    def test_parse_and_transform_rejects_leading_slash_path(self):
        """A leading-slash path is rejected at parse time."""
        script = '@testgroup /sub {\n    gens/gen1 1\n}\n'
        with pytest.raises(Exception):
            parse_and_transform(script, pathlib.Path('s.txt'))

    def test_statement_spans_path_qualified_testgroup(self):
        """statement_spans descends into a path-qualified testgroup (round-trip safety)."""
        from rbx.box.stressing.generator_script_parser import statement_spans

        script = '@testgroup g/s {\ngens/a 1\n@input "x"\n}\n'
        spans = statement_spans(script)
        kinds = [s.kind for s in spans]
        assert 'testgroup' not in kinds
        assert 'generator_call' in kinds and 'inline_input' in kinds
```

Ensure `import pytest` is present at the top of the file (it already imports pytest for other tests; confirm).

### Step 2: Run to verify failure

Run: `uv run pytest tests/rbx/box/stressing/test_generator_script_parser.py -q`
Expected: the new path/malformed tests FAIL (lark cannot tokenize `/` in `GROUP_NAME`; e.g. `UnexpectedCharacters`), and the two edited nested tests FAIL on the old `inner` value.

### Step 3: Implement parser changes

In `rbx/box/stressing/generator_script_parser.py`:

**(a)** Add `import re` near the top (after `import pathlib`).

**(b)** Broaden the `GROUP_NAME` token (≈ line 57) so path-like and trailing/double-slash tokens reach the transformer for a clear error (leading `/` is still rejected at tokenize time):

```
GROUP_NAME: /[a-zA-Z0-9][a-zA-Z0-9\-_\/]*/
```

**(c)** Update the `ScriptGeneratedInput.group` docstring/comment (≈ line 13-16):

```python
class ScriptGeneratedInput(GenerationInput):
    """Input generated from a generator script with optional group annotation.

    ``group`` is a ``/``-joined path (e.g. ``group`` or ``group/subgroup``)
    built from inline and/or nested ``@testgroup`` blocks, or ``None`` for
    untagged statements.
    """

    group: Optional[str] = None
```

**(d)** Add a module-level validator (just above the `TestPlanTransformer` class):

```python
_GROUP_PATH_SEGMENT = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9\-_]*$')


def _validate_group_path(path: str) -> None:
    """Validate a `/`-joined @testgroup path; raise on empty/malformed segments."""
    if not all(_GROUP_PATH_SEGMENT.match(seg) for seg in path.split('/')):
        raise ValueError(
            f'Invalid @testgroup path: {path!r}. Each `/`-separated segment '
            f'must be non-empty and match [a-zA-Z0-9][a-zA-Z0-9-_]*.'
        )
```

**(e)** Rewrite the body of the `testgroup` transformer (≈ lines 207-229) to validate and concatenate:

```python
        # First child is TESTGROUP_KEYWORD (@testgroup), second is the group path.
        group_name = str(children[1])
        _validate_group_path(group_name)

        # Rest are statements (can include nested testgroups).
        statements = children[2:]

        # Flatten and assign/extend the group path.
        result = []
        for stmt in statements:
            if stmt is None:
                continue
            elif isinstance(stmt, list):
                # Nested testgroup returns a list whose items already carry the
                # inner path; prefix this level's name to build the full path.
                for nested_stmt in stmt:
                    nested_stmt.group = (
                        group_name
                        if nested_stmt.group is None
                        else f'{group_name}/{nested_stmt.group}'
                    )
                    result.append(nested_stmt)
            elif isinstance(stmt, ScriptGeneratedInput):
                # Direct statement (always group=None here).
                if stmt.group is None:
                    stmt.group = group_name
                result.append(stmt)

        return result
```

### Step 4: Run to verify pass

Run: `uv run pytest tests/rbx/box/stressing/test_generator_script_parser.py -q`
Expected: PASS (all, including edited nested tests). Then run the spans helper test file is included above.

### Step 5: Commit

```bash
git add rbx/box/stressing/generator_script_parser.py tests/rbx/box/stressing/test_generator_script_parser.py
git commit -m "$(cat <<'EOF'
feat(testset): parse path-qualified @testgroup group/subgroup (#600)

Carry a `/`-joined path on GenerationInput.group, built from inline
`@testgroup a/b` and nested concatenation, with segment validation.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Handler — prefix-path group filter

**Files:**
- Modify: `rbx/box/generator_script_handlers.py`
- Test: `tests/rbx/box/test_generator_script_handlers.py`

### Step 1: Write the failing test

Add to `tests/rbx/box/test_generator_script_handlers.py` (inside `class TestRbxGeneratorScriptHandler`):

```python
    def _routed_args(self, group):
        from rbx.box.generator_script_handlers import RbxGeneratorScriptHandler

        script_entry = GeneratorScript(path=pathlib.Path('s.txt'), format='rbx')
        script = (
            'gen0 untagged\n'
            '@testgroup g {\n  gen1 g-only\n}\n'
            '@testgroup g/s1 {\n  gen2 s1-only\n}\n'
            '@testgroup g/s2 {\n  gen3 s2-only\n}\n'
        )
        handler = RbxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry, group)
        )
        return [inp.generator_call.args for inp in handler.parse()]

    def test_prefix_filter_subgroup_key_routes_distinctly(self):
        # Subgroup g/s1: untagged + parent-group-tagged + its own path; NOT g/s2.
        assert self._routed_args('g/s1') == ['untagged', 'g-only', 's1-only']
        assert self._routed_args('g/s2') == ['untagged', 'g-only', 's2-only']

    def test_prefix_filter_group_key_excludes_subgroup_lines(self):
        # Group g (no subgroup in key): untagged + g-only only; path lines dropped.
        assert self._routed_args('g') == ['untagged', 'g-only']

    def test_prefix_filter_none_group_returns_all(self):
        assert self._routed_args(None) == [
            'untagged',
            'g-only',
            's1-only',
            's2-only',
        ]
```

### Step 2: Run to verify failure

Run: `uv run pytest tests/rbx/box/test_generator_script_handlers.py -q -k prefix_filter`
Expected: FAIL — current equality filter (`inp.group == self.group`) drops `g-only` for key `g/s1` and never includes path lines.

### Step 3: Implement the prefix-path predicate

In `rbx/box/generator_script_handlers.py`, add a module-level helper (above `class GeneratorScriptHandler`):

```python
def _group_matches(annotation: Optional[str], key: str) -> bool:
    """Whether a line's @testgroup `annotation` applies to run-key `key`.

    Untagged lines (None) always match. Otherwise the annotation must equal the
    key or be a path-prefix of it, so a parent-group tag flows into its
    subgroups while a sibling subgroup's tag does not.
    """
    if annotation is None:
        return True
    return key == annotation or key.startswith(annotation + '/')
```

Replace the filter in `RbxGeneratorScriptHandler.parse()` (≈ lines 60-63):

```python
        if self.group is not None:
            inputs = [inp for inp in inputs if _group_matches(inp.group, self.group)]
```

### Step 4: Run to verify pass

Run: `uv run pytest tests/rbx/box/test_generator_script_handlers.py -q`
Expected: PASS.

### Step 5: Commit

```bash
git add rbx/box/generator_script_handlers.py tests/rbx/box/test_generator_script_handlers.py
git commit -m "$(cat <<'EOF'
feat(testset): prefix-path @testgroup filtering in script handler (#600)

A line's @testgroup annotation now matches a run-key when it equals the
key or is a path-prefix of it, so parent-group tags flow into subgroups
while sibling-subgroup tags do not.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Extractor — pass the full subgroup path as the filter key

**Files:**
- Modify: `rbx/box/testcase_extractors.py` (≈ line 306-308)
- Test: `tests/rbx/box/testcase_extractors_test.py`

### Step 1: Write the failing test

Add to `tests/rbx/box/testcase_extractors_test.py` (in the same class as `test_subgroup_inherits_problem_level_generator_script`, mirroring its setup):

```python
    async def test_shared_script_routes_distinct_testcases_to_subgroups(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A shared problem-level script routes path-qualified lines to the
        matching subgroup only; untagged lines still flow to every subgroup."""
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')
        plan_path = testing_pkg.add_testplan('shared')
        plan_path.write_text(
            'gen1 shared\n'
            '@testgroup main/sub1 {\n  gen1 s1\n}\n'
            '@testgroup main/sub2 {\n  gen1 s2\n}\n'
        )
        testing_pkg.yml.generatorScript = GeneratorScript(path=plan_path)
        testing_pkg.add_testgroup_with_subgroups(
            'main', [{'name': 'sub1'}, {'name': 'sub2'}]
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        await run_testcase_visitor(CollectingVisitor())

        sub1 = [e for e in visited_entries if e.subgroup_entry.group == 'main/sub1']
        sub2 = [e for e in visited_entries if e.subgroup_entry.group == 'main/sub2']

        # Untagged line reaches both (back-compat); path line reaches one only.
        assert [e.metadata.generator_call.args for e in sub1] == ['shared', 's1']
        assert [e.metadata.generator_call.args for e in sub2] == ['shared', 's2']
        # No sibling cross-contamination.
        assert all(
            e.metadata.generator_call.args != 's2'
            for e in sub1
        )
        assert all(
            e.metadata.generator_call.args != 's1'
            for e in sub2
        )
```

### Step 2: Run to verify failure

Run: `uv run pytest tests/rbx/box/testcase_extractors_test.py -q -k shared_script_routes`
Expected: FAIL — the extractor still passes `group_path` (`main`) as the filter key, so the prefix predicate drops `@testgroup main/sub1` / `main/sub2`, and both subgroups see only `['shared']`.

### Step 3: Implement the one-line key change

In `rbx/box/testcase_extractors.py`, in `_explore_subgroup`, change the script-run loop (≈ line 306-308) to use the full path key (`subgroup_path` is already computed as `'/'.join(prefix)` at ≈ line 194):

```python
            # Run each line from generator script. Pass the FULL subgroup path
            # (e.g. `main/sub1`) so path-qualified @testgroup lines route to the
            # matching subgroup; at the group level this equals `group_path`.
            for generation_input in _extract_script_lines(
                script, effective_generator_script, subgroup_path
            ):
```

### Step 4: Run to verify pass + no regression

Run: `uv run pytest tests/rbx/box/testcase_extractors_test.py -q`
Expected: PASS (new test and all existing extractor tests, including `test_subgroup_inherits_problem_level_generator_script` which uses an untagged script and is unaffected).

### Step 5: Commit

```bash
git add rbx/box/testcase_extractors.py tests/rbx/box/testcase_extractors_test.py
git commit -m "$(cat <<'EOF'
feat(testset): route generator-script lines by full subgroup path (#600)

Pass the full `group/subgroup` path as the script filter key so a shared
script routes path-qualified @testgroup lines to distinct subgroups.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: e2e fixture — problem-level script partitioned across groups AND subgroups

**Files (create a new package, mirroring `tests/e2e/testdata/simple-ac/`):**
- Create: `tests/e2e/testdata/subgroup-script-partition/problem.rbx.yml`
- Create: `tests/e2e/testdata/subgroup-script-partition/testplan.txt`
- Create: `tests/e2e/testdata/subgroup-script-partition/sols/main.cpp`
- Create: `tests/e2e/testdata/subgroup-script-partition/e2e.rbx.yml`

> Inputs are integer pairs so the trivial `main.cpp` (reads `a b`, prints `a+b`) generates outputs and the default checker is satisfied during `build`.

### Step 1: Create the package files

`problem.rbx.yml`:

```yaml
name: subgroup-script-partition
timeLimit: 1000
memoryLimit: 256

solutions:
  - path: sols/main.cpp
    outcome: ac

generatorScript:
  path: testplan.txt

testcases:
  - name: g1
  - name: g2
    subgroups:
      - name: s1
      - name: s2
```

`testplan.txt`:

```
@input "10 20"
@testgroup g1 {
    @input "11 11"
}
@testgroup g2/s1 {
    @input "21 21"
}
@testgroup g2/s2 {
    @input "22 22"
}
```

`sols/main.cpp` (copy from `tests/e2e/testdata/simple-ac/sols/main.cpp`):

```cpp
#include <iostream>
using namespace std;

int main() {
    int a, b;
    cin >> a >> b;
    cout << a + b << endl;
    return 0;
}
```

`e2e.rbx.yml`:

```yaml
scenarios:
  - name: partition
    description: >
      A problem-level generatorScript inherited by an empty group (g1) and by
      the subgroups (s1, s2) of a group with subgroups (g2). The untagged line
      flows to every group/subgroup (back-compat); path-qualified @testgroup
      lines route to exactly one subgroup, so siblings never duplicate.
    steps:
      - cmd: build
        expect:
          tests:
            count: 6
            groups:
              g1: 2
              g2: 4
            exist:
              - g1/000.in
              - g1/001.in
              - g2/1-s1-000.in
              - g2/1-s1-001.in
              - g2/2-s2-000.in
              - g2/2-s2-001.in
          file_contains:
            "build/tests/g1/001.in": "11 11"
            "build/tests/g2/1-s1-001.in": "21 21"
            "build/tests/g2/2-s2-001.in": "22 22"
```

> **Routing rationale (verify if counts differ):** g1 inherits at group level (key `g1`) → untagged + `@testgroup g1` = 2. g2 has subgroups so the parent skips the inherited script; s1 (key `g2/s1`) → untagged + `g2/s1` = 2 files (`1-s1-000.in`=`10 20`, `1-s1-001.in`=`21 21`); s2 (key `g2/s2`) → untagged + `g2/s2` = 2 files. `build/tests/g2/` therefore holds 4 files with no duplicated sibling content. The exact per-subgroup count (2 each) + the `file_contains` distinct-content checks together prove no cross-sibling duplication.

### Step 2: Run the e2e scenario

Run: `uv run pytest 'tests/e2e/testdata/subgroup-script-partition/e2e.rbx.yml::partition' -v`
(Or discover the exact node id with `uv run pytest tests/e2e/testdata/subgroup-script-partition/ --collect-only -q`.)
Expected: PASS. If file prefixes/counts differ from the rationale, re-derive from the actual `build/tests/` tree (run `uv run rbx build` inside a copy and inspect) and adjust `exist`/`groups`/`file_contains` — do **not** weaken the no-duplication assertion.

### Step 3: Confirm the package builds clean standalone (per e2e README)

Run (in a throwaway copy or rely on the e2e tmpdir isolation): `uv run pytest tests/e2e/testdata/subgroup-script-partition/ -q`
Expected: PASS.

### Step 4: Commit

```bash
git add tests/e2e/testdata/subgroup-script-partition/
git commit -m "$(cat <<'EOF'
test(testset): e2e for subgroup-partitioned generatorScript (#600)

Problem-level script inherited across a plain group and a group's
subgroups; asserts path-qualified @testgroup lines route to distinct
subgroups with no duplicated testcases across siblings.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Full verification sweep

**No new files — verification only.**

### Step 1: Run the targeted suites

Run:
```bash
uv run pytest \
  tests/rbx/box/stressing/test_generator_script_parser.py \
  tests/rbx/box/test_generator_script_handlers.py \
  tests/rbx/box/testcase_extractors_test.py -q
```
Expected: all PASS.

### Step 2: Run the e2e suite (non-docker)

Run: `mise run test-e2e` (or at minimum `uv run pytest tests/e2e/testdata/subgroup-script-partition/ tests/e2e/testdata/simple-ac/ -q`).
Expected: PASS (the new scenario + an untouched neighbor as a sanity check).

### Step 3: Lint & format

Run:
```bash
uv run ruff check rbx/box/stressing/generator_script_parser.py rbx/box/generator_script_handlers.py rbx/box/testcase_extractors.py
uv run ruff format --check rbx/box/stressing/generator_script_parser.py rbx/box/generator_script_handlers.py rbx/box/testcase_extractors.py
```
Expected: no errors (run `uv run ruff format .` on touched files if needed).

### Step 4: Broader regression check (generator/testset area)

Run: `uv run pytest tests/rbx/box -q -k "generator or testcase or extractor or script"`
Expected: PASS. Investigate any failure that touches generator-script/testcase paths; ignore pre-existing unrelated failures noted in project memory (C++/sandbox/docker/walltime/completion-drift).

### Step 5: Final commit (only if Step 3 reformatted anything)

```bash
git add -u
git commit -m "$(cat <<'EOF'
style(testset): ruff format for subgroup @testgroup filtering (#600)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Notes / non-goals

- **No Pydantic model change.** `GenerationInput.group` stays `Optional[str]`; it just holds a `/`-joined path now.
- **Back-compat is structural:** at the group level the filter key equals the old `group_path`, and the prefix predicate reduces to today's behavior for scripts without path-qualified tags.
- **Unknown/over-deep paths** (`@testgroup g/nope`, `a/b/c`) parse fine and simply match nothing — consistent with how filtered-out lines behave today. Surfacing a warning for paths that match no real subgroup is a possible follow-up, out of scope here.
- The handler's `GeneratorScriptHandlerParams.group` field keeps its name (semantics widened to "full path key") to avoid churn in `promotion.py` / `cli.py`, which pass no group.
```
