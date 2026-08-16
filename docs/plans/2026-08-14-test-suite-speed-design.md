# Speeding up the `tests/rbx` suite

Date: 2026-08-14

## Summary

The `tests/rbx` suite spends **76% of its time compiling C++**, and **89% of
those compiles rebuild a source that was already compiled earlier in the same
run**. The redundancy is caused by a cache key that embeds absolute file paths,
so the content-addressed global compilation cache can never hit across tests
(each test runs in a fresh temporary package directory).

Fixing the cache key is a five-line change to production code. Measured on the
full suite it cuts wall time by 41% and introduces no regressions.

This document records the measurements, the root cause, and a five-phase plan.

## Baseline measurements

All numbers from one machine: 8 cores, macOS 14.6, Apple clang 15.0.0,
`uv run pytest`, `-p no:randomly` unless noted.

| Command | Wall time |
| --- | --- |
| `pytest tests/rbx -n 8` (fixed order) | 3m15s |
| `pytest tests/rbx -n 8` (default random order) | 3m57s |
| `mise run test` (`-n auto`, whole tree) | 3m35s |
| `mise run test-cov` (serial + coverage, the CI command) | 10m13s |

`mise run test-cov` passes no `-n`, so CI runs single-threaded. That is the only
path above ten minutes. A reported 25-minute figure could not be reproduced on
this machine for any parallel invocation; the design targets the parallel path.

### Where the time goes

Total CPU across `tests/rbx` is 992s (wall 196s on 8 workers). Every subprocess
the sandbox spawns was instrumented by wrapping `Program.wait`:

| Kind | Time | n | Share of suite |
| --- | --- | --- | --- |
| C++ compilation | 756s | 498 | 76% |
| Program execution (all languages) | 99s | 512 | 10% |
| Python / pytest overhead | ~135s | -- | 14% |

Actually *running* programs -- including the deliberately slow and TLE ones --
is 10% of the suite. Compilation dominates.

### Concentration

123 tests (2.7% of 4553) account for 86% of runtime. The remaining 4430 tests
cost ~140s combined.

| Slice | Time | Share |
| --- | --- | --- |
| top 10 tests | 182s | 18.4% |
| top 25 tests | 331s | 33.4% |
| top 50 tests | 541s | 54.5% |
| top 100 tests | 822s | 82.9% |

Two tests alone are 8.5%: `test_get_solution_outcome_report` (44s) and
`test_solutions` (41s). Ideal wall time at perfect balance would be 992/8 =
124s; actual is 196s. The gap is the xdist tail -- one worker still running a
40s test while seven idle.

### Compilation cost primitives

| Program | Compile time |
| --- | --- |
| trivial `int main(){}` | 0.07s |
| `#include <iostream>` a+b | 0.34s |
| testlib.h generator, `-O2` | 2.61s |
| testlib.h generator, `-O0` | 1.45s |
| testlib.h generator, `-O2`, with PCH | 2.07s |
| equivalent Python program (no compile) | 0.02s |

testlib's cost is template instantiation and codegen, not preprocessing
(`-E` alone is 0.13s). That is why a precompiled header saves only ~0.5s of
2.6s, and why `-O0` is the more effective lever.

## Root cause

Of 498 C++ compiles, only **56 are distinct source blobs**. 442 compiles (89%)
rebuild a blob already compiled elsewhere in the run, worth ~614s -- 62% of the
suite's total CPU.

The three most-recompiled blobs are compiled **98 times each**: they are
`testlib.h` (207KB), `jngen.h` (183KB) and `tgen.h` (170KB), built as
precompiled headers by `_precompile_header` in `rbx/box/code.py`. That is ~350s,
**35% of the whole suite**, spent re-precompiling three headers.

A global, content-addressed PCH cache exists (`rbx/box/global_package.py`) and
is correctly session-scoped in tests (`clear_all_functools_cache` deliberately
excludes `global_package`). It never hits. Diffing the cache key input between
two consecutive tests in the same process:

```
-  "src": ".../cleandir0/pkg/.rbx/.preprocessed/.local.rbx/libs/testlib/testlib.h",
+  "src": ".../cleandir1/pkg/.rbx/.preprocessed/.local.rbx/libs/jngen/jngen.h",
   "digest": null,
```

`_build_cache_input` (`rbx/grading/caching.py:234-241`) replaces a source path
with its content digest **only when the file is a symlink into cacher storage**
(`cacher.digest_from_symlink`). The preprocessed headers are real copies, so the
absolute path stays in the key. Each test uses a fresh temporary package
directory, so the key differs every time.

Measured on three consecutive tests: 5, 4 and 4 compiles respectively,
`cache hit=2 miss=17`.

Two factors compound it. `testing_package._declare_standard_libraries` declares
testlib **and** jngen **and** tgen for every test package, so a test whose
generator only uses testlib still pays to precompile all three.

This is a production defect, not only a test-speed one: a path-keyed "global"
cache misses for real users whenever the package path changes.

## Phase 1 -- Content-address the compile cache key

In `_build_cache_input`, fall back to hashing file contents when
`digest_from_symlink` yields nothing:

```python
inferred_digest = await cacher.digest_from_symlink(input.src)
if inferred_digest is None and input.src.is_file():
    inferred_digest = digester.digest_file(input.src)
if inferred_digest is not None:
    input.digest = DigestHolder(value=inferred_digest)
    input.src = None
```

Keying on `(dest, content digest)` is strictly more precise than
`(dest, source path)`: the compiler command references `dest`, which is
preserved, so two identical files under different paths are genuinely
interchangeable.

Requires a `CACHE_STEP_VERSION` bump (`rbx/box/global_package.py`) to invalidate
existing user caches.

### Validated result

Prototyped and measured on the full suite:

| Metric | Before | After |
| --- | --- | --- |
| Wall (`-n 8`) | 196s | **116s** (-41%) |
| CPU | 992s | 578s (-42%) |
| C++ compiles | 498 | 219 (-56%) |
| Compile time | 756s | 363s (-52%) |
| testlib/jngen/tgen precompiles | 98x each | 7x each |
| Worst file (`generators_test`) | 107.4s | 56.6s (-47%) |
| Failures | 37 | **36** |

The three headers now compile roughly once per xdist worker, which is the
correct floor for 8 independent worker processes. Failures went *down* by one:
a previously failing test now passes. No new failures.

## Phase 2 -- Recover the remaining 163 redundant compiles

After Phase 1, 219 compiles remain over 56 distinct blobs -- still 163
redundant, ~200s of CPU. The remaining offenders are the small testlib
generators and validators in `rbx/testdata/` (one 167-byte generator is compiled
36 times, costing 98s).

The cache *keys* already match: two consecutive tests were verified to produce
byte-identical cache inputs.

**This section originally blamed `_build_output_fingerprint_list` and proposed
relaxing its eviction rule. That diagnosis was wrong, and the proposed fix would
have been a no-op that deleted a dormant safety check.** It is recorded here
because the correction is the useful part.

`_build_output_fingerprint_list` skips every output that is `hash`,
`intermediate`, or has no `dest`. `GradingFileOutput.hash` defaults to `True`
(`rbx/grading/steps.py:193`) and nothing in `rbx/` ever sets it `False` on an
output -- the single `hash=False` in the tree (`rbx/box/code.py:602`) is on a
`GradingFileInput`. The list is therefore structurally always empty, so
`_output_fingerprints_match` is always trivially true and evicts nothing.

Instrumenting every miss branch of `find_in_cache` over a real compile-heavy run
settled it:

```
key_lookup: 175   key_HIT: 109   key_MISS: 66
input_fingerprint_MISMATCH: 0
output_fingerprint_MISMATCH: 0
artifacts_NOT_OK: 0
```

No entry is evicted by any post-key validation. All 66 misses are **cold** --
the key is simply absent from the database. The cause is fixture layout, not
cache correctness: `cleandir` mints a fresh `tmp_path` per test, and the
problem-level `DependencyCache` and `FilesystemStorage` live under
`<problem>/.rbx` (`rbx/box/package.py`), so every test starts with an empty
cache DB and an empty content-addressed store. Only the precompilation cache is
session-scoped, which is exactly why Phase 1 moved the header precompiles from
98x to 7x while ordinary program compiles kept repeating.

**Actual fix: a session-wide problem dependency cache and storage in the test
fixtures**, mirroring what `precompilation_should_use_tmp_cache` already does.
This is a test-only change and safe *because* Phase 1 made keys
content-addressed rather than path-addressed.

### Sharing is opt-in, not the default

It was first built as the default, with an opt-out. That was rejected on review,
and rightly: sharing a compile cache across problems by default weakens
isolation everywhere, and a future bug in cache keying would mask itself across
the whole suite rather than failing loudly in one place. Correctness defaults
should be conservative; speed is the thing to opt into.

So the default is a per-problem cache -- exactly the pre-existing behaviour --
and a `shared_cache` marker opts specific modules in. It is applied only where
the measured gain is large *and* the tests do not depend on a compile actually
running:

| File | Isolated | Shared | Marked |
| --- | --- | --- | --- |
| `solutions_test.py` | 83.8s | 41.8s | yes |
| `unit_test.py` | 62.1s | 18.5s | yes |
| `validators_test.py` | 61.2s | 28.4s | yes |
| `generators_test.py` | 57.8s | 21.0s | yes, 1 test opts out |
| `generator_outputs_test.py` | 32.1s | 13.1s | yes, 2 tests opt out |
| `testcases/test_promote.py` | 23.1s | 8.8s | yes |
| `test_header.py` | 30.8s | 28.4s | no -- compiles via raw `g++` |
| `code_run_test.py` | 15.0s | 13.5s | no -- gain too small |
| `checkers_test.py` | 8.5s | 6.7s | no -- see below |
| `code_compile_integration_test.py` | 7.2s | 6.9s | no -- real-compile coverage |

The three tests that opt back out individually are the ones asserting on
compilation output or failure messages, which a warm cache would turn into
silent hits.

Cost of keeping isolation everywhere else: about 10s (roughly 60s -> 70s),
against ~119s with no sharing at all.

### A trap worth knowing about

`maybe_shared_problem_cache` is function-scoped, so the shared cache is only
installed for the duration of each test. A **module- or session-scoped fixture
that compiles runs before it**, writing into the isolated per-problem storage;
the marked tests then look for that digest in the shared storage and fail with
an opaque `KeyError: 'File not found.'`.

`checkers_test.py` is the live example -- marking it fails 14 of its 43 tests,
because `pkg_with_compiled_checker` is `scope='module'`. This is a property of
the opt-in mechanism, not evidence that sharing is unsafe for those tests: under
the original session-scoped-autouse version they passed. It costs nothing here,
since sharing was only worth 1.8s in that file. The constraint is documented on
the marker and in the fixture docstring.

Measured: `generators_test.py` 57.8s -> 21.0s on the marked path.

## Phases 3 and 4 -- descoped after re-measuring

**Not implemented.** Phases 1 and 2 changed the profile they were sized against,
so they were re-measured and dropped rather than executed on stale numbers.

After Phases 1-2, suite CPU fell from 992s to 351s and the number of tests over
3s fell from 108 to 22. Compilation is no longer the dominant cost, because
almost every compile is now a cache hit:

- **Phase 3** (jngen/tgen opt-in) targeted header precompiles that Phase 1
  already took from 98x to 7x each. Remaining value ~2s of wall time.
- **Phase 4** (Python programs for orchestration tests) targeted a 2.6s C++
  compile per program that is now a cache hit. It would have touched ~100 tests
  and traded away real-compiler coverage for a few seconds.

Both remain reasonable ideas if the profile shifts again; neither earns its
churn today. The analysis is kept below for that case.

### Phase 3 (not implemented) -- stop declaring libraries tests do not use

`testing_package._declare_standard_libraries` declares testlib, jngen and tgen
for every test package. Almost every test uses only testlib. Make jngen and tgen
opt-in via an argument to `TestingPackage`.

### Phase 4 (not implemented) -- Python program helpers

The contracts rbx enforces are protocol-only, so Python equivalents are exact
substitutes rather than approximations:

- **Checker**: exit code in `{0,1,2,3}` plus the last line of stderr.
  `_is_checker_exitcode` and `process_checker_run_log`
  (`rbx/box/checkers.py:210,255`). 0 = AC, 1/2 = WA, 3 = judge failed.
- **Validator**: exit code plus stderr (`rbx/box/validators.py:155,170`). An
  optional `validator.log` carries the bounds overview, needed only by tests
  that assert on bounds coverage.
- **Generator**: writes to stdout.

Cost per program: 2.6s to compile a testlib C++ program versus 0.02s to run a
Python one, which skips compilation entirely (`fileMapping.executable` maps to
the source).

Add helpers to `TestingPackage` so converted tests stay one-liners rather than
growing inline source blobs:

- `add_python_generator(path, *, echoes_argv=...)`
- `add_python_validator(path, *, verdict=..., message=...)`
- `add_python_checker(path, *, verdict=..., message=...)`

Convert tests that only exercise orchestration (does the generator get invoked,
is the verdict routed correctly, is the group wired up). **Deliberately retain a
tagged set of real-C++ full-flow tests** so the compiler path, testlib
integration, and the C++ toolchain stay covered. The goal is a handful of real
end-to-end tests, not a hundred.

Correcting the ~36 pre-existing failures is explicitly out of scope.

## Phase 5 -- the tail split

**`-O0` in the test environment: not implemented.** It measured 21% faster on
`generators_test` before the cache fixes, but compiles are cache hits now, so
there is little compilation left to make cheaper.

**Split the mega-tests: implemented, with a caveat.** `test_solutions` and
`test_get_solution_outcome_report` each ran all seven `problems/box1` solutions
in one shot; they are now seven tests, one per solution, sharing setup through a
fixture. All 22 original assertions were mapped 1:1 onto the new tests.

The caveat is honest: this was predicted to be worth ~15s of wall time and
delivered ~3s, inside this machine's run-to-run noise. At 8 workers the suite is
CPU-bound, not tail-bound -- 351s of CPU over 8 workers plus per-worker startup
and collection already puts the floor near 55s, so removing the 30s test mostly
removed slack. It costs ~3s of extra CPU (~1%) because shared setup now runs
seven times instead of two.

It was kept for structure rather than speed: seven tests named for the outcome
they check beat two grab-bags, and it removes a serialisation point that would
bite on more workers or faster hardware. Revert it cleanly if that trade is
unwanted.

## Out of scope

- Adding `-n auto` to `mise run test-cov`. Considered and declined.
- Fixing the 36-37 pre-existing test failures.
- The `tests/e2e`, `tests/casts` and `tests/docker` suites.

## Outcome

| Run | Before | After |
| --- | --- | --- |
| `tests/rbx -n 8`, fixed order | 196s | **69-78s** |
| Suite CPU | 992s | 351s |
| C++ compiles | 498 | 219 |
| Tests over 3s | 108 | 22 |

(An earlier revision shared the cache globally and reached ~60s. Restoring
per-problem isolation by default costs ~10s of that, deliberately.)

Failure count did not increase: 37 failed / 4512 passed before, 36 failed /
4520 passed after in fixed order (37 in random order, matching its own
baseline). The extra passes are the new cache tests and the solution split.

Two commits produced essentially all of the gain, and both are production
caching fixes that benefit real users, not just the test suite.
