# CLAUDE.md — MOJ packager

`MojPackager` (`rbx package moj`) targets **MOJ**
(`moj.naquadah.com.br`), judged by [`cd-moj/mojtools`](https://github.com/cd-moj/mojtools).
It extends `BasePackager` directly and shares no code with BOCA.

- Design doc: `docs/plans/2026-08-13-moj-next-packager-design.md`
- Implementation plan: `docs/plans/2026-08-13-moj-next-packager.md`

  (Both were written while this lived as a second `moj-next` packager beside the
  legacy one; it has since replaced it outright and taken the `moj` name.)

## Why it replaced the old one

The previous packager (a `BocaPackager` subclass) targeted a shape MOJ no longer
accepts: it authored a time limit MOJ *measures*, bundled a private copy of the
checker bridge that MOJ banned, emitted `docs/enunciado.pdf` (not a recognized
format), and named every test `001`/`002`, so a package had **no samples** and failed
validation outright. Interactive problems are the one thing it covered that this one
does not yet — see [Out of scope](#out-of-scope).

## The two rules that shape everything

**1. Stub on the host, copy in the jail.** From `mojtools/CLAUDE.md`: what runs on
the judge **host** (`scripts/compare.sh`) ships as a ~10-line stub pointing at
mojtools; only what enters the **jail** (`scripts/<lang>/{compile,run}.sh`) is a real
copy, because mojtools does not exist in there. A package carrying its own bridge
copy is what replicated one `bwrap` bug into **198 packages**, where the fix in
mojtools reached none of them. `scripts/compare.sh` is therefore a byte-copy of
mojtools' canonical `compare-stub.sh`, vendored at
`rbx/resources/packagers/moj/scripts/compare.sh` — a test asserts the emitted
file is byte-identical to it.

**2. The checker is one file.** `checker-bridge.sh` compiles the package's checker
under `bwrap` with **only** `checker.cpp` and `testlib.h` bound into `/tmp`, and
`-I /tmp`. Nothing else is reachable, so a checker including `rbx.h` or a local
header would report a judge error on *every* test. The packager amalgamates the whole
closure — rbx's own testlib included — into a single `scripts/checker.cpp` (~207 KB),
and **refuses to package** when that cannot be done. `scripts/testlib.h` is
deliberately *not* shipped: a local copy takes precedence in the bridge.

Solutions get the same treatment, since MOJ compiles a submission from one file too.

## Time limits: pinned, or calibrated on demand

**MOJ measures the time limit; rbx pins it.** `calibreitor.sh` runs every `sols/good`
solution, takes the worst time per language, and writes

```
TL[<lang>] = <TLMOD[calibrafactor]> * <worst measured time> + 0.02
```

into `tl`, with `TL[default]` the smallest of those; `build-and-test.sh` then adds
`TLMOD[<lang>.sum]` before judging. **`TLOVERRIDE` outranks all of it**:

```
TLOVERRIDE[<lang>] // TLOVERRIDE[default] // calibrated[<lang>]
```

is the limit MOJ judges with -- applied *after* the `TLMOD` arithmetic -- and the
same value it shows everywhere (training, contest, the TL sheet, `/problems/tl`).
It is read by **grep**, never evaluated, so the value is a literal number of
seconds. See [`timing.py`](timing.py), which owns every line emitted here.

**Default (`rbx package moj`): the limits are pinned from the `moj` limits profile.**
`rbx time -p moj` estimates them; the packager emits
`TLOVERRIDE[default]=<base>` plus a `TLOVERRIDE[<lang>]=<its limit>` for every
language whose limit differs from that default. The default is the **tightest**
limit involved (the profile's own base included), since a language the package
ships no scripts for falls back to it.

Calibration still runs and its measurements still land in `tl` -- harmlessly, since
the override wins regardless. (Changing an override changes the `tl-checksum` and so
triggers a recalibration; that is equally harmless.) rbx does **not** pin anything
through `TLMOD` any more: the pre-`TLOVERRIDE` trick -- a zero-slope
`TLMOD[calibrafactor]=<base - 0.02>+0` `bc` expression plus `TLMOD[<lang>.sum]`
increments -- is gone, and `calibrafactor` is now emitted only under `--calibrate`.

`CALIBRATIONTL` is raised alongside them: it is the dummy limit calibration enforces
while it runs the solutions, and its 5s default can be tighter than what this problem
allows. It is emitted as **max(largest pinned limit, 5s, `inferenceTimeout`)** --
the pinned limits because an accepted solution is allowed to run right up to its
language's limit, and `inferenceTimeout` because that is how long rbx itself waited
for a solution while estimating, and calibration re-runs the same ones
(`pass`/`slow`/`wrong` after `good`). Below the 5s default nothing is emitted.

**Without a profile the packager refuses**, rather than silently falling back to a
factor nobody chose: run `rbx time -p moj`, or pass `--calibrate`.

**`rbx package moj --calibrate`** hands the decision back to MOJ, emitting
`TLMOD[calibrafactor]=<acToTimeLimit>` -- rbx's own ratio, so the judge's measurements
land where `rbx time` would have put the limit, but measured on the judge machine
rather than the setter's. It needs `timing.multipliers` in `env.rbx.yml`: a problem
estimating with a *formula* defines no such ratio, and packaging errors out saying so.

**A third mode, `ProbePinned(default_ms, per_rbx_language_ms)`**, exists for the MOJ
*runner* and is not reachable from the CLI. It pins exactly what the timing run asked
to measure under, and `rbx time` asks for a different shape in each of its two phases:
one `inferenceTimeout` cap for every language while it estimates from the accepted
solutions (so `TLOVERRIDE[default]` alone), and `ceil(TL_lang × timeLimitToTle)` **per
language group** while it checks the solutions expected to be too slow (so one
`TLOVERRIDE[<lang>]` each). `per_rbx_language_ms` is keyed by rbx language name and
translated to MOJ ids by `_probe_time_limits`, which pins each language under the
emitted spelling *and* its normalized alias, exactly as `_fixed_time_limits` does; the
default is the loosest limit, since only a language the run did not name falls back to
it. What must never happen -- and cannot, since this mode consults no profile -- is
emitting the *`moj` profile's* per-language entries beside a limit this run chose,
which would measure some language under a limit nobody asked for.
`_require_limits_profile()` deliberately does not fire, but `inferenceTimeout` still
feeds `CALIBRATIONTL`, since calibration runs on that package too. The three modes are
`ProfilePinned` / `JudgeCalibrated` / `ProbePinned`; `_time_limit_lines`,
`_report_time_limits` and `check_timing_setup` all dispatch on them, and
`fixed_limit_lines` takes the `explanation` block that says which story the emitted
numbers came from.

`tl` itself is still never emitted -- the package remains unjudgeable until a judge
calibrates it, since mojtools refuses to judge without that file. Pinning removes
rbx's dependence on *what* calibration measures, not on it running.

### `STOPWHEN_*`

BINARY problems get `STOPWHEN_WA/TLE/RE=y`: the verdict is decided by the first
failing test, so the rest only cost judge time.

POINTS problems deliberately get **none of them**, and this is correctness rather than
taste. `build-and-test.sh` checks `STOPWHEN_*` *before* the `RUNALL` guard, so it
breaks out of the test loop even when the caller asked for every test.
`score-summary.sh` then finds a group with no executed tests and scores it `null`,
counted as failed — a submission that failed group 1 but would have passed group 2
silently loses group 2's points. Never enable these alongside `tests/score`.

Worth knowing: the early break only fires from inside the `JOBSCOUNT > NPROC-1` branch
of the loop, so with fewer tests than cores nothing stops early. It is a best-effort
speed optimization, not a guarantee.

**A probe package gets exactly the bits its caller asked for** (`ProbePackage.halt_on`),
whatever its scoring -- `TLE` alone for `rbx time`, all three for `rbx run --fail-fast`,
none for a plain `rbx run`. Each is
not a compromise between the two cases above: it is the exact rule rbx asks for
locally. Both `rbx time` phases pass
`abort_on=lambda ctx: ctx.evaluation.result.outcome.is_slow()`, so a timeout — and only
a timeout — ends a solution's run. rbx cannot enforce that itself here, because the
gate in `run_solutions` works by not *dispatching* the testcases after a timeout and a
testrun has already run the whole submission by the time rbx sees any of it (which is
what `supports_abort=False` says). So the judge does it. Without this, a solution
expected to be too slow runs to the limit on **every** test when one test already
settled the question — by definition the most expensive solutions in the run, at full
cost, on a shared park.

`STOPWHEN_WA` and `STOPWHEN_RE` stay **off**, and the asymmetry is the point. The
upper-bound solutions are the ones expecting TLE (`TIME_LIMIT_EXCEEDED`,
`TLE_OR_RTE`), and a `TLE_OR_RTE` one may legitimately crash; halting there would
truncate the timings of a solution that is *not* too slow — the case that has a real
measurement to hand back — and would cut short a crash that
`_record_validation_run` reports as broken rather than as a violated bound. A WA does
not abort locally either.

Two things make the truncation safe to read. `ran_nothing` keys on `total_tests`, which
the live probe watched stay at 72 on a run that reported 4 tests, so a truncated run is
never mistaken for a submission that failed to build; and the tests MOJ does not report
become `SKIPPED` with no timing, exactly what the local gate writes. The POINTS hazard
above does not reach a probe either — it is about `score-summary.sh` scoring an
unexecuted group `null`, and nothing reads a probe's score: `MojRunner` reads `tests[]`,
`verdict_canon` and `total_tests`.

**The probe is also where the early break actually fires.** The caveat above — it only
fires from inside the `JOBSCOUNT > NPROC-1` branch, so with fewer tests than cores
nothing stops early — is about a *parallel* package. A probe sets
`ALLOWPARALLELTEST=n`, which pins `NPROC=1`, so the condition is `JOBSCOUNT > 0` and
holds from the second test onward. It is still mojtools' best-effort optimization rather
than a guarantee, and rbx depends on it for nothing: a run that stops early and one that
does not produce the same verdict, only at different cost.

### `ALLOWPARALLELTEST`

**MOJ runs the testset in parallel by default.** `build-and-test.sh` sets
`NPROC=$(nproc)` and only drops to a single job when `ALLOWPARALLELTEST` is exactly `n`:

```sh
NPROC=$(nproc)
[[ "$ALLOWPARALLELTEST" == "n" ]] && NPROC=1 && LOG " - Parallel Test not allowed in this problem"
[[ -n "$MAXPARALLELTESTS" ]] && NPROC=$MAXPARALLELTESTS && ...
```

The park reports **56 CPUs**, so a package that says nothing is judged with dozens of
tests competing for the machine. That is fine for judging — and it is why the `tests`
array of a testrun comes back unordered — but it is fatal to *measuring*: every time
reported is inflated by whatever contention it happened to meet.

**A probe package therefore emits `ALLOWPARALLELTEST=n`**, and mojtools already agrees
this is the right call when measuring: `calibreitor.sh:125` exports the same value
before running the accepted solutions. Calibration measures, so it serialises; the probe
measures, so it does too.

A package a setter builds is left at MOJ's default: there, parallelism is a
judging-speed feature and the limits are pinned through `TLOVERRIDE`, so what the judge
measures decides nothing.

Note `MAXPARALLELTESTS` is applied *after* this knob and would override it. The packager
emits it nowhere, and a probe must never grow one.

**`TLERERUN` goes with it, and for the same reason.** It defaults to `y`, and
`build-and-test.sh` re-runs any test that hit the limit and takes the **rerun's** verdict
and time. Its own log line says what it is for:

```
LOG " - Rerun: because got TLE while running parallel tests"
```

It exists to absorb a false TLE caused by the contention `ALLOWPARALLELTEST=n` has just
removed. Left on for a probe it does three unhelpful things: replaces a measured time with
a second one taken under different conditions, spends the judge twice on the slowest
solutions (the ones that were already the most expensive), and does so **only until some
test stays TLE** — the script latches `TLERERUN=n` from that point on — so which tests got
a second chance depends on the order they happened to finish in. A probe therefore emits
`TLERERUN=n`.

A package a setter builds keeps the default: there a false TLE is a wrong verdict for a
student, and a second chance is exactly right.

### `ULIMITS[-f]` is fixed, and deliberately not `outputLimit`

`conf` emits `ULIMITS[-f]=102400` (100 MiB in KB), a constant — **not** the problem's
`outputLimit`, which is what it used to be.

MOJ applies this ulimit to the **compile** step, not only to the running solution.
Observed on the judge on 2026-08-21, packaging a problem whose `outputLimit` was 100 KB:

```
collect2: fatal error: ld terminated with signal 25 [File size limit exceeded]
```

The linker could not write the executable, so *every* submission came back
`Compilation Error` without reaching a single test — any problem with a tight output
limit was simply unjudgeable on MOJ.

One knob cannot serve both purposes: a compile needs megabytes, a sane output limit is
often a few hundred KB. Pinning it high is the side that fails safe. The cost, stated
plainly: **MOJ no longer enforces the problem's `outputLimit`** — a runaway solution is
cut off at 100 MiB instead of the setter's threshold. rbx still enforces `outputLimit`
locally, so a solution that overruns it shows up in `rbx run` long before MOJ would have
said anything. See `OUTPUT_ULIMIT_KB` in [`packager.py`](packager.py).

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

## Solutions

`ACCEPTED` → `good/`, `ACCEPTED_OR_TLE` → `pass/`, `is_slow()` → `slow/`, the
incorrect outcomes → `wrong/`, and `ANY` → `upcoming/`. `ANY` asserts nothing about
the outcome, so filing it under any of the others would state an expectation the
package does not make; `upcoming/` is MOJ's drafts directory.

Bounding what `upcoming/` buys: `calibreitor.sh` runs `sols/good` (for the time limit)
and then `pass`, `slow`, `wrong` (verification only, and skipped entirely under
`CALIBRATE_ONLY_GOOD=1`) — it **never runs `upcoming/`**. `tl-checksum.sh` hashes only
`sols/good` among the solution dirs, so a draft never forces a recalibration either.
Shipping drafts is about not losing them, not about getting them executed.

**`rbx package moj --reference-only` / `-ro` ships only the model solution** (`reference_only`,
read in `_solutions_to_ship` beside the probe case). Calibration runs everything the package
ships — `sols/good` to measure, then `pass`/`slow`/`wrong` to verify — so on a problem with many
solutions it is the bulk of an upload, paid again on every re-upload. The flag exists to make
that iteration cheap; what it costs is exactly the judge-side verification, so `_write_solutions`
says so out loud and the docs say to package again without it before the problem goes live.
It is orthogonal to the timing mode, and it feeds
`_languages_with_an_accepted_solution` — which reads the solutions **shipped**, not the ones
declared, so under `--calibrate` the uncalibrated-languages warning names the languages the flag
just dropped and points at the flag as the fix.

## Languages

`MojLanguageExtension` (key `moj`, in `rbx/box/extensions.py`) mirrors
`BocaLanguageExtension`: `languages` (MOJ ids) + a required `template`, plus optional
`flags`. `get_emitted_moj_languages()` returns the union across env languages, and a
`scripts/<id>/` directory is emitted for each.

Java and Kotlin build a **manifest jar** so `run.sh` is just `java -jar`. This follows
`rbx/resources/packagers/boca/compile/java` and is deliberately *better* than MOJ's own
`lang/java/compile.sh`, which elects the main class by grepping for `main` and falling
back to `ls *.class` — locale-dependent once javac emits nested `Main$X.class`.

**Java sources are renamed to their public type inside the jail**, by
`scripts/java/compile.sh`, before javac runs. javac is the only party that requires the
two to agree: rbx names a solution file after the *solution*
(`vinicius_fastIO.java` holding `public class Main`) and MOJ reads the name only to pick
the language, so the mismatch is expected and would otherwise be a hard compile error —
on a packaged solution during calibration, and equally on a contestant's submission
whose file name is not their class. Doing it in the jail rather than at package time is
what keeps both cases covered, and avoids the collision a host-side rename would create
the moment two solutions both declare `public class Main`.

## Statements (`statement.py`, `statement_assets.py`)

`statement_export_params()` forces externalize+demacro exactly as
`PolygonPackager` does, so the build leaves the `blocks.sub.yml` / `macros.json`
/ TikZ PDFs that [`statements/export.py`](../../statements/export.py) reads. The
packager then converts each block TeX → Markdown with pandoc and writes
`docs/enunciado.md` plus `docs/notes/<sample>.md`.

**`statement_types()` is overridden only to return nothing for a probe package**
(see [The probe package](#the-probe-package) below); for every package a setter
builds, the default `[StatementType.PDF]` applies — as for `PolygonPackager`, the other
block-consuming packager. That hook names the *output* a statement is built into,
and statements v2 emits only pdf/tex/md (`build_statements._emit_output`);
returning the *source* type `rbxTeX` fails the build outright with "statements v2
cannot yet emit output type rbxTeX. See #569 (S13)". Nor would TeX or Markdown
output do: externalization and demacro both run inside `render.compile_pdf`, so
anything other than the PDF build leaves no `macros.json` and no externalized
TikZ for the bundle to read. Consuming blocks is declared by
`statement_export_params()`, never here — `tests/rbx/box/packaging/test_statement_types.py`
pins this for every packager.

**MOJ renders statements with pandoc itself** (`render-statement.sh`, the single
source shared by the editor's *Pré-visualizar*, `gen-problem-json.sh` and
`validate-problem.sh`). So pandoc-flavored Markdown is the *target dialect*, not
a compromise: fenced divs, grid tables and attribute spans round-trip, and `$…$`
reaches the student as MathML with no conversion. `docs/enunciado.tex` was
rejected as an alternative -- MOJ would accept it, but the mandatory-heading
check greps markdown headings out of the raw source, so a `.tex` statement can
never pass the gate however well it renders.

What the packager owes the gate (`validate-problem.sh`):

- `## Entrada` / `## Saída`, **hard-required**, grepped from the raw file. Emitted
  unconditionally, even when the block is empty. Heading text follows the
  statement language (`entrada|input`, `saída|saida|output`, matched case
  insensitively), defaulting to Portuguese.
- **No title.** `render-statement.sh` injects the `<h1>` from `display_title` and
  strips a legacy `% Title` first line.
- **No examples section and no ``` fence** -- both land in `render_warnings`,
  since MOJ builds the examples itself from `tests/input/sample*`. `check_moj_gate`
  refuses to package rather than shipping a statement that warns.

### `--language`

`rbx package moj --language <lang>` picks the statement, mirroring
`rbx package polygon --language`; unset means the topmost one. `display_title`
resolves from **the same** statement, so the body and the rendered `<h1>` can
never come from different languages.

### The `docs/` remap base — read before touching `moj_layout()`

```
docs/enunciado.md              body
docs/notes/sample001.md        per-sample explanations, paired BY NAME
docs/assets/…                  statement-scope assets
docs/samples/{index}/…         sample-scope assets
```

`document_dirs['sample_explanation']` is a constant **`docs`**, not `docs/notes`,
even though that is where the note file lands. `gen-problem-json.sh` renders each
note with `--resource-path="$PKG/docs"` regardless of which sample it belongs to,
so `docs` is what its image references resolve against; a base of `docs/notes`
would derive `../assets/f.png` and break every note image. Expressing this needed
relaxing `SubtreeLayout`'s `{index}` requirement on document dirs (still required
for `asset_roots[SAMPLE]`, where many files land in the directory).

Note names come from `naming.testcase_name(..., is_sample=True)` rather than a
hand-spelled `sample%03d`, so a note can never stop pairing with its test.

### Figures: shipped as files, or inlined as base64

`statement.INLINE_IMAGES_AS_BASE64` picks between the two shapes. A **code-level
switch**, deliberately not a schema field: both produce a valid package, MOJ shows
the reader the same statement either way, and nothing about a problem says which
one it wants.

`False` (the default) ships `docs/assets/fig.png` and leaves the document citing
`![](assets/fig.png)` — the shape mojtools was built around, since
`render-statement.sh` passes `--resource-path=<pkg>/docs` precisely so pandoc can
find them, and it is the *renderer* that base64-embeds each figure into the HTML a
student reads. The files stay inspectable in the tarball and a figure cited twice
travels once.

`True` rewrites each reference to a `data:` URI carrying the file's bytes and ships
no image files at all (`statement_assets.base64_inliner` /
`discard_assets`, driven by `statement.discard_inlined_assets`), so the statement
renders identically wherever pandoc runs — no resource path, no files. It costs
~4/3 the size, carries a twice-cited figure twice, and makes the raw Markdown
unreadable by a human.

Two ordering facts the switch depends on. The rewrite runs on **pandoc's AST**
(`markdown_export.tex_to_markdown(..., rewrite_image_url=...)`), not over the
emitted Markdown, so a multi-kilobyte replacement is escaped and wrapped by
pandoc's own writer rather than by a regex. And it reads the **materialized**
figure, so `build_enunciado`/`build_notes` are called after `materialize` and
`rasterize_pdf_assets` — a TikZ figure is inlined as the rasterized PNG, never the
PDF the statement was authored against. Their `docs_root` is `docs/` for the body
*and* for the notes, for the same reason the remap base is (below); without it the
references are left alone whatever the switch says.

### PDF figures need poppler

MOJ renders to HTML and base64-embeds every image, so an `<img src="fig.pdf">` is
broken in every browser -- and rbx's TikZ externalization produces exactly that.
`RasterizingLayout` maps a `.pdf` placement to `.png` (in the *layout*, so the
derived remap already cites the rasterized name), and `rasterize_pdf_assets`
converts with `pdftoppm -png -r 300 -singlefile` after `materialize`. A statement
with no PDF figure never probes for poppler; one that has them and no poppler
**refuses to package**, naming the figures. SVG passes through untouched.

## `author`

MOJ hard-requires a non-empty `author` file. rbx has no first-class author field, so
`_author()` reads the `author` package **var** -- the same one a statement renders as
`\VAR{author}`, which is why it is a var rather than a new schema field: one place to
say the name, and the package and the statement cannot drift. Any primitive is
stringified (`vars` is untyped by design, and a name that parses as a number is still a
name); an absent or blank-once-stripped var falls back to `Unknown`, since an empty
`author: ""` must not travel through as an empty file that `validate-problem.sh` rejects.

## Out of scope

- **Interactive.** `task_types()` is `[BATCH]`. MOJ's arbiter protocol (test in
  `argv[1]`, last stderr line `WRONG <reason>`, FIFO driver, per-language SIGPIPE
  handling) is structurally unlike a testlib interactor and deserves its own design.
- **Collections and access control.** See `.moj-meta.json` below.

## `.moj-meta.json`

On a tar upload the server treats this file in **two tiers**:

- **Content fields** — `display_title`, `collections`, `languages` — are read from the
  tar. Absent or empty means *the server preserves what it already has*, not "reset".
- **Access fields** — `public`, `public_at`, `owner` — are **never** accepted from a
  tar; only dedicated API routes change them.

So the packager writes the content fields it can know and omits the rest:

| Field | Emitted? | Why |
|---|---|---|
| `display_title` | always | Required and never empty. Resolved with `naming.get_problem_title(...)`, the same helper BOCA uses — statement title override, then the package title, then `pkg.name`, with an actionable error when a package has several titles and no statement to disambiguate. |
| `languages` | when non-empty | The languages **`env.rbx.yml` declares** — see below. |
| `collections` | never | rbx has no notion of them; absent keeps the server's. |
| `public`, `public_at`, `owner`, `gitea` | never | Server-owned and ignored from a tar. `public` is additionally **fail-closed** in `gen-problem-json.sh` (absent = private); emitting it is how an unpublished problem leaks into an index served to anonymous users. |

**Why `languages` comes from `env.rbx.yml`** (issue #761). It is the whitelist of
submission languages — the API rejects anything outside it — so it answers "what may a
student write this in", and that is an environment-wide policy, not a property of which
solutions this problem happens to ship. It is exactly `get_emitted_moj_languages()`, so
every whitelisted language has a `scripts/<lang>/` dir *and* a `TLOVERRIDE` in `conf`:
MOJ can compile, run and time all of them.

It used to be the languages with an **accepted solution**, on mojtools' guidance that a
language without a good solution never gets a calibrated time limit. Pinning made that
reasoning obsolete — `_fixed_time_limits` emits a `TLOVERRIDE` per *emitted* language —
and left a bad failure mode standing: a problem whose setter wrote one C++ solution
silently became a C++-only problem, which is a contest-wide decision nobody took on
purpose.

Ids are normalized the way the server does: lowercased, `py2`/`py3` folded to `py`,
deduplicated, and sorted so the file is deterministic.

**The one case the whitelist outruns is `--calibrate`**, where the limits are MOJ's to
measure and it measures them from `sols/good`. A whitelisted language with no accepted
solution then falls back to `TL[default]` — the *tightest* measured limit, typically the
C++ one, which no Python submission survives. So `_report_submission_languages` prints
the enabled set always, and under `JudgeCalibrated` adds a warning naming those
languages, with both fixes (an accepted solution in them, or `rbx time -p moj`) — or,
under `--reference-only`, dropping the flag, which is what took their accepted
solution out of the package. Under the pinned modes there is nothing to warn about.

**A probe package still authors its own.** `ProbePackage(submission_languages=[...])` is
set when the package exists for rbx to *measure* timings on the judge rather than to be
judged (the MOJ runner). It ships **only the model solution** — `moj testrun` sends the
timed source in the request body, so the rest never have to be there, and
`calibreitor.sh` needs exactly one `sols/good` — and whitelists **every language rbx may
testrun**, which is a property of the run rather than of the env. The report is skipped
with it: it is about what the setter's env enables for students, and nobody else submits
to a throwaway `rbxt-` problem. A language it whitelists that the package emits no
scripts for gets `_warn_about_unscripted_languages` instead — a case the derived path
cannot reach, since there the two lists are the same one. The two axes are separate
constructor arguments because "what limits" and "what is in the package / who may
submit" are genuinely orthogonal.

## The probe package

`MojPackager(probe=ProbePackage(submission_languages=(...)), timing_mode=ProbePinned(...))`
builds a **throwaway package uploaded to measure timings**, never judged by students —
what the MOJ runner in [`rbx/box/runners/moj/`](../../runners/moj/) uploads to a private
`rbxt-` problem. Four differences from a package a setter builds, each argued where the
knob lives:

| | Probe | Why |
|---|---|---|
| `sols/` | model solution only | [`moj testrun`](#solutions) sends the timed source in the request body; calibration needs one `sols/good` |
| `languages` | every language rbx may testrun, across **both** `rbx time` phases | [the API rejects a submission outside it](#moj-metajson), a testrun included |
| `STOPWHEN_*` | whatever `halt_on` names (`TLE` while timing) | [the judge does what `abort_on` does locally](#stopwhen_) |
| `ALLOWPARALLELTEST` | `n` | [a timing measured against 55 competing tests is not a timing](#allowparalleltest) |
| `TLERERUN` | `n` | [the rerun's time replaces the measured one](#allowparalleltest) |
| `docs/` | always `DUMMY_STATEMENT` | see below |
| `conf` | the `TLOVERRIDE` block this run asked for | [the profile's limits are the ones this run exists to replace](#time-limits-pinned-or-calibrated-on-demand) |

The two axes are separate constructor arguments — "what limits" and "what is in the
package" are different questions — but of their product only one cell is legal, and
`__init__` rejects the rest: a probe must pin the limits the timing run asked for.

**Why the statement is always the dummy.** The real path reads `blocks.sub.yml` and the
externalized TikZ PDFs out of the v2 overlay, which only the forced-externalize
statement build writes. A runner calling `package()` directly would therefore hit
`StatementExportError` on any problem declaring an rbxTeX statement, and its only
escapes would be running pdflatex locally for a document nobody reads, or going through
`run_packager` — which re-runs the full local build *and every solution locally*, the
exact work the remote runner exists to avoid. `statement_types()` and
`statement_export_params()` return nothing for a probe for the same reason. Nothing on
MOJ ever renders a probe's statement, and a `MojGateError` over one would make
`rbx time --runner moj` refuse a timing run for a document that is never read.

**Pairing timings back.** `MojPackager.testcase_names()` is public precisely so the
runner never re-derives a name: it returns each built entry with the file name it takes
in the package, and `_write_tests` consumes that same list. The index is a **1-based
running counter over the built entries of each group**, not `entry.group_entry.index`
(0-based, over the declared ones), so a reimplementation yields well-formed names for
the *wrong* tests — silent timing misattribution, the one failure by-name pairing
exists to prevent.

**What a probe path can still raise.** `MojPackager` reports setter mistakes with
`typer.Exit`, which a programmatic caller sees as a control-flow exception. Suppressing
the statement build removes most of them; what a probe can still reach is the checker
amalgamation (`_amalgamate_checker`, and a non-C++ checker), a package with no
`samples` group, no accepted solution, and — for a runner amalgamating a solution to
upload — `solution_content()`. Task 5 must catch `typer.Exit` around `package()`
regardless.

## Running tests

```bash
uv run pytest tests/rbx/box/packaging/moj/
```

The checker-compilation tests skip without `g++`. To exercise the real bridge, clone
`cd-moj/mojtools` and run the emitted `scripts/compare.sh` with `MOJTOOLS_DIR` set:
correct output must exit 4, wrong output 6.

`test_statement_e2e.py` runs mojtools' actual `validate-problem.sh` and
`render-statement.sh` over an emitted package, asserting the hard statement
checks pass with **empty** `render_warnings` and that both the statement figure
and the sample-note figure come back as embedded `data:` URIs. It is the only
check that the remap and the notes' resource-path base are right rather than
merely self-consistent, and it skips without `MOJTOOLS_DIR` (or without
`bash`/`jq`/`pandoc`):

```bash
MOJTOOLS_DIR=/path/to/mojtools uv run pytest \
  tests/rbx/box/packaging/moj/test_statement_e2e.py
```
