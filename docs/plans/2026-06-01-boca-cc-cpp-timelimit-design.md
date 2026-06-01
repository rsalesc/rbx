# BOCA cc/cpp limit lookup fix (#493)

## Problem

In older BOCA installs, C++20 is named `cc`; newer ones use `cpp`. rbx supports
both, and the default preset aliases the rbx `cpp` language onto **both** BOCA
variants (`languages: ["cc", "cpp"]`, introduced for #453). The BOCA packager
therefore emits a `limits/<lang>` script for each variant.

The time/memory limit for a variant is looked up by passing the **BOCA** language
name straight into `limits_info.get_limits(language, profile='boca')`
(`packager.py:115`, `:120`). That bottoms out in
`LimitsProfile.timelimit_for_language` / `memorylimit_for_language`
(`schema.py:799`, `:812`), whose modifier lookup (`if language in self.modifiers`)
is keyed by **rbx** language names.

So when a package has a `cpp` modifier:

- `cpp` lookup finds the modifier → modified limit.
- `cc` lookup finds nothing → falls back to the base limit.

`limits/cc` and `limits/cpp` end up with different limits even though both are the
same underlying C++ compiler. Reproduced:

```
TL queried as 'cpp': 2000   # modifier applied
TL queried as 'cc' : 1000   # modifier missed, base fallback
```

## Fix

Reverse-map the emitted BOCA name to its underlying rbx language *before* the
limits lookup, using the existing `get_rbx_language_from_boca_language()` helper
(`boca_language_utils.py`, from #453). It maps `cc`→`cpp` and returns any
non-aliased name unchanged, so:

- both `cc` and `cpp` read the same rbx `cpp` entry → identical limits;
- `c`, `java`, `py3`, etc. are unaffected (no-op translation);
- it generalises to any future BOCA aliasing.

Applied in `BocaPackager._get_pkg_timelimit` and `_get_pkg_memorylimit`. Covers
both time and memory. `MojPackager` extends `BocaPackager` and inherits both
methods, so it is fixed for free. Polygon passes `None` and is untouched. The
limits layer (`limits_info` / `LimitsProfile`) stays packager-agnostic — BOCA
aliasing knowledge lives only where the BOCA names originate.

## Testing

### Fast unit regression

A packager-level test asserting
`_get_pkg_timelimit('cc') == _get_pkg_timelimit('cpp')` and the memory
equivalent, under the default-preset env (cpp→`["cc","cpp"]`) with a package
that declares a `cpp` modifier. Fails today, passes after the fix.

### e2e regression (per request)

The unzipped limit scripts live in a `tempfile.TemporaryDirectory` and are
deleted after zipping (`packaging/packager.py:283`); only the zip persists. The
bug therefore lives in zip **entry content**, which the e2e DSL cannot currently
assert (`zip_contains` checks presence only).

**New `zip_file_contains` matcher.** Mirrors `file_contains`'s substring/regex
semantics but reads a named entry out of a zip:

```yaml
expect:
  zip_file_contains:
    path: build/*.zip
    entries:
      limits/cc:  "echo 512"
      limits/cpp: "echo 512"
```

Touch points (each mirrors an existing pattern):

- `tests/e2e/spec.py`: `ZipFileMatcher` (`path: str`, `entries: Dict[str,str]`)
  + `Expect.zip_file_contains`.
- `tests/e2e/assertions.py`: `check_zip_file_contains`, reusing a `_match_text`
  helper factored out of `check_file_contains` (no behavior change to the latter).
- `tests/e2e/runner.py`: register in `_GENERIC_CHECKS`.
- `tests/e2e/test_assertions.py`: unit tests (hit, miss, regex, missing entry,
  missing zip).
- `tests/e2e/README.md`: schema-reference entry.

**Fixture.** Extend `tests/e2e/testdata/pkg-boca/`: add a `cpp` modifier to
`problem.rbx.yml` — primarily a **memory** override (e.g. `cpp: {memory: 512}`
over base 256), since memory is echoed verbatim with no rounding, giving a clean
exact assertion. A new scenario runs `build` → `time -s inherit -p boca` →
`pkg boca` and asserts both `limits/cc` and `limits/cpp` echo the modified
memory. A `cpp` time modifier is also added, with its emitted TL line pinned
empirically (time goes through BOCA's run-count rounding). The existing scenario
only checks entry presence, so the added modifier does not perturb it.

## Build order (TDD)

1. Failing unit test → core fix → green.
2. `zip_file_contains` matcher (+ its unit tests) → green.
3. Extend `pkg-boca` fixture + new scenario; confirm it fails before the core
   fix and passes after.
4. Run BOCA packaging suite + e2e.
