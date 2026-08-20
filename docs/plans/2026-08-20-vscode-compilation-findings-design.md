# VS Code run view: a Compilation Findings panel

Closes the gap #677 names: the extension reads `skeleton.yml`, the `.eval`
artifacts and `report.yml`, and every one of those describes a *run*. The
compile phase, which happens before any of it, leaves nothing on disk at all.

## The problem: the compile phase is invisible, and worse than invisible

Two facts `rbx run` knows and only ever prints:

- **Warnings.** `WarningStack` (`rbx/box/sanitizers/warning_stack.py`) collects
  every first-party file that compiled with warnings, and
  `CppCompilationWarningSummarizer` already parses each one into
  `_ParsedWarning(file, line, flag, msg)`. `print_warning_stack_report()`
  prints them under a `Warning stack` rule and they are gone.
- **Errors.** A solution that fails to compile raises `FailedToCompileSolutionIssue`,
  which lands in the console `Issues` tree.

The error case is sharper than #677 assumed. `_get_compiled_solutions_for_skeleton`
(`rbx/box/solutions.py`) filters a solution that failed to compile out of
`solutions` entirely — the `# TODO: Handle solutions that failed to compile.`
right above it — and it is absent from `compiled_solutions` too. So the row does
not go stale in the sidebar. **It disappears.** A setter looking at the run view
sees three solutions where the package declares four, with nothing anywhere
saying which one went missing or why.

Warnings are invisible in the plainer sense: nothing on disk mentions them, so
the sidebar is silent while the terminal is not.

## D1. Widen the skeleton; keep the stderr out of it

The skeleton is written at the moment the compile phase ends and knows exactly
who compiled — `compiled_solutions` already maps solution path to digest. It is
also written *before* the run rather than after, which is precisely when this
information exists. A sibling `compilation.yml` was the alternative; it buys
room for the wider `Issues` tree later, at the cost of a second file to write,
watch and parse for facts the skeleton is already the natural home of.

So: one new field, and no stderr in it.

```python
class CompilationWarning(BaseModel):
    file: str
    line: int
    flag: Optional[str]
    msg: str


class SolutionCompilation(BaseModel):
    path: pathlib.Path
    # The declaration, carried here because a solution that failed to compile is
    # absent from `solutions` and the panel still has to hue its label the way
    # the tree hues it.
    outcome: ExpectedOutcome
    status: Literal['WARNINGS', 'FAILED']
    # Relative to runs_dir: `compilation/0.log`.
    log: pathlib.Path
    warnings: List[CompilationWarning] = []
    # "'g++' was not found", from CompilationError.not_found_executable.
    reason: Optional[str] = None
```

`SolutionReportSkeleton` gains `compilation: List[SolutionCompilation] = []`,
holding **only the solutions with something to report**. A clean run adds an
empty list and nothing else, and the extension renders the list as it is handed
it rather than deriving who is interesting.

`solutions` and `compiled_solutions` keep their current meaning — the solutions
that entered the run — so nothing downstream of the skeleton shifts underneath
this. A solution that failed to compile appears in `compilation` and nowhere
else, which is also what makes `compilation` the one place that answers "why is
this solution not in the run".

The compiler output does not go in the YAML: it is unbounded, it is a
setter's whole screen when a template blows up, and the skeleton is parsed in
full by every reader. It is written instead to `.rbx/runs/compilation/<i>.log`,
where `i` indexes the `compilation` list, at the point `_get_report_skeleton`
creates `runs_dir` — after the `rmtree`, so it survives the wipe that marks the
start of a run, and is dropped with the run it belongs to like every other
artifact under `.rbx/runs`.

Both logs are already in memory when the skeleton is built. The warning case is
`WarningStack.warning_logs[path]`, a `List[PreprocessLog]` whose `.log` is the
compiler's combined stdout and stderr. The failure case is
`artifacts.logs.preprocess`, which `steps.compile` populates *before* it raises
— but `compile_item` re-raises without handing it back, so `CompilationError`
has to start carrying it.

## D2. Findings are compile errors and compiler warnings, and nothing else

`WarningStack` also holds linter messages and sanitizer logs, and prints all
three under the same console rule. They stay out. Linter messages are not
compiler output, and sanitizer warnings come from *running* a solution, not from
compiling it — publishing them under a panel called Compilation Findings would
make its name a small lie, and they belong to a run-phase surface of their own.

## D3. The panel lives inside the run webview

A second view in the `rbx` container would get collapse, drag-resize and state
persistence for free. What it cannot get is the badge: a `ViewBadge` is a plain
count on the container icon in the activity bar, not a coloured mark on the
section header, and a section title cannot be hued. Severity-at-a-glance is the
whole point of the badge here — red means a solution did not compile, yellow
means it compiled with something to look at — so the panel is a flex sibling of
`#tree` inside the existing webview, with its own header, chevron and badge.

That also puts it in reach of everything the view already decided: the same
`hue-*` table, the same codicon font, the same `escapeHtml`/`escapeAttr`
discipline, and the same split between a view model that decides and a renderer
that paints.

### Layout

`runView.ts`'s shell gains `<div id="findings">` after `#tree`. `#tree` becomes
`flex: 1; min-height: 0` and the panel `flex: 0 0 auto` with `max-height: 30%`
and its own scroll box; collapsed, it is exactly its header. `min-height: 0` on
the tree is load-bearing — without it a flex child refuses to shrink below its
content and the panel gets pushed off the bottom of the sidebar.

### Presence is the signal

A package whose solutions all compiled cleanly gets **no panel at all**, the way
a package whose declarations all held gets no mismatch strip. A header that is
always there saying "nothing to report" is a line of sidebar spent on the common
case.

### The header

Chevron · `Compilation Findings` · badge. The badge counts **rows** — one per
solution — so it always agrees with what opening the panel shows. It is
`hue-red` when any row is an error and `hue-yellow` when every row is a warning.

### Auto-open

The client keeps a signature of the findings set. When the signature changes —
which is what a new run looks like from inside the webview — and the new set
contains an error, the panel force-opens and the "the user touched this" flag
clears. Warnings-only never opens it; the yellow badge is what draws the eye
down. Afterwards the user's own collapse sticks until the next run changes the
signature again. This is the same distinction `touched` already draws for tree
rows: without it, a re-render cannot tell "never seen" from "deliberately
closed", and every file-watcher tick would reopen a panel the user shut.

### Rows

A row is severity on the left, identity in the middle, severity again on the
right:

```
▾ Compilation Findings ②
▎ sols/wrong.cpp                  CE       ⎘ ⧉
▾▎ sols/main.cpp                  3 warns  ⎘ ⧉
    41 · -Wsign-compare
    88 · -Wunused-variable
```

- A left rule and a faint wash, both in the severity hue. This is a third
  background fill in a stylesheet that keeps them scarce on purpose, and it
  earns its place the same way the mismatch wash does: the panel is meant to be
  scanned, not read.
- The label is hued and bolded by the solution's **declaration**, exactly as the
  tree hues it — so a row here and the same row above are recognisably the same
  solution. Severity is carried by the rule, the wash and the summary; it never
  touches the label. (This is why `SolutionCompilation` carries `outcome`: a
  solution that failed to compile has no entry in `solutions` to read it from.)
- The right-hand summary is `CE` or `3 warns`, hued by severity.
- Two codicon buttons: `go-to-file` opens the solution source, `output` opens
  the compile log.

### The stderr, and the source

The compile log opens as a read-only `rbx:` tab through `artifactFs.ts`, which
already does exactly this for testcase outputs: the URI path is a human-readable
label whose last segment becomes the tab title, the real path travels in the
query, and a `FileSystemProvider` streams it rather than holding it in memory as
a string — which is what makes a very long compile error cheap to open.

Expansion is deliberately thin. A warning row's twisty lists one compact line
per warning — `41 · -Wsign-compare`, the location and the *kind*, with the
message only as the hover title — because the panel is 30% of a sidebar and a
wall of `comparison of integer expressions of different signedness` is what it
must not become. Clicking one of those lines opens the source at that line.
Error rows do not expand; clicking one opens the log.

## D4. What the view model decides

`viewModel.ts` grows a section beside `rows`, and decides everything the
renderer would otherwise have to ask:

```ts
interface FindingWarning { line: number; flag?: string; msg: string }

interface FindingRow {
  id: string;
  label: string;              // the same shortened label the tree uses
  labelTitle?: string;
  labelHue?: Hue;             // the declaration, as above
  labelBold: boolean;
  severity: 'error' | 'warning';
  summary: string;            // 'CE' | '3 warns'
  reason?: string;            // hover title on an error row
  logLabel: string;           // tab title for the rbx: document
  logPath: string;            // absolute, for artifactUri
  sourcePath: string;
  warnings: readonly FindingWarning[];
}

interface Findings {
  rows: readonly FindingRow[];
  badge: number;
  hue: 'red' | 'yellow';
}
```

`RunViewModel` gains `findings?: Findings`, absent when there is nothing to
report. `render.ts` gains `renderFindings(findings, state)` and paints it; it
re-decides none of the above, per the rule that file already states.

Parsing follows wire.ts's tolerance rules: a skeleton written by an rbx that
predates the field yields no `compilation` key, which reads as an empty list,
which is a view model with no `findings`, which is no panel. An older extension
against a newer rbx ignores the field. Neither combination errors.

## D5. Two commands, one context section

- `rbx.openCompileLog` — `artifactUri(logPath, logLabel)`, then `vscode.open`.
- `rbx.openSolutionSource` — opens the `.cpp`, optionally at a line, which is
  what a warning line uses.

Both take a finding id and resolve it through the same id map `runView.ts`
already keeps, so the client keeps sending ids and nothing about a finding has
to survive `postMessage` beyond one. Rows carry `webviewSection: 'rbx.finding'`
for the context menu.

## Testing

Python:

- `SolutionCompilation` records are built for both statuses, with the log
  written and the relative path pointing at it.
- A run where one solution fails to compile writes a skeleton whose `solutions`
  is unchanged and whose `compilation` names the missing one, with its reason.
- An old skeleton (no `compilation` key) still parses.

TypeScript:

- `viewModel.test.ts`: mapping, badge count, badge hue (red wins over yellow),
  absent `findings` on a clean run.
- `render.test.ts`: the panel markup, collapsed vs open, the expansion lines,
  escaping of a solution path with a quote in it, and nothing rendered at all
  when there are no findings.
- `model.test.ts`: a skeleton with no `compilation`, and one with a malformed
  entry, both degrade rather than throw.

## Risks

1. **Compile caching.** `steps_with_caching.compile` can skip the compiler
   entirely on a second `rbx run`. If `artifacts.logs.preprocess` is not
   restored from the cache on a hit, the warnings are simply not known the
   second time and the panel would appear on one run and vanish on the next —
   the worst possible behaviour for a surface whose whole job is to be trusted
   when it is silent. This is worth settling before anything else is built; if
   the logs are not cached, the findings have to be cached alongside the digest.
2. **The single-solution path.** `compile_solutions` raises rather than skipping
   when there is one solution (`should_fail`), so `rbx run one.cpp` aborts
   before a skeleton exists. The panel cannot help there and the console keeps
   that case, which is fine — but it means the panel is not a complete answer to
   "why did nothing appear".

## Out of scope

- Linter and sanitizer warnings (D2), and the wider console-only `Issues` tree
  (`TimingIssue`, `TooMuchStderrIssue`, `FailedSolutionIssue`) that #677's last
  section suggests may deserve one artifact covering all of it.
- Warnings from generators, validators, checkers and interactors. `WarningStack`
  already holds them and they are a real gap — a run that aborts on a broken
  generator still shows an empty view — but they are not solutions, they have no
  outcome to be hued by, and they want their own section rather than a row in
  this one.
- The filter box at the top of the view does not filter the panel.
