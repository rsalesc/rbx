# BocaNext: a Python-based BOCA packager

Date: 2026-05-29
Issue: https://github.com/rsalesc/rbx/issues/488

## Motivation

The current BOCA packager (`rbx/box/packaging/boca/`) emits per-language **bash**
scripts from templates in `rbx/resources/packagers/boca/`. There are 7 `compile`
scripts (130–1200 lines each), 7 `run`, 7 `interactive`, plus shared
`compare.sh`, `checker.sh`, `interactor_*.sh`, `safeexec_compile.sh`,
`pipe_compile.sh`. ~80% of the compile/run/interactive content is duplicated
boilerplate (bocajail user detection, safeexec parameter assembly, chroot
mount/unmount, MD5 compile caching). It is hard to read, hard to test, and
hard to extend.

BOCA does not require these scripts to be bash. `autojudging.php` runs each
script **by path with its executable bit** (`chmod 0700` then `system()`), so
the shebang chooses the interpreter — Python works. Scripts receive only
file-path arguments, run under user `nobody` in a working directory, and may
run inside a `bocajail` chroot.

This document designs **BocaNext**: a *new, separate* packager (the existing
bash packager is left untouched and can be deprecated later once BocaNext is
proven). The goals are (1) maintainability and code reuse and (3) room to
redesign the execution model — not a 1:1 port.

## Two layers

BocaNext splits into two bodies of code with different lifecycles and test
strategies:

- **Layer 1 — rbx-side packager** (`rbx/box/packaging/boca_next/`). Runs at
  `rbx package` time. Reuses `BocaExtension`, limits resolution, and
  language-mapping utilities. Its only new job is to **assemble `.pyz` bundles**
  and lay them out in the directory shape BOCA expects
  (`compile/<lang>`, `run/<lang>`, `compare/<lang>`, `limits/<lang>`,
  `tests/<lang>`). **Tracked in a follow-up issue — out of scope for this
  design.**

- **Layer 2 — judge-side runtime library** (`rbx/resources/packagers/boca_next/runtime/`).
  The reusable code that actually runs on the judge. Authored as a clean,
  stdlib-only, importable Python package and **zipapp-bundled into every
  `.pyz`**. Because it is a real package in the source tree, it is directly
  unit-testable in rbx's own test suite — no shell, no judge required.
  **This document designs Layer 2.**

## Delivery form

Each emitted file (e.g. `run/cpp`) is a **`.pyz`** (PEP 441 zipapp) with a
`#!/usr/bin/env python3` shebang. BOCA selects scripts by *filename*, not by
argument, so the entrypoint and language are frozen per file.

```
run/cpp  (a .pyz)
 ├─ __main__.py          # generated: from rbx_boca import run; run.main()
 ├─ rbx_boca/            # Layer 2 runtime library (identical in every bundle)
 │   ├─ sandbox.py       # safeexec argv builder + executor
 │   ├─ assets.py        # native-asset compile + MD5 cache
 │   ├─ languages.py     # generic LanguageSpec engine + kind handlers
 │   ├─ tasks.py         # BatchTask / InteractiveTask orchestration
 │   ├─ verdicts.py      # exit-code -> BOCA-code pure mappers
 │   └─ entrypoints.py   # compile/run/compare/limits/tests glue
 ├─ manifest.json        # problem-specific config, baked at package time
 └─ assets/              # embedded sources: checker.cpp, testlib.h, rbx.h,
                         #   interactor.cpp, safeexec.c, pipe.c
```

`zipimport` loads pure-Python modules straight from the zip (no extraction);
embedded asset sources are read via the zip loader. The result is a single
self-contained file that survives the `bocajail` chroot, exactly like the
inline-heredoc bash approach does today.

### Runtime requirement

`.pyz` execution requires a `python3` interpreter (>= 3.8, stdlib only)
reachable wherever the script runs — the BOCA host and inside `bocajail` if
used. The current bash approach only needs `/bin/sh`, so this is a **new,
documented deployment requirement** of BocaNext.

## Layer 2 interfaces

The issue's three configuration axes map onto three abstractions, plus a
strategy for execution method and a pure verdict layer.

### Design rule: behavior in code, data in the manifest

Behavior (how to compile cpp, how to assemble safeexec flags, the interactive
verdict priority) lives in the runtime library **code**. The manifest carries
**only** values that cannot be known until package time. Combined with the
fact that each `.pyz` is per-(entrypoint, language) — so its manifest needs
config for *one* language only — the manifest collapses to a small flat record:

```json
{
  "task_type": "batch",
  "limits": { "time_ms": 1000, "memory_mb": 256, "max_runs": 10, "max_time_error": 0.2 },
  "policy": { "use_bocajail": true, "fallback_user": "nobody" },
  "language": { "...one LanguageSpec..." : true }
}
```

Asset *sources* are embedded zip files, not manifest fields; the manifest at
most names which assets are required (and the `Task` can derive even that).

### 1. `Manifest` (pure data)

A frozen dataclass parsed from `manifest.json`. Read by everything downstream;
no globals. Trivially unit-tested via parse round-trips.

### 2. `LanguageSpec` + generic engine (axis 3 — per-language compile/exec)

A `LanguageSpec` is **data**, not a hardcoded class or enum:

```json
{
  "id": "cpp",
  "kind": "compiled_static",
  "compile_argv": ["g++", "{flags}", "-o", "{exe}", "{src}"],
  "run_argv": ["{exe}"],
  "flags": "-std=c++20 -O2 -lm -static",
  "limit_modifiers": { "time_mult": 1.0, "memory_add_mb": 0 }
}
```

The runtime library contains **one generic engine** that interprets a
`LanguageSpec`, parameterized by its `kind`. This collapses the 7×130–1200-line
compile scripts into a single code path — the largest dedup win.

**`kind` + templates (hybrid) model.** A `LanguageSpec` carries a `kind` from a
small fixed set of **kind handlers** in the runtime:

- `compiled_static` — compile to a statically linked exe; verify static linkage
  (C/C++/cc).
- `jvm_jar` — compile to a JAR; emit a launcher; JVM memory/time defaults
  (Java/Kotlin, incl. Kotlin `Main.kt` handling).
- `interpreted` — syntax-check; prepend shebang; pypy3/python3 switch
  (py2/py3).

Adding a language by **reusing an existing kind** is pure config (no runtime
code) and covers the overwhelming majority of cases. A genuinely novel
execution model requires adding a new `kind` to the runtime library — a
deliberate, rare extension point. rbx ships default `LanguageSpec`s; users
extend/override via the `env.rbx.yml` extension mechanism (Layer 1 resolves and
bakes the spec for this bundle's language).

### 3. `SafeExecSpec` + `build_safeexec_argv(spec) -> list[str]` (axis 3 — sandbox params)

A **pure function** mapping resource limits + policy to safeexec argv
(`-r -t -T -d -m -f -F -U -G -R -C -o -e`). Asserted directly in tests. The
`SafeExec` *executor* wraps it with `.locate_or_build()` (compile `safeexec.c`,
cached) and `.run(...)`. The actual subprocess call sits behind an **injectable
`Runner`** so tests use a fake.

### 4. `NativeAsset` (axis 2 — which assets to build)

Represents a compiled-on-judge artifact: name, embedded source, compiler argv,
MD5 cache key, output path. `.ensure(runner) -> Path` performs the
`/tmp/boca-cache` check-or-compile **once**, tested once. Instances: `checker`,
`interactor`, `safeexec`, `pipe`. Caching behavior matches today's bash
scripts (MD5 of source + flags).

### 5. `Task` strategy (axis 1 — execution method)

`BatchTask` / `InteractiveTask`, selected by `manifest.task_type`. Each
implements:

- `required_assets()` — which `NativeAsset`s to build (axis 2 in action).
  Batch: `checker`, `safeexec`. Interactive: also `interactor`, `pipe`.
- `compile(ctx)` — build the solution (via the `LanguageSpec` engine) plus
  required assets.
- `run(ctx, args)` — batch: direct safeexec; interactive: pipe-coordinated
  (`pipe.exe` + `interactor.exe` over fifos).
- `compare(ctx, args)` — both run the checker; interactive also reads the
  testlib exit code from the pipe log.

A future execution method is a new `Task` subclass — nothing else changes.

### 6. `verdicts.py` (pure)

`safeexec_outcome(code)`, `checker_outcome(code)`, and the interactive
**6-level priority logic** rewritten as a pure function over a parsed `pipe.log`
structure -> BOCA exit code. Fully tested, no IO.

### 7. `entrypoints.py` (thin glue)

`compile / run / compare / limits / tests` each: parse argv -> build a
`RunContext` from manifest + cwd -> call the `Task` method -> translate the
result to an exit code + stderr details. Deliberately thin; all logic lives in
the tested units above. `limits` emits resolved limits; `tests` is a trivial
validation hook (`exit 0`).

## Argument contract (from `autojudging.php`)

| Entrypoint | Arguments |
|------------|-----------|
| `limits`   | (none) |
| `compile`  | `sourcename basename timelimit memory` |
| `run`      | `basename inputfile timelimit repetitions memory outputsize_kb` |
| `compare`  | `team_output expected_output input_file` |
| `tests`    | (none) |

## Testability

- **Pure units** (argv builders, verdict mappers, cache keys, manifest /
  LanguageSpec parsing) — tested directly by asserting return values.
- **Side-effecting units** (compile, run) — take an injectable `Runner` /
  filesystem so tests substitute fakes; no real subprocess or sandbox needed.
- **Integration** — a few tests build a real `.pyz` and run it against a **stub
  `safeexec`** that emits canned exit codes, exercising the full entrypoint ->
  task -> verdict path end to end.

## Explicitly out of scope (this session)

- **Layer 1** (the rbx-side bundler, env-config -> `LanguageSpec` resolution,
  `.pyz` assembly, directory layout, `rbx package boca-next` CLI wiring) —
  follow-up issue.
- Migrating or deprecating the existing bash packager.
- Polygon/BOCA upload integration changes.
