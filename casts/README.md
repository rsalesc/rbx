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
end_pause: 3s                # optional; hold the final frame (see below)

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
| `!Wait 3s` | Pause the *cast* without slowing the recording |
| `!Marker Chapter one` | A chapter marker in the player |
| `!Clear` | Clear the terminal |

`keys` accepts single characters, caret-escaped control codes (`^C`, `^D`,
`^M` for Enter), and durations (`500ms`) to pause between keystrokes. The keys
**must** leave the program exited, or the instruction hits its timeout.

### `end_pause`

Casts autoplay on a loop, so without a trailing hold the final frame — usually
the whole point of the recording — flashes past before anyone can read it.
Every recording therefore ends with a **3 second hold** by default. Set
`end_pause` to change it, or `0s` to opt out.

You do not need a trailing `!Wait` for this; the hold is applied after the last
instruction. A `!Wait` at the end would simply add to it.

The hold is a zero-byte output event at a later timestamp, not just an idle
gap — a player takes a cast's duration from its final event, so advancing the
clock without emitting anything would have no effect.

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
| `ab-problem` | A + B, one correct and one overflowing solution | build, run, irun, ui, BOCA packaging, `rbx time` |
| `graph-problem` | Connected-graph input, path checker, validator and checker unit tests | `rbx unit`, `rbx validate`, verification levels, build caching |
| `sum-problem` | Sum of N integers, `wa-overflow.cpp`, `vars.A.max` | both `rbx stress` recordings |
| `pair-problem` | Print any `a + b = N`, custom checker | custom-checker walkthrough |
| `guessing-problem` | Interactive guessing game with a testlib interactor | `rbx ui` on an interactive run |
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
