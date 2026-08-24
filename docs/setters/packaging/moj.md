# Packaging: MOJ

{{rbx}} provides a command to build packages for [MOJ](https://moj.naquadah.com.br),
the judge used by a few Brazilian universities.

```bash
rbx package moj
```

Or, if you want to build the package for all problems in your contest:

```bash
rbx each package moj
```

MOJ has no contest-level package, so `rbx each package moj` is as far as it goes -- you'll
get one package per problem.

Only **batch** problems are supported. Interactive problems are not: MOJ has an interaction
protocol of its own, which is structurally unlike a {{testlib}} interactor and doesn't map
onto one.

The MOJ packager uses the `moj` [limits profile](../profiling/profiles.md), so create it with
`rbx time -p moj` before packaging.

!!! tip
    You can also point `rbx run` and `rbx time` at MOJ itself, and have your solutions run on the
    judge park instead of on your machine. See [Running on the judge itself](../running/remote.md)
    and [Timing on the judge itself](../profiling/remote.md).

## Time limits

MOJ traditionally **measures** the time limit itself: it runs your accepted solutions on the
judge machine and derives the limit from the worst time it sees.

By default, {{rbx}} doesn't let it. It **pins** the limits you estimated with `rbx time -p moj`
into the package -- a base limit, plus a per-language limit for every language whose limit
differs from it. The limit a solution gets on MOJ is then the one you profiled, and the same one
MOJ shows everywhere it displays a time limit.

Since the limits come from a profile, packaging **fails** if you haven't created one. That's
deliberate: falling back to a factor nobody chose is exactly the silent behavior the pinning is
there to remove.

### Letting MOJ calibrate instead

If you'd rather have the limits measured on the judge machine -- which is, after all, the machine
that will judge the contest -- pass `--calibrate`:

```bash
rbx package moj --calibrate
```

MOJ then measures your accepted solutions and multiplies the worst time by the same ratio
{{rbx}} would have used locally, so the limit lands where `rbx time` would have put it, but
measured on the judge park.

!!! warning
    `--calibrate` needs `timing.multipliers` in your `env.rbx.yml`. A problem that estimates its
    limit through a [formula](../profiling/computing.md) defines no such ratio, and packaging
    will tell you so.

Either way, the package is only judgeable **after a judge calibrates it** -- that's a MOJ rule,
not an {{rbx}} one. Pinning removes your dependency on *what* calibration measures, not on it
running.

## Statements

MOJ renders statements with pandoc, so {{rbx}} converts your {{rbxtex}} statement into Markdown
and ships that, together with one file per sample explanation.

If you have multiple statements, you can pick which one goes into the package with the `-l` or
`--language` flag:

```bash
rbx package moj -l en
```

The rendered problem title comes from the very same statement, so the body and the title can
never disagree.

A few things to keep in mind:

- MOJ **builds the examples section itself** from the sample tests, so your statement must not
  have one of its own. {{rbx}} refuses to package a statement MOJ would render with warnings,
  rather than shipping it and letting you find out on the server.
- MOJ requires an **input** and an **output** section, and {{rbx}} always emits them, even when
  the corresponding block is empty.
- Figures are embedded into the rendered HTML, so a PDF figure (which is what TikZ
  externalization produces) is rasterized to PNG for you. That needs `pdftoppm`, from poppler; a
  statement with PDF figures and no poppler installed refuses to package, naming the figures.

## Test groups and scoring

Test groups are supported, and translate into MOJ's own scoring file for problems that score by
subtasks -- the ones whose `scoring` is set to `points` in `problem.rbx.yml`, with a `score` per
group. ICPC-style problems (`scoring: binary`, the default) ship no scoring file at all: MOJ
scores them by percentage of tests passed, and {{tags.accepted}} still requires all of them.

Two constraints come from MOJ's side, and {{rbx}} checks both before packaging:

- Group **weights must be integers**. MOJ's parser strips everything that isn't a digit, so a
  `40.5` would be read as `405`.
- Group **names must not contain `-`**, which MOJ uses as a field separator.

!!! danger "Per-test partial credit is unavailable"
    MOJ reports a {{testlib}} `quitp` (a partially correct verdict) as a judge error. If you
    want partial scoring, it has to go through test groups and their weights.

## Submission languages

MOJ keeps a whitelist of the languages a problem accepts, and {{rbx}} derives it from the
languages your environment declares in `env.rbx.yml` -- the same ones it ships compile and run
scripts for in the package. Packaging prints the list, so you always see what a student may
submit.

To take a language off the whitelist, remove it from `env.rbx.yml`. You don't need an accepted
solution in a language to enable it: the time limits are pinned from the `moj` limits profile,
which covers every language your environment declares.

The exception is [`--calibrate`](#letting-moj-calibrate-instead), where MOJ
measures the limits itself -- from the accepted solutions the package ships. A whitelisted
language with no accepted solution then falls back to the *tightest* limit MOJ measured,
usually the C++ one, which no Python submission is going to survive. Packaging warns by name
when that's the case; the fixes are an accepted solution in that language, or pinning the
limits with `rbx time -p moj`.

## Checkers

MOJ compiles the checker in an isolated environment where only the checker itself and
{{testlib}} are reachable, so a checker that includes a header of yours -- `rbx.h` included --
wouldn't find it, and would report a judge error on *every* test.

You don't have to do anything about it: {{rbx}} amalgamates your checker and everything it
includes into a single file before shipping it. What it will do is **refuse to package** when
that isn't possible, rather than hand you a package that fails on every test. The same applies
to the solutions it ships, since MOJ compiles a submission from a single file too.

## Uploading to MOJ

You can upload the package by setting the `--upload` / `-u` flag:

```bash
rbx package moj -u
```

Or, for the whole contest:

```bash
# Will upload all problems in the contest
rbx each package moj -u

# Will upload only problem A
rbx on A package moj -u
```

Uploading goes through the [`moj` CLI](https://github.com/cd-moj/moj-cli), so you have to be
logged in with `moj login` first. {{rbx}} reuses that session and never handles your credentials.

The problem is created on the server if it doesn't exist yet, and is named `<org>#<problem>`.
You tell {{rbx}} which org to use in your `env.rbx.yml`:

```yaml title="env.rbx.yml"
extensions:
  moj:
    org: "your-org"
```

!!! warning
    Leave `org` unset and the package goes to your **own login** -- a private personal org
    nobody else can see. {{rbx}} warns you when that happens, but it's much better to hear it
    here than from a co-setter.

The org itself is *not* created for you: uploading to an org that doesn't exist fails.

Combining `-u` with `--calibrate` also queues the calibration right after the upload. It's a long
server-side job and {{rbx}} doesn't wait for it -- check on it with `moj check <org>#<problem>`
whenever you want.

## Previewing what a contest uploads

Uploading a whole contest creates a problem per short name, and a typo in an org or a package
name is only visible once it's on the judge. `rbx tooling moj summary` shows you the whole list
first, from inside the contest directory:

```bash
rbx tooling moj summary
```

```
            MOJ upload summary: my-contest
┏━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ # ┃ Title     ┃ MOJ problem       ┃ Color          ┃
┡━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ A │ A Plus B  │ your-org#a-aplusb │ ● red #ff0000  │
│ B │ Chocolate │ your-org#b-choco  │ ● blue #0000ff │
└───┴───────────┴───────────────────┴────────────────┘
```

One row per problem: its short name in the contest, the title MOJ would display, the
`<org>#<problem>` it would be created as, and the color the contest gives it (empty when the
problem configures none).

Every value is resolved the way `rbx package moj` resolves it, so the table is a preview of the
upload rather than a second guess at it. The title in particular comes from the very statement
the package would ship -- the topmost declared one, or the one you name with `--language` / `-l`:

```bash
rbx tooling moj summary -l en
```

Nothing is built and nothing is sent to the judge. You don't even need to be logged in, as long
as `extensions.moj.org` is set: reading your login is the one thing a session is needed for, and
that only happens when no org is configured.

### Copying the list out

Add `--porcelain` when the list is going somewhere else -- a message to a co-setter, a
spreadsheet, a shell loop. You get one tab-separated line per problem, no table and no colors:

```bash
rbx tooling moj summary --porcelain
```

```
A	A Plus B	your-org#a-aplusb	#ff0000	red
B	Chocolate	your-org#b-choco	#0000ff	blue
```

The fields are the table's columns in order: short name, title, MOJ problem, color and color
name. A problem with no color still has the two (empty) fields, so `cut -f3` reads the ids of
every problem no matter how the contest is configured:

```bash
rbx tooling moj summary --porcelain | cut -f3
```

Warnings go to stderr in this mode, and a problem that couldn't be read is reported there
instead of taking a line -- so whatever consumes the output never sees a problem pointing at an
empty id.

## Downloading a submission

When a contestant's solution does something your testset didn't expect, you usually want to run
it here rather than read it on the contest page. Point any command that takes a solution at
`@moj/<contest>/<submission>` and {{rbx}} downloads the source into the package:

```bash
rbx run @moj/sbc2026/d89e6b7735c675fd7b50b3354ba64097
rbx download remote @moj/sbc2026/d89e6b7735c675fd7b50b3354ba64097
```

The submission id is the 32-character hexadecimal string MOJ shows beside the submission. The
downloaded file lands under the package's remote cache and, as with any downloaded code,
{{rbx}} shows it to you for review before running it.

If you work in one contest at a time, set `MOJ_CONTEST` and drop the contest from the reference:

```bash
export MOJ_CONTEST=sbc2026
rbx run @moj/d89e6b7735c675fd7b50b3354ba64097
```

Prefer the long form in `problem.rbx.yml`. A reference you commit is read months later on
someone else's machine, where nothing says which contest was meant.

### Logging in to a contest

Downloading needs a session **for that contest**, which is not the one `moj login` creates --
that one covers the training area alone. Contest accounts are handed out by whoever runs the
contest, and they log in through a second CLI, `moj-contest`:

```bash
moj-contest login sbc2026
```

Install it alongside `moj` if you don't have it yet:

```bash
curl -fLO https://moj.naquadah.com.br/moj-contest && chmod +x moj-contest
```

As with uploading, {{rbx}} reuses the session that command establishes and never handles your
credentials.

### What you're allowed to download

**Judges see every submission in the contest.** If your contest account is a judge, a chief
judge or an admin, any submission id in that contest downloads.

**Everyone else sees only their own.** A submission id that isn't yours is reported as not found
rather than downloaded, and {{rbx}} says which of the two cases it hit -- reading someone else's
code needs a judge account, not a different reference.

## Troubleshooting

### My problem has a tight `outputLimit`, but MOJ doesn't enforce it

It doesn't, and that's on purpose. MOJ applies a single file-size limit to both the *compilation*
and the *execution* of a submission, so a problem with a small `outputLimit` made the linker fail
to write the executable -- every submission came back as a compilation error without reaching a
single test.

{{rbx}} therefore pins that limit high (100 MiB) and accepts the cost: a runaway solution is cut
off there instead of at your threshold. {{rbx}} still enforces `outputLimit` locally, so a
solution that overruns it shows up in `rbx run` long before MOJ would say anything.
