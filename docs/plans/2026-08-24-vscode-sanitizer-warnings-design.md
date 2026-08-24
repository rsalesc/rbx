# Sanitizer warnings in the VS Code run view

`rbx run` marks a solution with `*` and prints

```
WARNING The solution had sanitizer errors or warnings, marked with *. See their
stderr for more details.
```

whenever any of its evaluations came back with `sanitizer_warnings` set. The VS
Code run view shows nothing at all for this.

It is the same blind spot the double-TL warnings had: **the warning fires on a
run that otherwise passed.** An ACCEPTED solution with an ASAN or UBSAN finding
has `status: OK`, `matchesExpectation: true` and a green `AC` chip, so every
channel the extension draws says the solution is fine. Only the terminal says
otherwise. See issue #676.

Unlike double-TL, nothing needs computing. `CheckerResult.sanitizer_warnings` is
already written into every `.eval` (`rbx/grading/steps.py:322`, set in
`rbx/box/checkers.py:365,379`) and rbx already pools it into
`SolutionOutcomeReport.sanitizerWarnings`. The extension simply never reads it.

The issue also names a second, adjacent problem: a sanitized run drops the time
limit and, when no solutions were named, runs only the ACCEPTED ones. Both are
facts about the *run mode*, not about any one solution, and both leave the view
quietly misleading. They are designed here too, in Part B.

## Part A — the per-solution warning

### D1. The aggregate is rbx's answer, not the client's

The extension parses every `.eval` already, so it could OR
`sanitizer_warnings` across a solution's testcases itself and change no Python
at all. That is rejected for the reason
[the run-report design](2026-08-16-run-report-artifact-design.md) exists: the
client is a reader. It would also be wrong in a case the client cannot see —
rbx pools over the evaluations *it ran*, and a subset run, a `--fail-fast` abort
or a skipped testcase leaves the on-disk set and the pooled set disagreeing.

So `RunSolutionReport` gains

```python
sanitizerWarnings: bool = False
```

read straight off `report.sanitizerWarnings` in `build_solution_report`. An
additive optional field is not a breaking change — an older reader drops what it
does not know — so `REPORT_VERSION` stays at 1, exactly as its own comment
instructs.

### D2. The group flag is derived, because it is a fact and not a decision

A warning that cannot say which group it came from sends the reader through
every group looking for it, which is why `_on_groups_markup` names them on the
console and why `runUnderDoubleTl` is published per group as well as pooled.

`GroupOutcomeReport` has no `sanitizerWarnings` to read off, so
`RunGroupReport.sanitizerWarnings` is derived in `build_solution_report`:

```python
sanitizerWarnings=any(eval.result.sanitizer_warnings for eval in group_evals),
```

Deriving it there is not the drift this module exists to prevent. The two
double-TL lists are routed through `per_group` because reaching them means an
`ExpectedOutcome.match` against two declaration layers — a *matcher*, and the
one thing that must have a single copy. A sanitizer finding weighs nothing
against anything: it is an OR over a boolean already on disk, in the same
constructor that derives `outcome` and `maxTime` from the same evaluations.

### D3. A third `WarningKind`, so the four channels stay as they are

`RunWarning` was introduced as the fourth channel precisely because the gutter,
the chip and the label hue all answer "did the declaration hold", and here the
answer is yes. A sanitizer finding is the same shape of news, so it is the same
mechanism: `WarningKind` gains `'sanitizer'`, `warningsOf` pushes it with
`warnedGroups(solution, (group) => group.sanitizerWarnings)` for attribution,
and the row mark, the warning card, the `warned` header count and the `warned`
gutter all follow with no new plumbing.

The sentence in `warningText` keeps the console's words and the shape of its two
neighbours:

```
Sanitizer errors or warnings on big. See the testcase's stderr.
```

`haystack` needs one repair on the way. It appends the literal tokens
`['warning', 'double-tl']` to any row carrying any warning, so a purely
sanitized solution would answer to a `double-tl` filter. The token becomes
per-kind: `warning` on every warned row, plus `double-tl` or `sanitizer`.

### D4. The testcase row carries the mark; the card carries no link

The console puts its `*` on each offending cell, and that is the half of the
report that says *which* stderr to open. `parseEvaluation` gains
`sanitizerWarnings` from `result.sanitizer_warnings`, and `testcaseRow` gives a
sanitized testcase `gutter: 'warned'` with a `sanitizer` entry in
`row.warnings` — the yellow triangle, its tooltip and the search token, all
existing machinery.

Its standing comment — that a testcase never carries a warning — narrows rather
than goes. It is true of a double-TL fact, which is decided over a whole layer
against that layer's expectation; a sanitizer finding is a per-testcase fact
that needed no layer to reach.

The solution's warning card gets no "open stderr" link. `rbx.openStderr` takes a
testcase node, and a pooled warning spans many testcases, so the card would have
to pick one on the reader's behalf. The per-testcase marks are the pointer, and
a marked row's primary command already opens stderr.

## Part B — the sanitized-run banner

A sanitized run changes two things the view presents as ordinary:

- The time limit is dropped for the environment default (`cli.py:611`), so every
  time in the view is measured against something the package did not declare.
- With no solutions named, rbx narrows the run to the ACCEPTED ones
  (`cli.py:617`). The view then shows a subset of the package's solutions and
  says nothing about why the others are missing.

Neither belongs on a solution row: no solution is at fault and every solution is
affected. They are one banner over the run.

### D5. The flags ride the skeleton, not the report

`SolutionReportSkeleton` already carries the run-mode flags — `verification`,
`capture_pipes`, and `merge_stderr`, which rides there so a toggled flag can
never serve a stale capture. The sanitized flags are the same kind of fact, and
the skeleton is written when the run *starts*: the banner is up while solutions
are still running, rather than appearing after the first one lands. `report.yml`
would deliver it only once there is a first solution report to attach it to.

```python
sanitized: bool = False
only_accepted: bool = False
```

`_get_report_skeleton` already takes `sanitized`; it only has to record it.
`only_accepted` is threaded from `cli.py`, which is where the narrowing decision
is made.

Two flags rather than one, and the second is named for the narrowing rather than
for the subset. A user who named solutions on the command line asked for that
subset and needs no banner about it; only the narrowing rbx performed on its own
is news.

### D6. The strip renders on a clean run

`renderHeader` today returns nothing when `mismatches` and `warned` are both
zero — the strip's presence is itself the signal. A sanitized run is exactly the
run that trips neither counter, so the condition grows: counts **or** notices.

`RunViewModel` gains `notices: readonly RunNotice[]`, required and normally
empty, read off `view.run.skeleton`. Required rather than optional for the same
reason `Row.warnings` is: a model that forgot to answer would silently draw
nothing.

```
Sanitized run — time limits were dropped, so these timings are not comparable.
Only ACCEPTED solutions were run.
```

Considered and dropped: greying out the time spans under a sanitized run. It is
a second, quieter channel saying what the banner already says, and it silently
changes what a column means for a reader who never sees the reason.

## Testing

Python, over `build_solution_report`: the pooled flag read off the outcome
report, the group flag set only on the group that raised it, and both absent
from a clean run. Over the skeleton: `sanitized` and `only_accepted` recorded as
passed.

TypeScript: `report.test.ts` for parsing both new fields and for the default an
older report leaves; `viewModel.test.ts` for the third warning kind, its group
attribution, the testcase gutter, the `warned` count not double-counting a
solution that also missed, the `double-tl`/`sanitizer` token split, and the
notices read off the skeleton; the render tests for the two new sentences and
for the strip appearing on a run with notices and no counts.
