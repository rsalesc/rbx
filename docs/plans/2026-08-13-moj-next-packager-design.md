# MojNext packager — design

**Date:** 2026-08-13
**Status:** approved, pending implementation
**Target platform:** [MOJ](https://moj.naquadah.com.br) — package format
[`PACOTE.html`](https://moj.naquadah.com.br/docs/PACOTE.html), judged by
[`cd-moj/mojtools`](https://github.com/cd-moj/mojtools).

## 1. Why a new packager

The existing `MojPackager` (`rbx/box/packaging/moj/packager.py`) extends `BocaPackager`
and emits a package shape that no longer matches MOJ. Every row below is a hard
break, not a refinement:

| Area | MOJ today | Existing `moj` packager |
|---|---|---|
| Time limit | **Measured, never authored.** `calibreitor.sh` runs `sols/good/*`, takes the worst time per language, multiplies by `TLMOD[calibrafactor]` (default 1.35), writes `tl`/`tl.<host>`. `build-and-test.sh` exits 3 when no `tl` exists. | Writes `tl` only under `--for-boca` |
| Checker | `scripts/checker.cpp` (standard testlib, **no** `-DBOCA_SUPPORT`) plus a ~10-line stub `scripts/compare.sh` delegating to `$MOJTOOLS_DIR/testlib/checker-bridge.sh` | Ships a full private bridge copy, plus vendored `testlib.h` and `rbx.h` under `scripts/` |
| Memory | `MEMLIMITMB` (peak RSS); setting it deliberately unsets the virtual-memory ulimit | Sets `ULIMITS[-v]`, the legacy knob |
| Statement | `docs/enunciado.{md,org,tex}`, mandatory `## Entrada` / `## Saída` | `docs/enunciado.pdf`, which is not a recognized format |
| Tests | Samples required and named `sample*` | Everything named `001`, `002`, … — zero samples, so validation fails |
| Subtasks | `tests/score`, all-or-nothing per group, test→group by name glob | Not emitted |

Rather than reshape a `BocaPackager` subclass into something that shares almost
nothing with BOCA, MojNext is a separate packager extending `BasePackager`
directly. The existing `moj` packager stays untouched and keeps serving interactive
problems. This mirrors the `boca_next` precedent already in the tree.

### The rule MOJ paid for

From `mojtools/CLAUDE.md`:

> **DRIVER CANÔNICO NO PACOTE = STUB, NUNCA CÓPIA.** What runs on the **host**
> (`scripts/compare.sh`, `scripts/<lang>/prep.sh`, `scripts/summary.sh`) ships as a
> ~10-line stub calling the canonical mojtools script. Only what enters the **jail**
> (`scripts/<lang>/{run,compile}.sh`) is a real copy — inside it, mojtools does not exist.

A bundled bridge copy replicated a `bwrap` bug into **198 packages**, and the fix in
mojtools reached none of them. MojNext sits on the correct side of this rule: the
compare driver is a byte-copy of mojtools' canonical stub, and only the in-jail
per-language scripts are real copies.

### The sharpest constraint

`checker-bridge.sh` compiles the package's checker under `bwrap` with **only**
`checker.cpp` and `testlib.h` bound into `/tmp`, and `-I /tmp`. No other header is
reachable. An rbx checker that includes `rbx.h`, or any flattened dependency header,
cannot work — so the checker must be amalgamated into a single self-contained
translation unit.

## 2. Scope

- New packager `MojNextPackager` in `rbx/box/packaging/moj_next/`.
- CLI: `rbx package moj-next`. Limits-profile key: `moj-next`.
- `task_types()` returns `[BATCH]`; interactive problems are rejected with a clear
  error and remain the legacy packager's business.
- `statement_types()` returns `[]`, so `run_packager` builds no statements at all and
  a problem with zero statements packages cleanly. A dummy `docs/enunciado.md` is
  written instead. Statements are explicitly out of scope for this iteration — MOJ's
  statement format is not properly supported by rbx yet.

## 3. Emitted layout

```
author                     "Unknown\n" placeholder
tags                       empty
.moj-meta.json             display_title (+ languages when derivable)
conf
docs/enunciado.md          dummy, PT-BR, with ## Entrada and ## Saída
tests/input/<name>
tests/output/<name>
tests/score                POINTS problems only
sols/{good,pass,slow,wrong}/<file>
scripts/checker.cpp        single amalgamated translation unit
scripts/compare.sh         byte-copy of mojtools' compare-stub.sh, 0755
scripts/<lang>/compile.sh  derived from rbx env, 0755
scripts/<lang>/run.sh      derived from rbx env, 0755
```

Deliberately **not** emitted: `tl` (calibration owns it), the access fields of
`.moj-meta.json` (see §10), `scripts/testlib.h` and `scripts/rbx.h` (both are inlined
into `checker.cpp`; a stray `scripts/testlib.h` would take precedence in the bridge
and silently shadow the vendored one).

The zip root is the package root, as today.

## 4. Time limits: calibration-only

MojNext ships **no `tl`**. The judge measures it. `conf` carries the only limit knobs:

```sh
MEMLIMITMB=<pkg.memoryLimit>
ULIMITS[-f]=<pkg.outputLimit>
# TODO(rbx): derive this from the authored timeLimit divided by the measured
# model-solution runtime, so the calibrated TL lands near rbx's number.
TLMOD[calibrafactor]=1.35
```

`MEMLIMITMB` replaces the legacy `ULIMITS[-v]`: it is the RSS-based knob, it feeds the
JVM's `-Xmx` through `binfile.sh`, and setting it makes `build-and-test.sh` drop the
virtual-memory limit that unfairly penalizes JVM/Go. Both rbx's `outputLimit` and
MOJ's `ULIMITS[-f]` are in KB, so that one maps directly.

The consequence, accepted deliberately: **the package is unjudgeable until a judge
calibrates it.** rbx's authored `timeLimit` becomes advisory. See §11.

## 5. Tests and scoring

Samples are named `sample001`, `sample002`, …; every other test is
`t<NN>_<group>_<NNN>`, where `NN` is the group's 1-based index in `problem.rbx.yml`
and `<group>` is the group name sanitized to `[A-Za-z0-9_]`. Subgroups flatten into
their top-level group, matching rbx's own scoring granularity.

Two properties are load-bearing:

- **Samples sort first.** MOJ's judging loop is a plain shell glob over
  `tests/input/*`, so ordering is lexicographic. `sample` < `t`, so samples are judged
  and reported in the same order the statement shows them. The group index prefix
  makes the remaining order match `problem.rbx.yml` regardless of group names.
- **Both of MOJ's group-matching heuristics work unchanged.** `score-summary.sh`
  first strips trailing digits (`t01_easy_001` → `t01_easy_`) and compares against the
  group name derived from each glob (`${PAT%\**}` of `t01_easy_*` → `t01_easy_`), then
  falls back to a real glob match. Both agree.

`tests/score` is emitted for POINTS problems only:

```
sample* - 0 pontos
t01_easy_* - 40 pontos
t02_full_* - 60 pontos
```

BINARY problems get no `tests/score`, so MOJ scores by percentage-of-tests and
Accepted still requires every test to pass — the correct ICPC semantics.

Three guardrails follow directly from reading `score-summary.sh`:

- **Weights must be integers.** The parser extracts the number with
  `${SCORE//[^0-9]/}`, so a weight of `40.5` silently becomes `405`. Error out.
- **Group names must not contain `-`.** The line is split with `IFS='-'`, so a dash in
  a group name corrupts the weight. The sanitizer already handles this; the guardrail
  is a defensive assertion.
- **At least one sample must exist.** MOJ's `examples_present` is a hard validation
  check, and `sols/good` calibration aside, a package without samples cannot be
  published.

Additionally, every test must match exactly one group or the submission is zeroed.
This holds by construction: distinct groups always get distinct index prefixes.

## 6. Checker

`scripts/checker.cpp` is a single amalgamated translation unit: rbx's own `testlib.h`,
`rbx.h`, and the entire transitive quoted-include closure are inlined. `<system>`
includes are left alone. `scripts/compare.sh` is a byte-copy of mojtools'
`compare-stub.sh`, vendored under `rbx/resources/packagers/moj_next/scripts/`, chmod
0755 — exactly what `install-checker.sh` does, which keeps the bridge upstream and
centrally fixable.

Inlining rbx's testlib rather than relying on MOJ's vendored copy (v0.9.40-SNAPSHOT)
makes the checker behave identically locally and on the judge.

The packager refuses to produce a package — with an actionable message — when the
closure cannot be safely inlined: an unresolvable quoted include, an include escaping
the package root, or a non-C++ checker. Shipping a package that UEs on every test is
strictly worse than failing at build time.

Two warnings rather than errors:

- A checker calling `quitp`/`_points`. The bridge maps testlib exit 7 to MOJ exit 7,
  which is *judge error*, not partial credit. Per-test partial scoring is structurally
  unavailable on MOJ; subtasks must go through `tests/score`.
- MOJ compiles the checker at `-std=gnu++17`, so C++20 features in a checker will fail
  on the judge even though they build locally.

For reference, the bridge's verdict mapping: `_ok`→AC, `_wa`/`_pe`/`_dirt`/unexpected
EOF→WA, `_fail`/`_points`→UE. Note that testlib's `_pe` means "unparseable output" and
is a wrong answer — it is **not** MOJ's `AC,PE`, which only the default diff comparator
ever emits.

## 7. Amalgamation library

The amalgamator is general-purpose and lives at
`rbx/box/dependencies/amalgamation.py`, alongside the existing `scanner.py`, `cpp.py`,
`python.py` and `graph.py` that already resolve quoted includes. It carries no MOJ
knowledge and is reusable by Polygon upload, BOCA's heredoc embedding, or anything
else needing one self-contained translation unit.

```python
@dataclasses.dataclass(frozen=True)
class AmalgamationResult:
    content: bytes
    inlined: List[pathlib.Path]   # in inlining order
    kept: List[str]               # spellings left untouched


class AmalgamationError(RbxException):
    ...


def amalgamate(
    root: pathlib.Path,
    *,
    extra_roots: Sequence[pathlib.Path] = (),
    keep: Optional[Callable[[str], bool]] = None,
    scanner: Optional[Scanner] = None,
) -> AmalgamationResult:
    ...
```

Behavior: depth-first over the scanner's resolved quoted includes; each file inlined at
most once, keyed on resolved realpath; `#pragma once` lines dropped; `<system>`
spellings left untouched; an unresolvable quoted spelling raises `AmalgamationError`
naming the including file and the offending line. Each inlined file gets a
`// amalgamated from <path>` banner so the output stays debuggable.

`extra_roots` is how builtins get resolved without the library knowing what they are —
the packager passes the directories holding `get_testlib()` and `header.get_header()`.
This is the one place where `flattening.py`'s treatment differs: it deliberately leaves
builtins as unresolved (`target=None`) because flat judges provide them, whereas
amalgamation must inline them.

## 8. Solutions

| rbx `ExpectedOutcome` | MOJ directory |
|---|---|
| `ACCEPTED` | `good/` |
| `ACCEPTED_OR_TLE` | `pass/` |
| `outcome.is_slow()` | `slow/` |
| `WRONG_ANSWER`, `INCORRECT`, `RUNTIME_ERROR`, `MEMORY_LIMIT_EXCEEDED`, `OUTPUT_LIMIT_EXCEEDED` | `wrong/` |
| `ANY` | skipped, with a warning |

All accepted solutions go to `good/`. Since calibration takes the *worst* time across
`good/` per language, a deliberately near-TL accepted solution will produce a more
generous judge TL than rbx's. This is accepted for now and is what the
`calibrafactor` TODO in §4 will address.

Basenames are preserved, because Java requires the filename to match its public class.
A basename collision inside one tag directory is an error, not a silent overwrite.

**Solutions are amalgamated too.** They are compiled from a single file inside the
jail, so a C/C++ solution including `rbx.h` or a local header would fail on MOJ exactly
as the checker would. Same library. For `py`/`java`/`kt`, a closure with more than one
file is an error.

## 9. Per-language scripts

`MojLanguageExtension` mirrors `BocaLanguageExtension`: a `languages: List[str]` of MOJ
ids plus a required `template`. A `get_emitted_moj_languages()` helper mirrors
`get_emitted_boca_languages()` and returns the union across env languages. Scripts are
emitted for **every** MOJ id in that union, independent of which languages have
accepted solutions. The extension key is `moj`, added to `LanguageExtensions` in
`rbx/box/extensions.py`.

These are real copies, not stubs — correct per MOJ's rule, since they run inside the
jail where mojtools does not exist. Templates live at
`rbx/resources/packagers/moj_next/scripts/<template>/{compile.sh,run.sh}` and follow
MOJ's contract:

```sh
# compile.sh — runs in the jail, in a writable /tmp/rwdir holding the source
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir
g++ {{rbxFlags}} -static "$SRC" -o main || exit 1
echo BIN=main          # MANDATORY; no BIN= line means Compilation Error
```

```sh
# run.sh — runs in the jail, binary in /tmp/dir (ro), input /tmp/in, output /tmp/out
exec &>/tmp/stderrlog
cd /tmp/dir
source binfile.sh      # provides BIN, MOJ_MEMLIMITMB, MOJ_STACKKB
exec ./$BIN < /tmp/in > /tmp/out
```

### Java and Kotlin: manifest jar

Following BOCA's approach (`rbx/resources/packagers/boca/compile/java`), `compile.sh`
derives the class from the source basename (falling back to `Main`), writes a
`Main-Class` manifest, and builds a jar:

```sh
klass=$(basename "$SRC" .java)
printf 'Main-Class: %s\n' "$klass" > Manifest.txt
javac *.java || exit 1
jar cfm prog.jar Manifest.txt *.class
echo BIN=prog.jar
```

Kotlin needs nothing extra: `kotlinc -include-runtime` already writes `Main-Class` from
`fun main()`. So both run scripts collapse to one shape:

```sh
source binfile.sh
exec java -Xms10m -Xmx${MOJ_MEMLIMITMB:-500}m -Xss${MOJ_STACKKB:-131072}k -jar "$BIN" < /tmp/in > /tmp/out
```

This is strictly better than MOJ's own `lang/java/compile.sh`, which elects the main
class by grepping sources for a `main` declaration and falling back to `ls *.class` —
a path that has already produced locale-dependent `Main$X.class` bugs upstream.

## 10. Metadata and statement

`author` is written as the placeholder `Unknown\n` — MOJ hard-requires the file, and
rbx has no author field. `tags` is written empty.

### `.moj-meta.json` (revised after review)

The first pass omitted this file entirely, reading "the server always writes this,
never the author" as "never ship it". That was wrong. On a tar upload the server
applies **two-tier** logic:

- **Content fields** (`display_title`, `collections`, `languages`) *are* sourced from
  the tar's `.moj-meta.json`; absent or empty means the server preserves its existing
  values rather than resetting them.
- **Access fields** (`public`, `public_at`, `owner`) are **never** accepted from a tar
  and move only through dedicated API routes.

So the packager writes the content fields it can know:

- `display_title` — required, never empty. From `pkg.titles`, preferring `pt`/`pt-br`/
  `en`, then the lowest language code, then `pkg.name`.
- `languages` — the whitelist of permitted submission languages; the API rejects
  anything outside it. Derived from the languages that have an **accepted solution**,
  which is MOJ's own criterion: it calibrates a time limit per language from
  `sols/good`, and a language without one never gets a limit, so a student cannot use
  it. Ids are normalized as the server does (lowercase, `py2`/`py3` → `py`, deduped)
  and sorted. Omitted when empty, since absent means "preserve" while `[]` is a no-op.
- `collections` is omitted: rbx has no notion of them and absent keeps the server's.
- `public`, `public_at`, `owner` and `gitea` are omitted. Beyond being ignored from a
  tar, `public` is **fail-closed** in `gen-problem-json.sh` — emitting it is how an
  unpublished problem ends up in an index served to anonymous users.

Deriving `languages` from the emitted `scripts/<lang>/` dirs was considered and
rejected: that set comes from the setter's `env.rbx.yml`, says nothing about who may
submit what, and would silently narrow the permissive default (absent = all languages)
to whatever the bundled preset happens to declare.

`docs/enunciado.md` is a dummy carrying only the two mandatory sections:

```markdown
Enunciado ainda não disponível.

## Entrada

A descrever.

## Saída

A descrever.
```

No title line (the renderer strips a legacy `% Título` and injects `<h1>` from
`display_title`), no examples (MOJ injects them from `tests/input/sample*`), and no
fenced code blocks — a fence trips `validate-problem.sh`'s soft `render_warnings`
heuristic for hand-written examples.

## 11. Known gaps

- **Calibration dependency.** The package cannot be judged until a judge calibrates
  it. mojtools' README states the judge agent calibrates on first submission, but that
  logic lives in the private `judge` repo. Confirm with MOJ operators before the first
  real upload.
- **Per-test partial credit is unavailable.** Subtasks must go through `tests/score`.
- **Interactive is out of scope.** MOJ's arbiter protocol (test in `argv[1]`, last
  stderr line `WRONG <reason>`, FIFO driver, per-language SIGPIPE handling) is
  structurally unlike a testlib interactor. Adapting one deserves its own design; the
  legacy `moj` packager continues to cover interactive problems in the meantime.
- **rbx compile flags reach MOJ only through the emitted `scripts/<lang>/`.** A
  language present on MOJ but absent from the env's `moj` extension lists gets MOJ's
  own defaults.

## 12. Testing

Unit tests under `tests/rbx/box/packaging/moj_next/` covering: emitted layout and file
modes; test naming and sample-first ordering; `tests/score` content for POINTS and its
absence for BINARY; integer-weight and sample-presence guardrails; `conf` contents;
`compare.sh` being byte-identical to the vendored stub; per-language script emission
driven by the extension lists; and the COMMUNICATION rejection.

Amalgamation gets its own unit tests under `tests/rbx/box/dependencies/`: diamond
includes inlined once, `#pragma once` handling, system includes preserved, and the
error paths. Where a compiler is available, an integration test compiles the
amalgamated checker with `-std=gnu++17` to catch the constraint from §6.
