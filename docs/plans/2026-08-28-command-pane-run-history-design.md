# Command pane run history

`rbx contest each` and `rbx contest on` open a TUI (`rbxCommandApp`) with one pane per
problem. When the app exits, everything those commands printed is gone. This design keeps
it: every finished command's final screen is written to disk, and running `each`/`on` with
no command re-opens a past session with every pane redrawn.

## Requirements

- Output survives the process. Reopening works in a new shell, days later.
- Only the **final** state of each command is kept -- no intermediate frames.
- The restored panes must behave like live ones: `ctrl+v` visual select, `ctrl+y` copy,
  mouse selection, the sub-command dropdown, tab switching.
- `each`/`on` with **no forwarded command** open a picker of the 5 most recent runs, newest
  first, showing each run's start time.
- A reopened session stays live: new commands typed into it run and are themselves saved
  into that same run.
- State is flushed on **every** command completion, so history is useful mid-session and
  survives a crash.

## What makes this cheap

Three facts about the vendored `toad` terminal decide the design.

`Terminal.write(text)` (`rbx/box/ui/_vendor/toad/widgets/terminal.py:244`) feeds text into
the ANSI stream parser. It is independent of the pty, so a pane can be filled without
spawning a process: restoring is `await pane.write(saved_ansi)`.

Selection is defined over the parser's output. `terminal_select.py` navigates
`Buffer.lines` and highlights through `Terminal._render_line`. A buffer rebuilt by the real
parser is indistinguishable from one built by a live command, so **copy and visual mode
work with no new code** -- provided we restore through `write()` rather than reconstructing
a `Buffer` ourselves.

Each `Buffer.lines[i].content` is a `rich.text.Text` (`_vendor/toad/ansi/_ansi.py:847`), and
rendering styled `Text` back to SGR-ANSI is a stock rich operation. So the dump direction is
as short as the load direction.

## Capture format

Three candidates were considered.

**A. ANSI dump of the final scrollback buffer.** On command completion, render every
`Buffer.lines` entry to SGR-ANSI and write one file per sub-command.

**B. Tee the raw pty byte stream.** Byte-exact, but stores every intermediate frame -- a
chatty `rbx run` with live tables would write megabytes to reproduce a screen we could
describe in kilobytes.

**C. Serialize `TerminalState` / `Buffer`.** Needs a bespoke (de)serializer for vendored
code we do not own, and would have to be kept in step with upstream.

**A is chosen.** It is symmetric with `Terminal.write()`, so one format serves both
directions; it stores only what the requirements ask for; the files are `cat`-able outside
the TUI; and it inherits selection support by construction.

### Dumping

```python
def dump_buffer_to_ansi(buffer: ansi.Buffer) -> str
```

A `rich.console.Console(file=StringIO(), force_terminal=True, color_system='truecolor',
width=max(buffer.max_line_width, 1))` prints each line with `no_wrap=True`, `crop=False`,
`markup=False`, `highlight=False`. Trailing blank lines are trimmed. Rich emits an SGR reset
at the end of each styled span, so a file truncated by a crash cannot bleed styles into
whatever is read after it.

Only the scrollback buffer is dumped. A command that finished on the alternate screen (a
full-screen child TUI) has nothing meaningful to persist there.

### Loading and width

Restoring writes the file into a mounted pane. Lines are stored **unfolded**, so they are
re-folded at whatever width the pane has when it is shown -- a table drawn at 200 columns
wraps if reopened in an 80-column window. This is inherent to storing logical lines and is
accepted.

It also makes ordering a non-issue: `Terminal.update_size()` reflows the buffer on resize,
so writing into a pane that is still at its fallback width and letting the existing
`sync_hidden_pane_sizes` machinery resize it afterwards produces the same result as writing
after the resize.

## Storage

Contest-rooted, beside the existing problem-level cache:

```
<contest root>/.box/runs/
  20260828-141233-a3f1/
    run.yml
    0/0.ansi        # tab 0 (problem A), sub-command 0
    0/1.ansi
    1/0.ansi
```

The run id is `<timestamp>-<random suffix>`: it sorts chronologically by name, and two
concurrent `each` invocations cannot collide.

There is no contest-level cache helper today (`package.get_problem_cache_dir` is
problem-scoped), so this adds `get_contest_cache_dir()` alongside it.

### The `RunStore` seam

Access goes through one interface:

```python
class RunStore(Protocol):
    def list_runs(self) -> List[RunManifest]: ...
    def create_run(self, manifest: RunManifest) -> RunHandle: ...
    def open_run(self, run_id: str) -> RunHandle: ...
    def prune(self, keep: int) -> None: ...
```

`ContestRunStore` is the only implementation shipped. A future machine-global store under
`get_app_path()` -- keeping the last few runs regardless of which contest they came from, as
redundancy against a wiped `.box` -- is then a second implementation plus a merge in the
picker, not a refactor. Nothing outside the store module knows where runs live.

A consequence worth stating: history under `.box/` is destroyed by a cache wipe. That is
accepted for now, and is precisely what the global fallback would later mitigate.

### Manifest

`run.yml` is a Pydantic model written through the project's existing YAML helpers:

- `run_id`, `started_at`, `updated_at`, contest id (the `-C` selection, if any)
- per tab: display name, the `ProblemLabelMode` label map, `cwd`, `prefix`
- per sub-command: name, shell command, status, exit code, `chained`

The picker **displays** `started_at`, as asked, but **sorts** by `updated_at`, so a run you
reopened and added commands to does not sink to the bottom of the list.

## Write points

- **Run creation.** `run.yml` is written when the app starts, before anything executes.
- **Every `CommandPane.CommandComplete`.** The app already handles that message to drive
  `SubCommand.status`; the handler additionally dumps that pane and rewrites `run.yml`. This
  is the incremental guarantee: history is complete up to the last finished command at all
  times, whatever happens next.
- **App unmount.** Every pane holding undumped content is written, so quitting mid-run keeps
  what was on screen.

## Reopening

`_build_command_argvs_or_die` currently rejects an empty command with `EmptyCommandError`.
That is the hook: an empty command means "show me history" rather than an error.

`rbx contest on`'s `problems` argument becomes **optional**. Bare `rbx contest on` behaves
like bare `rbx contest each` and lists every run; `rbx contest on A` with no command lists
only runs that touched problem `A`.

The picker is a small standalone app that returns a run id, following the `rbxReviewApp`
pattern (run the app, read a result attribute synchronously). Each row shows the start
timestamp, the command chain, the problems involved, and the aggregate status icon --
`_STATUS_MARKUP` already exists for that. With no runs recorded it prints a plain message and
exits non-zero.

Selecting a run starts an ordinary `rbxCommandApp` whose tabs and sub-commands come from the
manifest and whose panes load their `.ansi` file instead of executing. There is no read-only
mode: the shell input works, `cwd`/`prefix` come from the manifest, and commands typed into a
reopened session append to that same run directory under the same rules as a fresh one.

A sub-command is never reloaded as `PENDING` or `RUNNING`: nothing is executing when a run
is opened, and leaving a pending command that will never start would be a lie. `PENDING`
loads as `SKIPPED` (it never began) and `RUNNING` loads as a new `INTERRUPTED` status (it
began, its partial output was dumped on unmount, and its exit code is unknown). Both are
terminal, so `TabState.is_idle` and `aggregate_status` stay correct -- and the two are kept
distinct because resuming treats them differently.

## Resuming

Re-running a command needs nothing the manifest does not already hold. Enqueueing is:

```python
sub.status = CommandStatus.PENDING
task = self._task_queue.enqueue(sub.shell_command, terminal_id=tab_index)
sub.task_id = task.task_id
```

`TaskReady` then drives `pane.execute()` exactly as for a first run. Chain semantics come
along for free: `chained` is persisted, so if a resumed command fails, `_skip_rest_of_chain`
aborts the rest of that tab's chain just as it did originally.

Two verbs:

- **Retry** re-runs a single sub-command, the one on screen.
- **Resume** re-queues every sub-command **not in `SUCCESS`** -- `FAILED`, `SKIPPED` and
  `INTERRUPTED` alike -- in their original order, across every tab. This is the
  "`each build` over twelve problems, three failed, fix them, carry on" case, and it is why
  resume is run-wide rather than per-tab. Successful work is never repeated.

Resume deliberately includes `FAILED`: you resume *because* you fixed what failed, so
starting after the failure point would skip the command you actually wanted re-run.

`execute()` appends to the terminal state rather than clearing it, so re-running a
sub-command that already has output would concatenate two attempts in one pane. A retried
sub-command therefore gets a fresh pane mounted under the same id -- the same remove/mount
`_queue_command_in_tab` already performs -- and its `.ansi` file is overwritten when the new
attempt completes. Only the latest attempt is kept.

None of this is specific to reopened runs. A live session where a chain aborted on one
problem resumes by the same path, without quitting first.

## Testing

`tests/rbx/box/ui/` already drives panes headlessly (`test_command_app.py`,
`test_command_pane_select.py`), so the same fixtures apply.

- **Round trip.** Run a command printing styled output, dump the pane, load it into a fresh
  pane, assert the plain text and the styles match the original.
- **Selection after restore.** Enter visual mode on a restored pane and assert
  `get_selected_text()` returns what the command wrote -- the requirement that motivated
  format A.
- **Wrapped lines.** A line longer than the pane restores as one logical line, and re-folds
  when the pane is resized.
- **Incremental flush.** After one command of a chain completes, the store already holds that
  pane and a manifest naming its status.
- **Manifest and pruning.** Round-trip the model; assert only the newest `keep` runs survive.
- **Routing.** `each` with no args and `on` with a selector but no command open the picker;
  `on A` filters to runs touching `A`.
- **Continuation.** A command queued into a reopened run lands in that run's directory and is
  present when it is reopened again.
- **Load states.** A run persisted mid-chain reloads with `RUNNING` as `INTERRUPTED` and
  `PENDING` as `SKIPPED`, and the tab reports itself idle.
- **Resume.** Over a run with a mix of statuses, only the non-`SUCCESS` sub-commands are
  enqueued, in order; a resumed command that fails again skips the rest of its chain.
- **Retry hygiene.** Re-running a sub-command that already has output leaves the pane
  holding only the new attempt, and its stored `.ansi` matches.
