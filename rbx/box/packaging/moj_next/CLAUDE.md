# CLAUDE.md — MojNext packager

`MojNextPackager` (`rbx package moj-next`) targets **MOJ**
(`moj.naquadah.com.br`), judged by [`cd-moj/mojtools`](https://github.com/cd-moj/mojtools).
It is a **separate** packager extending `BasePackager` directly. The legacy
`rbx/box/packaging/moj/` packager (a `BocaPackager` subclass) is untouched and
still owns interactive problems.

- Design doc: `docs/plans/2026-08-13-moj-next-packager-design.md`
- Implementation plan: `docs/plans/2026-08-13-moj-next-packager.md`

## Why separate

The legacy packager targets a shape MOJ no longer accepts: it authors a time limit
MOJ *measures*, bundles a private copy of the checker bridge that MOJ banned, emits
`docs/enunciado.pdf` (not a recognized format), and names every test `001`/`002`,
so a package has **no samples** and fails validation outright.

## The two rules that shape everything

**1. Stub on the host, copy in the jail.** From `mojtools/CLAUDE.md`: what runs on
the judge **host** (`scripts/compare.sh`) ships as a ~10-line stub pointing at
mojtools; only what enters the **jail** (`scripts/<lang>/{compile,run}.sh`) is a real
copy, because mojtools does not exist in there. A package carrying its own bridge
copy is what replicated one `bwrap` bug into **198 packages**, where the fix in
mojtools reached none of them. `scripts/compare.sh` is therefore a byte-copy of
mojtools' canonical `compare-stub.sh`, vendored at
`rbx/resources/packagers/moj_next/scripts/compare.sh` — a test asserts the emitted
file is byte-identical to it.

**2. The checker is one file.** `checker-bridge.sh` compiles the package's checker
under `bwrap` with **only** `checker.cpp` and `testlib.h` bound into `/tmp`, and
`-I /tmp`. Nothing else is reachable, so a checker including `rbx.h` or a local
header would report a judge error on *every* test. The packager amalgamates the whole
closure — rbx's own testlib included — into a single `scripts/checker.cpp` (~207 KB),
and **refuses to package** when that cannot be done. `scripts/testlib.h` is
deliberately *not* shipped: a local copy takes precedence in the bridge.

Solutions get the same treatment, since MOJ compiles a submission from one file too.

## Time limits: calibration only

**MOJ measures the time limit; it is never authored.** `calibreitor.sh` runs every
`sols/good` solution, takes the worst time per language, scales it by
`TLMOD[calibrafactor]`, and writes `tl`/`tl.<host>`. So no `tl` is emitted and `conf`
carries the only knobs: `MEMLIMITMB` (peak RSS — setting it also makes MOJ drop the
virtual-memory ulimit and feeds the JVM `-Xmx` via `binfile.sh`), `ULIMITS[-f]`, and
`TLMOD[calibrafactor]=1.35`.

**Consequence:** the package is unjudgeable until a judge calibrates it, and rbx's
authored `timeLimit` is advisory. There is a **TODO** in `_write_conf` to derive the
factor from `timeLimit / measured model-solution runtime` so the calibrated limit
lands near rbx's number instead of 1.35x the model solution.

## Test naming (`naming.py`)

Samples are `sample001…`; everything else is `t<NN>_<group>_<NNN>` with `NN` the
group's index in `problem.rbx.yml`. Two properties are load-bearing:

- **Samples sort first.** MOJ's judging loop is a plain lexicographic glob over
  `tests/input/*`, and `sample` < `t`, so samples are judged and reported in the order
  the statement shows them. The index prefix makes the rest follow the authored order
  regardless of group names.
- **Both of MOJ's group heuristics agree.** `score-summary.sh` first strips trailing
  digits (`t01_easy_001` → `t01_easy_`) and compares against `${PAT%\**}` of each glob
  (`t01_easy_*` → `t01_easy_`), then falls back to a real glob match.

## Scoring

`tests/score` is emitted for POINTS problems only; BINARY gets none, so MOJ scores by
percentage of tests and Accepted still requires all of them. Guardrails learned from
reading `score-summary.sh`:

- Weights must be **integers** — the parser does `${SCORE//[^0-9]/}`, so `40.5` would
  be read as `405`. (`TestcaseGroup.score` is already an `int`; the check is defensive.)
- Group names must not contain `-` — lines are split with `IFS='-'`. The sanitizer
  reduces names to `[A-Za-z0-9_]`.
- A group with **no built tests is skipped**. An unmatched glob counts as "not
  executed" in `score-summary.sh`, which can never be Accepted.
- **Per-test partial credit is unavailable.** testlib `quitp`/`_points` maps to a
  judge error on MOJ; subtasks must go through `tests/score`. The packager warns when
  the checker *source* mentions them — checked on the source, never the amalgamated
  output, since testlib declares both itself.

## Languages

`MojLanguageExtension` (key `moj`, in `rbx/box/extensions.py`) mirrors
`BocaLanguageExtension`: `languages` (MOJ ids) + a required `template`, plus optional
`flags`. `get_emitted_moj_languages()` returns the union across env languages, and a
`scripts/<id>/` directory is emitted for each.

Java and Kotlin build a **manifest jar** so `run.sh` is just `java -jar`. This follows
`rbx/resources/packagers/boca/compile/java` and is deliberately *better* than MOJ's own
`lang/java/compile.sh`, which elects the main class by grepping for `main` and falling
back to `ls *.class` — locale-dependent once javac emits nested `Main$X.class`.

## Out of scope

- **Statements.** `statement_types()` returns `[]`, so nothing is built; a dummy
  `docs/enunciado.md` with the mandatory `## Entrada`/`## Saída` is written instead.
  It carries no title, no examples and no fenced blocks (a fence trips
  `validate-problem.sh`'s hand-written-example warning).
- **Interactive.** `task_types()` is `[BATCH]`. MOJ's arbiter protocol (test in
  `argv[1]`, last stderr line `WRONG <reason>`, FIFO driver, per-language SIGPIPE
  handling) is structurally unlike a testlib interactor and deserves its own design.
- **`.moj-meta.json`.** Server-owned; never written by the package.

## Running tests

```bash
uv run pytest tests/rbx/box/packaging/moj_next/
```

The checker-compilation tests skip without `g++`. To exercise the real bridge, clone
`cd-moj/mojtools` and run the emitted `scripts/compare.sh` with `MOJTOOLS_DIR` set:
correct output must exit 4, wrong output 6.
