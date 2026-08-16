# tests/rbx Suite Speedup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Cut `tests/rbx` wall time on 8 cores from ~3m15s to well under 1m30s by
eliminating redundant C++ compilation, without losing real-compiler coverage.

**Architecture:** The suite spends 76% of its time compiling C++, and 89% of
those compiles rebuild a source already built in the same run. The compile cache
key embeds absolute file paths, and every test runs in a fresh temporary package
directory, so the content-addressed global cache never hits. Phases 1-2 fix the
caching layer (production code, benefiting real users too); phases 3-5 remove
work the tests never needed.

**Tech Stack:** Python 3.14, pytest + pytest-xdist + pytest-asyncio (auto mode),
Pydantic v2, `uv` for dependency management, ruff for lint/format, commitizen for
commit messages.

**Background reading before starting:**
- `docs/plans/2026-08-14-test-suite-speed-design.md` -- the design and all
  measurements this plan implements.
- `rbx/grading/CLAUDE.md` -- how the grading engine, sandbox and caches fit
  together.
- `.claude/skills/commit.md` -- **required** commit message format. The
  pre-commit hook rejects non-compliant messages.

**Conventions you must follow:**
- Single quotes for strings (ruff enforces this).
- Absolute imports only; relative imports are banned (`TID` rule).
- Every commit message must be a conventional commit. Use the `/commit` skill.
- If the pre-commit hook rejects a commit, fix and make a NEW commit. Never amend.
- ruff auto-fixes import ordering on commit. If a commit fails with "files were
  modified by this hook", just `git add` the file again and re-commit.

**Important context about the current branch state:**

Commit `3306b98f` on this branch is an **unreviewed measurement spike** that
already contains the Phase 1 production change, but without a test or the
required cache-version bump. Task 1 reverts it so the work can be done
test-first. Do not skip that revert.

**How to measure:**

```bash
# Wall time for the whole suite (the number this plan optimises).
time uv run pytest tests/rbx -p no:randomly -n 8 -q
```

Baseline before any work: **196s wall, 992s CPU, 37 failed / 4512 passed.**

**There are ~36-37 pre-existing failures on this branch. They are out of scope.**
Never "fix" them. Only ever check that your change does not *increase* the
failure count. Record the count before and after each phase.

---

## Task 1: Revert the spike so Phase 1 can be done test-first

**Files:**
- Modify: `rbx/grading/caching.py`

**Step 1: Revert the spike commit**

```bash
git revert --no-edit 3306b98f
```

**Step 2: Verify the revert is clean**

Run: `git diff HEAD~1 HEAD --stat`
Expected: only `rbx/grading/caching.py` changed, 4 deletions.

Run: `grep -n 'digester.digest_file' rbx/grading/caching.py`
Expected: no output (the spike is gone).

---

## Task 2: Phase 1 -- content-address the compile cache key

The bug: `_build_cache_input` in `rbx/grading/caching.py:234-241` swaps a source
path for its content digest **only** when the file is a symlink into cacher
storage (`cacher.digest_from_symlink`). For any real file the absolute path
stays in the cache key, so two byte-identical files at different paths get
different keys.

**Files:**
- Modify: `rbx/grading/caching.py` (imports, and `_build_cache_input`)
- Test: `tests/rbx/grading/caching_test.py` (create)

**Step 1: Write the failing test**

Create `tests/rbx/grading/caching_test.py`. The fixtures `cleandir`,
`dependency_cache`, `file_cacher` and `sandbox` already exist in
`tests/rbx/grading/conftest.py` -- reuse them, do not write new ones.

```python
import pathlib

from rbx.grading import steps_with_caching
from rbx.grading.caching import DependencyCache
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    GradingArtifacts,
    GradingFileInput,
    GradingFileOutput,
    RunLogMetadata,
)


async def _run_from(
    src: pathlib.Path,
    out: pathlib.Path,
    sandbox: SandboxBase,
    dependency_cache: DependencyCache,
) -> GradingArtifacts:
    artifacts = GradingArtifacts()
    artifacts.inputs.append(
        GradingFileInput(src=src, dest=pathlib.Path('executable.py'))
    )
    artifacts.outputs.append(
        GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=out)
    )
    await steps_with_caching.run(
        'python3 executable.py',
        params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
        sandbox=sandbox,
        artifacts=artifacts,
        dependency_cache=dependency_cache,
        metadata=RunLogMetadata(),
    )
    return artifacts


async def test_cache_hits_for_identical_content_at_a_different_path(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    # Same bytes, two different absolute paths -- as happens when every test
    # copies its package into a fresh temporary directory.
    first = cleandir / 'a' / 'executable.py'
    second = cleandir / 'b' / 'executable.py'
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('print(7)')

    await _run_from(first, pathlib.Path('out-a.txt'), sandbox, dependency_cache)
    artifacts = await _run_from(
        second, pathlib.Path('out-b.txt'), sandbox, dependency_cache
    )

    assert (cleandir / 'out-b.txt').read_text().strip() == '7'
    assert artifacts.logs is not None
    assert artifacts.logs.cached


async def test_cache_misses_when_content_differs(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    first = cleandir / 'a' / 'executable.py'
    second = cleandir / 'b' / 'executable.py'
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_text('print(7)')
    second.write_text('print(8)')

    await _run_from(first, pathlib.Path('out-a.txt'), sandbox, dependency_cache)
    artifacts = await _run_from(
        second, pathlib.Path('out-b.txt'), sandbox, dependency_cache
    )

    assert (cleandir / 'out-b.txt').read_text().strip() == '8'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached
```

**Step 2: Run the tests to verify the first one fails**

Run:
```bash
uv run pytest tests/rbx/grading/caching_test.py -p no:randomly -v
```
Expected: `test_cache_hits_for_identical_content_at_a_different_path` FAILS on
`assert artifacts.logs.cached` (the cache misses because the paths differ).
`test_cache_misses_when_content_differs` PASSES already -- it is the guard rail
proving the fix does not over-cache.

**Step 3: Write the minimal implementation**

In `rbx/grading/caching.py`, add the import next to the existing digester import:

```python
from rbx.grading.judge import digester
```

Then in `_build_cache_input`, change the input loop body:

```python
            inferred_digest = await cacher.digest_from_symlink(input.src)
            if inferred_digest is None and input.src.is_file():
                # Key on content, not on the absolute path. Two byte-identical
                # files are interchangeable: the compiler command references
                # `dest`, which stays in the key, so nothing is lost.
                inferred_digest = digester.digest_file(input.src)
            if inferred_digest is not None:
                # Consume cache from digest instead of file.
                input.digest = DigestHolder(value=inferred_digest)
                input.src = None
```

**Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/rbx/grading/caching_test.py -p no:randomly -v`
Expected: both PASS.

**Step 5: Bump the cache version**

Existing on-disk caches were built with path-based keys and must be invalidated.
In `rbx/box/global_package.py:14`:

```python
CACHE_STEP_VERSION = 5
```

**Step 6: Run the full suite and compare against baseline**

Run: `time uv run pytest tests/rbx -p no:randomly -n 8 -q`

Expected: roughly **116s wall** (down from 196s), and **36 failed / 4513
passed** -- one *fewer* failure than baseline, because a previously failing test
starts passing. If the failure count is above 37, stop and investigate; you have
introduced a regression.

**Step 7: Commit**

```bash
git add rbx/grading/caching.py rbx/box/global_package.py tests/rbx/grading/caching_test.py
git commit -m "$(cat <<'EOF'
perf(grading): key the compile cache on content instead of path

The cache key embedded the absolute source path, so byte-identical files
at different paths never shared a cache entry. Every test runs in a fresh
temporary package directory, which meant the global compilation cache
could not hit even once across the suite.

Cuts tests/rbx from 196s to 116s on 8 workers and C++ compiles from 498
to 219. Bumps CACHE_STEP_VERSION to invalidate path-keyed entries.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Phase 2 -- materialize absent outputs instead of evicting

After Task 2, cache *keys* match across tests but 163 compiles are still
redundant (~200s CPU). The miss now happens in `_build_output_fingerprint_list`
(`rbx/grading/caching.py:164-177`): it digests each non-hash, non-intermediate
output at its `dest` path. In a fresh package that file does not exist yet, so
it fingerprints as `''`, `_output_fingerprints_match` fails, and `find_in_cache`
**evicts** the entry rather than restoring the artifact from storage.

**This task changes a cache-correctness invariant. Land it alone, and do not
combine it with any other task.** The behaviour that must be preserved: an
output that exists on disk but has been *modified* still evicts.

**Files:**
- Modify: `rbx/grading/caching.py` (`_output_fingerprints_match` / `find_in_cache`)
- Test: `tests/rbx/grading/caching_test.py` (extend)

**Step 1: Write the three failing/guard tests**

Append to `tests/rbx/grading/caching_test.py`. These cover the full matrix:

```python
async def test_cache_hits_when_output_is_absent(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    # An absent output means "not materialized yet", not "stale". It should be
    # restored from storage rather than forcing a rerun.
    src = cleandir / 'executable.py'
    src.write_text('print(11)')

    await _run_from(src, pathlib.Path('out.txt'), sandbox, dependency_cache)
    (cleandir / 'out.txt').unlink()

    artifacts = await _run_from(
        src, pathlib.Path('out.txt'), sandbox, dependency_cache
    )

    assert artifacts.logs is not None
    assert artifacts.logs.cached
    assert (cleandir / 'out.txt').read_text().strip() == '11'


async def test_cache_hits_when_output_is_present_and_matching(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    src = cleandir / 'executable.py'
    src.write_text('print(12)')

    await _run_from(src, pathlib.Path('out.txt'), sandbox, dependency_cache)
    artifacts = await _run_from(
        src, pathlib.Path('out.txt'), sandbox, dependency_cache
    )

    assert artifacts.logs is not None
    assert artifacts.logs.cached


async def test_cache_evicts_when_output_was_tampered_with(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    # This is the invariant Task 3 must NOT break.
    src = cleandir / 'executable.py'
    src.write_text('print(13)')

    await _run_from(src, pathlib.Path('out.txt'), sandbox, dependency_cache)
    (cleandir / 'out.txt').write_text('tampered\n')

    artifacts = await _run_from(
        src, pathlib.Path('out.txt'), sandbox, dependency_cache
    )

    assert artifacts.logs is not None
    assert not artifacts.logs.cached
    assert (cleandir / 'out.txt').read_text().strip() == '13'
```

**Step 2: Run them**

Run: `uv run pytest tests/rbx/grading/caching_test.py -p no:randomly -v`
Expected: `test_cache_hits_when_output_is_absent` FAILS on
`assert artifacts.logs.cached`. The other two PASS.

**Step 3: Implement**

Change the output-fingerprint comparison so an absent output (`''`) on the
*reference* side is treated as "materialize from storage", while a present but
differing fingerprint still evicts. Concretely, in `find_in_cache`, distinguish
the two cases rather than calling one `_output_fingerprints_match`:

```python
def _output_fingerprints_match(
    fingerprint: CacheFingerprint, reference: CacheFingerprint
) -> bool:
    """Compare stored and on-disk output fingerprints.

    An empty reference fingerprint means the output is simply not on disk yet
    -- the artifact is restored from content-addressed storage further down, so
    it must not evict. A non-empty fingerprint that differs means the file was
    modified behind our back, which must still evict.
    """
    lhs, rhs = fingerprint.output_fingerprints, reference.output_fingerprints
    if len(lhs) != len(rhs):
        return False
    return all(right == '' or left == right for left, right in zip(lhs, rhs))
```

Then confirm the existing `_copy_hashed_files` / `are_artifacts_ok` path
actually writes the missing file. If it does not cover non-hash outputs, extend
it to restore them from storage; the digests needed are already in
`fingerprint.digests`.

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/grading/caching_test.py -p no:randomly -v`
Expected: all five PASS.

**Step 5: Run the caching-adjacent suites**

Run:
```bash
uv run pytest tests/rbx/grading tests/rbx/box/code_compile_test.py \
  tests/rbx/box/code_compile_integration_test.py -p no:randomly -q
```
Expected: no *new* failures versus the pre-existing set.

**Step 6: Run the full suite**

Run: `time uv run pytest tests/rbx -p no:randomly -n 8 -q`
Expected: faster than Task 2's 116s; failure count no higher than 36.

**Step 7: Commit**

```bash
git add rbx/grading/caching.py tests/rbx/grading/caching_test.py
git commit -m "$(cat <<'EOF'
perf(grading): restore absent cached outputs instead of evicting

An output missing from disk means it has not been materialized yet, not
that the entry is stale, but the fingerprint check treated the two the
same and evicted. Every fresh package therefore recompiled sources whose
cache keys already matched. A present-but-modified output still evicts.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Phase 3 -- make jngen and tgen opt-in for test packages

`TestingPackage._declare_standard_libraries`
(`rbx/box/testing/testing_package.py:76-118`) declares testlib, jngen **and**
tgen as `always_include` libraries for every test package. Almost every test
only uses testlib, but all three headers get precompiled.

**Files:**
- Modify: `rbx/box/testing/testing_package.py:76-118`
- Modify: `tests/rbx/box/conftest.py` (only if a fixture needs the extra libs)

**Step 1: Find which tests actually need jngen or tgen**

Run:
```bash
grep -rln 'jngen\|tgen' tests/rbx
```
Note the list. `tests/rbx/box/test_header.py` and
`tests/rbx/box/test_libraries.py` are the likely users -- confirm rather than
assume.

**Step 2: Make the library set a parameter**

Change `TestingPackage.__init__` to accept `libraries: Sequence[str] = ('testlib',)`
and pass it through to `_declare_standard_libraries`, which filters `specs` to
the requested names. Keep the existing docstring -- especially the note that
`rbx/resources/predownloaded/{testlib,jngen,tgen}.h` must stay bundled as test
fixtures.

**Step 3: Give the tests that need them a way to ask**

Add a method so a test can opt in after construction:

```python
    def declare_library(self, name: str) -> None:
        """Declare an extra bundled header (jngen, tgen) for this package.

        Not declared by default: precompiling a ~180KB header costs ~1s, and
        almost every test only uses testlib.
        """
        self._declare_standard_libraries(self.preset, names=[name])
```

**Step 4: Run the tests that use jngen/tgen**

Run: `uv run pytest tests/rbx/box/test_header.py tests/rbx/box/test_libraries.py -p no:randomly -q`
Expected: they fail with a missing-header compile error until you add the
`declare_library` calls, then pass.

**Step 5: Run the full suite**

Run: `time uv run pytest tests/rbx -p no:randomly -n 8 -q`
Expected: faster still; failure count no higher than 36.

**Step 6: Commit**

```bash
git add rbx/box/testing/testing_package.py tests/rbx
git commit -m "$(cat <<'EOF'
test(box): declare only testlib by default in test packages

Every test package declared testlib, jngen and tgen as always-include
libraries, so all three ~180KB headers were precompiled even though
almost every test uses only testlib.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Phase 4a -- add Python program helpers

The contracts rbx enforces are protocol-only, so a Python program is an exact
substitute for a testlib C++ one, not an approximation:

- **Checker** (`rbx/box/checkers.py:210,255`): exit code in `{0,1,2,3}` plus the
  last line of stderr. 0 = accepted, 1/2 = wrong answer, 3 = judge failed.
- **Validator** (`rbx/box/validators.py:155,170`): exit code plus stderr. An
  optional `validator.log` carries the bounds overview, needed only by tests
  asserting on bounds coverage.
- **Generator**: writes to stdout.

Cost: compiling a testlib C++ program is 2.6s; running the Python equivalent is
0.02s and skips compilation entirely (`fileMapping.executable` maps to the
source, so `py` files are never compiled).

**Files:**
- Modify: `rbx/box/testing/testing_package.py`
- Test: `tests/rbx/box/testing/test_python_helpers.py` (create)

**Step 1: Write the failing test**

```python
from rbx.box.schema import ExpectedOutcome
from rbx.box.testing import testing_package


async def test_python_generator_echoes_its_argument(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_python_generator('gens/gen.py')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.py 123\n')

    from rbx.box.generators import generate_testcases

    await generate_testcases()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'
```

Add equivalent tests for `add_python_validator` (accepting and rejecting) and
`add_python_checker` (each of accepted / wrong answer / judge failed).

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/testing/test_python_helpers.py -p no:randomly -v`
Expected: FAIL with `AttributeError: 'TestingPackage' object has no attribute
'add_python_generator'`.

**Step 3: Implement the helpers**

Add to `TestingPackage`, mirroring the existing `add_generator` /
`add_solution` signatures so converted tests stay one-liners:

```python
    _PY_GENERATOR = """import sys

print(sys.argv[1])
"""

    _PY_VALIDATOR = """import sys

sys.stderr.write({message!r})
sys.exit({exit_code!r})
"""

    _PY_CHECKER = """import sys

sys.stderr.write({message!r})
sys.exit({exit_code!r})
"""

    def add_python_generator(self, path: PathOrStr) -> pathlib.Path:
        """A generator that echoes its first argument. Costs ~0.02s to run,
        versus ~2.6s to compile the testlib C++ equivalent."""
        ...

    def add_python_validator(
        self, path: PathOrStr, *, valid: bool = True, message: str = ''
    ) -> pathlib.Path:
        ...

    def add_python_checker(
        self,
        path: PathOrStr,
        *,
        outcome: Outcome = Outcome.ACCEPTED,
        message: str = 'ok',
    ) -> pathlib.Path:
        """Maps outcome to the testlib exit codes rbx parses: ACCEPTED -> 0,
        WRONG_ANSWER -> 1, JUDGE_FAILED -> 3."""
        ...
```

Write the source through the existing `self.add_file(path, ...)` machinery and
register the program in `self.yml` exactly as the C++ variants do.

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/box/testing/test_python_helpers.py -p no:randomly -v`
Expected: all PASS.

**Step 5: Commit**

```bash
git add rbx/box/testing/testing_package.py tests/rbx/box/testing/test_python_helpers.py
git commit -m "$(cat <<'EOF'
test(box): add Python generator, validator and checker helpers

rbx's checker and validator contracts are exit code plus stderr, so a
Python program is an exact substitute for a testlib C++ one. Running one
costs 0.02s against 2.6s to compile the C++ equivalent.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Phase 4b -- convert orchestration-only tests

Convert tests that only check *orchestration* -- was the generator invoked, was
the verdict routed, is the group wired up -- to the Python helpers. **Keep a
tagged set of real-C++ full-flow tests**: the compiler path, testlib integration
and the C++ toolchain must stay covered. The goal is a handful of genuine
end-to-end tests, not a hundred.

Work through these files in order of measured cost, **one file per commit**:

| File | Time | n | avg |
| --- | --- | --- | --- |
| `tests/rbx/box/generators_test.py` | 163.6s | 28 | 5.84s |
| `tests/rbx/box/validators_test.py` | 111.1s | 20 | 5.55s |
| `tests/rbx/box/solutions_test.py` | 106.2s | 64 | 1.66s |
| `tests/rbx/box/generator_outputs_test.py` | 89.6s | 11 | 8.15s |
| `tests/rbx/box/testcases/test_promote.py` | 71.7s | 22 | 3.26s |
| `tests/rbx/box/unit_test.py` | 145.6s | 20 | 7.28s |

**For each file:**

**Step 1: Time it before**

Run: `time uv run pytest <file> -p no:randomly -q`
Record the wall time and the failure count.

**Step 2: Identify the keepers**

Read the file. A test must **keep** real C++ when it asserts on any of:
compilation output or warnings, compilation failure messages, testlib-specific
behaviour (`registerGen`, `readInt` bounds, `quitf` formatting), sanitizers, or
language-specific timing. Everything else is a conversion candidate.

**Step 3: Convert one test, run it, then convert the rest**

Convert a single test first and run it. If the assertions still hold, convert
the remaining candidates in the file.

**Step 4: Run the file**

Run: `time uv run pytest <file> -p no:randomly -q`
Expected: substantially faster, and the failure count no higher than in Step 1.

**Step 5: Commit**

```bash
git add <file>
git commit -m "$(cat <<'EOF'
test(box): use Python programs for orchestration-only <area> tests

Keeps the tests that exercise the real compiler and testlib; the rest
only checked wiring and did not need a 2.6s C++ compile each.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Phase 5a -- compile test packages with -O0

Test packages copy the shipped preset verbatim (`TestingPreset.initialize`
copies `rbx/resources/presets/default/env.rbx.yml`), inheriting `-O2`. Measured
21% faster on `generators_test` before the cache fix.

**Files:**
- Modify: `rbx/box/testing/testing_preset.py` (`initialize`)

**Step 1: Override the optimisation level after copying the env**

Do **not** edit `rbx/resources/presets/default/env.rbx.yml` -- that is the file
shipped to users. Instead, in `TestingPreset.initialize`, after
`add_from_resources` copies the env, rewrite the C and C++ compilation commands
to use `-O0`:

```python
            # Tests do not measure generated-code quality, and -O0 roughly
            # halves the cost of compiling testlib-based programs.
            self._set_optimization_level('-O0')
```

Implement `_set_optimization_level` by loading the copied `env.rbx.yml`,
replacing `-O2` with the given flag in `languages[].compilation.commands` for
the `c` and `cpp` languages only, and writing it back. Leave the `boca`, `moj`
and `polygon` extension flags untouched -- packaging tests assert on those
exact strings.

**Step 2: Verify the packaging assertions still hold**

Run:
```bash
uv run pytest tests/rbx/box/packaging -p no:randomly -q
```
Expected: no new failures. If a packaging test now fails, you rewrote a flag
outside `languages[].compilation.commands`.

**Step 3: Add an opt-out for timing tests**

Any test that asserts on program performance must keep `-O2`. Check:

```bash
uv run pytest tests/rbx/box/test_timing_estimation.py \
  tests/rbx/box/test_timing_inference_run.py tests/rbx/box/walltime_test.py \
  -p no:randomly -q
```
If any fail, expose the level as a `TestingPreset` argument and have those tests
request `-O2`.

**Step 4: Run the full suite**

Run: `time uv run pytest tests/rbx -p no:randomly -n 8 -q`
Expected: faster; failure count no higher than 36.

**Step 5: Commit**

```bash
git add rbx/box/testing/testing_preset.py tests/rbx
git commit -m "$(cat <<'EOF'
test(box): compile test packages with -O0

Test packages inherited -O2 from the shipped preset. Tests do not measure
generated-code quality, and -O0 roughly halves compile cost for
testlib-based programs.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Phase 5b -- split the two tail tests

`test_get_solution_outcome_report` (44s) and `test_solutions` (41s) are 8.5% of
the suite on their own, and they are the xdist tail: the suite cannot finish
faster than its longest single test. At baseline, ideal wall time was 992/8 =
124s but actual was 196s, and this gap is why.

**Files:**
- Modify: `tests/rbx/box/solutions_test.py`

**Step 1: Confirm they are still the tail**

Run:
```bash
uv run pytest tests/rbx -p no:randomly -n 8 -q --durations=15
```
Note the current slowest tests. After Tasks 2-7 the ranking may have changed --
split whatever is actually longest now, not what this plan predicted.

**Step 2: Read the tests and find the seams**

These are broad tests asserting on many solutions at once. Split by the
independent thing each assertion covers (one test per outcome class, or per
solution group), sharing setup through a fixture so the split does not multiply
the compilation work.

**Step 3: Verify the split covers the same ground**

Run: `uv run pytest tests/rbx/box/solutions_test.py -p no:randomly -q`
Expected: the same assertions still run; failure count no higher than before.

**Step 4: Confirm the tail shrank**

Run: `uv run pytest tests/rbx -p no:randomly -n 8 -q --durations=15`
Expected: no single test dominates; wall time closer to CPU/8.

**Step 5: Commit**

```bash
git add tests/rbx/box/solutions_test.py
git commit -m "$(cat <<'EOF'
test(box): split the two longest solution tests

At 44s and 41s they were the xdist tail: the suite could not finish
faster than its longest single test, leaving seven workers idle.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Final verification and reporting

**Step 1: Full suite, fixed order**

Run: `time uv run pytest tests/rbx -p no:randomly -n 8 -q`
Record wall time and failure count.

**Step 2: Full suite, default random order**

Run: `time uv run pytest tests/rbx -n 8 -q`
Random ordering costs ~20% (measured 3m57s versus 3m15s at baseline). Confirm
no test depends on ordering after the caching changes -- the failure count must
match Step 1.

**Step 3: The canonical developer command**

Run: `time uv run mise run test`

**Step 4: Lint and format**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
```
Expected: clean.

**Step 5: Report**

State the before/after wall time, CPU time and failure count, and confirm the
failure count did not increase from the 37-failure baseline. Name explicitly any
phase that was skipped or only partly landed.

---

## Summary of expected gains

| Phase | Change | Expected |
| --- | --- | --- |
| 1 | Content-address the cache key | 196s -> 116s (measured) |
| 2 | Restore absent outputs | ~200s CPU recovered |
| 3 | Drop jngen/tgen by default | 2 of 3 header precompiles gone |
| 4 | Python programs for orchestration tests | 2.6s -> 0.02s per program |
| 5 | `-O0` plus tail split | ~21% on compile; closes the CPU/8 gap |

Target end state: comfortably under 90s wall on 8 cores, with compilation no
longer the dominant cost.
