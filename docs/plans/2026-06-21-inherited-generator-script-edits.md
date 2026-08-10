# Inherited `generatorScript` edits — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `rbx add-tests` (stress findings → group) and `rbx testcases promote` work for test groups/subgroups that inherit the problem-level `generatorScript` (#599/#601), with `@testgroup`-scoped edits and a promotion safety gate.

**Architecture:** One shared effective-script resolver (own script else inherited `pkg.generatorScript`) drives both flows. add-tests enumerates `@testgroup` blocks per run-key and inserts scoped lines; promotion registers the inherited path and only allows removals whose effect is confined to a single run-key. All edits stay in the single shared script — no per-group materialization, no `problem.rbx.yml` mutation for inherited scripts.

**Tech Stack:** Python 3, Pydantic v2, Typer, pytest, lark (DSL parser). Single quotes, absolute imports, ruff.

Background facts (origin/main, post-#604):
- `@testgroup` paths are `/`-qualified; `_group_matches(annotation, key)` in `rbx/box/generator_script_handlers.py` is `annotation is None or key == annotation or key.startswith(annotation + '/')`. Run-key = full `group` or `group/subgroup` path.
- Leaf (sub)groups with zero test params inherit `pkg.generatorScript`; a group with subgroups does not.
- Parser uses `propagate_positions=True`; `statement_spans()` already walks the tree.

Run tests with `uv run pytest`. Lint with `uv run ruff check . && uv run ruff format .`. Commit with the conventional-commits format (`docs(...)`, `feat(...)`, `refactor(...)`, `test(...)`), ending every message with:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: Shared effective-script resolver

**Files:**
- Modify: `rbx/box/testcase_extractors.py` (inline inheritance at ~L288-297, inside `_explore_subgroup`)
- Test: `tests/rbx/box/testcase_extractors_test.py`

**Step 1: Write the failing test** — add to `testcase_extractors_test.py`:

```python
async def test_iter_effective_scripts_covers_inherited_and_explicit(
    self, testing_pkg: testing_package.TestingPackage
):
    testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')
    shared = testing_pkg.add_testplan('shared')
    shared.write_text('@testgroup inherits { gen1 1 }\n')
    testing_pkg.yml.generatorScript = GeneratorScript(path=shared)
    testing_pkg.yml.testcases = testing_pkg.yml.testcases + [
        TestcaseGroup(name='inherits'),
    ]
    own = testing_pkg.add_testplan('own')
    own.write_text('gen1 2\n')
    testing_pkg.yml.testcases = testing_pkg.yml.testcases + [
        TestcaseGroup(name='explicit', generatorScript=GeneratorScript(path=own)),
    ]
    testing_pkg.save()

    from rbx.box.testcase_extractors import iter_effective_scripts
    mapping = {rk: gs.path for rk, gs in iter_effective_scripts()}

    assert mapping['inherits'] == shared
    assert mapping['explicit'] == own
```

**Step 2: Run, expect ImportError/fail**

Run: `uv run pytest tests/rbx/box/testcase_extractors_test.py -k iter_effective_scripts -x -q`
Expected: FAIL (`cannot import name 'iter_effective_scripts'`).

**Step 3: Implement.** In `rbx/box/testcase_extractors.py`, add module-level helpers and refactor `_explore_subgroup` to call `effective_generator_script`:

```python
def effective_generator_script(
    subgroup: TestcaseSubgroup, pkg: Package
) -> Optional[GeneratorScript]:
    """The (sub)group's own ``generatorScript`` else the inherited package default.

    A (sub)group with any test parameters of its own -- ``testcases``,
    ``testcaseGlob``, ``generators`` -- or with subgroups does NOT inherit.
    """
    if subgroup.generatorScript is not None:
        return subgroup.generatorScript
    if (
        subgroup.testcases
        or subgroup.testcaseGlob
        or subgroup.generators
        or getattr(subgroup, 'subgroups', None)
    ):
        return None
    return pkg.generatorScript


def iter_effective_scripts() -> Iterable[Tuple[str, GeneratorScript]]:
    """Yield ``(run_key, effective script)`` for each leaf (sub)group that
    resolves to a generator script, mirroring the visitor's traversal: the group
    itself (run-key ``group``) then each subgroup (run-key ``group/subgroup``).
    """
    pkg = package.find_problem_package_or_die()
    for group in pkg.testcases:
        gs = effective_generator_script(group, pkg)
        if gs is not None:
            yield group.name, gs
        for subgroup in group.subgroups:
            sub_gs = effective_generator_script(subgroup, pkg)
            if sub_gs is not None:
                yield f'{group.name}/{subgroup.name}', sub_gs
```

Replace the inline block in `_explore_subgroup` (~L288-297) with:

```python
        effective_generator_script_ = effective_generator_script(subgroup, pkg)
```

and use `effective_generator_script_` where `effective_generator_script` (the local) was used below (rename the local to avoid shadowing the new function). Add `Tuple` to the `typing` import if missing.

**Step 4: Run** — `uv run pytest tests/rbx/box/testcase_extractors_test.py -q`
Expected: PASS (new test + all existing inheritance tests).

**Step 5: Commit**

```bash
git add rbx/box/testcase_extractors.py tests/rbx/box/testcase_extractors_test.py
git commit -m "$(cat <<'EOF'
refactor(testset): extract effective_generator_script resolver (#601)

Single source of truth for own-else-inherited generatorScript, plus
iter_effective_scripts over every leaf run-key, reused by add-tests and
promotion. No behavior change in the visitor.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Parser — `@testgroup` block enumeration

**Files:**
- Modify: `rbx/box/stressing/generator_script_parser.py`
- Test: `tests/rbx/box/stressing/generator_script_parser_test.py` (create if absent; otherwise the existing parser test file)

**Step 1: Write failing tests:**

```python
from rbx.box.stressing import generator_script_parser as gsp

def test_testgroup_blocks_flat():
    script = 'gen 0\n@testgroup main {\n  gen 1\n}\n@testgroup other {\n  gen 2\n}\n'
    blocks = gsp.testgroup_blocks(script)
    paths = [(b.path, b.start_line) for b in blocks]
    assert ('main', 2) in paths
    assert ('other', 5) in paths

def test_testgroup_blocks_nested_path():
    script = '@testgroup a {\n  @testgroup b {\n    gen 1\n  }\n}\n'
    paths = {b.path for b in gsp.testgroup_blocks(script)}
    assert 'a' in paths and 'a/b' in paths

def test_testgroup_blocks_qualified_path():
    script = '@testgroup main/sub1 {\n  gen 1\n}\n'
    assert [b.path for b in gsp.testgroup_blocks(script)] == ['main/sub1']

def test_testgroup_blocks_end_line_is_closing_brace():
    script = '@testgroup main {\n  gen 1\n  gen 2\n}\n'
    (block,) = gsp.testgroup_blocks(script)
    assert block.start_line == 1
    assert block.end_line == 4  # the `}` line
```

**Step 2: Run, expect fail** — `uv run pytest tests/rbx/box/stressing/generator_script_parser_test.py -k testgroup_blocks -x -q` → FAIL.

**Step 3: Implement** in `generator_script_parser.py`:

```python
@dataclasses.dataclass
class TestgroupBlock:
    path: str        # full @testgroup path, e.g. 'main' or 'a/b'
    start_line: int  # line of the `@testgroup` keyword (1-indexed)
    end_line: int    # line of the matching closing `}` (1-indexed)


def _closing_brace_line(lines: List[str], start_line: int) -> int:
    """Line (1-indexed) of the `}` closing the block whose `{` is on/after
    ``start_line``; brace-depth scan that ignores braces inside strings is not
    needed here (rbx blocks contain only statements/comments)."""
    depth = 0
    seen_open = False
    for i in range(start_line - 1, len(lines)):
        for ch in lines[i]:
            if ch == '{':
                depth += 1
                seen_open = True
            elif ch == '}':
                depth -= 1
                if seen_open and depth == 0:
                    return i + 1
    return len(lines)


def testgroup_blocks(script: str) -> List[TestgroupBlock]:
    """All `@testgroup` blocks with their full `/`-joined path and line span."""
    tree = parse(script)
    lines = script.splitlines()
    blocks: List[TestgroupBlock] = []

    def walk(node, prefix: str):
        for child in node.children:
            if not isinstance(child, lark.Tree) or child.data != 'testgroup':
                continue
            name = str(child.children[1])
            full = name if not prefix else f'{prefix}/{name}'
            start = child.meta.line
            blocks.append(
                TestgroupBlock(
                    path=full,
                    start_line=start,
                    end_line=_closing_brace_line(lines, start),
                )
            )
            walk(child, full)

    walk(tree, '')
    blocks.sort(key=lambda b: b.start_line)
    return blocks
```

Note: a `@testgroup a/b` header's `GROUP_NAME` token is the literal `a/b`; nested concatenation builds `prefix/name`, matching the transformer's path semantics.

**Step 4: Run** — `uv run pytest tests/rbx/box/stressing/generator_script_parser_test.py -k testgroup_blocks -q` → PASS.

**Step 5: Commit** (`feat(testset): enumerate @testgroup blocks in generator scripts (#601)`).

---

### Task 3: Handler — block-scoped insertion

**Files:**
- Modify: `rbx/box/generator_script_handlers.py`
- Test: `tests/rbx/box/generator_script_handlers_test.py` (create if absent)

**Step 1: Write failing tests** (rbx handler; build with a `GeneratorScript` entry):

```python
import pathlib
from rbx.box import generator_script_handlers as gsh
from rbx.box.schema import GeneratorCall, GeneratorScript

def _handler(script):
    entry = GeneratorScript(path=pathlib.Path('p.txt'))
    return gsh.get_generator_script_handler(
        script, gsh.GeneratorScriptHandlerParams(entry)
    )

def test_append_in_block_inserts_before_closing_brace():
    h = _handler('@testgroup main {\n  gen 1\n}\n')
    h.append_in_block(1, [GeneratorCall(name='gen', args='2')], comment='added')
    assert h.script.splitlines() == [
        '@testgroup main {',
        '  gen 1',
        '  # added',
        '  gen 2',
        '}',
    ]

def test_append_new_block_creates_scoped_block():
    h = _handler('gen 0\n')
    h.append_new_block('main/sub1', [GeneratorCall(name='gen', args='9')])
    assert '@testgroup main/sub1 {' in h.script
    assert 'gen 9' in h.script.split('@testgroup main/sub1 {', 1)[1]

def test_append_top_level_unchanged():
    h = _handler('gen 0\n')
    h.append([GeneratorCall(name='gen', args='1')])
    assert h.script.rstrip().endswith('gen 1')
```

**Step 2: Run, expect fail.**

**Step 3: Implement** on `RbxGeneratorScriptHandler` in `generator_script_handlers.py`. Reuse `normalize_call_name`; indent inserted lines to match the block body:

```python
    def append_in_block(
        self,
        block_start_line: int,
        calls: List[GeneratorCall],
        comment: Optional[str] = None,
    ) -> None:
        from rbx.box.stressing import generator_script_parser as gsp

        block = next(
            (b for b in gsp.testgroup_blocks(self.script)
             if b.start_line == block_start_line),
            None,
        )
        if block is None:
            raise ValueError(f'No @testgroup block starts at line {block_start_line}.')
        lines = self.script.splitlines()
        # Indent to match the line above the closing brace, else 2 spaces.
        indent = '  '
        for ln in range(block.end_line - 2, block.start_line - 1, -1):
            stripped = lines[ln].rstrip()
            if stripped:
                indent = lines[ln][: len(lines[ln]) - len(lines[ln].lstrip())] or '  '
                break
        new_lines = []
        if comment:
            new_lines.append(f'{indent}# {comment}')
        for call in calls:
            name = self.normalize_call_name(call.name)
            new_lines.append(f'{indent}{name} {call.args or ""}'.rstrip())
        insert_at = block.end_line - 1  # before the `}` line (0-indexed)
        lines[insert_at:insert_at] = new_lines
        self.script = '\n'.join(lines) + ('\n' if self.script.endswith('\n') else '')

    def append_new_block(
        self,
        group_path: str,
        calls: List[GeneratorCall],
        comment: Optional[str] = None,
    ) -> None:
        body = []
        if comment:
            body.append(f'  # {comment}')
        for call in calls:
            name = self.normalize_call_name(call.name)
            body.append(f'  {name} {call.args or ""}'.rstrip())
        block = '\n'.join(
            [f'@testgroup {group_path} {{', *body, '}']
        )
        sep = '' if self.script.endswith('\n') or not self.script else '\n'
        self.script = f'{self.script}{sep}\n{block}\n'
```

**Step 4: Run** — `uv run pytest tests/rbx/box/generator_script_handlers_test.py -q` → PASS. Verify the existing top-level `append` is unchanged.

**Step 5: Commit** (`feat(testset): block-scoped insertion in rbx generator scripts (#601)`).

---

### Task 4: Promotion — effective-script awareness + isolation gate

**Files:**
- Modify: `rbx/box/promotion.py`
- Test: `tests/rbx/box/promotion_test.py`

**Step 1: Write failing tests.** Pure safety core (no I/O) + effective-script registration:

```python
def test_removal_affects_only_run_key_named_block_is_isolated():
    # annotation 'g1' affects only run-key 'g1' even when 'g2' shares the script.
    assert promotion.removal_affects_only_run_key('g1', 'g1', {'g1', 'g2'}) is True

def test_removal_affects_only_run_key_top_level_shared_not_isolated():
    assert promotion.removal_affects_only_run_key('g1', None, {'g1', 'g2'}) is False

def test_removal_affects_only_run_key_top_level_exclusive_is_isolated():
    assert promotion.removal_affects_only_run_key('g1', None, {'g1'}) is True

def test_removal_affects_only_run_key_parent_tag_bleeds_into_subgroups():
    # 'main' matches both subgroups -> removing it affects more than main/sub1.
    assert promotion.removal_affects_only_run_key(
        'main/sub1', 'main', {'main/sub1', 'main/sub2'}
    ) is False

def test_removal_affects_only_run_key_qualified_block_is_isolated():
    assert promotion.removal_affects_only_run_key(
        'main/sub1', 'main/sub1', {'main/sub1', 'main/sub2'}
    ) is True


def test_script_format_by_path_includes_inherited(
    testing_pkg: testing_package.TestingPackage,
):
    shared = testing_pkg.add_testplan('shared')
    shared.write_text('@testgroup g { gen 1 }\n')
    testing_pkg.yml.generatorScript = GeneratorScript(path=shared)
    testing_pkg.yml.testcases = testing_pkg.yml.testcases + [TestcaseGroup(name='g')]
    testing_pkg.save()

    formats = promotion.script_format_by_path()
    assert formats[shared] == 'rbx'
```

**Step 2: Run, expect fail.**

**Step 3: Implement** in `promotion.py`. Import `_group_matches`, `iter_effective_scripts`, and the parser. Reimplement the path-collecting helpers over effective scripts and add the gate:

```python
from rbx.box.generator_script_handlers import _group_matches
from rbx.box.testcase_extractors import iter_effective_scripts
from rbx.box.stressing import generator_script_parser as gsp


def script_format_by_path() -> Dict[pathlib.Path, str]:
    """Map each EFFECTIVE generator-script path (explicit or inherited) to its
    format ('rbx'/'box')."""
    res: Dict[pathlib.Path, str] = {}
    for _run_key, gs in iter_effective_scripts():
        res[gs.path] = gs.format
    return res


def run_keys_by_script_path() -> Dict[pathlib.Path, Set[str]]:
    """Map each effective script path to the set of run-keys using it."""
    res: Dict[pathlib.Path, Set[str]] = {}
    for run_key, gs in iter_effective_scripts():
        res.setdefault(gs.path, set()).add(run_key)
    return res


def removal_affects_only_run_key(
    run_key: str, annotation: Optional[str], run_keys: Set[str]
) -> bool:
    """True iff a line annotated ``annotation`` in a script shared by ``run_keys``
    matches ONLY ``run_key`` (so removing it cannot affect another group)."""
    matched = {k for k in run_keys if _group_matches(annotation, k)}
    return matched == {run_key}


def line_annotation(script_path: pathlib.Path, line: int) -> Optional[str]:
    """The @testgroup path of the statement at ``line`` (None if untagged)."""
    inputs = gsp.parse_and_transform(script_path.read_text(), script_path)
    for inp in inputs:
        if inp.generator_script is not None and inp.generator_script.line == line:
            return inp.group
    return None


def is_isolated_removal(
    entry: GenerationTestcaseEntry, run_keys_by_path: Dict[pathlib.Path, Set[str]]
) -> bool:
    """True iff removing ``entry``'s originating line affects only its run-key."""
    gse = entry.metadata.generator_script
    if gse is None:
        return False
    run_keys = run_keys_by_path.get(gse.path)
    if not run_keys:
        return False
    annotation = line_annotation(gse.path, gse.line)
    return removal_affects_only_run_key(
        entry.subgroup_entry.group, annotation, run_keys
    )
```

Update `remove_script_entries()` to build `script_entry_by_path` from effective scripts (so the inherited path resolves):

```python
    script_entry_by_path = {gs.path: gs for _rk, gs in iter_effective_scripts()}
```

Add `Set` and `Optional` to the `typing` import if missing.

**Step 4: Run** — `uv run pytest tests/rbx/box/promotion_test.py -q` → PASS (new + existing). The existing pure `is_promotable` tests are untouched (signature unchanged).

**Step 5: Commit** (`feat(testset): promotion isolation gate for inherited scripts (#601)`).

---

### Task 5: Wire the promotion gate into the commands

**Files:**
- Modify: `rbx/box/testcases/main.py` (`_non_promotable_reason` ~L173, `_promote_interactive` ~L432, `promote` ~L529-573)
- Test: `tests/rbx/box/testcases/test_promote.py`

**Step 1: Write failing tests** — promote an inherited-script test (isolated) succeeds; a shared top-level line is rejected. Use the existing `test_promote.py` fixtures/style (it drives the `promote` command). Sketch:

```python
async def test_promote_inherited_named_block(testing_pkg, ...):
    # problem-level script: @testgroup g { gen 1 } inherited by group g + a
    # manual group; promoting g/0 removes the line from the shared script.
    ...
    assert 'gen 1' not in shared.read_text()

async def test_promote_blocked_when_line_shared(testing_pkg, ...):
    # top-level `gen 1` inherited by g1 and g2; promoting g1/0 is rejected.
    ...
    # exit code 1 and reason mentions affecting other groups; line still present.
```

Mirror the existing test in `test_promote.py` for invocation/assertion mechanics (CliRunner / `promote` selectors).

**Step 2: Run, expect fail.**

**Step 3: Implement.** In `_promote_interactive` and `promote`, compute the run-key map once and gate with it:

```python
    script_formats = promotion.script_format_by_path()
    run_keys = promotion.run_keys_by_script_path()
    ...
    # filtering (interactive):
    entry for entry in all_entries
    if promotion.is_promotable(entry, script_formats)
    and promotion.is_isolated_removal(entry, run_keys)
    ...
    # validation (selectors):
    if not (
        promotion.is_promotable(entry, script_formats)
        and promotion.is_isolated_removal(entry, run_keys)
    ):
        reason = _non_promotable_reason(entry, script_formats, run_keys)
        ...
```

Extend `_non_promotable_reason(entry, script_formats, run_keys)` with a final branch:

```python
    if not promotion.is_isolated_removal(entry, run_keys):
        return (
            'comes from a line shared by other test groups '
            '(removing it would change them too)'
        )
```

Thread `run_keys` to `_promote_interactive` (add a parameter) like `script_formats`.

**Step 4: Run** — `uv run pytest tests/rbx/box/testcases/test_promote.py -q` → PASS.

**Step 5: Commit** (`feat(testcases): allow promoting inherited-script tests when isolated (#601)`).

---

### Task 6: add-tests picker — block-aware targets

**Files:**
- Modify: `rbx/box/promotion.py` (new target helpers), `rbx/box/cli.py` (~L1042-1148, the stress "add found tests" loop)
- Test: `tests/rbx/box/test_stress_promote.py` (helper-level), plus the e2e in Task 7

**Step 1: Write failing tests** for the pure helpers (no questionary):

```python
def test_script_add_targets_lists_blocks_and_new(testing_pkg):
    shared = testing_pkg.add_testplan('shared')
    shared.write_text('@testgroup g1 { gen 1 }\n')
    testing_pkg.yml.generatorScript = GeneratorScript(path=shared)
    testing_pkg.yml.testcases = testing_pkg.yml.testcases + [
        TestcaseGroup(name='g1'), TestcaseGroup(name='g2'),
    ]
    testing_pkg.save()

    targets = promotion.script_add_targets()
    by_key = {(t.run_key, t.block_start_line) for t in targets}
    assert ('g1', 1) in by_key        # existing @testgroup g1 block
    assert any(t.run_key == 'g2' and t.block_start_line is None for t in targets)

def test_add_calls_to_target_existing_block(testing_pkg):
    shared = testing_pkg.add_testplan('shared')
    shared.write_text('@testgroup g1 {\n  gen 1\n}\n')
    testing_pkg.yml.generatorScript = GeneratorScript(path=shared)
    testing_pkg.yml.testcases = testing_pkg.yml.testcases + [TestcaseGroup(name='g1')]
    testing_pkg.save()

    (target,) = [t for t in promotion.script_add_targets()
                 if t.run_key == 'g1' and t.block_start_line == 2]
    promotion.add_calls_to_target(target, [GeneratorCall(name='gen', args='2')], 'c')
    text = shared.read_text()
    assert 'gen 2' in text.split('@testgroup g1', 1)[1].split('}', 1)[0]
```

(Block start line is 2 here because the plan begins on line 1 only if no leading newline — adjust the asserted line to the actual `@testgroup` line; prefer asserting via `testgroup_blocks` rather than a hardcoded number.)

**Step 2: Run, expect fail.**

**Step 3: Implement** in `promotion.py`:

```python
@dataclasses.dataclass
class ScriptAddTarget:
    run_key: str
    script: GeneratorScript
    block_start_line: Optional[int]  # existing block; None => create/append
    top_level: bool                  # only when block_start_line is None
    label: str


def script_add_targets() -> List[ScriptAddTarget]:
    """Targets for appending tests, one per (run-key, existing @testgroup block)
    plus one create/append target per run-key. rbx-format .txt scripts only."""
    run_keys = run_keys_by_script_path()
    targets: List[ScriptAddTarget] = []
    for run_key, gs in iter_effective_scripts():
        if gs.format != 'rbx' or gs.path.suffix != '.txt' or not gs.path.is_file():
            continue
        rel = package.relpath(gs.path)
        blocks = [
            b for b in gsp.testgroup_blocks(gs.path.read_text()) if b.path == run_key
        ]
        for b in blocks:
            targets.append(ScriptAddTarget(
                run_key, gs, b.start_line, False,
                f'{run_key} @ {rel}:{b.start_line}',
            ))
        exclusive = run_keys.get(gs.path) == {run_key}
        targets.append(ScriptAddTarget(
            run_key, gs, None, exclusive,
            f'{run_key} @ {rel} ' + ('(append)' if exclusive else '(new @testgroup block)'),
        ))
    return targets


def add_calls_to_target(
    target: ScriptAddTarget, calls: List[GeneratorCall], comment: Optional[str] = None
) -> None:
    path = target.script.path
    handler = gsh.get_generator_script_handler(
        path.read_text(), gsh.GeneratorScriptHandlerParams(target.script)
    )
    if target.block_start_line is not None:
        handler.append_in_block(target.block_start_line, calls, comment)
    elif target.top_level:
        handler.append(calls, comment)
    else:
        handler.append_new_block(target.run_key, calls, comment)
    path.write_text(handler.script)
    package_utils.clear_package_cache()
```

In `cli.py`, replace the `groups_by_name` construction and the script-route branch (~L1042-1148) so the picker lists `[t.label for t in promotion.script_add_targets()]` alongside manual groups and the `(create new …)`/`(skip)` options, maps the chosen label back to its `ScriptAddTarget`, and calls `promotion.add_calls_to_target(target, [f.generator for f in report.findings], stress_text)`. Keep manual-group and `(create new manual group)` handling unchanged. `(create new script)` may remain (creates an explicit group), now just one more way to get a target.

**Step 4: Run** — `uv run pytest tests/rbx/box/test_stress_promote.py -q` → PASS. Manually sanity-check the cli loop compiles: `uv run python -c "import rbx.box.cli"`.

**Step 5: Commit** (`feat(stress): block-aware add-tests targets for inherited scripts (#601)`).

---

### Task 7: e2e fixture

**Files:**
- Create: `tests/e2e/testdata/<new-fixture>/` (problem with problem-level `generatorScript` partitioned by `@testgroup`, a generator, a solution, and a stress/finder or pre-seeded findings) + its `e2e.rbx.yml`
- Reference: `tests/e2e/README.md` for the YAML DSL

**Step 1:** Read `tests/e2e/README.md` and an existing fixture with a generator script. Author a fixture whose `problem.rbx.yml` sets a problem-level `generatorScript` with `@testgroup g1 { … }` / `@testgroup g2 { … }`, groups `g1`,`g2` inheriting it, and a manual group.

**Step 2:** Add e2e steps covering: (a) `rbx testcases promote` of an inherited `g1` test into the manual group (asserts the line is removed from the shared script and the manual `.in` appears); (b) a promote attempt on a shared top-level line is rejected. (add-tests via stress is interactive; cover the helper path in Task 6 and, if the DSL supports it, a non-interactive add — otherwise document the gap.)

**Step 3:** Run: `mise run test-e2e` (or the documented single-fixture invocation). Expected: PASS.

**Step 4: Commit** (`test(testset): e2e for inherited generatorScript add/promote (#601)`).

---

### Task 8: Docs + final verification

**Files:**
- Modify: `rbx/box/CLAUDE.md` (Test Generation section — note inherited-script add/promote and the isolation rule), `docs/` user docs if generator-script editing is documented there.

**Steps:**
1. Update `rbx/box/CLAUDE.md` Test Generation / promotion notes.
2. `uv run ruff check . && uv run ruff format .`
3. Full suite (excluding slow CLI): `uv run pytest --ignore=tests/rbx/box/cli -n auto -q`
4. Targeted: `uv run pytest tests/rbx/box/promotion_test.py tests/rbx/box/testcase_extractors_test.py tests/rbx/box/testcases/test_promote.py tests/rbx/box/stressing/generator_script_parser_test.py tests/rbx/box/generator_script_handlers_test.py -q`
5. Commit (`docs(testset): document inherited generatorScript editing (#601)`).
6. Open PR against `rsalesc/rbx:main` titled `feat(testset): add-tests/promotion for inherited generatorScript (#601)`, body summarizing both scenarios, the Option-A decision, and the isolation rule. Closes #601.

---

## Open considerations / watch-outs

- **`is_promotable` stays pure** (path→format dict only); the isolation gate is separate because the existing unit tests use script paths with no file on disk.
- **Box-format / non-`.txt`**: excluded from the new block logic; promotion already rejects them.
- **`line_annotation` re-parses** the script per entry; fine for interactive use. If a batch promote is slow, memoize by path.
- **`@testgroup` start-line vs the picker label**: assert block lines via `testgroup_blocks` in tests, not hardcoded numbers.
- **`relpath` vs absolute**: `iter_effective_scripts` yields `GeneratorScript` whose `.path` is package-relative as stored; `remove_script_entries`/metadata use the same path objects, so keys match. Verify in Task 4/5 that `entry.metadata.generator_script.path` equals the `gs.path` key (both are the relative path produced by the parser via `script_entry.path`).
