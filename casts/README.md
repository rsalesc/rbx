# Documentation recordings

The terminal animations in the docs are **generated artifacts**, not hand-made
recordings. Each one is described by a YAML spec in this directory, produced by
`mise run record`, and committed as a `.cast` file under `docs/assets/casts/`.

Nothing is uploaded anywhere. The docs play the committed file with a vendored
[asciinema-player](https://github.com/asciinema/asciinema-player), so refreshing
a recording never changes a URL and never requires editing a page.

## Commands

```bash
mise run record                 # re-record everything
mise run record run-basic       # re-record one
mise run record-check           # check every reference resolves (local only)
```

`record-check` is deliberately not wired into CI. It is a convenience for
spotting a page that references a cast nobody recorded, a cast nobody
references, or a leftover `TODO(record)` marker.

## Adding a recording

1. **Pick or add a fixture.** Fixtures in `fixtures/` are real `rbx` packages,
   shaped for teaching rather than for testing. Verify a new one builds
   standalone before using it:

   ```bash
   cd casts/fixtures/<name> && uv run rbx build
   ```

   Then delete the generated `build/`, `.rbx/` and `rbx.h` — `.gitignore`
   covers them, so `git status` should be clean.

2. **Write the spec** as `casts/<name>.yml`. The filename is the recording's
   name everywhere: it becomes `docs/assets/casts/<name>.cast` and the argument
   to the macro.

3. **Record and watch it.**

   ```bash
   mise run record <name>
   asciinema play docs/assets/casts/<name>.cast
   ```

4. **Embed it** with `{{ asciinema("<name>") }}`.

## Spec reference

```yaml
fixture: ab-problem          # required; a directory under casts/fixtures/
title: Running solutions     # optional; shown by the player
width: 100                   # optional; terminal columns (default 100)
height: 30                   # optional; terminal rows (default 30)
type_speed: 60ms             # optional; delay between typed characters
timeout: 120s                # optional; per-instruction limit
end_pause: 0s                # optional; extra dwell baked in (see below)

setup:                       # optional; runs for real, never shown
  - rbx build

instructions:                # required; at least one
  - rbx run                  # a bare string is a visible command
  - !Wait 3s

expect_contains:             # optional but strongly recommended
  - Timing summary
```

### Instructions

A bare string is a command that gets typed on screen and run. The tagged forms
give you more:

| Instruction | Meaning |
| --- | --- |
| `!Command {command: ..., hidden: true}` | Run it, but keep it out of the cast |
| `!Interactive {command: ..., keys: [...]}` | Run it and feed it keys — for TUIs and prompts |
| `!Command {command: ..., speed: 8}` | Run it, but play it back eight times faster (see below) |
| `!Command {command: ..., width: 80, height: 20}` | Run it in a terminal of its own size (see below) |
| `!Wait 3s` | Pause the *cast* without slowing the recording |
| `!Marker Chapter one` | A chapter marker in the player |
| `!Clear` | Clear the terminal |

`speed` and the two size keys work on `!Interactive` too.

`keys` accepts single characters, caret-escaped control codes (`^C`, `^D`,
`^M` for Enter), durations (`500ms`) to pause between keystrokes, and `x8`
tokens that change the playback rate from that point on. The keys **must**
leave the program exited, or the instruction hits its timeout.

### `speed`, and the `x8` key

A cast's timeline is real elapsed time, so a command that computes for a minute
costs a minute of playback. `speed` divides the time that command contributes:
`speed: 8` plays a minute of work in under eight seconds without dropping a
frame of it.

It scales **measured** time only. The typing animation is synthesized at
`type_speed`, so a fast-forwarded command still types its own name at a
readable pace.

One instruction, one rate is not always enough. `rbx time` is a single
interactive command holding both the seconds that let a reader take in a prompt
and the minute that waits out the estimation, so an `x8` inside its `keys`
switches rate part-way through and `x1` switches back:

```yaml
- !Interactive
  command: rbx time
  keys:
    - 4s          # read the strategy prompt at real speed
    - '^M'
    - x8          # ...then hurry through the estimation
    - 45s
    - x1
    - '^M'
```

An `x8` steers the recording rather than the program: it costs no time and is
never written to the pty.

One thing this buys beyond pacing: a key dwell is an authored duration, not a
measured one, so a scaled window has the same length on any machine. The
warning below about recording on an idle machine does not apply to what you
fast-forward.

### `width` and `height` per instruction

The spec's `width`/`height` size the whole recording, which sizes every screen
to the tallest one in it. An instruction can ask for its own:

```yaml
- !Command {command: rbx time --auto, height: 20}
```

Each instruction already runs on its own pty, so this is a genuinely smaller
terminal rather than a crop applied afterwards — `COLUMNS`/`LINES` go with it,
and Rich reflows into the smaller view instead of being clipped. The recorder
emits an asciicast `r` event so the player follows the change, and restores the
spec's size afterwards so a crop meant for one instruction does not leak into
the next.

### `end_pause`

Casts autoplay on a loop, and the final frame is usually the whole point of the
recording, so **every player waits 3 seconds on it before restarting**. That
wait lives in `docs/assets/casts-loop.js`, not in the cast file, and
`end_pause` therefore defaults to `0s`.

Create players through its `rbxCast(src, elementId, options, pauseMs)` helper
and nowhere else. There are two call sites — the `asciinema()` macro in
`main.py` for pages, and `docs/templates/home.html` for the landing page — and
when they each created their own player, the home page kept `loop: true` and
went on restarting instantly after the macro learned to pause. A test guards
this.

It has to live there. A trailing gap inside the cast is idle time like any
other: the player first clamps it to `idleTimeLimit` (1 second) and then
divides it by `speed`, so a recorded "3 second hold" plays for one second, or
half of one on a `speed=2` embed. The macro pauses in wall-clock time instead,
which is the same three seconds at any playback rate.

Set `end_pause` only when a recording wants extra dwell baked into the file
itself; it adds to the player's pause rather than replacing it. The hold it
writes is a zero-byte output event at a later timestamp, not just an idle gap —
a player takes a cast's duration from its final event, so advancing the clock
without emitting anything would have no effect.

### `expect_contains`

Each string must appear in the recorded output, checked *before* the cast is
written. This is what stops a stale recording from being published silently: if
`rbx run` changes its verdict table, the recording fails loudly and the
previous good cast is left untouched.

Pick strings that would genuinely disappear if the command broke — a solution
path, a section heading — not decoration.

Match against **one uninterrupted run of plain text**. Verification reads the
recorded bytes, and Rich splits a styled phrase with escape sequences, so
`Added 1 tests to test group corner's generatorScript` never matches even
though that is exactly what the terminal shows — the styling sits between
`corner` and `'s`. When an expectation fails on a string you can plainly see in
the playback, that is why: shorten it to a fragment that carries no markup.

## Fixtures

| Fixture | Shape | Used by |
| --- | --- | --- |
| `ab-problem` | A + B, one correct and one overflowing solution | build, run, irun, ui, BOCA packaging |
| `timing-problem` | Count pairs summing to K: an accepted C++ and Python solution, and a quadratic one that is genuinely too slow | every `rbx time` recording |
| `graph-problem` | Connected-graph input, path checker, validator and checker unit tests | `rbx unit`, `rbx validate`, verification levels, build caching |
| `sum-problem` | Sum of N integers, `wa-overflow.cpp`, `vars.A.max` | both `rbx stress` recordings |
| `pair-problem` | Print any `a + b = N`, custom checker | custom-checker walkthrough |
| `guessing-problem` | Interactive guessing game with a testlib interactor | `rbx ui` on an interactive run |
| `statement-contest` | Two-problem contest with `en`/`pt` statements, both contest templates and an infosheet | both statement recordings |
| `workspace` | Empty directory, not a package | `rbx create`, which needs somewhere to create *into* |

`graph-problem` also carries `broken/validator-without-connectivity.cpp`: the
same validator with its connectivity check removed, swapped in by the
`unit-validator-failure` setup so that recording can show a unit test actually
failing. It is not part of the package and nothing else reads it.

The fixtures are transcribed from the docs pages they illustrate, so a reader
sees the same code they just read. Three of them needed **corrections** the
pages still carry, because the snippets as printed do not run:

- The validator, checker and interactor snippets rely on `testlib.h` pulling
  `std` into scope. Under GCC 15 it does not, so the fixtures add the includes
  and the `using namespace std;`.
- The interactor in `docs/setters/grading/interactors.md` never writes `N` to
  the participant, though the statement above it says it does — any solution
  that opens by reading `N` deadlocks. It also reads the guess with
  `ouf.readInt`, rejecting the `? X` format the same statement specifies. The
  fixture fixes both.

`timing-problem` is the one fixture that carries **its own environment**, in
`.local.rbx/`. Everything the profiling pages teach — the ratios, the
upper-bound check they make possible, and the language groups that hand `java`
a limit derived from `cpp` — is configured in `env.rbx.yml` and nowhere else, so
a recording that leaned on the installed default environment would show
whatever that machine happened to have. A problem cannot fill the gap on its
own: `timing.multipliers` in `problem.rbx.yml` only *overrides* an environment
that already sets them, and errors otherwise.

That environment declares `testlib`, so the fixture needs it materialized
before the default checker will compile. Each timing recording does it in a
hidden setup step:

```yaml
setup:
  - rbx download testlib
```

It comes from rbx's library cache once warm; a cold cache makes that step reach
the network.

`timing-problem` also carries `broken/mislabeled.cpp`: a solution declared too
slow that is nothing of the kind, swapped in by the
`time-upper-bound-violation` setup so that recording can show the upper-bound
check catching one. It is not part of the package and nothing else reads it.

## Re-record on an idle machine

A cast's timeline is real elapsed time: the engine advances its clock by the
wall-clock time each command actually took. A recording made while the machine
is busy is therefore a *slower recording*, permanently — and the compile-heavy
fixtures are the ones that suffer. Recording the whole set with `mkdocs serve`
rebuilding in the background once stretched `unit-tests` from 9s to 22s.

So close the docs server and anything else expensive first, and re-record only
what changed rather than everything. Compare against the previous file before
committing; a cast that got noticeably longer with no change to its spec was
timed against load, not against `rbx`.

## Known gaps

- **`create-problem` needs the network.** `rbx create` clones the preset from
  GitHub and materializes its libraries, so this is the one recording that
  cannot be re-made offline. It is pinned in practice by the tool tag rbx
  checks out (the installed version), not by the spec.
- **`create-problem` does not `ls` the problem it just made**, even though the
  page prints an annotated tree right below it. The tree says `documents/`
  while the preset ships `statement/`, so showing both would put the
  contradiction on screen. Once the page and the preset agree, add the `ls`.
- **The BOCA upload recording** (`boca.md`, `packaging-walkthrough.md`) is still
  hosted on asciinema.org. `rbx package boca -u` uploads to a live BOCA server,
  and the pipeline has no way to stand one up. `record-check` reports these two
  as "not yet migrated" by design.

    It is still *played* by the vendored player, pointed at the hosted `.cast`
    (asciinema.org serves it with `Access-Control-Allow-Origin: *`), rather
    than by asciinema.org's `<script>` embed. That embed brings its own player,
    which only takes `data-loop` and restarts the instant the last frame is
    drawn — so going through ours is what gives it the same loop pause as every
    other recording. It remains the one embed that needs the network to play,
    and the only one whose bytes are not in this repository.
- **`stress-walkthrough` stops at the save confirmation** rather than going on
  to `rbx build`. Choosing `(create new script)` and typing `tests/corner`
  creates the file at `tests/corner.txt` but writes `path: corner.txt` into
  `problem.rbx.yml`, and the path is resolved from the package root — so the
  next build fails with `Generator script not found`. That is an rbx bug, not a
  recording one.

## How recording works

`scripts/record.py` drives `scripts/casts/`:

1. The fixture is copied to a tmpdir, so recording side effects never touch the
   source tree.
2. Each instruction is spawned as its **own process on its own pty**. EOF marks
   completion, so there is no shell prompt to detect and nothing to tune
   against `rbx`'s progress rendering. Shell state therefore does **not**
   persist between instructions — every one runs in the same directory with the
   same environment, so a `cd` inside a recording affects only that
   instruction.
3. The prompt and typing animation are synthesized straight into the cast
   timeline, so the recorded output contains only the command's own output.
4. Machine-specific detail is scrubbed: the tmpdir becomes `~/problems/<name>`,
   the home directory becomes `~`, and Rich's random OSC-8 hyperlink ids are
   dropped so an unchanged re-recording produces an unchanged file.

The real `HOME` is used, not a synthetic one: `rbx` keeps its compiler
configuration there, and a pristine `HOME` silently breaks compilation — a cast
of a failed build teaches nothing.

## Why not an off-the-shelf tool

- **VHS** renders beautifully but cannot emit asciicast; its export PR is still
  open. GIFs are far heavier and lose selectable text and player controls.
- **autocast** matched the design on paper, but v0.1.0 hangs on macOS 14 /
  arm64 with both its bash and python shells, with and without a tty.
- Prompt-detection recorders in general are fragile against `rbx`'s Rich
  progress output. Spawning one process per instruction sidesteps the problem
  rather than tuning around it.

See `docs/plans/2026-08-08-asciinema-recording-pipeline-design.md` for the full
rationale.
