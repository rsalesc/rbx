# Block generators from depending on `rbx.h` — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Error out when a C++ generator directly `#include`s `rbx.h`, with two escape hatches (per-include disable directive, env.rbx.yml removal) and a Troubleshooting docs link.

**Architecture:** Add a new `rbx-header` linter to the existing `rbx/box/linters/` framework, scoped to `AssetKind.GENERATOR`, emitting an ERROR `LinterMessage` for any direct include whose basename is `rbx.h`. The framework already provides env-config on/off, the `// rbx-header-linter: disable` suppression directive, ERROR→`RbxException` routing that blocks the build, and tree-sitter-cpp parsing. Enable it by default by adding `rbx-header` to the bundled default env's C++ `linters:` list.

**Tech Stack:** Python, Pydantic v2, tree-sitter-cpp, pytest, mkdocs-material.

**Reference design:** `docs/plans/2026-06-08-generators-rbx-header-linter-design.md`

---

### Task 1: The `rbx-header` linter (pure detection)

**Files:**
- Create: `rbx/box/linters/cpp/rbx_header.py`
- Test: `tests/rbx/box/linters/test_rbx_header.py`

Model the linter on `rbx/box/linters/cpp/testlib.py` and the include traversal in `rbx/box/dependencies/cpp.py` (`_quoted_include_nodes`). Test conventions mirror `tests/rbx/box/linters/test_testlib.py`.

**Step 1: Write failing tests**

```python
# tests/rbx/box/linters/test_rbx_header.py
from rbx.box.linters.cpp.rbx_header import RbxHeaderLinter
from rbx.box.linters.linter import LinterSeverity
from rbx.box.schema import CodeItem


def _lint(src: str):
    return RbxHeaderLinter().lint(CodeItem(path='gen.cpp'), src)


def test_quoted_include_is_flagged():
    msgs = _lint('#include "rbx.h"\nint main() {}\n')
    assert len(msgs) == 1
    assert msgs[0].severity is LinterSeverity.ERROR


def test_angled_include_is_flagged():
    assert len(_lint('#include <rbx.h>\nint main() {}\n')) == 1


def test_include_with_subdir_basename_is_flagged():
    assert len(_lint('#include "sub/rbx.h"\nint main() {}\n')) == 1


def test_other_includes_are_ignored():
    src = '#include <bits/stdc++.h>\n#include "testlib.h"\nint main() {}\n'
    assert _lint(src) == []


def test_no_include_is_ok():
    assert _lint('int main() { return 0; }\n') == []


def test_message_has_location_and_hints():
    msgs = _lint('\n#include "rbx.h"\nint main() {}\n')
    assert msgs[0].line == 2
    assert msgs[0].col is not None
    # Both escape hatches and the docs link are surfaced.
    assert 'rbx-header-linter: disable' in msgs[0].message
    assert 'env.rbx.yml' in msgs[0].message
    assert 'rbx.rsalesc.dev/generators-and-rbx-h' in msgs[0].message


def test_multiple_includes_yield_multiple_messages():
    src = '#include "rbx.h"\n#include <rbx.h>\nint main() {}\n'
    assert len(_lint(src)) == 2


def test_string_literal_mentioning_rbx_h_is_not_flagged():
    # A string that contains the text must not be detected as an include.
    assert _lint('const char* s = "#include \\"rbx.h\\"";\nint main(){}\n') == []
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/linters/test_rbx_header.py -v`
Expected: FAIL — `ModuleNotFoundError: rbx.box.linters.cpp.rbx_header`.

**Step 3: Implement the linter**

```python
# rbx/box/linters/cpp/rbx_header.py
import pathlib
from typing import List, Optional

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from rbx.box.linters import registry
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.linter import Linter, LinterMessage, LinterSeverity
from rbx.box.schema import CodeItem

_HEADER_NAME = 'rbx.h'

_MESSAGE = (
    'Generators must not #include "rbx.h". It exposes the problem\'s '
    'variables/constraints via getVar, so a generator that reads them '
    'silently changes its tests whenever a constraint changes.\n'
    '  - To intentionally allow it here: add '
    '`// rbx-header-linter: disable` after the include line.\n'
    '  - To turn this check off everywhere: remove `rbx-header` from '
    '`linters` in your env.rbx.yml.\n'
    '  - Why this matters: https://rbx.rsalesc.dev/generators-and-rbx-h/'
)

_LANGUAGE = Language(tree_sitter_cpp.language())


def _parser() -> Parser:
    return Parser(_LANGUAGE)


def _include_spelling(node: Node) -> Optional[str]:
    """The header path of a ``preproc_include`` node, quoted or angled."""
    for child in node.children:
        if child.type in ('string_literal', 'system_lib_string'):
            text = child.text.decode('utf-8')
            # Strip the surrounding "..." or <...>.
            return text[1:-1] if len(text) >= 2 else text
    return None


class RbxHeaderLinter(Linter):
    """Flags generators that directly depend on ``rbx.h``.

    ``rbx.h`` exposes the problem's variables/constraints via ``getVar``. A
    generator reading them produces tests that change silently when a
    constraint changes, so depending on it from a generator is an error.
    """

    name = 'rbx-header'
    applies_to = {AssetKind.GENERATOR}

    def lint(self, code: CodeItem, source: str) -> List[LinterMessage]:
        tree = _parser().parse(bytes(source, 'utf8'))
        messages: List[LinterMessage] = []
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type == 'preproc_include':
                spelling = _include_spelling(node)
                if (
                    spelling is not None
                    and pathlib.PurePosixPath(spelling).name == _HEADER_NAME
                ):
                    row, col = node.start_point
                    messages.append(
                        LinterMessage(
                            severity=LinterSeverity.ERROR,
                            message=_MESSAGE,
                            line=row + 1,
                            col=col + 1,
                        )
                    )
            stack.extend(node.children)
        return messages


registry.register(RbxHeaderLinter)
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/rbx/box/linters/test_rbx_header.py -v`
Expected: PASS (8 tests).

**Step 5: Lint/format**

Run: `uv run ruff check rbx/box/linters/cpp/rbx_header.py tests/rbx/box/linters/test_rbx_header.py && uv run ruff format rbx/box/linters/cpp/rbx_header.py tests/rbx/box/linters/test_rbx_header.py`
Expected: clean.

**Step 6: Commit**

```bash
git add rbx/box/linters/cpp/rbx_header.py tests/rbx/box/linters/test_rbx_header.py
git commit -m "$(cat <<'EOF'
feat(linters): add rbx-header linter detecting rbx.h in generators

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Self-register the linter

**Files:**
- Modify: `rbx/box/linters/__init__.py`
- Test: `tests/rbx/box/linters/test_rbx_header_registration.py`

The registry only knows linters whose modules were imported. `testlib` is imported in `__init__.py`; do the same for `rbx-header`.

**Step 1: Write failing test**

```python
# tests/rbx/box/linters/test_rbx_header_registration.py
import rbx.box.linters  # noqa: F401  (triggers self-registration)
from rbx.box.linters import registry
from rbx.box.linters.asset_kind import AssetKind


def test_rbx_header_is_registered_and_scoped_to_generators():
    linter = registry.get_linter('rbx-header')
    assert linter.name == 'rbx-header'
    assert linter.applies_to == {AssetKind.GENERATOR}
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/linters/test_rbx_header_registration.py -v`
Expected: FAIL — `get_linter` raises `RbxException` ("Unknown linter: rbx-header"), because the module was never imported.

**Step 3: Implement**

Current `rbx/box/linters/__init__.py`:
```python
from rbx.box.linters.cpp import testlib  # noqa: F401  (registers TestlibLinter)
```
Change to:
```python
from rbx.box.linters.cpp import rbx_header  # noqa: F401  (registers RbxHeaderLinter)
from rbx.box.linters.cpp import testlib  # noqa: F401  (registers TestlibLinter)
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/linters/test_rbx_header_registration.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/linters/__init__.py tests/rbx/box/linters/test_rbx_header_registration.py
git commit -m "$(cat <<'EOF'
feat(linters): register rbx-header linter on import

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: End-to-end behavior through the runner (scope, suppression, error)

**Files:**
- Test: `tests/rbx/box/linters/test_rbx_header_integration.py`

Mirror `tests/rbx/box/linters/test_testlib_integration.py`. The ERROR path raises `RbxException` (see `rbx/box/linters/runner.py:90-95`); `str(exc)` contains the printed message. Use the real linter through `runner.run_linters` with `find_language` monkeypatched, and through the pure `runner.run_linters_for_messages` for scope/suppression.

**Step 1: Write failing tests**

```python
# tests/rbx/box/linters/test_rbx_header_integration.py
import pytest

from rbx.box import code
from rbx.box.environment import LinterConfig
from rbx.box.exception import RbxException
from rbx.box.linters import runner
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.cpp.rbx_header import RbxHeaderLinter
from rbx.box.schema import CodeItem
from rbx.box.testing import testing_package

_OFFENDING = '#include "rbx.h"\nint main() { return 0; }\n'


def _cpp_language_with_linters(configs):
    base = code.find_language(CodeItem(path='x.cpp', language='cpp'))
    return base.model_copy(update={'linters': configs})


async def test_error_blocks_compile_for_generator(
    testing_pkg: testing_package.TestingPackage, monkeypatch
):
    cpp_file = testing_pkg.add_file('gen.cpp')
    cpp_file.write_text(_OFFENDING)
    code_item = CodeItem(path=cpp_file, language='cpp')

    language = _cpp_language_with_linters([LinterConfig(name='rbx-header')])
    monkeypatch.setattr('rbx.box.code.find_language', lambda _: language)

    with pytest.raises(RbxException) as exc_info:
        await runner.run_linters(code_item, AssetKind.GENERATOR)
    assert 'rbx.h' in str(exc_info.value)


def test_not_flagged_for_non_generator_kind():
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='rbx-header', applies_to=None)],
        linters=[RbxHeaderLinter()],
        kind=AssetKind.VALIDATOR,
        code=CodeItem(path='val.cpp'),
        source=_OFFENDING,
    )
    assert msgs == []


def test_suppressed_by_disable_directive_on_include_line():
    src = '#include "rbx.h"  // rbx-header-linter: disable\nint main() {}\n'
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='rbx-header', applies_to=None)],
        linters=[RbxHeaderLinter()],
        kind=AssetKind.GENERATOR,
        code=CodeItem(path='gen.cpp'),
        source=src,
    )
    assert msgs == []
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/linters/test_rbx_header_integration.py -v`
Expected: FAIL — at minimum `test_error_blocks_compile_for_generator` fails until the runner sees the registered linter (registration from Task 2 must be in place; the pure-function tests construct the linter directly and should pass once Task 1 exists).

> Note: `test_error_blocks_compile_for_generator` depends on `code.find_language`/`run_linters` resolving `rbx-header` via the registry — confirm Task 2 is committed. If the sandbox/compile environment is unavailable locally, `run_linters` itself does not compile (it only reads source + lints), so this test does not require a working sandbox.

**Step 3: No new implementation** — behavior comes from Tasks 1–2. If a test reveals a gap, fix the linter and re-run.

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/linters/test_rbx_header_integration.py -v`
Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add tests/rbx/box/linters/test_rbx_header_integration.py
git commit -m "$(cat <<'EOF'
test(linters): cover rbx-header scope, suppression and error path

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Enable by default in the bundled env

**Files:**
- Modify: `rbx/resources/presets/default/env.rbx.yml` (the `linters:` line under the `cpp` language — currently `linters: [testlib]`)

This file backs both the default preset and `get_app_environment_path('default')`, so editing it turns the check on by default.

**Step 1: Pre-flight — ensure no fixture generator would newly fail**

Run: `grep -rln --include='*.cpp' --include='*.cc' -E '#\s*include\s*[<"][^>"]*rbx\.h[>"]' rbx/testdata rbx/resources tests | grep -v -E 'val|check|interactor'`
Expected: no **generator** sources listed (validators/checkers/interactors legitimately use `rbx.h` and are out of scope). Investigate any hit that is a generator before proceeding.

**Step 2: Edit the env**

Change `    linters: [testlib]` to `    linters: [testlib, rbx-header]` under the `cpp` language entry.

**Step 3: Verify the env still parses**

Run: `uv run python -c "from rbx.box import environment as e; lang = e.get_environment('default'); cpp = next(l for l in lang.languages if l.name == 'cpp'); print([c.name for c in cpp.linters])"`
Expected: `['testlib', 'rbx-header']`.

**Step 4: Run the broader linter + environment test suites for regressions**

Run: `uv run pytest tests/rbx/box/linters tests/rbx/box/test_environment.py -q` (drop the second path if it does not exist)
Expected: PASS (no fixture regressions from the new default).

**Step 5: Commit**

```bash
git add rbx/resources/presets/default/env.rbx.yml
git commit -m "$(cat <<'EOF'
feat(env): enable rbx-header linter for C++ by default

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Troubleshooting docs page

**Files:**
- Create: `docs/generators-and-rbx-h.md`
- Modify: `mkdocs.yml` (the `Troubleshooting` nav block, around lines 64-68)

**Step 1: Write the docs page**

```markdown
# Generators and `rbx.h`

`rbx` refuses to build a problem when a **generator** depends on `rbx.h`. This
page explains why and how to proceed if you really need to.

## Why this is an error

`rbx.h` exposes `getVar<T>("NAME")`, which reads the problem's
[variables](setters/variables.md) — your constraints — at compile time. That is
exactly what a **validator** wants. A **generator** is different: its job is to
produce a fixed, reproducible testset.

If a generator reads a constraint through `getVar`, then changing that constraint
silently changes every test the generator produces — with no edit to the
generator and no warning. A test that used to stress `N = 10^5` quietly becomes
`N = 10^6` (or shrinks), solutions that were once correctly judged may flip, and
nothing in your diff hints at why.

### Example

```cpp
// gen_max.cpp — DON'T: depends on a constraint
#include "rbx.h"
#include "testlib.h"

int main(int argc, char* argv[]) {
    registerGen(argc, argv, 1);
    int n = getVar<int>("MAX_N");   // <-- silent dependency on MAX_N
    println(n);
    return 0;
}
```

Bump `MAX_N` in `problem.rbx.yml` and this generator now emits a different test,
invisibly. Instead, pass the size explicitly as a generator argument so the
testset is pinned by your generator calls:

```cpp
// gen_max.cpp — DO: size comes from the call
#include "testlib.h"

int main(int argc, char* argv[]) {
    registerGen(argc, argv, 1);
    int n = atoi(argv[1]);          // value is fixed by the generator call
    println(n);
    return 0;
}
```

```yaml
# problem.rbx.yml — the size lives with the call, visible in your diff
generators:
  - name: "gen_max"
    path: "gen_max.cpp"
# ...
  - generator: { name: "gen_max", args: "100000" }
```

## Escape hatches

If you understand the trade-off and still want a generator to use `rbx.h`:

- **For a single generator**, add the suppression directive after the include:

  ```cpp
  #include "rbx.h"  // rbx-header-linter: disable
  ```

- **For the whole package**, remove `rbx-header` from the `cpp` language's
  `linters` list in your `env.rbx.yml`:

  ```yaml
  - name: "cpp"
    # ...
    linters: [testlib]   # rbx-header removed
  ```
```

**Step 2: Add to the nav**

In `mkdocs.yml`, under `- "Troubleshooting":`, add an entry, e.g.:
```yaml
  - "Troubleshooting":
      - "Generators and rbx.h": "generators-and-rbx-h.md"
      - "cpp-on-macos.md"
      - "stack-limit.md"
      - "intro/windows-git.md"
      - "Migrating to rbx v1": "migrating-to-v1.md"
```

**Step 3: Verify the docs build (non-strict — see project note on pre-existing strict warnings)**

Run: `uv run mkdocs build 2>&1 | tail -20`
Expected: build succeeds; the new page resolves (ignore the ~9 pre-existing unrelated strict warnings).

**Step 4: Commit**

```bash
git add docs/generators-and-rbx-h.md mkdocs.yml
git commit -m "$(cat <<'EOF'
docs(troubleshooting): explain generators must not depend on rbx.h

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Full verification

**Step 1: Run the full linter suite + format/lint gate**

Run:
```bash
uv run pytest tests/rbx/box/linters -q
uv run ruff check . && uv run ruff format --check .
```
Expected: all linter tests pass; ruff clean.

**Step 2: Sanity-check the error message renders the docs URL and both hatches**

Run: `uv run python -c "from rbx.box.linters.cpp.rbx_header import RbxHeaderLinter; from rbx.box.schema import CodeItem; print(RbxHeaderLinter().lint(CodeItem(path='gen.cpp'), '#include \"rbx.h\"\n')[0].message)"`
Expected: message lists the `// rbx-header-linter: disable` hatch, the `env.rbx.yml` hatch, and the `rbx.rsalesc.dev/generators-and-rbx-h/` link.

**Step 3:** No commit (verification only). Then use superpowers:finishing-a-development-branch to open the PR referencing #386.

---

## Notes / gotchas

- `LinterMessage.message` is multi-line; the runner prints it after a `line:col` prefix under "Linter errors in …". That's fine.
- Detection is **direct include only** (confirmed). A generator hiding `rbx.h` behind a local header is intentionally not caught.
- The suppression directive is the framework's existing whole-file `is_linter_suppressed` mechanism (`rbx/box/linters/runner.py:34`); placing it on the include line is convention, not a separate code path.
- Per project memory: C++ compile/sandbox/checker tests fail pre-existingly on this machine. The new tests avoid the sandbox — `run_linters` lints source without compiling — so they are unaffected.
