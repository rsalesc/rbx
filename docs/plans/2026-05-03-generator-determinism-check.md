# Generator Determinism Check Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect non-deterministic generators (those not seeded by `argv`) by running each generator twice and comparing output digests; raise a hard error on mismatch when `VerificationLevel >= VALIDATE`.

**Architecture:** Inside `BuildTestcaseVisitor._visit` in `rbx/box/generators.py`, run the existing `generate_standalone` call concurrently with a second `run_item` invocation that streams stdout into a `DigestHolder`. After both finish, compare the disk-file digest with the holder's digest and raise `GenerationError` on mismatch. Gating is plumbed through `generate_testcases(..., verification: VerificationLevel)` from `builder.build()`; the visitor itself only sees a `check_determinism: bool`.

**Tech Stack:** Python 3, asyncio, Pydantic v2, pytest, Typer (rbx CLI), C++ generators using testlib.

**Design doc:** `docs/plans/2026-05-03-generator-determinism-check-design.md`

---

## Task 1: Add a non-deterministic test generator fixture

**Files:**
- Create: `rbx/testdata/generators/gen-nondet.cpp`

**Step 1: Create the C++ generator**

Mirror `rbx/testdata/generators/gen-id.cpp` but emit a value derived from a non-`argv` source so two runs reliably differ. Use `time(NULL)` plus the process PID and a tight loop nonce — the loop nonce guarantees divergence even if the two runs land in the same second.

```cpp
#include "testlib.h"
#include <ctime>
#include <unistd.h>

using namespace std;

int main(int argc, char *argv[]) {
  registerGen(argc, argv, 1);
  // Intentionally NOT seeded from argv: this generator is used in tests to
  // verify the determinism check. It must produce different output on
  // back-to-back runs.
  static int nonce = 0;
  unsigned long long v =
      (unsigned long long)time(NULL) ^
      (unsigned long long)getpid() ^
      (unsigned long long)(++nonce);
  cout << v << endl;
  return 0;
}
```

**Step 2: Verify the file compiles standalone (sanity check)**

Run: `ls rbx/testdata/generators/gen-nondet.cpp`
Expected: file listed.

The generator gets compiled inside the rbx sandbox during the actual tests; no separate compile step needed here.

**Step 3: Commit**

```bash
git add rbx/testdata/generators/gen-nondet.cpp
git commit -m "test(generators): add non-deterministic generator fixture"
```

---

## Task 2: Write failing test — non-determinism is detected at VerificationLevel.VALIDATE

**Files:**
- Modify: `tests/rbx/box/generators_test.py` (append a new test)

**Step 1: Add the failing test**

At the bottom of `tests/rbx/box/generators_test.py`, append:

```python
async def test_generator_determinism_check_detects_nondeterministic_generator(
    testing_pkg: testing_package.TestingPackage,
):
    from rbx.box.environment import VerificationLevel
    from rbx.box.generators import GenerationError

    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-nondet.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123\n')

    with pytest.raises(GenerationError):
        await generate_testcases(verification=VerificationLevel.VALIDATE)
```

**Step 2: Run the test, confirm it fails**

Run: `uv run pytest tests/rbx/box/generators_test.py::test_generator_determinism_check_detects_nondeterministic_generator -v`
Expected: FAIL — likely `TypeError: generate_testcases() got an unexpected keyword argument 'verification'` (no `verification` param yet).

**Step 3: Commit the failing test**

```bash
git add tests/rbx/box/generators_test.py
git commit -m "test(generators): add failing test for determinism check"
```

---

## Task 3: Plumb `verification` param through `generate_testcases`

**Files:**
- Modify: `rbx/box/generators.py` (signature of `generate_testcases` near line 421; visitor instantiation near line 467)
- Modify: `rbx/box/builder.py:45`

**Step 1: Add the import and parameter in `generators.py`**

At the top of `rbx/box/generators.py`, add to the existing `from rbx.box import (...)` block: ensure `environment` is importable. Add a dedicated import line:

```python
from rbx.box.environment import VerificationLevel
```

Change the `generate_testcases` signature from:

```python
async def generate_testcases(
    progress: Optional[StatusProgress] = None, groups: Optional[Set[str]] = None
):
```

to:

```python
async def generate_testcases(
    progress: Optional[StatusProgress] = None,
    groups: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
):
```

Just before the visitor instantiation (currently `visitor = BuildTestcaseVisitor(groups)` near line 467), compute the boolean:

```python
check_determinism = verification.value >= VerificationLevel.VALIDATE.value
```

(The visitor is updated in Task 4 to accept this parameter.)

**Step 2: Pass the value from `builder.build()`**

In `rbx/box/builder.py`, change line 45 from:

```python
await generate_testcases(s, groups=groups)
```

to:

```python
await generate_testcases(
    s, groups=groups, verification=VerificationLevel(verification)
)
```

`VerificationLevel` is already imported at line 5.

**Step 3: Run the (still-failing) test, confirm the failure mode changed**

Run: `uv run pytest tests/rbx/box/generators_test.py::test_generator_determinism_check_detects_nondeterministic_generator -v`
Expected: still FAIL, but no longer with `unexpected keyword argument`. It now fails because `GenerationError` is not raised — the determinism check is not yet implemented.

**Step 4: Commit**

```bash
git add rbx/box/generators.py rbx/box/builder.py
git commit -m "feat(generators): plumb VerificationLevel into generate_testcases"
```

---

## Task 4: Teach `BuildTestcaseVisitor` to take a `check_determinism` flag

**Files:**
- Modify: `rbx/box/generators.py` (around lines 437–468)

**Step 1: Update the visitor**

`BuildTestcaseVisitor` currently inherits its `__init__` from `TestcaseGroupVisitor` (instantiated as `BuildTestcaseVisitor(groups)`). Add an explicit `__init__` that captures the boolean and forwards `groups` to the parent:

```python
class BuildTestcaseVisitor(TestcaseGroupVisitor):
    def __init__(
        self,
        groups: Optional[Set[str]],
        *,
        check_determinism: bool = False,
    ):
        super().__init__(groups)
        self.check_determinism = check_determinism

    async def visit(self, entry: GenerationTestcaseEntry):
        ...
```

Update the visitor instantiation a few lines below to:

```python
visitor = BuildTestcaseVisitor(groups, check_determinism=check_determinism)
```

`_visit` is unchanged in this task; the flag is wired but not yet consumed.

**Step 2: Run the existing generator tests to confirm no regression**

Run: `uv run pytest tests/rbx/box/generators_test.py -v -k 'not nondeterministic'`
Expected: all existing tests PASS.

**Step 3: Commit**

```bash
git add rbx/box/generators.py
git commit -m "refactor(generators): add check_determinism flag to BuildTestcaseVisitor"
```

---

## Task 5: Implement the determinism check inside `_visit`

**Files:**
- Modify: `rbx/box/generators.py` (the `_visit` method around lines 442–465; add a new helper above it)

**Step 1: Add the helper that runs a generator into a `DigestHolder`**

Add this helper at module scope, somewhere above `generate_testcases` (e.g. just after `_compile_generator` near line 60):

```python
async def _run_generator_to_digest(
    generator: CodeItem,
    generator_digest: str,
    args: Optional[str],
) -> str:
    """Run a generator with stdout captured into a DigestHolder and return the digest.

    Used by the determinism check: re-runs a generator with the same args as a
    prior invocation and returns the digest of its stdout, without touching the
    on-disk testcase file.
    """
    holder = DigestHolder()
    log = await run_item(
        generator,
        DigestOrSource.create(generator_digest),
        stdout=DigestOrDest.create(holder),
        extra_args=args or None,
    )
    if not log or log.exitcode != 0 or holder.value is None:
        raise GenerationError(
            f'Determinism re-run of generator {generator.path} failed '
            f'(exit={None if log is None else log.exitcode}).'
        )
    return holder.value
```

**Step 2: Update `_visit` to run both invocations in parallel and compare**

Replace the `elif entry.metadata.generator_call is not None:` branch (currently lines 453–461) with:

```python
elif entry.metadata.generator_call is not None:
    call = entry.metadata.generator_call
    generator_digest = compiled_generators[call.name]
    primary = generate_standalone(
        entry.metadata,
        group_entry=entry.group_entry,
        validate=False,
        generator_digest=generator_digest,
    )
    if self.check_determinism:
        verify = _run_generator_to_digest(
            package.get_generator(call.name),
            generator_digest,
            call.args,
        )
        _, verify_digest = await asyncio.gather(primary, verify)
    else:
        await primary
        verify_digest = None
```

Then, after the existing `assert entry.metadata.copied_to.inputPath.is_file()` line, before the `return digest_file(...)`:

```python
first_digest = digest_file(entry.metadata.copied_to.inputPath)
if verify_digest is not None and verify_digest != first_digest:
    raise GenerationError(
        f'Generator [item]{call.name}[/item] with args [item]{call.args}[/item] '
        f'is non-deterministic: two runs produced different output. '
        f'This usually means the generator is not seeded from its argv.'
    )
return first_digest
```

(Remove the previous `return digest_file(entry.metadata.copied_to.inputPath)` line — it is replaced by the block above.)

Note: `verify_digest` must be defined on every code path through `_visit` before the comparison. For the `copied_from` and `content` branches, set `verify_digest = None` at the start of those branches, or hoist `verify_digest = None` to the top of `_visit`.

**Step 3: Run the failing test, confirm it now passes**

Run: `uv run pytest tests/rbx/box/generators_test.py::test_generator_determinism_check_detects_nondeterministic_generator -v`
Expected: PASS.

**Step 4: Run the full generators test file to confirm no regressions**

Run: `uv run pytest tests/rbx/box/generators_test.py -v`
Expected: all tests PASS.

**Step 5: Commit**

```bash
git add rbx/box/generators.py
git commit -m "feat(generators): check determinism by re-running generators"
```

---

## Task 6: Add the positive-path test (deterministic generator passes)

**Files:**
- Modify: `tests/rbx/box/generators_test.py`

**Step 1: Append the test**

```python
async def test_generator_determinism_check_passes_for_deterministic_generator(
    testing_pkg: testing_package.TestingPackage,
):
    from rbx.box.environment import VerificationLevel

    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123\n')

    # Should not raise.
    await generate_testcases(verification=VerificationLevel.VALIDATE)

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'
```

**Step 2: Run the test**

Run: `uv run pytest tests/rbx/box/generators_test.py::test_generator_determinism_check_passes_for_deterministic_generator -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/rbx/box/generators_test.py
git commit -m "test(generators): cover deterministic generator passes the check"
```

---

## Task 7: Add the gating test (no check at VerificationLevel.NONE)

**Files:**
- Modify: `tests/rbx/box/generators_test.py`

**Step 1: Append the test**

```python
async def test_generator_determinism_check_skipped_at_verification_none(
    testing_pkg: testing_package.TestingPackage,
):
    from rbx.box.environment import VerificationLevel

    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-nondet.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123\n')

    # No verification → no determinism check → no error even though the
    # generator is non-deterministic.
    await generate_testcases(verification=VerificationLevel.NONE)
```

**Step 2: Run the test**

Run: `uv run pytest tests/rbx/box/generators_test.py::test_generator_determinism_check_skipped_at_verification_none -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/rbx/box/generators_test.py
git commit -m "test(generators): cover that determinism check is gated by verification"
```

---

## Task 8: Final verification

**Step 1: Run the full generators test file**

Run: `uv run pytest tests/rbx/box/generators_test.py -v`
Expected: all tests PASS.

**Step 2: Run the broader fast test suite**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: all tests PASS (or pre-existing failures unrelated to this change).

**Step 3: Lint and format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors. If formatting differs, run `uv run ruff format .` and amend.

**Step 4: Final commit (only if Step 3 produced reformatting)**

```bash
git add -u
git commit -m "style: apply ruff format"
```
