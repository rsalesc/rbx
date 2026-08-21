# VS Code run view: what a testcase shows

Today a testcase is a row and a tab. This gives it the two things `rbx ui` has
and the extension does not: **more than one artifact on screen at once**, and
**the facts that are not in any artifact** — why the checker rejected it, and
where the test came from.

## The problem: the row is the whole story, and the tab is one file

Selecting a testcase in the run view runs `rbx.diffOutput`, which opens a
`vscode.diff` of output against the expected answer when the testcase failed,
and the input otherwise. One editor tab. Everything else the extension already
knows is reachable only from the row's context menu — `rbx.openInput`,
`rbx.openOutput`, `rbx.openAnswer`, `rbx.openStderr` — one at a time, each
replacing the last.

Two facts are worse off than that: they are parsed, held in memory, and
rendered **nowhere**.

- **The checker message.** `Evaluation.message` (`src/rbx/model.ts`) is read out
  of every `.eval` and used by nothing. It is the answer to "why is this WA",
  and the extension has been throwing it away.
- **Provenance.** `TestcaseEntry` carries `generatorName`, `generatorArgs` and
  `copiedFrom`, parsed and commented "for the build tree (M2) and for tooltips
  today" — there are no tooltips. A setter looking at a failing test cannot see
  which generator call produced it without going back to the terminal.

`rbx ui`'s `RunTestExplorerScreen` shows all of it at once: an **Input** pane, a
switcher beneath it (`1` output / `2` stderr / `3` log, two-sided against the
expected answer), a **run metadata** box (`r`) with the verdict, time, memory and
checker message, and a **testcase metadata** box (`m`) with the group, index,
copied-from and generator call. That is the target, adapted to a host that has
real editors and a narrow sidebar rather than a full-screen grid.

## D1. Native editors for the artifacts, the sidebar for the facts

The obvious alternative is a custom webview in the editor area — one "Testcase"
tab holding every pane, fully under our control, immune to being pulled apart.
It was rejected for one reason that outweighs the rest: **testcases are large**.
A webview would have to ship a virtual scroller before it could display a
multi-megabyte input without locking up, and then reimplement find, go-to-line,
word wrap and syntax highlighting on top of it. A `TextDocument` in a real
editor group gets all of that, plus the diff editor's change navigation, which
is not worth rewriting badly.

Two further properties of native editors turn out to matter:

- **Preview tabs are per-group.** With each pane in its own group, arrowing down
  the testcase list *replaces* the documents in place and accumulates no tabs.
  That is `rbx ui`'s live-follow behaviour, for free, from a mechanism a webview
  does not have.
- **The user can rearrange them.** Which is a requirement, not a bonus — see D3.

What native cannot do is render a fact. An editor shows a file; the checker
message and the generator call are not files, and synthesising a document to
hold them would be a worse version of a panel. So the split follows the actual
seam: **files go in file viewers, facts about the run go in the view that
already knows about runs.**

## D2. The metadata card carries only what nothing else says

A region at the foot of the sidebar, following the **selected** row, on the
Compilation Findings precedent — including its best property: it is **absent
entirely** when there is nothing to say.

```
├─ 1-gen-002 ──────────────┤
│ wrong answer, expected   │
│ 14, found 12             │
│ gen_random 5 3 --seed=7  │
│ [out] [err] [log]        │
└──────────────────────────┘
```

The verdict, the time and the memory are **not** in it. The row already carries
all three, and the card sits a few pixels below the row; repeating them would
put the same fact on screen twice within one glance, and spend the card's space
on the half of the story that was never missing.

- **The checker message**, wrapped and in full. Absent on a hard TLE, where the
  checker never saw the output — that absence is informative and is not papered
  over with a placeholder. `_get_checker_msg_last_line` is what `rbx ui` shows;
  the card shows the whole message, having the room for it.
- **Provenance** — copied-from, the generator call, and the generator script,
  in the order `get_generation_metadata_markup` prints them. Two of the three
  are **clickable**: rbx records a script entry as a real `path:line` and a
  copied-from as a path, so both open where they point. A generator *call* is
  text, because it names a generator declared in `problem.rbx.yml` rather than a
  file, and resolving it would mean threading the manifest into the run view for
  one line — while a button that did nothing would promise a destination the
  view cannot reach.
- **The channel buttons** — `out`, `err`, `log`. See D4.

Because the card fills on **selection** rather than on open, a whole failing
group can be scanned for checker messages without opening a single editor. That
is the cheapest thing in this design and probably the most used.

An inline expansion under the selected row was the alternative. It keeps the
facts beside the test they describe, at the cost of the tree reflowing under the
cursor as you arrow through it, and a long checker message shoving the rest of
the group off screen. A fixed region in a place the eye learns is worth more
than adjacency.

## D3. The layout is seeded, never enforced

`Enter` or a double click on a testcase opens two groups: the **input** in one,
the **channel** in the other, defaulting to `diff(output ↔ answer)`.

The arrangement could go through `vscode.setEditorLayout`, which takes a nested
`EditorGroupLayout` — `{orientation, groups}`, groups nesting for orthogonal
splits, `size` fractions summing to 1 per row. It does not: the built-in
`workbench.action.editorLayoutTwoColumns` and `...TwoRows` produce exactly the
two shapes wanted, say in their names which is which, and are the same commands
the Layout menu runs, while `orientation` has two values that are easy to get
backwards and impossible to unit-test.

The trap either way is that laying out is **global and destructive**: it
rearranges the entire editor area, including the solution source being edited.
Doing it on every `Enter` would undo the user's own arrangement every time they
picked a different testcase.

So it is a **fallback, not a policy**:

1. On open, look for the extension's own tabs in `vscode.window.tabGroups`.
   They are recognisable because every artifact goes through the `rbx:` scheme,
   so a `TabInputText` or `TabInputTextDiff` whose URIs carry that scheme is
   ours, and the group holding it is the group to reuse.
2. **Found** — swap the documents into those groups. No layout call. Wherever
   the panes were dragged, they stay, for that testcase and every one after.
3. **Not found** — first open of the session, or the user closed them — lay out
   the grid once, as a starting suggestion, **and only if the editor area has
   no arrangement of its own yet** (one group or none). Laying out is global:
   offering a two-pane suggestion to an empty editor is helpful, while
   collapsing somebody's three-group workspace to two is the exact thing this
   decision exists to avoid. An editor area that is already arranged is
   *joined* — the input into the active group, the channel beside it — not
   rearranged.

`rbx.testcaseLayout` (`below` | `beside`) seeds step 3 only. `below` stacks them
the way `rbx ui` does; `beside` gives the input its own column. After the first
drag neither value matters again, which is the point.

**`below` is the default, and the diff is the reason.** VS Code ships
`diffEditor.useInlineViewWhenSpaceIsLimited` on, so it silently drops a narrow
diff to an inline view; `beside` hands the channel pane a fraction of an editor
area that has already lost width to the sidebar, and on a laptop that renders
the output against the answer inline with nothing on screen saying why. Stacked,
the diff spans the full width and side-by-side holds at any size. `beside` was
the first choice, on the grounds that testcases are tall rather than wide —
which is true of the *input*, and the input is not the pane that breaks.

The trigger is deliberately **explicit**. Following the highlight, as `rbx ui`
does, would seize the editor area the moment the sidebar was touched. The card
of D2 is what follows the highlight instead, and it covers the scanning case
without opening anything.

## D4. One channel, three ways to switch it

The second group holds a channel, and the channel is what `rbx ui`'s
`ContentSwitcher` holds:

| Channel | Group B shows |
|---|---|
| `out` | `diff(output ↔ answer)` |
| `err` | stderr |
| `log` | the run log |

`out` is the diff rather than the output alone, mirroring `rbx ui`, whose
output box shows the output beside the expected answer in two-sided mode. This
keeps one concept — a channel — rather than a cycle plus two loose buttons, and
gives `alt+1/2/3` an exact correspondence with `rbx ui`'s `1/2/3`.

The cost is that the answer cannot be opened alone. The diff editor's own
inline/side-by-side toggle covers reading it, and `rbx.openAnswer` stays in the
context menu.

### How the diff renders is not ours

Deliberately no `rbx.*` setting for side-by-side versus inline. The diff editor
already carries the whole question — `diffEditor.renderSideBySide` as a setting,
the More Actions menu as a live switch, and `toggle.diff.renderSideBySide` as a
bindable command — and a mirror here could not win anyway: the diff editor reads
`diffEditor.*`, not ours, and `vscode.diff` takes a `TextDocumentShowOptions`
carrying column, preview and focus but nothing about rendering. The only thing
this design owes the subject is a **default layout that does not provoke the
responsive behaviour**, which is D3's `below`.

There is no `in` button: the input lives permanently in group A, and a button
pointing it at group B would put the same file on screen twice.

Switching happens three ways, all through the same commands: `alt+1/2/3` while
the view has focus, the card's buttons, and the command palette.

**The channel is sticky across testcases.** Reading stderr and arrowing down
keeps stderr, exactly as the switcher does.

No button is ever **disabled**. Dimming was the plan, on the grounds that the
button row must not reflow while arrowing through a group — but whether a
testcase *has* stderr is a fact about the disk, and the view reads a run's
metadata rather than statting three artifacts per testcase on every watcher
tick. So nothing is dimmed: a button with nothing behind it says so, in words,
when it is pressed — the same informational message `rbx.openStderr` has always
shown. That keeps the button row the one thing in the card that never moves, and
says more than a dimmed button would.

A hard TLE has no output to diff. `rbx.diffOutput` already falls back to showing
whichever half exists, and that behaviour carries over unchanged.

## What this needs from the code

- `TestcaseRun` (`src/rbx/store.ts`) gains a **`logPath`**. `Ext.Log` already
  exists in `src/rbx/layout.ts` and every other artifact path is already
  resolved there; the log is the one channel with no field behind it.
- `TestcaseEntry` (`src/rbx/model.ts`) gains **`generatorScript`** and
  **`generatorScriptLine`**, parsed from `metadata.generator_script`. It is the
  only provenance the card can open, and nothing was reading it.
- The webview gains the card, its selection plumbing, and the three buttons.
  `Evaluation.message` and `TestcaseEntry.{generatorName,generatorArgs,copiedFrom}`
  are already parsed, so no new reading.
- `rbx.openTestcase` replaces `rbx.diffOutput` as the leaf gesture, with the
  tab-group lookup, the seeded layout, and the sticky channel behind it.
- Settings: `rbx.testcaseLayout` (`beside` | `below`).
- `alt+1/2/3` is handled **inside the webview's own keydown listener** rather
  than contributed as a keybinding: a webview does not reliably forward
  unhandled keys to the workbench, and a shortcut that works only sometimes is
  worse than one that lives where the view can see it. `alt` and not the bare
  digits `rbx ui` uses, because this view has a filter box and a bare `2` has to
  be able to reach it.

## What is out of scope

- **Interactions.** `interactionPath` is parsed and a `.pio` is not a text file:
  `rbx ui` renders it through `InteractionBox`. Nothing native displays it, and
  it is a communication-task feature with its own questions. Its own issue.
- **Comparing two solutions** on one testcase, which `rbx ui` offers with `s`.
  It needs a solution picker and a three-way answer to "what is the channel",
  and the run view has no notion of a second solution today.
- **Visualizers** (`v` / `V` in `rbx ui`), which shell out to an external
  program.

## The README changes

The gesture table in `vscode/README.md` currently says a testcase opens "the
diff against the expected answer if it failed, the input otherwise". A testcase
now opens **two panes**, and that row, plus the paragraph above it about every
row opening "always the same way", needs rewriting.
