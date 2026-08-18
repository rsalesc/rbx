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
`TLMOD[<lang>.sum]` before judging. Both knobs are spliced into `bc` expressions as
**text**, which is what makes a fixed limit expressible at all -- see
[`timing.py`](timing.py), which owns every expression here.

**Default (`rbx package moj`): the limits are pinned from the `moj` limits profile.**
`rbx time -p moj` estimates them; the packager emits
`TLMOD[calibrafactor]=<base - 0.02>+0`, so the expression becomes
`<base - 0.02> + 0 * worst + 0.02` -- a line with slope zero. Every language, and
`TL[default]` with them, lands on the same base whatever the judge measured. Each
language above that base then gets `TLMOD[<lang>.sum]=<its limit - base>`. The base is
the **tightest** limit involved (the profile's own base included, since a language the
package ships no scripts for falls back to `TL[default]`), so no increment is ever
negative.

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

## Languages

`MojLanguageExtension` (key `moj`, in `rbx/box/extensions.py`) mirrors
`BocaLanguageExtension`: `languages` (MOJ ids) + a required `template`, plus optional
`flags`. `get_emitted_moj_languages()` returns the union across env languages, and a
`scripts/<id>/` directory is emitted for each.

Java and Kotlin build a **manifest jar** so `run.sh` is just `java -jar`. This follows
`rbx/resources/packagers/boca/compile/java` and is deliberately *better* than MOJ's own
`lang/java/compile.sh`, which elects the main class by grepping for `main` and falling
back to `ls *.class` — locale-dependent once javac emits nested `Main$X.class`.

## Statements (`statement.py`, `statement_assets.py`)

`statement_export_params()` forces externalize+demacro exactly as
`PolygonPackager` does, so the build leaves the `blocks.sub.yml` / `macros.json`
/ TikZ PDFs that [`statements/export.py`](../../statements/export.py) reads. The
packager then converts each block TeX → Markdown with pandoc and writes
`docs/enunciado.md` plus `docs/notes/<sample>.md`.

**`statement_types()` is deliberately not overridden**, so the default
`[StatementType.PDF]` applies — as for `PolygonPackager`, the other
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

### PDF figures need poppler

MOJ renders to HTML and base64-embeds every image, so an `<img src="fig.pdf">` is
broken in every browser -- and rbx's TikZ externalization produces exactly that.
`RasterizingLayout` maps a `.pdf` placement to `.png` (in the *layout*, so the
derived remap already cites the rasterized name), and `rasterize_pdf_assets`
converts with `pdftoppm -png -r 300 -singlefile` after `materialize`. A statement
with no PDF figure never probes for poppler; one that has them and no poppler
**refuses to package**, naming the figures. SVG passes through untouched.

### Known limitation: no math in sample notes

`gen-problem-json.sh` renders notes **without** `--mathml`, unlike the body, so
math inside an explanation reaches the student as a literal `\(x\)`. Nothing in
the package can fix it; rbx warns when a note contains math.

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
| `languages` | when non-empty | The languages with an **accepted solution** — see below. |
| `collections` | never | rbx has no notion of them; absent keeps the server's. |
| `public`, `public_at`, `owner`, `gitea` | never | Server-owned and ignored from a tar. `public` is additionally **fail-closed** in `gen-problem-json.sh` (absent = private); emitting it is how an unpublished problem leaks into an index served to anonymous users. |

**Why `languages` comes from `sols/good`.** It is the whitelist of submission
languages, and the API rejects anything outside it. MOJ measures a time limit per
language from the accepted solutions, and mojtools' guide is explicit: put a good
solution in every language you want to enable. (With pinned limits a language without
an accepted solution would still be *judgeable* -- it falls back to `TL[default]`,
which is the same pinned base -- but it is one nothing has ever been shown to solve,
so the whitelist deliberately stays keyed to the accepted solutions.) Deriving the list from the emitted
`scripts/<lang>/` dirs instead would key it off the setter's `env.rbx.yml`, which says
nothing about who may submit what — and would silently *narrow* the default (absent =
all languages) to whatever the preset happens to declare.

Ids are normalized the way the server does: lowercased, `py2`/`py3` folded to `py`,
deduplicated, and sorted so the file is deterministic.

**The narrowing is reported, never silent.** The package ships `scripts/<lang>/` for
every language the env declares, but the whitelist is derived from accepted solutions,
so a setter who ships only a C++ solution gets a C++-only problem. Packaging therefore
prints the enabled set and warns by name about every emitted language left out —
"no **ACCEPTED** solution in those languages" — with the fix (add an accepted solution
in that language). See `_report_submission_languages`.

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
