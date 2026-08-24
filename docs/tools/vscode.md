# rbx for VS Code

The rbx extension puts everything {{rbx}} writes to disk inside your editor: the
verdicts of the last run, the diff of what a solution printed against what it
should have printed, the tests your generators produced, and what
`problem.rbx.yml` declares about each solution.

The motivation is simple: `rbx run` prints a table, and a table is where the
answer *stops*. The moment a solution fails you want the input that broke it,
the checker's own message, and the source file open side by side -- three
things that live in three different places under `.rbx/`, and that you were
finding by hand.

!!! note "It never runs rbx for you"
    Execution stays in the terminal. You type `rbx run`; the extension watches
    the package and renders whatever lands there. Every {{rbx}} invocation has
    side effects on the package cache and could race a run already in flight,
    so the extension is a reader and nothing else.

## Installing

From the editor's integrated terminal:

```bash
rbx vscode install
```

That sideloads the `.vsix` bundled with your {{rbx}}, so the extension always
matches the CLI that produced the runs it reads. **Reload the window
afterwards** -- a freshly installed extension does not activate in windows that
are already open.

Cursor, Windsurf and VSCodium work the same way: they all report themselves as
VS Code, and {{rbx}} tells them apart by which app the terminal belongs to. Pass
`--editor` if it guesses wrong, which is also how you install from a terminal
outside the editor.

```bash
rbx vscode install --editor cursor
```

Over SSH or in a devcontainer this installs into the *remote* extension host,
which is the right place -- that is where your package lives.

The extension is not published on any marketplace. When your {{rbx}} ships a
newer extension than the one you have installed, `rbx run` says so once and
points you back at this command.

## The run view

The **rbx** icon in the activity bar opens the run view: solution, group,
testcase, filled in live as `rbx run` works through them.

![The run view](vscode/run-view.png)

Three different things can be true of a solution at once, and the view keeps
them in three separate places so they cannot be mistaken for one another:

| Channel | Says |
|---|---|
| the **name**, coloured | what `problem.rbx.yml` *declared* -- exactly as `rbx run` colours the same name |
| the **chip** on the right | what the run actually *produced*, one icon per verdict |
| the **gutter** on the left | whether those two agree: a tick when the declaration was met, a red triangle when it was missed, a yellow one when {{rbx}} warned about a run that still passed |

So `sols/wa.cpp` answering wrongly is a calm row, and the main solution breaking
is not -- a miss is the only thing in the view with a background colour.

Every solution and every group carries its own summary: the verdict underneath
it, the points it earned, and the **max** time and memory across its testcases.
A solution still running shows how far it has got (`12/40`) instead of a
verdict.

In a contest, a dropdown in the header picks which problem you are looking at,
naming problems by their contest letter and colour. It follows the problem that
is *running*, so `rbx contest each run` walks the view along with it. The
dropdown is hidden entirely when the workspace holds a single package.

## Opening a testcase

<kbd>Enter</kbd> on a testcase -- or a click on it -- opens **two editor
panes**: the input, and the output diffed against the expected answer.

![A testcase, input above and diff below](vscode/testcase-panes.png)

The second pane is a channel, and it switches: <kbd>alt+1</kbd> for the output
diff, <kbd>alt+2</kbd> for stderr, <kbd>alt+3</kbd> for the run log, mirroring
`rbx ui`'s `1`/`2`/`3`. The choice is sticky, so arrowing down a group keeps
reading the same channel.

Both are real editors rather than a webview, because testcases are large: you
get highlighting, find, go-to-line, and VS Code's own diff -- including its
`diffEditor.*` settings and its **More Actions** menu for switching between
side-by-side and inline.

The panes are laid out once, the first time a testcase is opened, and then left
alone; afterwards the extension finds its own panes and reuses whichever groups
they are sitting in. Drag them where you want them and they stay there.

Under the tree, a card describes the selected testcase and carries the two facts
its row cannot fit:

- **the checker's own message**, wrapped and whole -- the answer to *why* a
  solution answered wrongly;
- **where the test came from** -- the generator call, the generator script, or
  the testcase it was copied from, with the ones that point at a real file
  opening it.

The card fills on *selection*, so a whole failing group can be scanned for
checker messages without opening a single editor.

## Compilation findings

A solution that did not compile never ran, and {{rbx}} leaves it out of the run
entirely. The extension gives it a place to be seen: a **Compilation Findings**
panel with one row per solution the compile phase had something to say about,
badged red the moment one failed to compile and yellow while everything merely
warned.

![Compilation findings](vscode/compilation-findings.png)

A row with warnings expands into one line per warning -- its line and its flag,
`22 · -Wshadow` -- and clicking one goes to that line in the source. A row that
failed to compile opens the compiler output verbatim.

The same findings are published as **diagnostics**, so they reach the Problems
panel, the editor's own gutter and <kbd>F8</kbd> without the sidebar being open
at all.

## Browsing the testset

The run view is about what a solution *did*. The **Tests** view, beside it, is
about what `rbx build` *made*: the groups, their testcases, and where each one
came from.

![The Tests view](vscode/tests-view.png)

Everything that wants more width than a sidebar has gets a panel of its own,
which follows whatever the sidebar has selected:

- a **visualization gallery**, when your package declares a visualizer;
- **constraint coverage** -- which of your validator's bounds the testset
  actually hit, and which no test ever touched;
- **testset stats** -- sizes and counts, group by group.

![Constraint coverage](vscode/testset-coverage.png)

## While you are editing

A declaration is a promise a solution makes before any run exists, and the
extension shows it away from the views too. Every file `problem.rbx.yml` names
is **badged in the Explorer** -- solutions with the outcome they were declared
to have, in the glyph and colour `rbx run` already prints, everything else with
two neutral letters naming its role. And with a solution open, the same
declaration is spelled out in words on a **CodeLens** above line one and in the
**language status area**, which survives scrolling and can be pinned: the pooled
`outcome`, then every `outcomePerGroup` override, then the expected `score`.

## Settings

Every surface above can be turned off on its own.

| Setting | Default | Does |
|---|---|---|
| `rbx.decorateExplorer` | `true` | Badge declared files in the Explorer and on editor tabs |
| `rbx.solutionCodeLens` | `true` | Show a solution's declaration above its first line |
| `rbx.solutionStatus` | `true` | Show it in the language status area |
| `rbx.compilationDiagnostics` | `true` | Report compiler warnings and failures in the Problems panel |
| `rbx.solutionLabel` | `trimmed` | How much of a solution's path the run view shows: `full`, `trimmed` or `basename` |
| `rbx.testcaseLayout` | `below` | Where the second testcase pane is *first* placed: `below` or `beside` |

The badge colours are contributed as `rbx.expected*` and default to the theme's
own chart colours, so a colour theme can restyle them and the run view and the
Explorer will still agree.

For the keyboard, everything these views do is also a command: `rbx: Select
Problem`, `rbx: Reveal Problem in Explorer`, `rbx: Show Constraint Coverage` and
the rest, all under the `rbx:` prefix in the command palette.
