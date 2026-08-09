# Per-Group Vars Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let a setter declare per-test-group `vars` overrides in `problem.rbx.yml`, so that `getVar<T>()` inside a validator returns the value effective for the group currently being validated, and statements can render those resolved values per group.

**Architecture:** `rbx.h` is generated per package and already embeds every var's value. It gains (a) a self-contained `--group` parser that captures `argv` via an `.init_array` constructor, needing no call in `main()` and no dependency on testlib, and (b) a per-group override table consulted before the package-level defaults. Nothing new travels at runtime: rbx already passes `--group <name>` to validators. Checkers and interactors are deliberately out of scope.

**Tech Stack:** Python 3 / Pydantic v2 / Typer (rbx), C++17 (generated `rbx.h`), Jinja2 + LaTeX (statements), pytest.

**Design doc:** `docs/plans/2026-08-09-per-group-vars-design.md`

**Read first:** `rbx/box/CLAUDE.md` (schema system, code compilation), `rbx/box/statements/CLAUDE.md` (Jinja context).

---

## Conventions for every task

- Run tests with `uv run pytest <path> -v` from the repo root.
- Single quotes in Python (ruff enforces). Absolute imports only.
- Lint before each commit: `uv run ruff check --fix . && uv run ruff format .`
- Commit messages follow commitizen; see `.claude/skills/commit.md`. Always append
  `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Never `git add -A`. Stage the files named in the task.

---

### Task 1: Deep-merge helper and per-group var resolution

`vars` in the schema is `RecVars` — a *nested* dict (`{AB: {min: -200, max: 200}}`) which `expand_vars` later flattens to dotted keys (`AB.min`). The merge must happen on the nested form, **before** expansion, so that a partial override keeps its siblings and so overrides can participate in variable interpolation.

**Files:**
- Modify: `rbx/box/fields.py` (add `merge_recvars`)
- Modify: `rbx/box/schema.py` (add `vars` to `TestcaseGroup`; add `Package.expanded_vars_for_group`)
- Test: `tests/rbx/box/schema_test.py`

**Step 1: Write the failing test**

Append to `tests/rbx/box/schema_test.py`:

```python
def test_merge_recvars_is_deep_and_keeps_siblings():
    from rbx.box.fields import merge_recvars

    base = {'AB': {'min': -200, 'max': 200}, 'N': 10}
    override = {'AB': {'min': 0}}

    assert merge_recvars(base, override) == {
        'AB': {'min': 0, 'max': 200},
        'N': 10,
    }
    # The inputs must not be mutated.
    assert base == {'AB': {'min': -200, 'max': 200}, 'N': 10}
    assert override == {'AB': {'min': 0}}


def test_merge_recvars_allows_group_only_keys():
    from rbx.box.fields import merge_recvars

    assert merge_recvars({'N': 10}, {'maxOps': 5}) == {'N': 10, 'maxOps': 5}


def test_merge_recvars_scalar_replaces_subtree():
    from rbx.box.fields import merge_recvars

    assert merge_recvars({'AB': {'min': 1}}, {'AB': 7}) == {'AB': 7}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/schema_test.py -k merge_recvars -v`
Expected: FAIL with `ImportError: cannot import name 'merge_recvars'`

**Step 3: Write minimal implementation**

Add to `rbx/box/fields.py`:

```python
def merge_recvars(base: RecVars, override: RecVars) -> RecVars:
    """Deep-merge ``override`` onto ``base``, leaf by leaf.

    A dict value merges recursively so a partial override keeps its siblings;
    any non-dict value replaces whatever was there. Neither input is mutated.
    """
    res: RecVars = dict(base)
    for key, value in override.items():
        prev = res.get(key)
        if isinstance(value, dict) and isinstance(prev, dict):
            res[key] = merge_recvars(prev, value)
        else:
            res[key] = value
    return res
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/schema_test.py -k merge_recvars -v`
Expected: PASS (3 tests)

**Step 5: Write the failing schema test**

Append to `tests/rbx/box/schema_test.py`:

```python
def test_expanded_vars_for_group_applies_override():
    from rbx.box.schema import Package

    pkg = Package.model_validate(
        {
            'name': 'test',
            'timeLimit': 1000,
            'memoryLimit': 256,
            'vars': {'AB': {'min': -200, 'max': 200}},
            'testcases': [
                {'name': 'sub2', 'vars': {'AB': {'min': 0}}},
                {'name': 'sub4'},
            ],
        }
    )

    assert pkg.expanded_vars == {'AB.min': -200, 'AB.max': 200}
    assert pkg.expanded_vars_for_group('sub2') == {'AB.min': 0, 'AB.max': 200}
    assert pkg.expanded_vars_for_group('sub4') == {'AB.min': -200, 'AB.max': 200}
    # Unknown or absent group falls back to the package vars.
    assert pkg.expanded_vars_for_group('nope') == {'AB.min': -200, 'AB.max': 200}
    assert pkg.expanded_vars_for_group(None) == {'AB.min': -200, 'AB.max': 200}
```

**Step 6: Run it to verify it fails**

Run: `uv run pytest tests/rbx/box/schema_test.py -k expanded_vars_for_group -v`
Expected: FAIL — `extra_forbidden` on `vars` (TestcaseGroup sets `extra='forbid'`)

**Step 7: Implement**

In `rbx/box/schema.py`, import the helper alongside the existing field imports:

```python
from rbx.box.fields import merge_recvars
```

Add to `class TestcaseGroup` (after the `validator` field, around line 545):

```python
    vars: RecVars = Field(
        default={},
        description="""
Variables that override the package-level `vars` for this group only.

Merged leaf-by-leaf onto the package `vars`, so a partial override keeps its
siblings. The effective values are what `getVar<T>()` returns inside a
validator run for this group, and what `problem.groups.<name>.vars` renders in
a statement. Keys need not exist at package level.
""",
    )
```

Add to `class Package`, next to `expanded_vars` (around line 1055):

```python
    def expanded_vars_for_group(self, group: Optional[str]) -> Vars:
        """Package vars with the named group's overrides applied.

        Falls back to the package vars when ``group`` is None or names no
        declared group (interactive validation, unit tests, samples).
        """
        if group is None:
            return self.expanded_vars
        for testcase_group in self.testcases:
            if testcase_group.name == group:
                return expand_vars(merge_recvars(self.vars, testcase_group.vars))
        return self.expanded_vars
```

Check that `expand_vars` and `Optional` are already imported in `schema.py`; add them if not.

**Step 8: Run it to verify it passes**

Run: `uv run pytest tests/rbx/box/schema_test.py -k 'merge_recvars or expanded_vars_for_group' -v`
Expected: PASS (4 tests)

**Step 9: Regenerate the JSON schema if the repo tracks it**

Run: `uv run rbx schema --help` and check `git status` for a changed schema artifact under `schemas/`. If one changed, include it in the commit.

**Step 10: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/fields.py rbx/box/schema.py tests/rbx/box/schema_test.py
git commit -m "$(cat <<'EOF'
feat(schema): allow per-group vars overrides

Merged leaf-by-leaf onto the package vars so a partial override keeps its
siblings, and merged before expansion so overrides can participate in
variable interpolation.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Self-contained `--group` parsing in the rbx.h template

`rbx.h` must learn the group with **no dependency on testlib** (no include, no symbol, no `_TESTLIB_H_` conditional) and **no call in `main()`**. glibc and Apple's dyld both invoke `.init_array` entries with `(argc, argv, envp)`, which lets a header capture the command line.

**Files:**
- Modify: `rbx/resources/templates/rbx.h`
- Test: `tests/rbx/box/test_header.py`

**Step 1: Write the failing test**

Append to `tests/rbx/box/test_header.py`. Model it on the existing compile-and-run test at line 373 — reuse whatever helper that test uses to compile a snippet against the generated header; if it compiles inline with `subprocess`, do the same here.

```python
GROUP_PROBE_SOURCE = """
#include "rbx.h"
#include <cstdio>

// Resolved before main() runs, to prove the constructor hook fires early.
static const std::string kEarly = rbx::getGroup();

int main() {
  std::printf("early=[%s]\\n", kEarly.c_str());
  std::printf("late=[%s]\\n", rbx::getGroup().c_str());
  return 0;
}
"""


@pytest.mark.parametrize(
    'argv,expected',
    [
        (['--group', 'sub2'], 'sub2'),
        (['--group=sub2'], 'sub2'),
        (['--AB.min=-200', '--group', 'sub2', '--other', 'x'], 'sub2'),
        ([], ''),
        (['--group'], ''),  # trailing flag with no value
        (['--groups', 'sub2'], ''),  # must not prefix-match
    ],
)
def test_get_group_parses_argv(argv, expected, ...):
    """rbx::getGroup() reads --group itself, with no testlib involved."""
    # compile GROUP_PROBE_SOURCE against the generated header, run with argv
    # assert both printed lines equal f'[{expected}]'
```

**Step 2: Run it to verify it fails**

Run: `uv run pytest tests/rbx/box/test_header.py -k get_group_parses_argv -v`
Expected: FAIL — compile error, `rbx` has no member `getGroup`

**Step 3: Implement**

Insert at the top of `rbx/resources/templates/rbx.h`, immediately after the existing `#include` block (before `getStringVar`), so the generated var functions can call it:

```cpp
#include <cstring>

namespace rbx {
namespace detail {

static int g_argc = 0;
static char** g_argv = nullptr;

// glibc and Apple's dyld both invoke .init_array entries with
// (argc, argv, envp), which lets this header see the command line without the
// program having to call anything from main().
__attribute__((constructor)) static void rbxCaptureArgs(int argc, char** argv,
                                                        char** /*envp*/) {
  g_argc = argc;
  g_argv = argv;
}

inline std::string parseGroupFromArgv() {
  static const char kFlag[] = "--group";
  static const std::size_t kFlagLen = sizeof(kFlag) - 1;
  if (g_argv == nullptr) {
    return "";
  }
  for (int i = 1; i < g_argc; i++) {
    const char* arg = g_argv[i];
    if (arg == nullptr || std::strncmp(arg, kFlag, kFlagLen) != 0) {
      continue;
    }
    // "--group=value"
    if (arg[kFlagLen] == '=') {
      return std::string(arg + kFlagLen + 1);
    }
    // "--group value"; a trailing flag with no value reads as absent.
    if (arg[kFlagLen] == '\0') {
      if (i + 1 < g_argc && g_argv[i + 1] != nullptr) {
        return std::string(g_argv[i + 1]);
      }
      return "";
    }
    // Anything else ("--groups", ...) is a different flag.
  }
  return "";
}

}  // namespace detail

// The test group currently being validated, as passed by rbx via `--group`.
// Empty when the program was not run for a specific group, in which case
// getVar returns the package-level values.
//
// Parsed once, on first use.
inline const std::string& getGroup() {
  static const std::string group = detail::parseGroupFromArgv();
  return group;
}

}  // namespace rbx
```

**Step 4: Run it to verify it passes**

Run: `uv run pytest tests/rbx/box/test_header.py -k get_group_parses_argv -v`
Expected: PASS (6 parametrizations)

**Step 5: Prove there is no testlib dependency**

Add a test asserting the template never mentions testlib:

```python
def test_header_does_not_depend_on_testlib():
    header = pathlib.Path('rbx.h').read_text()
    assert 'testlib' not in header.lower()
    assert '_TESTLIB_H_' not in header
```

Run: `uv run pytest tests/rbx/box/test_header.py -k does_not_depend_on_testlib -v`
Expected: PASS

**Step 6: Verify it coexists with testlib in both include orders**

Add a test that compiles a real testlib validator including `rbx.h` **before** `testlib.h` and another including it **after**, asserting both compile and both agree with `rbx::getGroup()`. Use the testlib at `rbx/resources/predownloaded/testlib.h`. This is the regression guard for the name collision: `rbx::getGroup()` must never clash with testlib's global `getGroup()`.

Run: `uv run pytest tests/rbx/box/test_header.py -k include_order -v`
Expected: PASS

**Step 7: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/resources/templates/rbx.h tests/rbx/box/test_header.py
git commit -m "$(cat <<'EOF'
feat(header): add rbx::getGroup() reading --group from argv

Captures argv through an .init_array constructor so the group resolves with
no call in main() and no dependency on testlib -- a global getGroup() would
collide with testlib's own, hence the namespace.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Emit per-group var tables into rbx.h

**Files:**
- Modify: `rbx/resources/templates/rbx.h` (four new sentinels)
- Modify: `rbx/box/header.py`
- Test: `tests/rbx/box/test_header.py`

**Step 1: Write the failing test**

```python
def test_getvar_resolves_group_override(...):
    """getVar returns the group's value under --group, the package's otherwise."""
    # package vars: AB.min=-200, AB.max=200
    # group sub2 overrides AB.min=0; group sub4 overrides nothing
    # compile a probe printing getVar<int>("AB.min") and getVar<int>("AB.max")
    # --group sub2  -> 0    200
    # --group sub3  -> -200 200   (declared, overrides AB.max only)
    # --group sub4  -> -200 200
    # (no flag)     -> -200 200
```

Also cover a group-only var:

```python
def test_group_only_var_is_visible_in_its_group_and_throws_outside(...):
    # group sub2 declares vars: {maxOps: 5}, package declares none
    # --group sub2 -> getVar<int>("maxOps") == 5
    # no flag      -> getVar<int>("maxOps") throws std::runtime_error
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_header.py -k 'group_override or group_only_var' -v`
Expected: FAIL — group override ignored, returns the package value

**Step 3: Add the sentinels to the template**

In `rbx/resources/templates/rbx.h`, put a group block *before* the existing default block in each of the four accessors, e.g.:

```cpp
std::optional<int64_t> getIntVar(std::string name) {
  const std::string& group = rbx::getGroup();
  (void)group;  // unused when no group declares overrides
  //<rbx::int_var_groups>
  //<rbx::int_var>
  return std::nullopt;
}
```

Do the same for `getStringVar` (`//<rbx::string_var_groups>`), `getFloatVar` (`//<rbx::float_var_groups>`) and `getBoolVar` (`//<rbx::bool_var_groups>`).

**Step 4: Implement generation**

In `rbx/box/header.py`, extend `_preprocess_header`:

```python
def _preprocess_header(header: str) -> str:
    return (
        header.replace('//<rbx::string_var>', _get_string_var_block())
        .replace('//<rbx::int_var>', _get_int_var_block())
        .replace('//<rbx::float_var>', _get_float_var_block())
        .replace('//<rbx::bool_var>', _get_bool_var_block())
        .replace('//<rbx::string_var_groups>', _get_group_block(str, _string_repr))
        .replace('//<rbx::int_var_groups>', _get_int_group_block())
        .replace('//<rbx::float_var_groups>', _get_group_block(float, lambda x: f'{x}'))
        .replace(
            '//<rbx::bool_var_groups>',
            _get_group_block(bool, lambda x: 'true' if x else 'false'),
        )
    )
```

and add:

```python
def _groups_with_vars() -> List[str]:
    pkg = package.find_problem_package_or_die()
    return [group.name for group in pkg.testcases if group.vars]


def _get_group_block(
    t: Type, transform: Callable[[Primitive], str]
) -> str:
    """One `if (group == "...") { ... }` arm per group declaring overrides.

    Emitted before the package-level block, so a group that overrides nothing
    for a given key falls through to the default.
    """
    pkg = package.find_problem_package_or_die()
    entries = []
    for name in sorted(_groups_with_vars()):
        vars = pkg.expanded_vars_for_group(name)
        mappings = {
            var: transform(value)
            for var, value in vars.items()
            if isinstance(value, t)
        }
        if not mappings:
            continue
        body = _get_var_block(mappings)
        indented = ''.join(f'  {line}\n' for line in body.splitlines())
        entries.append(f'  if (group == "{name}") {{\n{indented}  }}\n')
    return ''.join(entries)


def _get_int_group_block() -> str:
    # Mirrors _get_int_var_block: bools are also ints in the int accessor.
    def _transform(x: Primitive) -> str:
        if isinstance(x, bool):
            return f'static_cast<int64_t>({int(x)})'
        check_int_bounds(int(x))
        return f'static_cast<int64_t>({x})'

    pkg = package.find_problem_package_or_die()
    entries = []
    for name in sorted(_groups_with_vars()):
        vars = pkg.expanded_vars_for_group(name)
        mappings = {
            var: _transform(value)
            for var, value in vars.items()
            if isinstance(value, (int, bool))
        }
        if not mappings:
            continue
        body = _get_var_block(mappings)
        indented = ''.join(f'  {line}\n' for line in body.splitlines())
        entries.append(f'  if (group == "{name}") {{\n{indented}  }}\n')
    return ''.join(entries)
```

Add `List` to the `typing` import.

Note the group arm emits the group's **full resolved** var set, not just its overrides. That costs a few lines of generated code and removes any ordering subtlety between the two blocks.

**Step 5: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_header.py -v`
Expected: PASS (whole file, including the pre-existing tests)

**Step 6: Confirm a package with no group vars generates unchanged output**

Add a test asserting the generated header for a package without group overrides contains no `if (group ==` at all, so existing packages are byte-stable apart from the new `getGroup` block.

Run: `uv run pytest tests/rbx/box/test_header.py -k no_group_vars -v`
Expected: PASS

**Step 7: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/resources/templates/rbx.h rbx/box/header.py tests/rbx/box/test_header.py
git commit -m "$(cat <<'EOF'
feat(header): resolve getVar against the current test group

Emits one arm per group declaring overrides, consulted before the
package-level defaults, so an existing validator becomes group-aware without
any source change.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Send group-resolved vars on the validator command line

rbx passes package vars as `--{k}={v}` (`rbx/box/validators.py:112`). Those must become the group's effective vars, or a setter reading `opt<int>("AB.min")` and one reading `getVar<int>("AB.min")` would disagree.

**Files:**
- Modify: `rbx/box/validators.py:158-167` (`validate_file`)
- Test: `tests/rbx/box/validators_test.py`

**Step 1: Write the failing test**

Model it on `test_validator_receives_group_argument` (`tests/rbx/box/validators_test.py:560`) and its fixture `rbx/testdata/validators/group-validator.cpp`. Add a new fixture validator that reads bounds via `getVar` and validates a single int against them, then a test asserting the *same* validator accepts a value in one group and rejects it in another.

```python
async def test_validator_uses_group_resolved_vars(...):
    """One validator, different effective bounds per group."""
    # package vars: N: {min: 1, max: 1000}
    # group 'small' overrides N.max = 10
    # input "500" passes in the default group and fails in 'small'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/validators_test.py -k group_resolved_vars -v`
Expected: FAIL — the value is accepted in both groups

**Step 3: Implement**

In `rbx/box/validators.py`, change `validate_file`:

```python
async def validate_file(
    testcase: pathlib.Path,
    validator: CodeItem,
    validator_digest: str,
    group: Optional[str] = None,
) -> Tuple[bool, Optional[str], HitBounds]:
    pkg = package.find_problem_package_or_die()
    return await _validate_testcase(
        testcase,
        validator,
        validator_digest,
        vars=pkg.expanded_vars_for_group(group),
        group=group,
    )
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/validators_test.py -k group_resolved_vars -v`
Expected: PASS

**Step 5: Run the whole validator suite for regressions**

Run: `uv run pytest tests/rbx/box/validators_test.py -v`
Expected: PASS

**Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/validators.py tests/rbx/box/validators_test.py rbx/testdata/validators/
git commit -m "$(cat <<'EOF'
feat(validators): pass group-resolved vars on the command line

Keeps opt()-based and getVar-based readers in agreement; they would otherwise
see different bounds for the same testcase.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Keep hit-bounds reporting per group

`_has_group_specific_validator()` (`rbx/box/validators.py:96`) gates whether the hit-bounds report merges bounds across groups. With per-group vars the *same* validator has genuinely different bounds per group, so merging produces bogus "min-value not hit" warnings.

**Files:**
- Modify: `rbx/box/validators.py:96-100`
- Test: `tests/rbx/box/validators_test.py`

**Step 1: Write the failing test**

```python
def test_has_group_specific_validator_true_when_group_declares_vars(...):
    # package with one package-level validator, no per-group validator,
    # but a group declaring `vars` -> must report True
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/validators_test.py -k has_group_specific_validator -v`
Expected: FAIL — returns False

**Step 3: Implement**

```python
def _has_group_specific_validator() -> bool:
    pkg = package.find_problem_package_or_die()

    return any(
        group.validator is not None or bool(group.vars) for group in pkg.testcases
    )
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/validators_test.py -k has_group_specific_validator -v`
Expected: PASS

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/validators.py tests/rbx/box/validators_test.py
git commit -m "$(cat <<'EOF'
fix(validators): report hit bounds per group when group vars differ

Merging bounds across groups reports spurious "min-value not hit" when the
same validator enforces different bounds per group.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Expose group-resolved vars to statements

`groups` is already in the statement context (`rbx/box/statements/context.py:117`, wrapped by `JinjaGroupsGetter`, iterable in insertion order). Hang resolved vars off each group. `g.vars` must be the **resolved** set — exposing the raw override would render blanks for every group that doesn't override a given key.

**Files:**
- Modify: `rbx/box/statements/context.py`
- Modify: `rbx/box/statements/build_statements.py:287`
- Test: `tests/rbx/box/statements/` (match the existing test layout in that directory)

**Step 1: Write the failing test**

```python
def test_group_vars_are_resolved_in_statement_context():
    # package vars AB: {min: -200, max: 200}; group sub2 overrides AB.min = 0
    ns = problem_jinja_kwargs(...)
    groups = ns['problem']['groups']
    assert groups['sub2'].vars['AB.min'] == 0
    assert groups['sub2'].vars['AB.max'] == 200   # inherited
    assert groups['sub4'].vars['AB.min'] == -200  # no override at all
    assert groups['sub2'].name == 'sub2'          # model passthrough
    assert groups['sub2'].score == 20


def test_missing_group_var_raises_strict_undefined():
    # rendering \VAR{problem.groups.sub2.vars.AB.mim} must raise, not render ''
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/ -k group_vars -v`
Expected: FAIL — `AttributeError`/`KeyError`, groups carry the raw model

**Step 3: Implement the view**

Add to `rbx/box/statements/context.py`:

```python
class GroupView:
    """A testcase group as seen by a statement template.

    Proxies attribute access to the underlying ``TestcaseGroup`` so ``g.name``
    and ``g.score`` keep working, but serves ``vars`` as the group's *resolved*
    vars (package vars with this group's overrides applied) rather than the raw
    override block. A template asking for a var the group does not override
    must still get the inherited value, not a blank.
    """

    def __init__(self, group: Any, vars: Vars):
        self._group = group
        self.vars = _wrap(vars, f'groups.{group.name}.vars')

    def __getattr__(self, name: str) -> Any:
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return getattr(self._group, name)
```

**Step 4: Wire it up**

In `rbx/box/statements/build_statements.py`, change the `groups=` argument (line 287) from

```python
            groups={g.name: g for g in pkg.testcases},
```

to

```python
            groups={
                g.name: GroupView(g, pkg.expanded_vars_for_group(g.name))
                for g in pkg.testcases
            },
```

and import `GroupView` from `rbx.box.statements.context`. Check for other construction sites: `grep -rn 'groups={' rbx/box/statements/` and update each.

**Step 5: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/ -v`
Expected: PASS

**Step 6: Verify a real render end to end**

Build a statement in a fixture package whose template iterates `problem.groups` and prints `g.vars.*`, and assert the rendered output. Use the `mock_pdflatex` fixture rather than a real LaTeX run.

**Step 7: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/statements/context.py rbx/box/statements/build_statements.py tests/rbx/box/statements/
git commit -m "$(cat <<'EOF'
feat(statements): expose group-resolved vars via problem.groups

g.vars is the resolved set, not the raw override, so a subtasks table renders
inherited values instead of blanks for groups that override nothing.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Stop arming the unused-opt trap in the preset validator

`rbx/resources/presets/default/problem/validator.cpp:9` calls `prepareOpts(argc, argv)` but never calls `opt()`. That yields nothing today and turns into `FAIL Opts: unused key 'N.max'` the moment a setter adds one `opt(key, default)` call, because rbx injects the package vars as `--{k}={v}`.

**Files:**
- Modify: `rbx/resources/presets/default/problem/validator.cpp`
- Test: whichever preset test asserts the shipped files build (`grep -rn 'presets/default' tests/`)

**Step 1: Remove the call**

Delete line 9 (`prepareOpts(argc, argv);`).

**Step 2: Verify the preset still builds**

Run: `uv run pytest tests/rbx/box/presets -v`
Expected: PASS

Then manually: `rbx create` a scratch problem from the default preset in a temp dir and run `rbx build`.
Expected: builds clean, no validator failures.

**Step 3: Commit**

```bash
git add rbx/resources/presets/default/problem/validator.cpp
git commit -m "$(cat <<'EOF'
fix(presets): drop prepareOpts from the default validator

It enables nothing (the template reads vars via getVar) but arms testlib's
unused-opt check, so the first opt() a setter adds fails every testcase on the
vars rbx injects.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: End-to-end fixture

**Files:**
- Create: `tests/e2e/testdata/group-vars/` (`problem.rbx.yml`, `e2e.rbx.yml`, `validator.cpp`, `gens/`, `sols/`, `testlib.h`)
- Read first: `tests/e2e/README.md` for the YAML DSL

**Step 1: Build the fixture**

A problem with two scored groups whose `vars` differ, one validator reading bounds via `getVar`, and a generator producing values legal in one group and illegal in the other.

**Step 2: Assert the failure is caught**

The e2e scenario asserts `rbx build` reports a validation failure naming the offending group, and that fixing the generator makes it pass. This is the regression test for the original bug: a constraint that should fail must actually fail.

**Step 3: Run**

Run: `mise run test-e2e`
Expected: PASS

**Step 4: Commit**

```bash
git add tests/e2e/testdata/group-vars/
git commit -m "$(cat <<'EOF'
test(e2e): cover per-group vars in validation

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Docs

**Files:**
- Modify: `docs/setters/verification/validators.md` (per-group vars section, after the existing group-validator section at lines 256-282)
- Modify: `docs/setters/reference/package/index.md` (the `vars` field on testcase groups; the validator↔CLI contract at lines 353-395)
- Modify: `docs/setters/cheatsheet.md` (a "vary constraints per group" entry near line 221)

**Content that must appear:**

1. How to declare per-group `vars` and that `getVar` picks them up with no source change.
2. `rbx::getGroup()` exists for the cases that genuinely are not parameters.
3. **`opt()` does not work in a validator.** testlib's `registerValidation` never calls `prepareOpts`, so `opt<T>("group", "")` silently returns the default and the branch is dead. Use per-group vars, or `validator.group()` / `rbx::getGroup()`. This is the trap that motivated the feature and is the single most valuable line in the change.
4. Why checkers and interactors have no equivalent: they follow Kattis's convention of taking context from the input/answer files, and testlib's `registerInteraction` cannot accept extra flags at all.
5. That per-group vars are also readable in statements as `problem.groups.<name>.vars.<key>`.

**Verify:** `uv run mkdocs build` (non-strict — the repo has ~9 pre-existing unrelated strict warnings).

**Commit:**

```bash
git add docs/
git commit -m "$(cat <<'EOF'
docs(setters): document per-group vars and the opt() trap

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Full verification

**Step 1:** `uv run pytest --ignore=tests/rbx/box/cli -n auto`

Expected: PASS, except the pre-existing local failures recorded in
`docs/plans/` / project memory (C++/sandbox/docker-dependent tests, and
`test_compute_walltime_uses_active_environment`). Compare against a
`git stash`-free baseline on `main` before blaming this change.

**Step 2:** `uv run pytest tests/rbx/box/cli -v`

**Step 3:** `mise run test-e2e`

**Step 4:** Re-run the original reproduction from the aula package: a validator using per-group vars must fail the group whose generator violates them.

**Step 5:** Open a PR. Do not push to main.
