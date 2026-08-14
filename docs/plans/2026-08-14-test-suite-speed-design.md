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
byte-identical cache inputs. The miss happens later, in
`_build_output_fingerprint_list` (`rbx/grading/caching.py:164-177`). It digests
each non-hash, non-intermediate output at its `dest` path. In a fresh package
the compiled binary does not exist yet, so it fingerprints as `''`, mismatches
the stored fingerprint, and `find_in_cache` **evicts the entry** rather than
materializing the artifact from storage.

Fix: when the only discrepancy is that an output is absent, materialize it from
content-addressed storage instead of evicting.

This is the subtlest change in the plan -- it modifies the invariant that
guarantees on-disk artifacts are current. Land it isolated, with its own tests
covering: output absent (materialize), output present and matching (hit),
output present but modified (evict, as today).

## Phase 3 -- Stop declaring libraries tests do not use

`testing_package._declare_standard_libraries` declares testlib, jngen and tgen
for every test package. Almost every test uses only testlib. Make jngen and tgen
opt-in via an argument to `TestingPackage`.

Independent of Phases 1-2, and removes two-thirds of header precompilation even
if those phases regress.

## Phase 4 -- Python program helpers, and convert the obvious tests

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

## Phase 5 -- Two cheap wins

**`-O0` in the test environment.** Test packages copy the shipped preset
`env.rbx.yml` verbatim (`TestingPreset.initialize` copies
`presets/default/env.rbx.yml`), inheriting `-O2`. Overriding the C and C++
compilation commands to `-O0` in the test preset measured 21% faster on
`generators_test` before the cache fix. Test-only; tests that assert on program
performance must opt out.

**Split the two mega-tests.** `test_get_solution_outcome_report` (44s) and
`test_solutions` (41s) are the xdist tail. The suite cannot finish faster than
its longest single test, so splitting them is what closes the 196s-versus-124s
gap.

## Out of scope

- Adding `-n auto` to `mise run test-cov`. Considered and declined.
- Fixing the 36-37 pre-existing test failures.
- The `tests/e2e`, `tests/casts` and `tests/docker` suites.

## Expected outcome

Phase 1 alone is validated at 196s -> 116s. With Phases 2-5, compilation should
stop being the dominant cost and wall time should land well under 90s on 8
cores, with the tail-latency fix mattering proportionally more as total CPU
falls.
