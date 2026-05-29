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
 │   ├─ interactor_launcher.py  # re-entrant mode: setrlimit + watchdog + execv
 │   └─ entrypoints.py   # compile/run/compare/limits/tests glue
 ├─ task.json            # language-agnostic config (task_type, output_kb)
 ├─ language.json        # this bundle's LanguageSpec + per-language limits
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
**only** values that cannot be known until package time. Three forces shrink it
to almost nothing:

- **Behavior lives in the `kind` handlers** (how to compile cpp, assemble
  safeexec flags, the interactive verdict priority) — never in data.
- **Asset *sources* are embedded zip files**, not manifest fields; the `Task`
  derives which assets it needs from `task_type`.
- **The time-rounding / `nruns` computation is a package-time (Layer 1) job**,
  not judge-side. `_get_limits` today computes the integer time limit and run
  count on the packaging machine (using `maximumTimeError` / `_MAX_REPS`); the
  `limits/<lang>` script just echoes four literal numbers, which BOCA then feeds
  *back* as argv to `compile` / `run` / `compare`. So `maximumTimeError` and the
  rounding logic never reach the judge, and `compile` / `run` / `compare` read
  their effective limits from **argv**, not the manifest. `bocajail` is detected
  at runtime (`id -u bocajail`) with a universal `nobody` fallback, so no policy
  data is baked either.

### 1. Two manifests, split by axis of variation

Rather than one blob, BocaNext bakes **two** small JSON files, separated by
*what varies*:

**`task.json`** — language-agnostic, problem-level, identical in every bundle:

```jsonc
{ "task_type": "batch", "output_kb": 65536 }   // pkg.outputLimit is problem-wide
```

**`language.json`** — everything that varies per language; each `.pyz` carries
the one for its own language:

```jsonc
{
  "language": { "...one LanguageSpec..." : true },
  "limits":   { "time_sec": 3, "runs": 2, "memory_mb": 256 }
}
```

Consumption: `limits` reads `output_kb` (task) + `time_sec/runs/memory_mb`
(language) and echoes the four numbers BOCA expects; `compile` / `run` read
`language.json` + `task_type`; `compare` reads `task_type`. Both files parse
into frozen dataclasses, read by everything downstream — no globals, trivially
unit-tested via parse round-trips.

### 2. `LanguageSpec` + generic engine (axis 3 — per-language compile/exec)

The runtime library contains **one generic engine** that interprets a
`LanguageSpec`, parameterized by its `kind`. This collapses the 7×130–1200-line
compile scripts into a single code path — the largest dedup win. The crucial
design decision is **where the data/code line falls**: research on the existing
bash templates (compile + run + interactive, all 7 languages) showed that *most*
of what "varies per language" is actually `kind`-level structure, not data.

**The `kind` handler owns the structural behavior** (identical within a kind):

| Behavior                         | `compiled_static` | `jvm_jar`                          | `interpreted`        |
|----------------------------------|-------------------|------------------------------------|----------------------|
| Artifact                         | static ELF        | `run.jar`                          | script + shebang     |
| Static-link check                | required          | —                                  | —                    |
| Sandbox fd limit                 | `-F10`            | `-F256 -u256`                      | `-F256 -u256`        |
| Run memory → safeexec            | real (`-d/-m`)    | fixed large + `-Xmx`/`-Xss=heap/10`| real (`-d/-m`)       |
| `nruns` (repeat timing)          | supported         | forced to 1                        | forced to 1          |
| JVM flags (`-XX:+UseSerialGC` …) | —                 | generated                          | —                    |
| Syntax pre-check                 | —                 | —                                  | py3 `py_compile`     |

**The `LanguageSpec` (data) fills the small holes the kind leaves:**

```jsonc
{
  "id": "cpp",
  "kind": "compiled_static",
  "compiler_argv": ["g++", "{flags}", "-o", "{exe}", "{src}"],  // C adds -lm via flags
  "compiler_fallbacks": ["/usr/bin/g++"],
  "flags": "-std=c++20 -O2 -lm -static",
  "run_argv": ["{exe}"],          // kind injects computed holes like {jvm_flags}
  "sandbox_overrides": {}          // optional escape hatch over kind defaults
}
```

`jvm_jar` additionally carries a **`build` selector** in data
(`javac_then_jar` vs `kotlinc_include_runtime`) and the `run_argv` form
(`-jar {jar}` vs `-cp {jar} {jvm_flags} MainKt`), since those genuinely differ
Java-vs-Kotlin but both stay inside one kind.

Adding a language by **reusing an existing kind** is pure config (no runtime
code) and covers the overwhelming majority of cases. A genuinely novel execution
model requires adding a new `kind` to the runtime library — a deliberate, rare
extension point. rbx ships default `LanguageSpec`s; users extend/override via the
`env.rbx.yml` extension mechanism (Layer 1 resolves and bakes the spec for this
bundle's language).

**Fidelity decisions** (from auditing the current bash). BocaNext *unifies* two
genuine bugs/drift and *preserves* two semantically-meaningful behaviors as
overridable `kind` defaults:

- **Unify:** Kotlin compile currently skips the `bocajail`/chroot logic every
  other language applies — apply it uniformly. Kotlin compile hardcodes
  `-t20 -T32 -istdin0` unlike Java — derive its compile sandbox params from the
  kind like Java's.
- **Preserve:** the JVM's large fixed virtual-memory grant (it cannot start
  otherwise; the real limit is enforced via `-Xmx`), and `nruns = 1` for
  JVM/interpreted (startup variance makes repeated timing meaningless).

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

The exit-code translations, rewritten as pure functions over parsed data — the
surface that is impossible to test in today's bash. There are **two BOCA code
spaces** (the run script's exit code, interpreted by the autojudge, and the
compare script's `4/6/43/47`), so three mappers:

- `batch_run_exit(safeexec_exit) -> run_exit` — incl. the `>10 -> 9` RTE remap.
- `interactive_run_decision(first_tag, ecsf, ecint) -> (run_exit, testlib_code?)`
  — the 6-level priority logic, de-duplicated into ordered rules (table below).
- `compare_verdict(testlib_code?, checker_exit?) -> boca_code` — shared by both
  task types.

All three are pure, with table-driven tests over every code combination.

See **Interactive execution** below for the priority table.

### Interactive execution

Coordination is split native-vs-Python at clean seams:

- **`pipe.exe` (`pipe.c`) and `safeexec` stay `NativeAsset`s.** `pipe.exe`
  launches the two children, wires their stdin/stdout over `fifo.in`/`fifo.out`,
  uses `epoll` on per-child notify pipes to detect which exits first, and writes
  a **3-line `pipe.log`**: `first_tag` (1=solution, 2=interactor),
  `solution_status`, `interactor_status` (bash-like: `0-255`, or `128+signal`).
  Kept *as-is* — it is a clean contract with no bug to fix.
- **`InteractiveTask` (Python) replaces `interactor_run.sh`**: create the fifos,
  build the `pipe.exe` argv (solution-under-safeexec `=` interactor-under-
  launcher), invoke it, parse `pipe.log`, then apply
  `interactive_run_decision`.

**Interactor launcher (Python).** The interactor runs *unsandboxed* (trusted
judge code that needs the fifos + notify fd), so it goes through a thin launcher
instead of safeexec. `pipe.exe` execs the **same `.pyz` re-entrantly** with a
sentinel argv (`<pyz> __interactor_launcher__ <ittime> ./interactor.exe ...`);
`__main__` dispatches to `rbx_boca/interactor_launcher.py`, which does
`resource.setrlimit(RLIMIT_AS, 1GB)`, arms a process-group watchdog
(`SIGTERM` after the budget, `SIGKILL` +5s), then `os.execv`s the interactor.

> **Implementation risk to verify:** the bash watchdog does `exec {fd}>&-` so it
> drops its copy of `pipe.exe`'s notify fd — otherwise the pipe never `HUP`s and
> first-exit detection hangs. The Python launcher must replicate this exactly:
> the watchdog child must **not inherit** the notify fd, and the main interactor
> process must hold it open until exit. fd-inheritance / close-on-exec / `killpg`
> semantics get **integration coverage** (real `.pyz` + stub interactor); the
> pure parts (rlimit value, timeout computation) are extracted as tested helpers.

**6-level priority logic** (`interactive_run_decision`). The ordering *is* the
spec — resource limits beat the interactor verdict, which beats solution RTE:

| # | Condition | Result |
|---|-----------|--------|
| 1 | interactor-first & `ecint ∉ {0,1,2,3,4}` (interactor crashed) | `run_exit=4` (judge error) |
| 2 | `ecsf ∈ {3,7}` | `run_exit=ecsf` (TLE / MLE) |
| 3 | interactor-first | `ecint∈{1..4}` → emit testlib code, `run_exit=0`; `0` → fall through; else `run_exit=4` |
| 4 | `ecsf ≠ 0` | `run_exit=ecsf` (solution RTE) |
| 5 | (always) re-check interactor | as #3 |
| 6 | otherwise | `run_exit=0` (success → compare decides) |

`compare_verdict` then reads the emitted `testlib exitcode` line if present
(`1,2 → WA(6)`, `3 → 43`, else `47`); otherwise it runs the checker
(`0 → AC(4)`, `1,2 → WA(6)`, `3 → 43`, else `47`).

### 7. `entrypoints.py` (thin glue)

`compile / run / compare / limits / tests` each: parse argv -> build a
`RunContext` from `task.json` / `language.json` + cwd -> call the `Task` method
-> translate the result to an exit code + stderr details. Deliberately thin; all
logic lives in the tested units above. `limits` echoes the four pre-computed
numbers (`time_sec`, `runs`, `memory_mb`, `output_kb`); effective per-run limits
arrive as argv from BOCA. `tests` is a trivial validation hook (`exit 0`).

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
