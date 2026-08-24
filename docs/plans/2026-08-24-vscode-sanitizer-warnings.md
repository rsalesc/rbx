# Sanitizer Warnings in the VS Code Run View — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make an ASAN/UBSAN finding visible in the VS Code run view — on the
solution row, the group row and the offending testcase row — and put a banner
over a sanitized run explaining that its timings are not comparable and that its
solution list may be a subset.

**Architecture:** rbx publishes the facts, the extension renders them and decides
nothing. Two additive optional fields on `report.yml`
(`RunSolutionReport.sanitizerWarnings`, `RunGroupReport.sanitizerWarnings`) and
two on `skeleton.yml` (`sanitized`, `only_accepted`). The extension gains a third
`WarningKind`, which inherits the row mark, the warning card and the `warned`
header count already built for double-TL, plus a `notices` list on the view model
for the run-mode banner. Design:
[2026-08-24-vscode-sanitizer-warnings-design.md](2026-08-24-vscode-sanitizer-warnings-design.md).
Issue: #676.

**Tech Stack:** Python 3 / Pydantic v2 / pytest on the rbx side; TypeScript with
`node --test` on the extension side (no test framework beyond `node:test` and
`node:assert`).

**Conventions that are easy to get wrong here:**

- Python strings are single-quoted; imports are absolute only (ruff `TID`).
  `uv run ruff format .` before every commit.
- Commits are Conventional Commits, checked by a pre-commit hook. Use the
  `.claude/skills/commit.md` workflow: `<type>(<scope>): <lowercase imperative>`,
  under 72 chars, with the `Co-Authored-By: Claude <noreply@anthropic.com>`
  trailer. If the hook rejects a commit, make a NEW commit; never amend.
- The extension is a *reader*. Nothing in `vscode/src` may re-derive a verdict,
  match an expectation, or rank an outcome. Every task below reads a published
  field.
- The codebase comments the *why*, at length, in full sentences. Match it — a
  new field with no comment explaining why it exists will look wrong here.

**Commands you will use repeatedly:**

```bash
# rbx side, from the repo root
uv run pytest tests/rbx/box/run_report_test.py -v
uv run ruff format . && uv run ruff check .

# extension side, from vscode/
cd vscode && npm test          # runs pretest (esbuild) then node --test
cd vscode && npm run typecheck
```

---

## Task 1: Publish `sanitizerWarnings` on the solution report

**Files:**
- Modify: `rbx/box/run_report.py` (the `RunSolutionReport` model, and the
  `RunSolutionReport(...)` construction at the end of `build_solution_report`)
- Test: `tests/rbx/box/run_report_test.py`

**Step 1: Write the failing test**

Append to `tests/rbx/box/run_report_test.py`. `make_evaluation` already takes
`sanitizer_warnings` (`tests/rbx/box/conftest.py:299`), so nothing new is needed
in the fixtures.

```python
def test_a_solution_with_a_sanitizer_finding_says_so(tmp_path, mock_skeleton):
    solution = Solution(path=tmp_path / 'main.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'main': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED, sanitizer_warnings=True),
    ]

    entry = build(solution, skeleton, evals)

    # The whole point: the run passed, and the warning is the only channel
    # saying otherwise.
    assert entry.matchesExpectation
    assert entry.outcome == Outcome.ACCEPTED
    assert entry.sanitizerWarnings


def test_a_clean_run_publishes_no_sanitizer_warning(tmp_path, mock_skeleton):
    solution = Solution(path=tmp_path / 'main.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'main': 2})
    evals = [make_evaluation(Outcome.ACCEPTED), make_evaluation(Outcome.ACCEPTED)]

    entry = build(solution, skeleton, evals)

    assert not entry.sanitizerWarnings
```

**Step 2: Run them to verify they fail**

```bash
uv run pytest tests/rbx/box/run_report_test.py -k sanitizer -v
```

Expected: FAIL — `AttributeError: 'RunSolutionReport' object has no attribute
'sanitizerWarnings'` (Pydantic v2 models reject unknown attribute access).

**Step 3: Add the field**

In `rbx/box/run_report.py`, inside `class RunSolutionReport`, immediately after
the `doubleTlVerdicts: List[Outcome] = []` field and before `groups`:

```python
    # Whether any of this solution's runs tripped a sanitizer.
    #
    # Published for the reason the double-TL facts above are: it is a warning
    # about a run that otherwise *passed*. An ACCEPTED solution with an ASAN or
    # UBSAN finding has `status: OK` and `matchesExpectation: true`, so a client
    # reading only those draws a clean green row for a solution rbx is printing
    # a WARNING about in the terminal.
    #
    # Read off the aggregate rbx already computes for that warning rather than
    # re-pooled here: rbx pools over the evaluations it actually ran, and a
    # subset run or a `--fail-fast` abort leaves that set and the one on disk
    # disagreeing.
    sanitizerWarnings: bool = False
```

Then, in the `RunSolutionReport(...)` construction at the end of
`build_solution_report`, beside `doubleTlVerdicts=`:

```python
        sanitizerWarnings=report.sanitizerWarnings,
```

**Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/rbx/box/run_report_test.py -v
```

Expected: PASS, all of them — the existing tests must still pass, and the
round-trip test proves the new field survives YAML.

**Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check .
git add rbx/box/run_report.py tests/rbx/box/run_report_test.py
git commit -m "$(cat <<'EOF'
feat(run-report): publish whether a solution tripped a sanitizer

The warning fires on a run that otherwise passed, so a client reading only
`status` and `matchesExpectation` has no way to know it happened. Additive
optional field, so REPORT_VERSION stays put. Refs #676.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Publish `sanitizerWarnings` per group

**Files:**
- Modify: `rbx/box/run_report.py` (`RunGroupReport`, and the
  `RunGroupReport(...)` construction in the loop of `build_solution_report`)
- Test: `tests/rbx/box/run_report_test.py`

**Why derived rather than read off `per_group`:** `GroupOutcomeReport`
(`rbx/box/solutions.py:1818`) has no sanitizer field to read. Deriving it here is
safe because it is an OR over a boolean already on disk — no expectation
matcher, unlike the double-TL lists beside it. It exists so the warning can name
the group, the way `_on_groups_markup` does on the console.

**Step 1: Write the failing test**

```python
def test_a_sanitizer_finding_is_attributed_to_its_group(tmp_path, mock_skeleton):
    solution = Solution(path=tmp_path / 'main.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'small': 2, 'big': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED, sanitizer_warnings=True),
        make_evaluation(Outcome.ACCEPTED),
    ]

    entry = build(solution, skeleton, evals)

    groups = {group.name: group for group in entry.groups}
    # Only the group that raised it, so the warning can say where to look
    # instead of sending the reader through every group.
    assert not groups['small'].sanitizerWarnings
    assert groups['big'].sanitizerWarnings
    assert entry.sanitizerWarnings
```

Note the eval order: `mock_skeleton` builds entries group by group in the order
of the `entries_per_group` dict, and `_get_evals_per_group` zips the evaluations
onto them in that same order — so evals 0-1 are `small` and 2-3 are `big`.

**Step 2: Run it to verify it fails**

```bash
uv run pytest tests/rbx/box/run_report_test.py -k attributed_to_its_group -v
```

Expected: FAIL — no `sanitizerWarnings` on `RunGroupReport`.

**Step 3: Add the field**

In `class RunGroupReport`, after `doubleTlVerdicts: List[Outcome] = []`:

```python
    # Whether anything in this group tripped a sanitizer.
    #
    # Derived from the group's evaluations rather than read off its
    # `GroupOutcomeReport`, which has no such field -- and safely so: this is an
    # OR over a boolean already on disk, not an `ExpectedOutcome.match` like the
    # two lists above it. Published per group for the same reason they are: the
    # console names the groups a warning came from, and a client with only the
    # aggregate would have to guess.
    sanitizerWarnings: bool = False
```

In the `RunGroupReport(...)` construction, beside `doubleTlVerdicts=`:

```python
                sanitizerWarnings=any(
                    eval.result.sanitizer_warnings for eval in group_evals
                ),
```

**Step 4: Run the whole file to verify**

```bash
uv run pytest tests/rbx/box/run_report_test.py -v
```

Expected: PASS.

**Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check .
git add rbx/box/run_report.py tests/rbx/box/run_report_test.py
git commit -m "$(cat <<'EOF'
feat(run-report): attribute a sanitizer finding to its group

So the warning can name where to look, the way the console does. Derived
from the group's evals: it is an OR over a published boolean, not an
expectation match. Refs #676.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Record the sanitized run mode on the skeleton

**Files:**
- Modify: `rbx/box/solutions.py` (`SolutionReportSkeleton` ~line 288;
  `_get_report_skeleton` ~line 711, which already takes `sanitized`; the
  `SolutionReportSkeleton(...)` construction ~line 775)
- Modify: `rbx/box/cli.py` (~line 611-624, the `run` command's sanitized branch)
- Test: `tests/rbx/box/run_report_test.py` (or a new
  `tests/rbx/box/solutions_skeleton_test.py` if the skeleton has no natural home
  there — check first with `grep -rn "SolutionReportSkeleton(" tests/`)

**Step 1: Find how the flags reach `_get_report_skeleton`**

```bash
grep -n "_get_report_skeleton" -r rbx/
grep -n "only_accepted\|tracked_solutions is None" rbx/box/cli.py
```

`run_solutions` and its callers already thread `sanitized`. `only_accepted` is
decided in `cli.py` (`if sanitized and tracked_solutions is None:`) — thread a
new keyword-only `only_accepted: bool = False` from there down the same path
`sanitized` takes. Add it to every signature on that path with a `= False`
default so no other caller changes.

**Step 2: Write the failing test**

```python
def test_the_skeleton_records_a_sanitized_run(tmp_path, mock_skeleton):
    skeleton = mock_skeleton([])

    # The default is the ordinary run: nothing to say.
    assert not skeleton.sanitized
    assert not skeleton.only_accepted
```

plus, in whichever test module covers `_get_report_skeleton` end to end (if
none does, this default test plus the CLI wiring reviewed by eye is enough —
do not invent an integration harness for two booleans).

**Step 3: Run it to verify it fails**

```bash
uv run pytest tests/rbx/box/run_report_test.py -k sanitized_run -v
```

Expected: FAIL — no attribute `sanitized`.

**Step 4: Add the fields**

In `class SolutionReportSkeleton`, after `merge_stderr: bool = False`:

```python
    # Whether this run was sanitized (`rbx run -s`).
    #
    # A run-mode fact rather than a per-solution one, and it rides the skeleton
    # beside `verification` and `merge_stderr` for the same reason: the skeleton
    # is written when the run starts, so a client can say what kind of run it is
    # showing while the solutions are still going.
    #
    # It matters because a sanitized run drops the problem's time limit for the
    # environment default, which makes every time in a client's view a
    # measurement against a limit the package never declared.
    sanitized: bool = False
    # Whether rbx narrowed this run to the ACCEPTED solutions on its own.
    #
    # Set only for the narrowing rbx performed, never for a subset the user
    # asked for: naming solutions on the command line is a deliberate act and
    # needs no warning, while a client showing a silently shortened list has no
    # way to tell the reader that the rest were never run.
    only_accepted: bool = False
```

In the `SolutionReportSkeleton(...)` construction inside `_get_report_skeleton`,
beside `capture_pipes=`:

```python
        sanitized=sanitized,
        only_accepted=only_accepted,
```

In `cli.py`, set a local in the narrowing branch and pass it to `run_solutions`:

```python
    only_accepted = False
    if sanitized and tracked_solutions is None:
        console.console.print(
            '[warning]Sanitizers are running, and no solutions were specified to run. Will only run [item]ACCEPTED[/item] solutions.'
        )
        only_accepted = True
        tracked_solutions = OrderedSet(...)
```

**Step 5: Run the tests**

```bash
uv run pytest tests/rbx/box/ -x -q
```

Expected: PASS. (Some C++/sandbox tests fail locally for unrelated reasons — see
the note at the end of this plan. `-k` down to the report/solutions modules if
the noise gets in the way.)

**Step 6: Verify by hand that the flag actually lands**

```bash
cd /tmp && rm -rf sanitized-check && uv run --directory /path/to/repo rbx create sanitized-check
# then, inside the package:
uv run rbx run -s
grep -n "sanitized\|only_accepted" .rbx/runs/skeleton.yml
```

Expected: both `true`. Then `uv run rbx run` and expect both absent or `false`.
If `rbx create` needs interactive input, use any existing package under
`tests/**/testdata/` instead — the point is only to see the flag written.

**Step 7: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check .
git add rbx/box/solutions.py rbx/box/cli.py tests/
git commit -m "$(cat <<'EOF'
feat(solutions): record the sanitized run mode on the skeleton

A sanitized run drops the time limit and, unasked, narrows itself to the
ACCEPTED solutions. Both are facts about the run rather than any solution,
and a client showing the run has no way to derive either. Refs #676.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Parse the new report fields in the extension

**Files:**
- Modify: `vscode/src/rbx/report.ts` (the `GroupReport` and `SolutionReport`
  interfaces ~lines 33 and 80; the two parse sites ~lines 111 and 172)
- Test: `vscode/src/rbx/report.test.ts`

**Step 1: Write the failing tests**

Follow the shape of the existing double-TL tests at `report.test.ts:125-149`.

```ts
test('a sanitizer finding is parsed on the solution and on its group', () => {
  const report = parseRunReport({
    version: 1,
    solutions: [
      {
        path: 'sols/main.cpp',
        index: 0,
        expectedOutcome: 'ACCEPTED',
        status: 'OK',
        sanitizerWarnings: true,
        groups: [{ name: 'big', sanitizerWarnings: true }],
      },
    ],
  });
  const solution = report!.solutions[0];
  assert.strictEqual(solution.sanitizerWarnings, true);
  assert.strictEqual(solution.groups[0].sanitizerWarnings, true);
});

test('a report written before the field reads as no warning', () => {
  const report = parseRunReport({
    version: 1,
    solutions: [
      {
        path: 'sols/main.cpp',
        index: 0,
        expectedOutcome: 'ACCEPTED',
        status: 'OK',
        groups: [{ name: 'big' }],
      },
    ],
  });
  const solution = report!.solutions[0];
  assert.strictEqual(solution.sanitizerWarnings, false);
  assert.strictEqual(solution.groups[0].sanitizerWarnings, false);
});
```

Copy the exact call and assertion style from the neighbouring tests — check
whether they call `parseRunReport` or something else, and match it.

**Step 2: Run to verify they fail**

```bash
cd vscode && npm test 2>&1 | tail -30
```

Expected: FAIL — `undefined !== false`, plus a `tsc` error about an unknown
property if `pretest` typechecks.

**Step 3: Add the field to both interfaces and both parse sites**

In `GroupReport`, beside `doubleTlVerdicts`:

```ts
  /** Whether anything in this group tripped a sanitizer -- see `SolutionReport`. */
  readonly sanitizerWarnings: boolean;
```

In `SolutionReport`, beside `doubleTlVerdicts`:

```ts
  /**
   * Whether any of this solution's runs tripped a sanitizer.
   *
   * A warning about a run that *passed*: rbx sets `status: OK` and
   * `matchesExpectation: true` on exactly these solutions, so the three channels
   * that answer "did the declaration hold" all say yes.
   */
  readonly sanitizerWarnings: boolean;
```

At both parse sites:

```ts
    sanitizerWarnings: asBoolean(field(raw, 'sanitizerWarnings')) ?? false,
```

**Step 4: Run to verify they pass**

```bash
cd vscode && npm test 2>&1 | tail -20
```

Expected: PASS. The `viewModel.test.ts` helpers `groupReport`/`solutionReport`
(lines 39 and 60) now need `sanitizerWarnings: false` in their defaults — add it,
or the file will not compile.

**Step 5: Commit**

```bash
git add vscode/src/rbx/report.ts vscode/src/rbx/report.test.ts vscode/src/rbx/viewModel.test.ts
git commit -m "$(cat <<'EOF'
feat(vscode): read the sanitizer flags off the run report

Defaulting to false, so a report written by an older rbx reads as a clean
run rather than as a parse failure. Refs #676.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: A third `WarningKind`

**Files:**
- Modify: `vscode/src/rbx/viewModel.ts` (`WarningKind` line 134; `warningsOf`
  line 633; `haystack` line 543)
- Modify: `vscode/src/webview/render.ts` (`warningText` line 117)
- Test: `vscode/src/rbx/viewModel.test.ts`, `vscode/src/webview/render.test.ts`

**Step 1: Write the failing tests**

In `viewModel.test.ts`, modelled on the double-TL tests around line 700:

```ts
test('a solution that passed with a sanitizer finding is warned, not clean', () => {
  const model = buildViewModel(
    view([
      solution(0, 'sols/main.cpp', 'ACCEPTED', [group('big', [])], solutionReport({
        sanitizerWarnings: true,
        groups: [groupReport({ name: 'big', sanitizerWarnings: true })],
      })),
    ]),
  );
  const row = model.rows.find((candidate) => candidate.kind === 'solution')!;
  assert.strictEqual(row.gutter, 'warned');
  assert.deepStrictEqual(
    row.warnings.map((warning) => warning.kind),
    ['sanitizer'],
  );
  // Named, so the reader is not sent through every group looking.
  assert.deepStrictEqual(row.warnings[0].groups, ['big']);
  assert.strictEqual(model.warned, 1);
  assert.strictEqual(model.mismatches, 0);
});

test('a sanitizer warning does not answer to a double-tl filter', () => {
  const model = buildViewModel(
    view([
      solution(0, 'sols/main.cpp', 'ACCEPTED', [], solutionReport({
        sanitizerWarnings: true,
      })),
    ]),
  );
  const row = model.rows.find((candidate) => candidate.kind === 'solution')!;
  assert.ok(row.search.includes('sanitizer'));
  assert.ok(row.search.includes('warning'));
  assert.ok(!row.search.includes('double-tl'));
});
```

Match the exact helper signatures already in the file — `view`, `solution`,
`group`, `solutionReport`, `groupReport` — rather than the sketch above, which
may differ in argument order.

In `render.test.ts`, one test that the sentence reaches the card. Copy the
existing double-TL render test's setup exactly.

**Step 2: Run to verify they fail**

```bash
cd vscode && npm test 2>&1 | tail -30
```

Expected: FAIL — `gutter` is `'met'`, `warnings` is `[]`, and a `tsc` error on
the `'sanitizer'` kind.

**Step 3: Implement**

`WarningKind` (line 134):

```ts
export type WarningKind = 'double-tl-passed' | 'double-tl-verdicts' | 'sanitizer';
```

In `warningsOf`, after the `doubleTlVerdicts` block:

```ts
  if (report.sanitizerWarnings) {
    warnings.push({
      kind: 'sanitizer',
      verdicts: [],
      groups:
        solution === undefined
          ? []
          : warnedGroups(solution, (group) => group.sanitizerWarnings),
    });
  }
```

In `haystack`, replace the hardcoded pair

```ts
    ...(warnings.length === 0 ? [] : ['warning', 'double-tl']),
```

with a per-kind token, so a purely sanitized solution stops answering to a
`double-tl` filter:

```ts
    // `warning` on every warned row -- what a user scanning for anything wrong
    // types -- plus a token per kind, for someone who already knows what they
    // are hunting. Per kind and not a fixed pair: a sanitized solution answering
    // to a `double-tl` filter is a filter that lies.
    ...(warnings.length === 0 ? [] : ['warning']),
    ...warnings.map((warning) =>
      warning.kind === 'sanitizer' ? 'sanitizer' : 'double-tl',
    ),
```

`haystack` deduplicates through a `Set` at the end, so two double-TL warnings on
one row still contribute a single `double-tl`.

In `render.ts`'s `warningText`, a third case:

```ts
    case 'sanitizer':
      return `Sanitizer errors or warnings${where}. See the testcase's stderr.`;
```

`warningText`'s switch is exhaustive over `WarningKind`, so `tsc` will point at
it if you forget.

**Step 4: Run to verify**

```bash
cd vscode && npm test && npm run typecheck
```

Expected: PASS, clean typecheck.

**Step 5: Commit**

```bash
git add vscode/src/rbx/viewModel.ts vscode/src/webview/render.ts vscode/src/rbx/viewModel.test.ts vscode/src/webview/render.test.ts
git commit -m "$(cat <<'EOF'
feat(vscode): warn on a solution that tripped a sanitizer

The fourth channel already exists for double TL; a sanitizer finding is the
same shape of news -- a run that passed and still deserves a mark -- so it
becomes a third warning kind. Closes part of #676.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Mark the offending testcase

**Files:**
- Modify: `vscode/src/rbx/model.ts` (`Evaluation` interface line 99;
  `parseEvaluation` line 253)
- Modify: `vscode/src/rbx/viewModel.ts` (`testcaseRow` line 897)
- Test: `vscode/src/rbx/model.test.ts`, `vscode/src/rbx/viewModel.test.ts`

**Step 1: Write the failing tests**

`model.test.ts` — the field is read straight off the `.eval`:

```ts
test('an evaluation carries its sanitizer flag', () => {
  const evaluation = parseEvaluation({
    result: { outcome: 'accepted', sanitizer_warnings: true },
    log: { time: 0.01 },
  });
  assert.strictEqual(evaluation!.sanitizerWarnings, true);
});
```

`viewModel.test.ts` — the row that says which stderr to open:

```ts
test('a sanitized testcase carries the mark, so the reader knows which stderr', () => {
  const model = buildViewModel(
    view([
      solution(0, 'sols/main.cpp', 'ACCEPTED', [
        group('big', [
          testcase('001', { outcome: 'accepted' }),
          testcase('002', { outcome: 'accepted', sanitizerWarnings: true }),
        ]),
      ]),
    ]),
  );
  const rows = model.rows.filter((row) => row.kind === 'testcase');
  assert.strictEqual(rows[0].gutter, 'none');
  assert.strictEqual(rows[1].gutter, 'warned');
  assert.deepStrictEqual(
    rows[1].warnings.map((warning) => warning.kind),
    ['sanitizer'],
  );
});

test('a marked testcase does not count towards the header', () => {
  // The strip counts solutions; a run whose solution row is clean must not
  // be reported as warned just because a testcase row carries a mark.
  // (Construct a run with a sanitized testcase but no solution report, and
  // assert model.warned === 0.)
});
```

Use the file's own `testcase` helper (line ~25) and extend its `over` argument
rather than inventing a new one.

**Step 2: Run to verify they fail**

```bash
cd vscode && npm test 2>&1 | tail -30
```

**Step 3: Implement**

In `model.ts`, on `Evaluation`:

```ts
  /**
   * Whether this run tripped a sanitizer.
   *
   * Unlike `noTleOutcome`, this needs no answer from rbx to be worth showing:
   * it is a fact about this run alone, not a verdict weighed against an
   * expectation, so the row can carry it directly.
   */
  readonly sanitizerWarnings?: boolean;
```

In `parseEvaluation`:

```ts
    sanitizerWarnings: asBoolean(field(raw, 'result', 'sanitizer_warnings')),
```

Check that `asBoolean` is imported/available in `model.ts`; `report.ts` has one,
so lift it to wherever the two share helpers rather than writing a second.

In `testcaseRow`, replace the `gutter: 'none'` and `warnings: []` lines and
narrow the comment that justified them:

```ts
  const sanitized = evaluation?.sanitizerWarnings === true;
  ...
    // A testcase declares no expectation of its own, so nothing here can be
    // `met` or `missed`; a sanitizer finding is the one thing a testcase row
    // has to say on its own account, and `warned` is the channel for it.
    gutter: sanitized ? 'warned' : 'none',
    ...
    // A double-TL fact is decided over a whole group or a whole solution, never
    // over one testcase: a single soft TLE says nothing until it is weighed
    // against the expectation the layer above it declared. A sanitizer finding
    // needed no such weighing -- it is exactly a fact about this run -- and this
    // row is the only one that can say *which* stderr to open.
    warnings: sanitized ? [{ kind: 'sanitizer', verdicts: [], groups: [] }] : [],
```

Confirm `haystack` for the testcase row is passed those warnings too, so
`sanitizer` filters down to the marked testcases:

```ts
    search: haystack(`${node.group.name}/${testcase.stem}`, verdict, false, undefined, warnings),
```

which needs `warnings` hoisted to a local above the object literal.

**Step 4: Run to verify**

```bash
cd vscode && npm test && npm run typecheck
```

**Step 5: Commit**

```bash
git add vscode/src/rbx/model.ts vscode/src/rbx/viewModel.ts vscode/src/rbx/model.test.ts vscode/src/rbx/viewModel.test.ts
git commit -m "$(cat <<'EOF'
feat(vscode): mark the testcase a sanitizer fired on

The solution-level warning says a sanitizer fired somewhere; this is the
half that says where, and the row's primary command already opens its
stderr. Closes part of #676.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Parse the run-mode flags

**Files:**
- Modify: `vscode/src/rbx/model.ts` (`Skeleton` interface line 88;
  `parseSkeleton` line 168)
- Modify: the four `Skeleton` literals in tests:
  `vscode/src/rbx/nodes.test.ts:31`, `vscode/src/rbx/viewModel.test.ts:94`,
  `vscode/src/rbx/diagnostics.test.ts:29,133`
- Test: `vscode/src/rbx/model.test.ts`

**Step 1: Write the failing test**

```ts
test('a sanitized run is parsed off the skeleton', () => {
  const skeleton = parseSkeleton({
    solutions: [],
    entries: [],
    groups: [],
    sanitized: true,
    only_accepted: true,
  });
  assert.strictEqual(skeleton!.sanitized, true);
  assert.strictEqual(skeleton!.onlyAccepted, true);
});

test('an ordinary run says so by omission', () => {
  const skeleton = parseSkeleton({ solutions: [], entries: [], groups: [] });
  assert.strictEqual(skeleton!.sanitized, false);
  assert.strictEqual(skeleton!.onlyAccepted, false);
});
```

**Step 2: Run to verify they fail**

**Step 3: Implement**

On `Skeleton` (required, not optional — `parseSkeleton` always answers, and an
optional field would let a caller forget to ask):

```ts
  /**
   * Whether the run was sanitized (`rbx run -s`), which drops the problem's
   * time limit for the environment default. Every time in the view is then
   * measured against a limit the package never declared.
   */
  readonly sanitized: boolean;
  /**
   * Whether rbx narrowed the run to the ACCEPTED solutions on its own -- which
   * it does for a sanitized run with no solutions named. The view then shows a
   * subset of the package's solutions with nothing saying why.
   */
  readonly onlyAccepted: boolean;
```

In `parseSkeleton`'s return:

```ts
  return {
    solutions,
    entries,
    groups,
    compilation: parseCompilation(root),
    sanitized: asBoolean(root.sanitized) ?? false,
    onlyAccepted: asBoolean(root.only_accepted) ?? false,
  };
```

Note the snake_case on the wire (`skeleton.yml` is `model_to_yaml` of a Pydantic
model with snake_case fields) and camelCase in the interface, which is what the
file already does for `copiedFrom` etc.

Add `sanitized: false, onlyAccepted: false` to the four test literals.

**Step 4: Run to verify** — `npm test && npm run typecheck`.

**Step 5: Commit**

```bash
git add vscode/src/rbx/model.ts vscode/src/rbx/model.test.ts vscode/src/rbx/nodes.test.ts vscode/src/rbx/viewModel.test.ts vscode/src/rbx/diagnostics.test.ts
git commit -m "$(cat <<'EOF'
feat(vscode): read the run mode off the skeleton

Refs #676.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: The banner

**Files:**
- Modify: `vscode/src/rbx/viewModel.ts` (`RunViewModel` line 371; `EMPTY_MODEL`
  line 392; `buildViewModel`'s return line 1070)
- Modify: `vscode/src/webview/render.ts` (`renderHeader` line 657)
- Modify: `vscode/src/webview/style.css` if the notice needs a rule of its own —
  reuse `.header-warned` first and only add one if it genuinely reads wrong
- Test: `vscode/src/rbx/viewModel.test.ts`, `vscode/src/webview/render.test.ts`

**Step 1: Write the failing tests**

```ts
test('a sanitized run carries its notices', () => {
  const model = buildViewModel(viewWithSkeleton({ sanitized: true, onlyAccepted: true }));
  assert.deepStrictEqual(
    model.notices.map((notice) => notice.kind),
    ['sanitized-run', 'accepted-only'],
  );
});

test('an ordinary run carries none', () => {
  const model = buildViewModel(view([]));
  assert.deepStrictEqual(model.notices, []);
});
```

and, in `render.test.ts`, the one that matters — the strip today returns `''`
when both counts are zero, which is exactly the sanitized run:

```ts
test('the strip appears for a notice on a run with nothing else to say', () => {
  const html = renderHeader(
    { rows: [], mismatches: 0, warned: 0, empty: false, notices: [{ kind: 'sanitized-run' }] },
    STATE,
  );
  assert.ok(html.includes('time limits were dropped'));
});
```

You will need a `viewWithSkeleton` helper, or an extra argument on the existing
`view`/`run` helpers. Extend the existing ones rather than adding a parallel set.

**Step 2: Run to verify they fail**

**Step 3: Implement**

In `viewModel.ts`:

```ts
/**
 * A fact about the run itself rather than about any solution in it.
 *
 * Separate from `RunWarning` because no row owns it: a sanitized run affects
 * every solution shown and every solution *not* shown, so it belongs over the
 * whole view. Which notices a run gets is rbx's answer, published on the
 * skeleton; only the words are decided here.
 */
export type NoticeKind = 'sanitized-run' | 'accepted-only';

export interface RunNotice {
  readonly kind: NoticeKind;
}
```

On `RunViewModel`, required and normally empty, for the reason `Row.warnings` is:

```ts
  /** Facts about the run itself -- see `RunNotice`. Usually empty. */
  readonly notices: readonly RunNotice[];
```

`EMPTY_MODEL` gains `notices: []`. In `buildViewModel`:

```ts
    notices: noticesOf(view.run?.skeleton),
```

with

```ts
function noticesOf(skeleton: Skeleton | undefined): RunNotice[] {
  if (skeleton === undefined) {
    return [];
  }
  const notices: RunNotice[] = [];
  if (skeleton.sanitized) {
    notices.push({ kind: 'sanitized-run' });
  }
  // Only the narrowing rbx did on its own: a user who named solutions asked for
  // that subset and needs no banner about it.
  if (skeleton.onlyAccepted) {
    notices.push({ kind: 'accepted-only' });
  }
  return notices;
}
```

In `render.ts`, `renderHeader` grows a notice clause and its early return grows a
condition:

```ts
  if (model.mismatches === 0 && model.warned === 0 && model.notices.length === 0) {
    return '';
  }
```

```ts
/**
 * What kind of run this is, when it is not an ordinary one.
 *
 * In the strip rather than a banner of its own: the strip is already the place
 * a reader looks for "is there anything I should know before reading these
 * rows", and a second bar above it would push the tree down on every sanitized
 * run.
 */
function noticeText(notice: RunNotice): string {
  switch (notice.kind) {
    case 'sanitized-run':
      return 'Sanitized run — time limits were dropped, so these timings are not comparable.';
    case 'accepted-only':
      return 'Only ACCEPTED solutions were run.';
  }
}
```

rendered as `<span class="header-count header-warned">` entries beside the
counts, with `codicon('info')` rather than `warning` — the run is not wrong, it
is a different kind of run.

Check that every other construction site of `RunViewModel` compiles: `tsc` will
list them, and there is at least `EMPTY_MODEL` and the test fixtures.

**Step 4: Run to verify** — `npm test && npm run typecheck && npm run lint`.

**Step 5: Commit**

```bash
git add vscode/src/rbx/viewModel.ts vscode/src/webview/render.ts vscode/src/webview/style.css vscode/src/rbx/viewModel.test.ts vscode/src/webview/render.test.ts
git commit -m "$(cat <<'EOF'
feat(vscode): say when a run was sanitized

A sanitized run drops the time limit and may show only the ACCEPTED
solutions, so both the timings and the list mean something other than what
they look like. Closes #676.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Full verification

**Step 1: The whole extension suite**

```bash
cd vscode && npm test && npm run typecheck && npm run lint
```

Expected: all pass, no `tsc` output, no eslint findings.

**Step 2: The rbx suite**

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto -m 'not (e2e or slow or docker)'
```

Expected: pass, except the known-unrelated local failures — C++/sandbox tests
and `test_compute_walltime_uses_active_environment`. Compare against
`git stash && <same command>` before blaming anything on this branch.

**Step 3: See it in the real view**

Build a package with a solution that trips ASAN (an out-of-bounds read is
enough), run `uv run rbx run -s`, and open the run view. Confirm:

- the solution row is green-with-a-warning-triangle, not plain green
- expanding it shows the warning card sentence
- the group row names the group
- the offending testcase row carries the triangle, and its stderr opens
- the strip says the run was sanitized and, if you named no solutions, that only
  ACCEPTED ones ran
- an ordinary `uv run rbx run` shows none of it

**Step 4: Push and open the PR**

```bash
git push -u origin worktree-vscode-sanitizer-warnings
```

Draft PR referencing #676, describing both halves.

---

## Notes for whoever executes this

- **Do not** let the extension derive a sanitizer aggregate itself, even though
  it has every `.eval` in hand. The whole point of `run_report.py` is that rbx
  answers and the client reads. See D1 in the design.
- **Known-unrelated local failures:** some C++/sandbox tests and
  `test_compute_walltime_uses_active_environment` fail on this machine for
  reasons that predate this branch. Verify against a clean tree before treating
  one as yours.
- The `.claude/skills/commit.md` workflow is mandatory for every commit here.
