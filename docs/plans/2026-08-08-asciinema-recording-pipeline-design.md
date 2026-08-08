# Systematic asciinema recordings for the docs

**Date:** 2026-08-08
**Status:** Design approved, pending implementation plan

## Problem

The docs embed 21 `{{ asciinema("<id>") }}` macros across 13 pages, each pointing at a
recording hosted on asciinema.org. Producing one means opening a terminal, recording by
hand, uploading, and pasting the returned ID into Markdown. Refreshing them after a
significant CLI change means doing that 21 times.

Three references are already rotting: `REPLACE_ME_CAST_ID` in
`setters/stress-testing-walkthrough.md`, and two `<!-- TODO(record) -->` markers in
`setters/custom-checker-walkthrough.md`.

The blocker is not the recording. It is the hosting: asciinema.org's
`POST /api/v1/recordings` always mints a **new** ID, and `PATCH` only edits metadata.
Re-recording therefore always forces a doc edit, so "refresh everything" can never become
a single command while the casts live there.

## Decisions

| Question | Decision |
| --- | --- |
| Hosting | Self-host `.cast` files in the repo; no asciinema.org uploads |
| Trigger | Local, manual (`mise run record`); no CI regeneration |
| Engine | [autocast](https://github.com/k9withabone/autocast) behind a thin in-repo wrapper |
| Fixtures | Dedicated, pedagogically shaped packages under `casts/fixtures/` |

### Engine alternatives considered

- **VHS** (Charm) — best maintained, best TUI handling, official Docker image and GitHub
  Action. Rejected because it emits GIF/MP4/WebM only; the asciicast-export PR
  ([#706](https://github.com/charmbracelet/vhs/pull/706)) is still open. GIFs are much
  heavier than casts and lose selectable text and player-side speed/idle controls.
- **Own the recorder** (a `pexpect` harness in-repo) — no foreign toolchain, shares
  fixtures and Pydantic-spec patterns with `tests/e2e`, full control over timeline
  normalization. Rejected *for now* as roughly 300–500 LOC of new surface to maintain.
  It remains the designated fallback; the spec files survive an engine swap unchanged.
- **`asciinema rec --headless -c`** alone — cannot simulate typing or drive a TUI, and
  several casts are of `rbx ui` and interactive `rbx irun`.

autocast wins on fit: it emits `.cast` natively, waits on **prompt detection** rather
than hand-tuned sleeps (important because `rbx build` durations vary), supports hidden
setup commands, exposes `Interactive` instructions with key sequences for TUIs, and its
`Wait` inserts pause time into the cast without slowing the run.

Its risk is maintenance: last commit May 2024, a Rust binary each contributor must
install, bash-only prompt configuration. The wrapper isolates it.

## Layout

Sources live outside `docs/` so MkDocs does not copy fixtures into the built site. Only
generated casts live inside.

```
casts/
  fixtures/ab-problem/          # real rbx packages, shaped for teaching
  fixtures/custom-checker/
  run-basic.yml                 # one spec per recording
  ui-navigation.yml
docs/assets/casts/run-basic.cast    # generated, committed
scripts/record.py                   # the wrapper
```

Spec filename = cast basename = macro argument. One name throughout; no ID mapping table.

## Spec format

A thin header over autocast's own instruction schema, so the engine stays swappable.

```yaml
# casts/run-basic.yml
fixture: ab-problem
title: Running solutions
width: 100
height: 30
setup:                          # hidden; warms caches, never shown
  - rbx build
instructions:                   # passed through to autocast
  - rbx run
  - !wait 3s
expect_contains:                # anti-rot assertion
  - "Accepted"
```

## The wrapper

`scripts/record.py` does what autocast will not:

1. **Isolate.** Copy `casts/fixtures/<fixture>` to a tmpdir and record there. Source
   fixtures are never mutated — the same discipline as the e2e runner.
2. **Normalize the environment.** Fixed `COLUMNS`/`LINES` so Rich wraps identically on
   every run, `TERM=xterm-256color`, `LC_ALL=C.UTF-8`, `TZ=UTC`, `HOME` redirected into
   the tmpdir so the real `~/.cache/rbx` never leaks, and ambient `RBX_*` stripped.
3. **Record.** Emit the autocast input and run `autocast … --overwrite` into
   `docs/assets/casts/<name>.cast`.
4. **Scrub.** Rewrite tmpdir paths (`/private/var/folders/…`) to a stable
   `~/problems/<name>` and clean the header. Skipping this leaks machine-specific paths
   into published docs.

## Embedding

Vendor the standalone `asciinema-player` bundle (MIT, actively maintained) into
`docs/assets/`, declared through `extra_css` / `extra_javascript`.

The `main.py` macro keeps its signature — `{{ asciinema("run-basic", speed=1.5) }}` — but
emits a player instance pointed at the local `.cast`, mapping `idleness` and `speed` onto
player options.

**The macro keeps a fallback:** an argument shaped like a 25-character asciinema.org ID
still renders the old script embed. Migration then proceeds page by page instead of as
one 21-file commit. The theme does not enable `navigation.instant`, so inline player
initialisation is safe.

## Freshness

Two guards, neither adding CI surface:

- **`expect_contains`** — after recording, the wrapper asserts the declared strings
  appear in the cast text. If `rbx run` changes its verdict table, recording fails loudly
  instead of silently publishing a cast of an error message.
- **`mise run record-check`** — a local-only task asserting every `{{ asciinema(...) }}`
  reference resolves to an existing cast and every cast is referenced by at least one
  page. Catches the `REPLACE_ME_CAST_ID` / `TODO(record)` rot and orphans left behind by
  deleted pages. Explicitly **not** wired into any workflow and **not** a pytest test.

## Commands

```
mise run record            # all recordings
mise run record run-basic  # one recording
mise run record-check      # local link lint
```

## Errors and testing

A missing `autocast` binary fails preflight with install instructions. A hung command
hits autocast's `--timeout`, and the wrapper reports which instruction stalled.

Tests: pure-function unit tests for spec parsing, environment normalization, and path
scrubbing; one `slow`-marked end-to-end record of the smallest fixture that skips when
autocast is absent.

## Migration

1. Build the harness, vendor the player, add the macro fallback.
2. Port two casts to validate — one plain (`rbx run`) and one TUI (`rbx ui`), the latter
   exercising autocast's `Interactive` mode, the riskiest capability.
3. Record the three rotting placeholders. Immediate payoff.
4. Port the remaining 18 opportunistically; drop the fallback when the last ID is gone.

## Open risks

Both are validated in migration step 2 rather than designed around:

- Whether autocast's bash prompt detection is robust against `rbx`'s Rich progress
  output.
- Whether `rbx ui`'s Textual TUI records cleanly through autocast's `Interactive` mode.

If either fails, that is the trigger to fall back to owning the recorder. The spec files
survive unchanged.
