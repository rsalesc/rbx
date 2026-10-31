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

Both **batch** and **interactive** problems are supported, though interactive ones come with a
few caveats -- see [Interactive problems](#interactive-problems).

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

MOJ shows each reader the statement in their language, and it knows three: Portuguese, English
and Spanish. Each one has a fixed place in the package, a *slot*. The main slot is the
Portuguese one, and English and Spanish each get a slot of their own. MOJ always serves the main
slot as Portuguese, whatever language you put in it.

{{rbx}} fills one slot per language from your statements, taking the topmost (first-listed)
statement in each language:

- The Portuguese statement goes to the main slot.
- The English and Spanish statements each go to their own slot, sample explanations included.

{{rbx}} leaves out any other statement and tells you why: a statement in a language MOJ
doesn't know, or a second statement in a language that already has one. At the end of the
build, {{rbx}} prints which statement went into which slot.

Each statement shows its own title: the statement's `title`, or else the package's `titles`
entry for its language. A statement with neither shows the main title. The main title comes
from the statement in the main slot, so the body and the title always match.

If the Portuguese statement isn't the topmost one, it still takes the main slot, and {{rbx}}
warns you. The topmost statement goes to its own slot if it's in English or Spanish. If it's in
a language MOJ doesn't know, {{rbx}} stops and asks you to
[choose the main statement](#choosing-the-main-statement) yourself.

If your problem has no Portuguese statement, the topmost statement takes the main slot, whatever
its language. When it's in English or Spanish, it fills its own slot too, so English readers
still find it under English.

A few things to keep in mind:

- MOJ **builds the examples section itself** from the sample tests, so your statement must not
  have one of its own. {{rbx}} refuses to package a statement MOJ would render with warnings,
  rather than shipping it and letting you find out on the server.
- A problem **without sample tests** packages fine, and its statement simply shows no examples.
  {{rbx}} tells MOJ so explicitly, and warns you when it does -- left to its own devices, MOJ
  would fall back to publishing your first two *secret* tests as the examples.
- MOJ requires an **input** and an **output** section, and {{rbx}} always emits them, even when
  the corresponding block is empty -- in every translation, each in its own language.
- Figures are embedded into the rendered HTML, so a PDF figure (which is what TikZ
  externalization produces) is rasterized to PNG for you. That needs `pdftoppm`, from poppler; a
  statement with PDF figures and no poppler installed refuses to package, naming the figures.

### Choosing the main statement

You can put a different statement in the main slot with the `-l` or `--language` flag, passing
the language exactly as your statement declares it:

```bash
rbx package moj -l en
```

The `en` statement then fills the main slot and its own `en` slot. Because MOJ reads Portuguese
from the main slot only, your Portuguese statement has nowhere left to go: {{rbx}} leaves it out
and warns you, but does what you asked. If no statement is in the language you pass, {{rbx}}
stops.

Putting English in the main slot is rarely what you want. MOJ serves the main slot as
Portuguese, so it shows the English text under a Portuguese label, and readers who pick
Portuguese get English. If what you're after is an English-first contest, keep the Portuguese statement in the main slot and set the language
on the MOJ contest instead. In the contest's configuration, `LOCALE` picks the language teams
see first (for example, `LOCALE=en`), and `STATEMENT_LANGS` picks which ones they can switch
to, as MOJ's
[contest statement script](https://github.com/cd-moj/cdmoj/blob/master/server/api/v1/lib/contest-statement.sh)
reads them. Those are contest settings on MOJ, not something a package can set.

## Test groups and scoring

Test groups are supported, and translate into MOJ's own scoring file for problems that score by
subtasks -- the ones whose `scoring` is `points`, or a mapping configuring it, in `problem.rbx.yml`, with a `score` per
group. ICPC-style problems (`scoring: binary`, the default) ship no scoring file at all: MOJ
scores them by percentage of tests passed, and {{tags.accepted}} still requires all of them.

Two constraints come from MOJ's side, and {{rbx}} checks both before packaging:

- Group **weights must be integers**. MOJ's parser strips everything that isn't a digit, so a
  `40.5` would be read as `405`.
- Group **names must not contain `-`**, which MOJ uses as a field separator.

A group can also depend on other groups, so that it only scores when every group it depends on
passes too. You list them in the group's `deps`. To add them to every group at once, set
`scoring.dependencies` in [`problem.rbx.yml`](/setters/reference/package). With `samples`, every
group depends on `samples`. With `ladder`, each group depends on the one before it.

MOJ has no such notion: it scores each group on its own tests alone. So {{rbx}} copies into each
group the tests of every group it depends on, directly or through another group, and MOJ then
scores it exactly as `rbx run` does. The copies make the package larger and the judging slower,
and {{rbx}} prints how many it made.

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

## Interactive problems

*If you haven't read the [Interactors section](../grading/interactors.md) yet, you should read it
before proceeding.*

MOJ doesn't know what a {{testlib}} interactor is. You don't have to do anything about it:
{{rbx}} ships your interactor together with a small driver of its own, which runs it against the
solution and decides the verdict by the same rules as `rbx run`. The one exception is the time
limit, covered in the warning below. A solution that crashes gets a runtime error, a solution
your interactor rejected gets a wrong answer even if the solution then keeps running or
crashes, and the message your interactor gave shows up on MOJ.

What you *do* have to keep in mind is that MOJ never runs a checker after the interaction, and
never shows your interactor the expected output. So the interactor must decide the verdict on
its own, and {{rbx}} will **refuse to package**:

- an interactor that relies on a checker (`legacy: true`, see
  [Do I need to write a checker?](../grading/interactors.md#do-i-need-to-write-a-checker));
- an interactor that isn't written in C++.

!!! warning "Leave headroom in the time limits"
    MOJ measures an interactive solution by the **wall time** of the whole interaction: your
    interactor and the language runtime's startup count against the limit too. The limits
    `rbx time -p moj` estimated locally don't include them, so a tight limit can turn a crash or
    a wrong answer into a time limit. Give interactive problems a comfortable margin, or
    [measure on MOJ itself](../profiling/remote.md#timing-on-moj) with `rbx time -p moj --runner moj`, whose
    timings already include the whole interaction.

MOJ doesn't show examples for an interactive problem, since a test's input is the interactor's
secret. So {{rbx}} writes your samples into the statement itself, under an **Example** section:
each sample's interaction goes in a single block, with the interactor's lines indented and your
program's lines as they are, followed by the sample's explanation.

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

!!! note "On macOS, check your bash first"
    The CLI needs bash 4 or newer, and macOS ships 3.2. Installing a newer bash isn't enough on
    its own -- see [The MOJ CLI needs bash 4 or newer](#the-moj-cli-needs-bash-4-or-newer).

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

Uploading also queues the calibration right after it, whether or not you passed `--calibrate`:
a package is only judgeable once a judge has calibrated it, so there's nothing to gain from
uploading one and leaving it uncalibrated. It's a long server-side job and {{rbx}} doesn't wait
for it -- check on it with `moj check <org>#<problem>` whenever you want.

The calibration is queued on **every judge in the park**, not just on the first one free. MOJ's
judges aren't identical machines, and it publishes the time limit as the *maximum* across the
judges that calibrated -- so a package measured on one machine is judged, on every other one,
against a limit nothing ever measured there. Calibrating everywhere makes the published limit
the one that holds on the slowest judge a submission can land on. When no judge is reachable at
all, {{rbx}} says so and falls back to a single calibration rather than leaving your uploaded
package unjudgeable; re-run `moj calibrate <org>#<problem> --all-judges` once the park is back.

## Iterating faster with a single solution

Calibration runs **every solution the package ships**: the accepted ones to measure the limits,
then the rest to check they get the verdict you declared. On a problem with a dozen solutions
that's the slowest part of an upload, and it's paid again on every re-upload.

While you're still iterating -- fixing a statement, re-cutting the tests, re-uploading over and
over -- `--reference-only` (or `-ro`) ships just the reference solution, your main one, and
drops the rest:

```bash
rbx package moj -u -ro
```

Calibration then has exactly one solution to run, which is the minimum MOJ accepts. Everything
else about the package is unchanged, and your solutions are still all run and checked locally
before it's built -- what you give up is the judge's own verification of them.

!!! warning
    A package built this way is for iterating, not for the contest. Package again without the
    flag before the problem goes live, so calibration verifies your solutions on the judge --
    and, under `--calibrate`, so MOJ measures a limit for every language you ship a solution in.

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
the package would ship as the main one -- the Portuguese one, else the topmost declared, or the
one you name with `--language` / `-l`:

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

### The MOJ CLI needs bash 4 or newer

If `moj` greets you with

```
moj: preciso de bash >= 4 (macOS: brew install bash e rode com ele)
```

then the CLI is fine and your shell isn't. `moj` is a bash script that uses features added in
bash 4, and macOS still ships bash **3.2** as `/bin/bash` -- it has for well over a decade, and
it isn't going to change.

Installing a newer one is only half the fix. `moj` starts with `#!/usr/bin/env bash`, so the
shell that runs it is whichever `bash` comes **first on your `PATH`** -- and Homebrew installs
its own without touching the system one. If `/opt/homebrew/bin` (or `/usr/local/bin`, on Intel)
isn't ahead of `/bin`, you get 3.2 no matter what you installed.

So put it there, in the file your shell reads on every session:

```bash title="~/.zshrc"
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Then check that you got the one you meant:

```bash
bash --version   # should say 5.x, not 3.2
moj whoami
```

`moj-contest` carries the same requirement, and the same fix covers it.

#### If you can't change your `PATH`

Point {{rbx}} at an interpreter and the script instead:

```bash
export RBX_MOJ_BINARY="$(brew --prefix)/bin/bash $(command -v moj)"
```

{{rbx}} splits `RBX_MOJ_BINARY` the way a shell would, so it holds a whole command rather than a
path. This is a fallback, not the fix: it hard-codes paths that break when you change machines,
and it does nothing for the times you run `moj` yourself. Prefer the `PATH`.

### My problem has a tight `outputLimit`, but MOJ doesn't enforce it

It doesn't, and that's on purpose. MOJ applies a single file-size limit to both the *compilation*
and the *execution* of a submission, so a problem with a small `outputLimit` made the linker fail
to write the executable -- every submission came back as a compilation error without reaching a
single test.

{{rbx}} therefore pins that limit high (100 MiB) and accepts the cost: a runaway solution is cut
off there instead of at your threshold. {{rbx}} still enforces `outputLimit` locally, so a
solution that overruns it shows up in `rbx run` long before MOJ would say anything.

### rbx warns about mojtools when packaging

A MOJ package includes a few scripts that belong to MOJ itself rather than to {{rbx}}: small
pointers that tell the judge to use its own checker bridge or, for an interactive problem, to
compile your interactor and read its verdict. {{rbx}} downloads a fresh copy of each from
[mojtools](https://github.com/cd-moj/mojtools), the judge's toolkit, every time it builds a
package.

You may see one of two warnings about it:

- **It could not fetch from mojtools.** You're probably offline. {{rbx}} falls back to the
  copy it ships with and names the mojtools version that copy came from. The package still
  works, but its scripts may be older than MOJ's current ones, so package again once you're
  online if you can.
- **mojtools changed since the copy bundled with rbx.** Nothing for you to do: the package
  already uses the current upstream files. It only means a newer {{rbx}} will catch up.
