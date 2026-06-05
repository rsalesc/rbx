# Mirror the package directory structure in the sandbox

**Issue:** [#522](https://github.com/rsalesc/rbx/issues/522) — Rethink compilation
and execution working directory in sandbox.

## Problem

When rbx compiles or runs a program it creates a fresh temporary directory in the
sandbox, copies the relevant files in (declared as *grading artifacts* so the
cache can track them), runs the command with `cwd` = sandbox root, then copies the
declared outputs back. This works, but the temp directory is **flat** and does not
reflect the package layout. Two consequences:

1. A program at `gens/gen.cpp` is placed in the sandbox as the bare basename
   `gen.cpp` at the root. There is no way for it to `#include "../lib.h"` a header
   that lives at the package root, because (a) the source is not mirrored into a
   `gens/` subdir, and (b) the only way to add extra files — `compilationFiles` —
   is restricted to files *under the code's own folder* (a hard
   `is_relative_to(code_dir)` check in `package.get_compilation_files`).

2. There is **no execution-time equivalent** of `compilationFiles`, so runtime
   companion files cannot be declared at all.

The fix should mirror the package directory structure into the sandbox so that
relative includes / relative paths resolve naturally, while **minimizing breakage**
— existing packages must keep working.

## Scope

In (Phase 1 — this design):

- Mirror the **source file** to its package-relative path inside the sandbox for
  the languages that reference `{source}` (C, C++, Python). `cwd` stays the
  sandbox root, which now faithfully mirrors the package root.
- Repurpose `compilationFiles` so extra files land at their **package-relative**
  path, and **lift** the "must be under the code's folder" restriction (relax to
  "under the package root"). This enables `../lib.h`-style includes.
- Place auto-injected builtin headers (testlib / jngen / tgen / rbx) in the
  **source's own directory** (instead of always at the sandbox root) so quoted
  `#include "testlib.h"` keeps resolving for mirrored sources, with **no `-I.`**.
- Keep precompiled headers (`.gch`) working for nested sources.

Out (Phase 2 — separate design/plan, lower priority per the issue):

- `executionFiles` on every `CodeItem` (the runtime equivalent of
  `compilationFiles`).
- Default-on, recursive, quoted-only **auto-expansion** of dependencies from
  `#include "..."` (C++) and relative / sibling imports (Python), feeding both the
  compile and execution artifacts.

## How it works today (research the issue asked for)

- **Compilation** (`box/code.py:compile_item` → `grading/steps.py:compile`):
  - `_get_code_variables` (`code.py:220`) sets `source = code.path.name` — the
    **basename**. So `gens/gen.cpp` is copied in flat as `gen.cpp`.
  - The compilable file's dest is `file_mapping.compilable`, whose default is
    `'{source}'`. The compile command is built from `{compilable}` /
    `{executable}`, e.g. `g++ -std=c++20 -O2 -o executable gen.cpp`.
  - `compilationFiles` flow through `package.get_compilation_files` (`package.py:541`):
    dest = path **relative to the code's dir**, and the file **must** be
    `is_relative_to(code_dir)`. That restriction is exactly what blocks a
    root-level `lib.h`.
  - Builtin headers are injected at the **root** (`testlib_grading_input` →
    `dest='testlib.h'`); they resolve because the source is *also* at the root.
  - `<bits/stdc++.h>` is special: when the host lacks it, the bundled header is
    injected at `bits/stdc++.h` **and** `-I.` is appended to the cxx commands
    (`code.py:653-660`). It is an angle-bracket include resolved via that `-I.`.
  - `cwd` = sandbox root for both compile and run.
- **Execution** (`code.py:run_item` / `_prepare_run` → `grading/steps.py:run`):
  same flat model — binary at `executable`, stdin/stdout at the root, `cwd` =
  root. There is **no** `executionFiles` concept.
- **Caching** (`grading/caching.py`): the cache key is
  `commands + input file digests + input dest paths + output structure + sandbox
  params`. Changing dest paths changes the key → a one-time recompile. The
  fingerprint machinery is unaffected.

## The key insight

The sandbox **already supports nested paths** — `create_file` and `create_symlink`
both `mkdir(parents=True)` (`judge/sandbox.py:329,356`), and `bits/stdc++.h` is
already injected nested. **Mirroring needs no sandbox-layer change.** The flatness
is purely three conventions:

1. `source` = basename → should become the package-relative path.
2. the "must be under code's folder" restriction on `compilationFiles`.
3. builtin headers pinned to the root → should sit in the source's directory.

### One variable drives the mirroring

Per-language `fileMapping` (default env):

| Language | `compilable`        | `executable`   | Uses `{source}`? |
|----------|---------------------|----------------|------------------|
| C / C++  | `{source}`          | `executable`   | yes (compile)    |
| Python   | `{source}`          | `{compilable}` | yes (compile+run)|
| Java     | `{javaClass}.java`  | `Main.jar`     | no               |
| Kotlin   | `Main.kt`           | `Main.jar`     | no               |

Changing `source` from `code.path.name` → `str(code.path)` (package-relative POSIX
path) therefore:

- **C/C++**: mirrors the source at compile time; the produced binary stays a
  generic `executable` at the root (binaries are position-independent — nothing to
  mirror at run time).
- **Python**: mirrors **both** compile and run (`executable = {compilable} =
  {source}`, run command `python3 {source}`). Running `python3 gens/gen.py` from
  the root puts `gens/` on `sys.path[0]`, so same-dir imports resolve from the
  mirrored location — the right foundation for Phase 2.
- **Java / Kotlin**: untouched — they never reference `{source}`, so they stay
  pinned at the root with their class-name mapping. No behavior change.

This is the minimal lever: one variable, landing on exactly the languages that
benefit, leaving the JVM languages alone.

## Design

### 1. Core mechanism

`code.py:_get_code_variables` — change `source` to the package-relative POSIX path
of `code.path` (e.g. `gens/gen.cpp`) instead of the basename. This flows through
`file_mapping.compilable`, the compile command, and (for Python) the
execution command. `cwd` stays the sandbox root.

### 2. Repurpose `compilationFiles`

`package.get_compilation_files` — dest becomes the **package-relative path**
(`pathlib.Path(compilation_file)`), not the path relative to the code dir. **Drop**
the `is_relative_to(code_dir)` check; keep a sanity check that the file exists and
lives under the package root.

**Why this is zero-breakage for currently-valid packages.** Today
`compilationFiles` were *forced* under the code's dir. Under mirroring, the source
and its companion headers all keep their package-relative paths, so they move by
the **same offset**. A user's `#include "helper.h"` / `#include "sub/h.h"` that
worked in the flat layout still resolves via the source's mirrored directory — the
source code is unchanged. Lifting the restriction is purely **additive**: it newly
permits `../lib.h` (previously a hard error).

### 3. Builtin headers in the source's directory

`code.py:compile_item` (the single chokepoint, `code.py:628-631`) — inject
testlib / jngen / tgen / rbx at `code.path.parent / <name>` instead of always at
the root. For a flat package `code.path.parent == .`, so the dest equals the root
— **byte-identical to today**. For a subdir source it lands beside the source so
quoted `#include "testlib.h"` resolves with **no `-I.`** (consistent with the
issue's preference to avoid language-specific flag hacks).

`<bits/stdc++.h>` is **left untouched**: it stays at the root with its own `-I.`,
and angle-bracket resolution via `-I.` works regardless of where the source sits.

### 4. Precompiled headers for nested sources — for free

`_precompile_header` sets the `.gch` dest to
`input_artifact.dest.with_suffix('.h.gch')` (`code.py:553`). With the builtin
header now at `gens/testlib.h`, the precompiled output lands at
`gens/testlib.h.gch` — right beside it, where the compiler picks it up. Because
there is now a **single** copy of each builtin (source dir only), there is no
double-precompile and no extra logic required. The precompile filter at
`code.py:662-685` matches on `dest.name`, which is unchanged.

### 5. Audit for flat-layout assumptions

The `{source}` change is centralized, but before finishing we grep for any code
that assumes the flat basename layout (e.g. constructs sandbox paths from
`code.path.name`, or expects the compilable/executable at a fixed flat name).
Notable areas to re-check: `_prepare_run` artifact construction, anything reading
back outputs by name, packaging/import paths that synthesize `compilationFiles`
(e.g. Polygon importer at `packaging/polygon/importer.py:190`).

## Migration impact

- **Flat packages** (source at the root): `str(code.path) == code.path.name`, and
  the builtin dest collapses to the root → **byte-identical** behavior.
- **Subdir packages with companion headers under the code dir**: keep working
  (same relative offset), and `#include "testlib.h"` keeps resolving thanks to the
  source-dir builtin placement.
- **New capability**: `../lib.h`-style includes from a subdir source, declared via
  the now-unrestricted `compilationFiles` (and, in Phase 2, auto-expanded).
- **Known starting-point limitation**: a header reached cross-directory (via `../`)
  that *itself* `#include "testlib.h"` will not find the builtin (it only sits in
  the primary source's dir). This case is impossible today, so it is not a
  regression. Builtin auto-placement is expected to be deprecated later anyway.
- **Cache**: dest paths change → a one-time global recompile. Acceptable.

## Testing

Reuse `tests/rbx/box/conftest.py` fixtures (`testing_pkg`, `cleandir`,
`pkg_from_testdata`) per the testing conventions. The local C++/sandbox suite is
known to fail pre-existingly on this machine — verify via the normal CI path / the
relevant subset.

- **Unit**
  - `_get_code_variables` returns the package-relative path for nested sources and
    the basename-equal path for root sources.
  - `get_compilation_files` returns package-relative dests and accepts a file that
    reaches outside the code dir (e.g. `../lib.h`), while still rejecting files
    outside the package root and non-existent files.
  - Builtin header artifacts are placed at `code.path.parent`.
- **Integration** (real compilation via `code_compile_test.py`-style fixtures)
  - Subdir C++ generator that `#include "../lib.h"` (root-level header) compiles
    and runs.
  - Subdir C++ generator that `#include "testlib.h"` still compiles (source-dir
    builtin + precompiled `.gch`).
  - Flat package compiles identically (regression guard).
  - Python subdir source runs from its mirrored location.
  - Java source still compiles (pinned at root, unaffected).

## Phase 2 (deferred)

`executionFiles` on every `CodeItem` plus default-on, recursive, quoted-only
auto-expansion (C++ `#include "..."`, Python relative / sibling imports) feeding
both compile and execution artifacts, with the manual fields remaining as an
override / escape hatch. Tracked as a follow-up plan.
