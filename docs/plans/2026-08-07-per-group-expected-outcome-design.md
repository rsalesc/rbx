# Per-group expected outcomes for solutions — design

**Date:** 2026-08-07
**Status:** Design approved; implementation pending.

## Summary

Add `outcomePerGroup` to `Solution` in `problem.rbx.yml`: a map from testcase
group name to `ExpectedOutcome`, with a reserved `'*'` key acting as the default
for every group individually. The existing `outcome` field keeps its exact
current meaning — a single expectation checked against the **whole testset
pooled together**. The two are **additive layers**: a solution fails if either
layer fails.

`rbx/box/solutions.py` gains per-group verdict reporting so the run report can
show, per group, whether that group met its expectation, and can attribute a
solution failure to the offending group.

```yaml
solutions:
  - path: sols/partial.cpp
    outcome: incorrect        # pooled: some bad verdict must show up somewhere
    outcomePerGroup:
      '*': accepted           # default applied to every group individually
      group3: tle             # ...except group3, which must time out
```

## Motivation

Today a partial solution can only declare one expectation for the entire
testset. `outcome: incorrect` says "this fails somewhere", which is exactly the
assertion that stops catching regressions: a solution meant to be correct on the
small subtasks and only time out on the big one passes just as well if it starts
failing on the small ones instead. Groups are already the unit the run report
prints and the unit IOI scoring uses, so they are the natural place to pin
expectations down.

## Semantics

| Layer | Scope | Rule |
|---|---|---|
| `outcome` | all evals, pooled | Unchanged from today |
| `outcomePerGroup[g]` | group `g`'s evals alone | Same rule, applied per bucket |

"Same rule" is what `_get_verdict_report` already implements for the pooled
case:

1. Every bad verdict in the scope must `match()` the expectation.
2. If the expectation is itself bad (does not match `ACCEPTED`), at least one
   matching bad verdict must exist in the scope — the existential requirement.

Applying (2) per bucket is precisely what makes per-group expectations stronger
than a pooled one.

Keys are **top-level group names** from `testcases`, `samples` included, which
are the same buckets the run report prints and the same keys used by
`gotScorePerGroup`. `'*'` expands over all of them, `samples` included; override
it with an explicit `samples:` entry when the default does not fit. Subgroups
are **not** addressable — evaluation and reporting bucket by top-level group, so
subgroup expectations would need a new aggregation layer with no current
consumer.

Resolution for a group `g`: explicit `outcomePerGroup[g]`, else
`outcomePerGroup['*']`, else **no per-group check at all** for `g`.

### Rejected alternatives

- **Per-group default taken from `outcome`** (every group checked individually,
  unlisted groups against `outcome`). Rejected: it silently redefines
  `outcome: tle` as "must time out on *every* group", which breaks existing
  packages, since a slow solution rarely times out on the small groups. The
  `'*'` key expresses the same intent opt-in.
- **Override + exclude from global** (a listed group's evals leave the pooled
  check). Rejected: `outcome` should keep meaning "this holds for the testset as
  a whole" regardless of what the per-group layer says.

## Schema (`rbx/box/schema.py`)

```python
class Solution(CodeItem):
    outcome: ExpectedOutcome = ExpectedOutcome.ANY
    outcomePerGroup: Dict[str, ExpectedOutcome] = {}
```

Helpers on `Solution`:

- `expected_outcome_for_group(group: str) -> Optional[ExpectedOutcome]` —
  explicit key, else `'*'`, else `None`.
- `all_expected_outcomes() -> Set[ExpectedOutcome]` —
  `{self.outcome} | set(self.outcomePerGroup.values())`, consumed by the derived
  behaviors below.

### Validation

Group names are only known at `Package` level, so these are `Package`
`model_validator`s alongside the existing `check_deps` / `check_scoring_fields`:

- **Unknown group key** — every non-`'*'` key must name a group in `testcases`.
  A typo would otherwise silently assert nothing.
- **Main-solution guard** — the first solution generates the reference outputs,
  so it must be AC everywhere: error if any of its resolved per-group
  expectations fails to match `ACCEPTED`.
- **Contradiction** — a per-group expectation unsatisfiable under the pooled
  one is an error. Computed precisely, not heuristically: if the group
  expectation is bad, some bad verdict matching it must also match `outcome`
  (via the existing `get_matching_outcomes()` / `match()`). Catches
  `outcome: accepted` + `group2: wa`.

## Report model (`rbx/box/solutions.py`)

`_get_verdict_report` is already parameterized by an expected outcome and needs
no change. `get_solution_outcome_report` changes:

- Per-group verdict reports are computed **always**, not only under `POINTS`
  scoring. This retires the `# TODO: add outcome per group` at the top of that
  loop.
- Groups with **zero evals are skipped**. Without this, a group that has not run
  yet would spuriously fail the existential requirement during live reporting,
  where the reporters call this function mid-run with only the evals collected
  so far.
- POINTS scoring is untouched: it keys off `verdict_report_per_group[g].passed()`,
  which inspects bad verdicts only and never the expectation.
- New on `SolutionOutcomeReport`: `pooledStatus` (the pooled layer's own status)
  and `perGroup`, one `GroupOutcomeReport` per checked group, carrying that
  group's expectation, verdicts, status and double-TL state. `failedGroups` is a
  property derived from `perGroup`. The TUI can consume these later (see
  "Not covered").
- `status` becomes `UNEXPECTED_VERDICTS` when the pooled check **or** any group
  check fails. `UNEXPECTED_SCORE` keeps its current last-wins precedence.
- The timing-issue heuristic (`has_unmatched_slow_verdict` →
  `TimingIssue`) keeps today's inputs; where a group has an explicit
  expectation, that expectation replaces the pooled one for that group's own
  signal. ICPC packages therefore gain no new spurious warnings.

### Drive-by fix

The per-group loop rebinds the `evals` parameter
(`evals = evals_per_group.get(group.name, [])`), so for POINTS problems
`report.evals` ends up holding only the **last group's** evals — the report's
Time and Memory lines are wrong today. Renaming the loop variable fixes it.

## Rendering

A shared helper renders a group's expectation status, used from
`render_group_end` in `FullRunReporter`, `LiveRunReporter` and
`SingleSolutionRunReporter` so the three stay consistent. A group with an
expectation gets an inline mark; the per-solution verdict line names each
offending group:

```
sols/partial.cpp (.box/runs/2)
samples (2) 12ms, 3MB ✓ as expected
group1 (10) 45ms, 4MB ✓ as expected
group2 (10) 1.02s, 4MB ✗ expected TIME_LIMIT_EXCEEDED, got: ACCEPTED
FAILED group2: expected TIME_LIMIT_EXCEEDED, got: ACCEPTED
```

The success mark carries a word because the group line already ends in a run of
per-testcase `✓`/`✗`/`⧖` glyphs, which a bare `✓` would blend into.

At group end the pooled report is still partial, but a finished group's own
report is complete — which is what makes the per-group mark trustworthy mid-run.

## Derived behaviors

Three sites that read `solution.outcome` today are generalized over
`all_expected_outcomes()`:

- **`is_fast`** — `not any(o.is_slow() for o in all_expected_outcomes())`, so a
  group expected to TLE keeps the solution out of
  `--verification=fast-solutions`, exactly as a pooled TLE expectation does.
- **Double-TL warning** — pooled as today, OR'd with per-group reports whose
  expectation is TLE-ish; the warning names the groups whose own
  `runUnderDoubleTl` is set.
- **Timing summary** (`_print_timing`) — *good* if every expectation is
  `ACCEPTED`, *pass* if all are in `{ACCEPTED, ACCEPTED_OR_TLE}`, *slow* if any
  `is_slow()`.

## Tests

- Schema validation: unknown group key, `'*'` resolution and explicit-key
  precedence, main-solution guard, contradiction.
- `get_solution_outcome_report`: a group failing while the pooled check passes,
  `'*'` default, empty-group skip, POINTS scoring unchanged.
- Rendering: capture console output for a package with a per-group expectation.
- `testing_package.add_solution` gains an `outcomePerGroup` kwarg.

## Docs

The field docstring flows into the generated schema page
(`docs/setters/reference/package/schema.md`). Add a short subsection to
`docs/setters/reference/package/index.md` next to the existing `outcome`
example.

## Not covered (filed as an issue)

Every other site reading `solution.outcome` keeps ignoring `outcomePerGroup`.
The full inventory with file:line and a per-site assessment goes into a
follow-up issue: `get_main_solution`, the "first solution must be ACCEPTED"
check, `get_matching_solutions` / `--outcome` filtering (`rbx run`, `rbx irun`,
`rbx time`), `rbx summary` buckets, all four packagers (Polygon solution tags,
MOJ good/slow/wrong, PKG accepted-only copy, BOCA submitter), the TUI badge and
`SolutionReportScreen`, `Solution.href()` styling, and `rbx run --detailed`'s
group table. Stress and unit expectations are intentionally excluded — neither
has groups.
