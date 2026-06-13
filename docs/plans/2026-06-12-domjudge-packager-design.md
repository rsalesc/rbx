# DOMjudge packager design

`rbx package domjudge` builds a DOMjudge-importable problem zip. DOMjudge consumes the
ICPC problem package format plus a few DOMjudge-specific extensions
(`domjudge-problem.ini`, root-level `problem.pdf`, Kattis-protocol output validators).
The layout below follows what [pol2dom](https://github.com/dario2994/pol2dom) produces,
which is known to import cleanly.

Scope (v1): build the zip only. No upload, no contest-level packager, BATCH problems
only (rbx COMMUNICATION problems pair an interactor with a checker, which does not map
cleanly onto DOMjudge's single output validator; follow-up work).

## Zip layout

```
<shortname>-<name>.zip            # via BasePackager.package_basename()
├── domjudge-problem.ini          # short-name, name, timelimit (s), color (if any)
├── problem.yaml                  # limits: {memory MiB, output MiB}, validation[, validator_flags]
├── problem.pdf                   # main built statement PDF (omitted if no statements)
├── data/
│   ├── sample/001.in 001.ans …   # per-directory 3-digit counters
│   └── secret/001.in 001.ans …
├── output_validators/            # only when validation: custom
│   ├── checker.cpp               # flattened via flattening.build_flat_namespace
│   ├── <flattened deps…>
│   ├── testlib.h                 # patched for the DOMjudge/Kattis validator protocol
│   └── rbx.h
└── submissions/
    ├── accepted/…
    ├── wrong_answer/…
    ├── time_limit_exceeded/…
    └── run_time_error/…
```

## Decisions

- **Metadata split (pol2dom convention).** `domjudge-problem.ini` carries `short-name`
  (contest letter when available, else package name), `name` (statement title, `'`
  replaced by `` ` ``), `timelimit` in exact fractional seconds (no float rounding),
  and `color` when the problem belongs to a contest that assigns one. `problem.yaml`
  carries only `limits` (memory in MiB == rbx MB value; output rounded up from KB to
  MiB) and the validation settings.
- **Limits profile.** Limits come from `limits_info.get_limits(profile='domjudge')`,
  so an `rbx time -p domjudge` profile is honored but, unlike BOCA, not required —
  DOMjudge has a single per-problem time limit, so the package falls back to base
  package limits.
- **Checker.** The rbx checker is *always* shipped as a custom output validator
  (`validation: custom`), so DOMjudge judges with exactly the checker rbx uses
  locally — we never fall back to DOMjudge's default validators (review decision:
  always honor the rbx checker). This applies to builtins (`wcmp`, …) and user
  checkers alike. Shipped under `output_validators/`, flattened with its include
  closure (`checker.cpp` reserved name), plus `rbx.h` and a patched `testlib.h`.
  Checker must be C++ (testlib protocol), detected via
  `LanguageKind.CPP in environment.language_kinds(code.find_language(checker))`
  rather than file suffixes; other languages error.
- **testlib patch.** DOMjudge output validators speak the Kattis protocol (exit 42/43,
  feedback dir, team output on stdin), which vanilla testlib does not. We port
  pol2dom's runtime patch (originally from cn-xcpc-tools/testlib-for-domjudge) into
  `testlib_patch.py`: rewrite the `*_EXIT_CODE` defines, replace
  `registerTestlibCmd`/`registerInteraction` bodies, drop `skipBom()` calls. The patch
  is applied to rbx's bundled testlib at package time and fails loudly if an anchor is
  missing, so testlib upgrades that break it are caught by tests.
- **Solutions.** `submissions/` is part of the package format (DOMjudge judges them on
  import and flags verdict mismatches on the jury verifier page). *Every* solution is
  shipped — none dropped (review decision). DOMjudge derives the expected verdict from
  the submission directory name when it normalizes to a real verdict token, else honors
  an `@EXPECTED_RESULTS@` source annotation. So single-verdict outcomes go to the
  matching standard dir (ACCEPTED→accepted, WRONG_ANSWER→wrong_answer,
  TIME_LIMIT_EXCEEDED→time_limit_exceeded, RUNTIME_ERROR→run_time_error,
  OUTPUT_LIMIT_EXCEEDED→output_limit) with no annotation; multi-verdict outcomes
  (MEMORY_LIMIT_EXCEEDED→`RUN-ERROR, TIMELIMIT`, ACCEPTED_OR_TLE→`CORRECT, TIMELIMIT`,
  TLE_OR_RTE→`TIMELIMIT, RUN-ERROR`, INCORRECT→all non-`CORRECT`, ANY→all) go to
  `submissions/mixed/` (a non-verdict dir name, so the annotation survives) with a
  multi-token `@EXPECTED_RESULTS@` comment (`#` for Python else `//`). MLE is the one
  lossy case — DOMjudge has no memory-limit verdict. Basename collisions fall back to a
  `__`-joined relative path.
- **Statement.** Reuses the already-built PDF (`run_packager` builds statements before
  `package()`); the main statement (first, or `--language`) becomes `problem.pdf`.

## CLI

`rbx package domjudge [-l <language>]`, registered in `rbx/box/packaging/main.py` like
the other formats; guarded by `@package.within_problem`.

## Testing

`tests/rbx/box/packaging/test_domjudge.py` with the `testing_pkg` fixture:
- testlib patch applies to the bundled testlib (exit codes, function bodies, anchors)
  and raises on missing anchors;
- problem.yaml is always `validation: custom`; builtin and custom checkers both ship;
- custom checker flattening rewrites cross-directory includes (mirrors MOJ tests);
  non-C++ checker errors;
- submissions: single-verdict outcomes → standard dirs (no annotation), multi-verdict
  outcomes → `mixed/` with `@EXPECTED_RESULTS@` (Python `#` vs C++ `//`), collisions;
- full `package()` smoke test asserting the zip layout.
