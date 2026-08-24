# Profiling docs restructure — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split the 649-line `docs/setters/profiling/index.md` into a six-page Feature Guide
section built on one running example, and add the two cast-pipeline knobs those pages need.

**Architecture:** Three phases, in order, because each depends on the last. **Phase A** adds
`speed`/`x8` fast-forward and per-instruction view cropping to the recorder — pure Python, TDD,
independently shippable. **Phase B** adds the `timing-problem` fixture and the five cast specs
that use Phase A. **Phase C** rewrites the prose into six pages, embeds the casts, repoints the
nine inbound links that the split breaks, and adds the new style-guide rule.

**Tech Stack:** Python 3 + pydantic (`scripts/casts/`), pytest (`tests/casts/`), mkdocs-material
with `pymdownx.snippets` and `mkdocs-macros`, asciicast v2, a vendored asciinema-player.

**Design:** [`2026-08-24-profiling-docs-restructure-design.md`](2026-08-24-profiling-docs-restructure-design.md).
Read it before starting. Read [`docs/plans/docs-writing-style-guide.md`](docs-writing-style-guide.md)
before writing any prose, and `casts/README.md` before touching a cast.

**Commit convention:** this repo enforces Conventional Commits via commitizen. Use the
`/commit` skill, or follow `.claude/skills/commit.md`. Never `git add -A`.

---

## Phase A — cast pipeline

### Task A1: Scoped fast-forward on an instruction

A cast's clock advances by the real time each command took, so a 45-second compute costs 45
seconds of playback. `speed: 8` scales that command's elapsed time by 8 while leaving the
synthesized typing animation alone.

**Files:**
- Modify: `scripts/casts/spec.py` (the `RecordingSpec` model)
- Modify: `scripts/casts/engine.py` (`Engine._drain`, `Engine._instruction`, `Engine._command`)
- Test: `tests/casts/test_engine.py`

**Step 1: Write the failing test**

Append to `tests/casts/test_engine.py`, in the timing section next to
`test_cast_duration_tracks_real_elapsed_time`:

```python
def test_speed_compresses_a_commands_elapsed_time(tmp_path: pathlib.Path):
    # The cast clock advances by real elapsed time, so a slow command costs its
    # full duration in playback. `speed` scales that window down without
    # dropping a single frame.
    slow = _duration(
        _run(_spec(instructions=[Tagged('Command', {'command': 'sleep 1'})]), tmp_path)
    )
    fast = _duration(
        _run(
            _spec(
                instructions=[Tagged('Command', {'command': 'sleep 1', 'speed': 4})]
            ),
            tmp_path,
        )
    )

    assert fast < slow / 2


def test_speed_leaves_the_typing_animation_alone(tmp_path: pathlib.Path):
    # Typing is synthesized at `type_speed`, not measured, so compressing a
    # command must not make its own name scroll past unreadably.
    raw = _run(
        _spec(
            instructions=[Tagged('Command', {'command': 'true', 'speed': 10})],
            type_speed='100ms',
        ),
        tmp_path,
    )

    assert _duration(raw) >= 0.4
```

`_duration` already exists in this file; if it does not, read how
`test_the_hold_extends_the_last_event_not_just_the_clock` reads the final timestamp and reuse it.

**Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/casts/test_engine.py -k speed -v
```

Expected: FAIL — `RecordingSpec`/the engine does not know `speed`.

**Step 3: Implement**

In `scripts/casts/engine.py`, give `Engine` a scale that only `_drain`'s `sync()` consults:

```python
    def _drain(self, session, capture, keys=(), speed: float = 1.0):
        ...
        def sync() -> None:
            nonlocal tick
            moment = time.monotonic()
            # Only measured time is scaled. The typing animation is synthesized
            # at `type_speed` and must keep its authored pace, or a
            # fast-forwarded command becomes unreadable before it even runs.
            self.cast.advance((moment - tick) / speed)
            tick = moment
```

Thread `speed` through `_run` and `_command`, and read it in `_instruction` for both the
`Command` and `Interactive` tags (`float(value.get('speed', 1))`). Reject a non-positive value
with `RecordingError`.

**Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/casts/test_engine.py -v
```

Expected: PASS, and every pre-existing engine test still passes.

**Step 5: Commit**

```bash
git add scripts/casts/engine.py scripts/casts/spec.py tests/casts/test_engine.py
```
Message: `feat(casts): let an instruction fast-forward its own elapsed time`

---

### Task A2: `x<factor>` tokens inside an `!Interactive` keys list

`rbx time` is a single interactive command whose 4-second "read the prompt" dwells are worth
watching and whose 45-second compute is not. Task A1's per-instruction `speed` cannot tell them
apart. An `x8` token in `keys` switches the scale mid-command.

**Files:**
- Modify: `scripts/casts/engine.py` (`Engine._drain`'s key loop)
- Test: `tests/casts/test_engine.py`

**Step 1: Write the failing test**

```python
def test_a_speed_token_scales_only_the_keys_that_follow_it(tmp_path: pathlib.Path):
    # `rbx time` is one interactive command: the dwell that lets a reader take
    # in the prompt and the dwell that waits out the compute must be paced
    # differently, and only a mid-command switch can do that.
    raw = _run(
        _spec(
            instructions=[
                Tagged(
                    'Interactive',
                    {'command': 'cat', 'keys': ['1s', 'x10', '1s', '^D']},
                )
            ]
        ),
        tmp_path,
    )

    # ~1s at 1x plus ~1s at 10x, well clear of the ~2s an unscaled run costs.
    assert _duration(raw) < 1.8
```

**Step 2: Run it to verify it fails**

```bash
uv run pytest tests/casts/test_engine.py -k speed_token -v
```

Expected: FAIL — `x10` is fed to the command as literal keystrokes.

**Step 3: Implement**

In `_drain`, the key loop already tries `parse_duration(key)` and falls back to writing bytes.
Add a third case *before* both, and hold the scale in a local the `sync()` closure reads:

```python
_SPEED_TOKEN = re.compile(r'^x(\d+(?:\.\d+)?)$')
```

A matching token sets the current scale and consumes no time. Document in the docstring that the
scale persists until the next token or the end of the instruction, and that `x1` restores 1×.
An instruction-level `speed:` from Task A1 sets the starting scale.

**Step 4: Run to verify it passes**

```bash
uv run pytest tests/casts/test_engine.py -v
```

**Step 5: Commit** — `feat(casts): scale cast time from inside an interactive keys list`

---

### Task A3: Per-instruction view cropping

The `rbx time` tables are tall; the strategy prompt is not. One `height` for a whole spec forces
the shorter screens to be padded out with dead rows.

**Files:**
- Modify: `scripts/casts/engine.py` (`_Session` sizing, `CastBuilder`)
- Test: `tests/casts/test_engine.py`

**Step 1: Write the failing test**

```python
def test_an_instruction_can_run_in_a_smaller_terminal(tmp_path: pathlib.Path):
    # Each instruction gets its own pty, so a narrower view is a genuinely
    # narrower terminal rather than a crop applied after the fact.
    raw = _run(
        _spec(
            instructions=[Tagged('Command', {'command': 'tput cols', 'width': 40})],
            width=100,
        ),
        tmp_path,
    )

    assert '40' in cast_text(raw)


def test_a_resized_instruction_emits_a_resize_event(tmp_path: pathlib.Path):
    # A cast header carries one size; the player follows `r` events for the
    # rest. Without one the smaller output would be drawn into the full frame.
    raw = _run(
        _spec(
            instructions=[
                Tagged('Command', {'command': 'true', 'width': 40, 'height': 10})
            ],
            width=100,
            height=30,
        ),
        tmp_path,
    )

    events = [json.loads(line) for line in raw.splitlines()[1:] if line.strip()]
    resizes = [event for event in events if event[1] == 'r']

    assert resizes[0][2] == '40x10'
    # ...and it goes back, so the next instruction is not left cropped.
    assert resizes[-1][2] == '100x30'
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/casts/test_engine.py -k terminal -v
uv run pytest tests/casts/test_engine.py -k resize -v
```

**Step 3: Implement**

Add `resize(cols, rows)` to `CastBuilder`, emitting `(clock, 'r', f'{cols}x{rows}')`. In
`_command`, when an instruction carries `width`/`height` that differ from the spec's, emit the
resize before typing the command, pass the size to `_Session`, and emit the restoring resize
after the command finishes. Default each to the spec value.

**Step 4: Run the full cast suite**

```bash
uv run pytest tests/casts/ -v
```

**Step 5: Commit** — `feat(casts): let an instruction record in its own terminal size`

---

### Task A4: Document both knobs

**Files:**
- Modify: `casts/README.md` (the "Instructions" table and a subsection each)

**Step 1: Extend the instruction table**

Add rows for `!Command {command: ..., speed: 8}` and
`!Command {command: ..., width: 80, height: 20}`, and mention the `x8` key token in the
paragraph that already documents `keys` accepting durations.

**Step 2: Add two short subsections** after `### end_pause`, matching that section's register —
say why the knob exists and what it cannot do. For `speed`, state that key dwells are authored
durations so a scaled window has a deterministic length, which is why fast-forwarding also
blunts the "re-record on an idle machine" hazard for those windows. For sizing, state that it is
a real pty size rather than a post-hoc crop, and that the player follows the `r` events.

**Step 3: Verify nothing else claims a cast has a single size**

```bash
grep -n "width\|height" casts/README.md
```

**Step 4: Commit** — `docs(casts): document fast-forward and per-instruction sizing`

---

## Phase B — fixture and recordings

### Task B1: The `timing-problem` fixture

**Files:**
- Create: `casts/fixtures/timing-problem/problem.rbx.yml`, `gens/`, `sols/`, `tests/`

**Step 1: Build it**

Model it on `casts/fixtures/ab-problem`. It needs, per design §5: an accepted C++ solution, an
accepted Python solution, Java reachable in the environment but with **no** solution, a clearly
`tle` solution, and one tuned to sit near the bound so the upper-bound check can be shown
failing. Keep input sizes small enough that a full `rbx time` records in a tolerable time —
recording cost is paid on every re-record.

**Step 2: Verify it builds standalone**

```bash
cd casts/fixtures/timing-problem && uv run rbx build
```

Expected: a clean build.

**Step 3: Verify the timing story actually holds**

```bash
cd casts/fixtures/timing-problem && uv run rbx time --auto
```

Expected: an estimate is produced, and the upper-bound check reports the near-bound solution.
If it does not, retune that solution — the cast in Task B3 depends on this behaviour, and a
fixture that does not reproduce it will waste a recording.

**Step 4: Clean the generated artifacts**

```bash
cd casts/fixtures/timing-problem && rm -rf build .rbx rbx.h && git status --short
```

Expected: only the fixture's source files are listed.

**Step 5: Commit** — `test(casts): add the timing-problem fixture`

---

### Task B2: Rework `time-estimate`

**Files:**
- Modify: `casts/time-estimate.yml`
- Modify: `docs/assets/casts/time-estimate.cast` (regenerated)

**Step 1: Point the spec at the new fixture** and replace the bare `45s` dwell with an `x8`
window around it, per Task A2. Keep the 4-second dwell on the strategy prompt at 1×.

**Step 2: Record and watch it**

```bash
mise run record time-estimate
asciinema play docs/assets/casts/time-estimate.cast
```

Close `mkdocs serve` and anything else expensive first — `casts/README.md` explains why.

**Step 3: Check the duration went down, not up**

```bash
git diff --stat docs/assets/casts/time-estimate.cast
```

**Step 4: Update `expect_contains`** to strings from the new fixture, matching one uninterrupted
run of plain text (Rich splits styled phrases with escape sequences).

**Step 5: Commit** — `docs(casts): re-record time-estimate on the timing fixture`

---

### Task B3: The four new casts

Do these **one at a time**, committing each: a recording that fails is easier to diagnose alone,
and each costs real minutes.

**Files:**
- Create: `casts/time-upper-bound-violation.yml`, `casts/time-language-groups.yml`,
  `casts/time-profiles.yml`, `casts/limits-editor.yml`
- Create: the corresponding `docs/assets/casts/*.cast`

For each: write the spec, `mise run record <name>`, `asciinema play` it and actually watch it,
then commit. Use `x8` for compute windows and per-instruction sizing where a screen is short.
See design §6 for what each must show.

`limits-editor` drives the TUI, so it needs `!Interactive` with keys — model it on
`casts/ui-navigation.yml`.

**Commit each** — e.g. `docs(casts): record the upper-bound violation flow`

---

## Phase C — the pages

### Task C1: The shared MOJ partial

**Files:**
- Create: `docs/_partials/moj-backend.md`
- Modify: `docs/setters/running/remote.md:45-66`
- Modify: `mkdocs.yml` (exclude the partial from the build if it would otherwise be a page)

**Step 1: Extract** the `### What it needs` and `### What MOJ cannot tell you` bodies from
`running/remote.md` into the partial, worded so both commands can include it: name the throwaway
problem generically and let each page name its own `-run` / `-slow` suffix in its own prose.

**Step 2: Include it** from `running/remote.md` with `--8<-- "_partials/moj-backend.md"`.

**Step 3: Verify the page still renders identically**

```bash
uv run mkdocs build 2>&1 | tail -20
```

Expected: no new warnings. Per memory, ~9 unrelated warnings pre-exist; do **not** use
`--strict`.

**Step 4: Commit** — `docs(running): extract the MOJ backend contract into a partial`

---

### Task C2: Verify every claim against the code

Do this **before** writing prose — design §9 lists what to check, and `--share` is already
confirmed missing from the flag table.

**Step 1: Read the source**, not the current page: `rbx/box/cli.py:669` for flags, the live
`LimitsProfile` model for the schema, and the ratio-handling code for the semantics.

**Step 2: Write down every drift you find** in a scratch note. Anything the current page claims
that the code does not do must not survive into the new pages.

**Step 3: If you find an rbx bug** rather than a docs bug, record it and leave the code alone —
design §10 puts behaviour changes out of scope.

No commit; this feeds C3–C8.

---

### Tasks C3–C8: Write the six pages

One task per page, one commit each, in this order — each page assumes the ones before it exist,
and the style guide forbids forward-referencing a mechanism the reader has not met.

| Task | File | Design § |
| --- | --- | --- |
| C3 | `docs/setters/profiling/index.md` (rewrite) | 4.1 |
| C4 | `docs/setters/profiling/profiles.md` | 4.2 |
| C5 | `docs/setters/profiling/estimating.md` | 4.3 |
| C6 | `docs/setters/profiling/computing.md` | 4.4 |
| C7 | `docs/setters/profiling/language-groups.md` | 4.5 |
| C8 | `docs/setters/profiling/remote.md` | 4.6 |

For each page:

**Step 1: Re-read the style guide sections** that govern it — §10 (page architecture), §11
(recordings), §13 (the DO/DON'T checklist), and the new rule from Task C9.

**Step 2: Write it** against the `timing-problem` running example, with each cast immediately
after the snippet that introduces its command.

**Step 3: Check it against the checklist** — sentence-case headings, a lead-in before every
snippet and a plain-language recap after, extras in their own `##` below the happy path, no
victory lap, em dashes rationed.

**Step 4: Build the docs**

```bash
uv run mkdocs build 2>&1 | tail -20
```

**Step 5: Commit** — e.g. `docs(profiling): split limits profiles onto their own page`

Notes that apply across the six:

- `computing.md` inherits the `{{ default_timing_formula() }}` macro from the old page. It must
  render the macro, never restate the formula.
- `estimating.md` documents `--share`, which no page documents today.
- `remote.md` includes `_partials/moj-backend.md` and cross-links `running/remote.md`.
- Decide the deprecated `timing.multipliers.inferenceTimeout` note per design §9 — keep it in
  the guide, or drop it and leave it to `migrating-to-v1.md`. Say which you chose in the commit
  body.

---

### Task C9: The new style-guide rule

**Files:**
- Modify: `docs/plans/docs-writing-style-guide.md`

**Step 1: Add a short section** — "Document the contract, not the implementation" — after §11,
and a matching DO/DON'T pair in §13. Design §8 has the content and the
`default_timing_formula()` precedent. Keep the register of the surrounding sections: a rule, then
a quoted example from a real page.

**Step 2: Commit** — `docs: ration internal detail in the writing-style guide`

---

### Task C10: Repoint the inbound links

The split breaks **nine** references across six files. All of them are anchors into the old
single page.

| File | Line | Points at | Should point at |
| --- | --- | --- | --- |
| `docs/setters/running/remote.md` | 28 | `/setters/profiling/#measuring-on-the-judge-itself` | `/setters/profiling/remote/` |
| `docs/setters/running/remote.md` | 40 | same | same |
| `docs/setters/packaging-walkthrough.md` | 30 | `/setters/profiling` | unchanged (index still exists) |
| `docs/setters/packaging-walkthrough.md` | 77 | `/setters/profiling#time-limit-ratios` | `/setters/profiling/computing/#time-limit-ratios` |
| `docs/setters/packaging-walkthrough.md` | 108 | `/setters/profiling#language-groups` | `/setters/profiling/language-groups/` |
| `docs/setters/packaging-walkthrough.md` | 289 | `/setters/profiling` | unchanged |
| `docs/setters/packaging/boca.md` | 19 | `../profiling/index.md` | `../profiling/profiles.md` |
| `docs/setters/statements/index.md` | 245 | `../profiling/index.md#limits-profiles` | `../profiling/profiles.md` |
| `docs/setters/statements/index.md` | 253 | `../profiling/index.md` | unchanged |
| `docs/setters/reference/environment/index.md` | 232 | `/setters/profiling#time-limit-ratios` | `/setters/profiling/computing/#time-limit-ratios` |

(`docs/setters/reference/cli.md:17` matches the grep but is the unrelated `--profiling` flag.
Leave it.)

**Step 1: Fix each one**, confirming the target anchor exists in the page you point at.

**Step 2: Confirm none are left**

```bash
grep -rn "setters/profiling" docs --include "*.md" | grep -v "^docs/plans/"
```

Expected: no reference to an anchor that no longer exists.

**Step 3: Build and check for broken links**

```bash
uv run mkdocs build 2>&1 | tail -30
```

**Step 4: Commit** — `docs: repoint links at the split profiling pages`

---

### Task C11: Nav, and the tests that name the old page

**Files:**
- Modify: `mkdocs.yml:37-38` (the `Profiling` group)
- Modify: `tests/casts/test_macro.py:35`

**Step 1: Add the five entries** under `Profiling`, matching the shape used by `Running` and
`Grading` — bare `index.md` first, then titled siblings, in the design §3 order.

**Step 2: Fix the test that pins the formula macro to the old page.**
`test_the_profiling_docs_do_not_restate_the_default_formula` reads
`docs/setters/profiling/index.md`; the macro now lives in `computing.md`. Point it there and
keep its comment accurate.

**Step 3: Run the suite**

```bash
uv run pytest tests/casts/ -v
```

Expected: PASS.

**Step 4: Check every cast is referenced and every reference resolves**

```bash
mise run record-check
```

Expected: no missing casts, no orphans, no leftover `TODO(record)` for the five casts.

**Step 5: Commit** — `docs(profiling): put the split section in the nav`

---

### Task C12: Read the whole section end to end

**Step 1: Serve the docs**

```bash
uv run mkdocs serve
```

**Step 2: Read all six pages in nav order** as a setter who has never profiled anything. Check
the three things that motivated the split: the running example holds across pages, no page
forward-references a mechanism the reader has not met, and every optional capability has its own
`##` below the happy path.

**Step 3: Watch every cast in place** at its embedded speed. A cast that is unreadable at the
embedded rate needs its spec adjusted, not its embed.

**Step 4: Run the full check**

```bash
uv run pytest tests/casts/ -v
uv run mkdocs build 2>&1 | tail -20
uv run ruff check . && uv run ruff format --check .
```

**Step 5: Commit** any fixes, then open the PR.

---

## Out of scope

Per design §10: the auto-generated Reference schema pages, any change to `rbx` behaviour, and
the narrative Walkthrough track.
