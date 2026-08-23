# Live run progress: a solution-scoped Live and a runner status board

Follow-up to #692 (`feat(runners): measure time limits on the MOJ judge park`).

## The problem

`rbx time --runner moj` can sit for minutes with nothing on screen moving. The
run is not stuck -- it is waiting on a judge park -- but nothing says so, and
nothing says which of the things it could be waiting on it is actually waiting
on.

Three separate causes, all in the reporting layer:

1. **The reporter's live region is scoped to a group.** `LiveRunReporter` starts
   a `rich.live.Live` in `render_group` and stops it in `render_group_end`. The
   solution header is a plain `console.print` (`_print_solution_header`), so by
   the time anything interesting is known about the solution, its header is
   already frozen in scrollback and cannot be written to.

2. **The runner knows things it has no way to say.** `MojRunner.run_solution`
   dispatches *every* solution onto a background `asyncio.Task` immediately, so
   while the report blocks on solution #1, solutions #2..#N are genuinely in
   flight on the judge. `TestrunStatus` already carries `status`, `correct`,
   `total_tests`, `duration_s`; the runner already tracks the testrun id, the
   MOJ problem id and whether a result came from cache. None of it reaches the
   screen until after the fact.

3. **The one progress line that exists is invisible.** `_evaluation_from_job`
   calls `ctx.progress.update('Waiting for MOJ to judge ...')`, but every caller
   exits its `with utils.StatusProgress(...)` block *before* `print_run_report`
   (`cli.py`, `timing.py`). The `Status` is stopped, so that update renders
   nowhere. This has never been visible to a setter.

Nothing here is MOJ-specific in its shape. A local run has the same hole,
smaller: there is no elapsed time anywhere, so a slow solution and a hung one
look identical.

## What this is not

Not a progress *bar*. The number of testcases is known, but the thing a setter
is waiting on during a remote run is not testcase count -- it is a queue
position on someone else's machine. A bar would imply a rate that does not
exist.

Not a whole-report Live showing every solution at once. That is closer to what
MOJ actually does, and it was considered and dropped: it rewrites the reporter's
rendering model and changes the `--share` recorded output far more than the
value justifies. The report is read top-to-bottom, one solution at a time; the
live region should follow the reader.

## Design

### 1. The solution block Live

`LiveRunReporter` moves Live ownership from the group up to the solution.
`render_solution` starts it, `render_solution_end` stops it. The renderable is a
`rich.console.Group`:

```
sols/slow.cpp (runs/2)  · 12.4s · moj rbxt-a1b2 · testrun 4821 · running 34/72
  samples (3)  (120ms, 4MB)
  main (12)    4/WA (890ms, 12MB)
  big (7)      3/.. 5/..  (1.1s, 12MB)      <- current group
```

`_update_live` keeps building exactly the group renderable it builds today; it
appends into a block instead of *being* the whole renderable. The group-line
logic -- pre/post-evaluated counters, skipping clean ACs, capped times, the
partial group score -- is untouched.

Four invariants:

- **Wall-clock chips render only when `console.is_terminal`.** A shared report
  (`sharing.recording_console()`), an e2e golden and an asciinema cast are all
  non-terminal consoles, and an elapsed time in any of them is a diff on every
  run. Runner chips are not wall-clock and do render there: a setter reading a
  shared report wants the testrun id.

- **Auto-refresh only on a terminal.** Today the Live is `auto_refresh=False`
  and refreshes on evaluation events. A ticking clock needs
  `refresh_per_second=4`; a non-terminal must not spawn a refresh thread for
  frames it will never emit. (`rich.live.Live.refresh` is a no-op on a
  non-terminal until `stop`, so the *output* is one finalized frame either way
  -- this is about not running the thread.)

- **Height guard.** If `2 + len(groups) > console.height`, fall back to today's
  per-group Live. A package with more groups than the terminal has rows would
  otherwise flicker or truncate. One branch, and the degraded mode is exactly
  the behaviour that ships today.

- **The non-terminal newline moves.** `render_group_end` prints an explicit
  newline for non-terminals because a per-group Live finalizes without one. With
  one Live per solution the whole block finalizes at once, so that newline
  belongs to `render_solution_end`.

`SingleSolutionRunReporter` keeps its current structure -- it prints a line per
testcase, and a Live around an unbounded number of lines is the thing the height
guard exists to avoid -- but its header gets the elapsed chip.

### 2. The runner status board

```python
# rbx/box/runners/base.py
@dataclasses.dataclass(frozen=True)
class RunnerChip:
    text: str
    style: str = 'bright_black'

class RunProgress:
    """What a backend wants said about a solution while the report waits on it."""
    def set(self, solution_path: str, chips: List[RunnerChip]) -> None: ...
    def get(self, solution_path: str) -> List[RunnerChip]: ...
```

Created by `run_solutions`, placed on `RunContext` (the runner writes) and on
`RunSolutionResult` (the reporter reads, on every render). Both live on the same
event loop, so a write is a plain dict assignment: no lock, no callback, no
ordering hazard, and a backend that never writes costs nothing.

**Chips, not a typed `RunnerStatus`.** A typed status would put MOJ's state
vocabulary -- `queued`, `running`, `done`, and whatever the next judge calls its
states -- into the reporter, and the next backend's vocabulary after that. The
backend owns its own words; the reporter owns the layout. The reporter renders
what it is handed and knows nothing about judges.

**Pull, not push.** The reporter reads the board when it renders, rather than
the runner calling into the reporter. A push channel would need the reporter to
exist before the run starts, and it does not: `run_solutions` returns first and
the reporter is built from its result.

### 3. What MOJ writes

| Where | Chips |
|---|---|
| `run_solution`, at dispatch | `moj rbxt-a1b2`, `waiting for a slot` |
| `_submit_and_poll`, cache hit | `cached`, `testrun 4821` |
| `_submit_and_poll`, after submit | `testrun 4821`, `submitted` |
| `_wait_for_testrun`, each poll | `testrun 4821`, `running`, `34/72` |
| `_wait_for_testrun`, on `done` | `done in 34.1s` |
| failure | nothing -- the exception speaks |

`_wait_for_testrun` is documented today as "Bounded, and silent", justified by:
"a poll writing a status line from here makes the display flip between solutions
and the reporter's own message every few seconds". The board dissolves that
argument rather than working around it -- a poll writes into *its own solution's*
slot, and the reporter renders only the slot it is currently blocked on -- so
that docstring is rewritten, not merely bypassed.

`TestrunStatus` gains `host`, which the 2026-08-21 probe observed as
`judge-sp1`. It answers "which judge is this on", which matters when a park is
heterogeneous and a timing is being read off one machine.

### 4. Removing the dead path

`_evaluation_from_job`'s `ctx.progress.update(...)` becomes a board write. The
invisible mechanism is deleted rather than left beside the working one.

## Testing

- A fake runner writing canned chips, plus a capture console, asserting the
  header line carries them.
- A short console asserting the height guard falls back to per-group Live.
- A non-terminal console asserting **no** elapsed chip and exactly one finalized
  frame per solution.
- `tests/rbx/box/runners/moj/test_run_solution.py` gains board assertions at
  each write point.

Expected churn: `tests/rbx/box/test_sharing.py`, `tests/rbx/box/test_run_cli.py`,
`tests/rbx/box/solutions_test.py`, and a `mise run record` pass over the `run-*`
and `time-estimate` casts.

## Shipping

Two PRs, because the first is worth having on its own:

1. **The solution block Live**, plus the elapsed clock and the height guard.
   Backend-agnostic; a purely local run gets an elapsed time out of it. The code
   is small; the risk is the recorded-output goldens.
2. **The status board and the MOJ chips**, plus `host` and the removal of the
   dead progress path. Almost entirely additive, and it lands on rendering that
   PR 1 has already settled.
