# Abort-on-inference-timeout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop running a solution's remaining testcases once a caller-supplied
predicate says they cannot change the outcome, and use it to skip the tests of
a solution already capped by `timing.multipliers.inferenceTimeout`.

**Architecture:** A per-solution gate wraps each lazy `Deferred[Evaluation]`.
When the caller's predicate trips it, later deferreds for that solution
short-circuit to a real `Evaluation` carrying a new `Outcome.SKIPPED` instead
of executing. Enforcing at the `Deferred` level (rather than breaking a report
loop) is required because several consumers independently force the deferreds.

**Tech Stack:** Python 3, Pydantic v2, Typer, pytest, `uv`.

**Design doc:** `docs/plans/2026-08-14-abort-on-inference-timeout-design.md`.
Read it before starting. Branch: `stack-inference-abort`, stacked on #643.

**Conventions:** single quotes, absolute imports only, `uv run pytest`,
`uv run ruff check --fix . && uv run ruff format .` before each commit,
conventional commits (see `.claude/skills/commit.md`).

---

## Background you need

- Evaluations are lazy: `Deferred` (`rbx/box/deferred.py`) memoizes into
  `self.cache` and **treats `cache is None` as "not computed yet"**. Never let
  a deferred resolve to `None` -- it would re-run on every await.
- `_run_solution` (`rbx/box/solutions.py:397`) is called **once per (solution,
  group)** from `_produce_solution_items` (`:624-631`), so the gate must be
  created per *solution* and passed in across group calls.
- The run loop is strictly sequential (no `gather`/`create_task` in
  `solutions.py`/`tasks.py`), which is what makes a mutable gate safe.
- `deps` are only legal under `scoring: points` (`rbx/box/schema.py:1362`).

---

## Task 1: Add `Outcome.SKIPPED`

**Files:**
- Modify: `rbx/grading/steps.py:38-80`
- Test: `tests/rbx/grading/steps_test.py` (create if absent)

**Step 1: Write the failing tests**

```python
def test_skipped_is_less_severe_than_real_failures():
    assert (
        Outcome.worst_outcome([Outcome.ACCEPTED, Outcome.TIME_LIMIT_EXCEEDED, Outcome.SKIPPED])
        == Outcome.TIME_LIMIT_EXCEEDED
    )


def test_skipped_beats_accepted():
    assert Outcome.worst_outcome([Outcome.ACCEPTED, Outcome.SKIPPED]) == Outcome.SKIPPED


def test_skipped_is_not_slow_nor_limit_exceeded():
    assert not Outcome.SKIPPED.is_slow()
    assert not Outcome.SKIPPED.is_limit_exceeded()
    assert Outcome.SKIPPED.short_name() == 'SKIP'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/grading/steps_test.py -v`
Expected: FAIL, `AttributeError: SKIPPED`.

**Step 3: Implement**

Insert the member **immediately after `ACCEPTED`** -- `worst_outcome` ranks by
`cls._member_names_.index(...)` (`steps.py:53`, the only index-dependent site
in the codebase, verified by grep), so index 1 makes `SKIPPED` beat `ACCEPTED`
without masking the verdict that tripped the abort.

```python
class Outcome(Enum):
    ACCEPTED = 'accepted'
    SKIPPED = 'skipped'
    WRONG_ANSWER = 'wrong-answer'
    ...
```

Add to `short_name()`: `if self == Outcome.SKIPPED: return 'SKIP'`.

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/grading/steps_test.py -v` → PASS.

**Step 5: Commit**

```
feat(grading): add a SKIPPED outcome
```

---

## Task 2: `ExpectedOutcome.match(SKIPPED)`

A skipped testcase was not awarded, so it satisfies every expectation except
`ACCEPTED`.

**Files:**
- Modify: `rbx/box/schema.py:250` (`ExpectedOutcome.match`)
- Test: `tests/rbx/box/schema_test.py`

**Step 1: Write the failing test**

```python
@pytest.mark.parametrize('expected', list(ExpectedOutcome))
def test_skipped_matches_everything_but_accepted(expected: ExpectedOutcome):
    assert expected.match(Outcome.SKIPPED) == (expected != ExpectedOutcome.ACCEPTED)
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/schema_test.py -k skipped -v`
Expected: FAIL for `WRONG_ANSWER`, `COMPILATION_ERROR`, and others whose arms
return `False`.

**Step 3: Implement**

An early branch is required -- the per-member arms each compare against a
specific outcome and would all return `False`:

```python
    def match(self, outcome: Outcome) -> bool:
        if self == ExpectedOutcome.ANY:
            return True
        # A skipped testcase was not awarded, so it satisfies any expectation
        # that does not demand success.
        if outcome == Outcome.SKIPPED:
            return self != ExpectedOutcome.ACCEPTED
        ...
```

**Step 4:** Run the test → PASS. Also run
`uv run pytest tests/rbx/box/schema_test.py -v` to catch regressions.

**Step 5: Commit**

```
feat(schema): make SKIPPED satisfy every non-accepted expectation
```

---

## Task 3: Console styling for `SKIPPED`

**Files:**
- Modify: `rbx/box/solutions.py:1129-1163`
  (`get_outcome_style_verdict`, `get_outcome_markup_verdict`)
- Test: `tests/rbx/box/solutions_test.py`

**Step 1: Write the failing test**

```python
def test_skipped_outcome_has_its_own_style_and_icon():
    assert get_outcome_style_verdict(Outcome.SKIPPED) == 'bright_black'
    assert '⊘' in get_outcome_markup_verdict(Outcome.SKIPPED)
```

**Step 2:** Run → FAIL (falls through to `'magenta'` / `'✗'`).

**Step 3: Implement** -- add an arm to each function, before the fallbacks.
Verify `bright_black` is a valid style in the custom theme
(`rbx/box/console.py`); if not, pick an existing dim style from that theme.

**Step 4:** Run → PASS.

**Step 5: Commit**

```
feat(solutions): style the SKIPPED verdict
```

---

## Task 4: The gate (pure logic)

**Files:**
- Modify: `rbx/box/solutions.py` (near `EvaluationItem`, `:95`)
- Test: `tests/rbx/box/solutions_test.py`

**Step 1: Write the failing tests**

Build `GroupSkeleton`s directly -- no package fixture needed.

```python
def _group(name: str, deps: List[str]) -> GroupSkeleton:
    return GroupSkeleton(name=name, score=100, deps=deps, testcases=[])


def test_binary_scoring_aborts_the_whole_testset():
    skeleton = [_group('a', []), _group('b', []), _group('c', [])]
    gate = _AbortGate(skeleton=skeleton, scoring=ScoreType.BINARY)
    gate.trip('a')
    assert all(gate.is_skipped(g.name) for g in skeleton)


def test_points_scoring_aborts_the_group_and_its_dependents():
    # c depends on b, b depends on a; d is independent.
    skeleton = [_group('a', []), _group('b', ['a']), _group('c', ['b']), _group('d', [])]
    gate = _AbortGate(skeleton=skeleton, scoring=ScoreType.POINTS)
    gate.trip('a')
    assert gate.is_skipped('a')
    assert gate.is_skipped('b')
    assert gate.is_skipped('c')  # indirect dependency
    assert not gate.is_skipped('d')


def test_gate_is_not_skipped_before_tripping():
    skeleton = [_group('a', [])]
    gate = _AbortGate(skeleton=skeleton, scoring=ScoreType.POINTS)
    assert not gate.is_skipped('a')
```

**Step 2:** Run → FAIL, `_AbortGate` undefined.

**Step 3: Implement**

```python
@dataclasses.dataclass(frozen=True)
class AbortContext:
    """What a caller may use to decide that a solution's remaining testcases
    cannot change its outcome."""

    solution: Solution
    group: GroupSkeleton
    entry: TestcaseEntry
    expected_outcome: ExpectedOutcome
    group_expected_outcome: Optional[ExpectedOutcome]
    evaluation: Evaluation


AbortPredicate = Callable[[AbortContext], bool]


class _AbortGate:
    """Tracks which groups of a single solution must no longer run.

    Safe because the run loop is sequential: nothing in `solutions.py` or
    `tasks.py` schedules evaluations concurrently.

    The caller's predicate must only trip on an outcome that already dooms the
    group -- the skipped groups are reported as failed, not as unmeasured.
    """

    def __init__(self, skeleton: List[GroupSkeleton], scoring: ScoreType):
        self.skeleton = skeleton
        self.scoring = scoring
        self.skipped_groups: Set[str] = set()

    def is_skipped(self, group_name: str) -> bool:
        return group_name in self.skipped_groups

    def trip(self, group_name: str) -> None:
        if self.scoring != ScoreType.POINTS:
            # `deps` only exist under POINTS, and a binary verdict is
            # all-or-nothing, so nothing later can change the outcome.
            self.skipped_groups.update(group.name for group in self.skeleton)
            return
        self.skipped_groups.add(group_name)
        self.skipped_groups.update(self._dependents_of(group_name))

    def _dependents_of(self, group_name: str) -> Set[str]:
        """Groups that depend on `group_name`, directly or indirectly.

        They would score 0 anyway -- `_check_deps` zeroes a group whenever any
        of its dependencies failed.
        """
        res: Set[str] = set()
        changed = True
        while changed:
            changed = False
            for group in self.skeleton:
                if group.name in res:
                    continue
                if group_name in group.deps or (res & set(group.deps)):
                    res.add(group.name)
                    changed = True
        return res
```

**Step 4:** Run → PASS.

**Step 5: Commit**

```
feat(solutions): add an abort gate for solution runs
```

---

## Task 5: Wire the gate into the runner

**Files:**
- Modify: `rbx/box/solutions.py:397` (`_run_solution`), `:572`
  (`_produce_solution_items`), `:635` (`run_solutions`)
- Test: `tests/rbx/box/solutions_test.py`

**Step 1: Write the failing test**

Use a real package fixture (see `tests/rbx/box/conftest.py`; `pkg_from_testdata`
/ `@pytest.mark.test_pkg`). The point is that the sandbox is never entered for
a skipped test, so assert on the *verdicts*, and additionally on a spy over
`rbx.box.tasks.run_solution_on_testcase` counting invocations.

```python
async def test_abort_skips_every_later_testcase_of_that_solution(...):
    result = await run_solutions(
        abort_on=lambda ctx: ctx.evaluation.result.outcome != Outcome.ACCEPTED,
        ...
    )
    evals = [await e() for e in <that solution's deferreds in entry order>]
    outcomes = [e.result.outcome for e in evals]
    # everything after the first non-AC is SKIPPED, and nothing is None
    assert Outcome.SKIPPED in outcomes
    assert all(o == Outcome.SKIPPED for o in outcomes[outcomes.index(Outcome.SKIPPED):])
    # other solutions are untouched
    assert Outcome.SKIPPED not in <other solution's outcomes>
```

**Step 2:** Run → FAIL, `run_solutions() got an unexpected keyword argument`.

**Step 3: Implement**

1. Add `abort_on: Optional[AbortPredicate] = None` to `run_solutions` and
   thread it to `_produce_solution_items`.
2. In `_produce_solution_items`, build **one gate per solution** (the loop at
   `:624-631` calls `_run_solution` once per group, so it must outlive a single
   call):

```python
    for solution in skeleton.solutions:
        gate = (
            _AbortGate(skeleton.groups, package.get_scoring())
            if abort_on is not None
            else None
        )
        for group in skeleton.groups:
            res.extend(
                yield_items(solution, skeleton.get_entries_for_group(group.name), gate)
            )
```

3. In `_run_solution`, wrap the existing `run_fn`. Keep the wrapper *inside*
   the deferred so nothing runs eagerly:

```python
        async def run_fn(i=i, testcase=testcase, output_path=output_path, entry=entry):
            if gate is not None and gate.is_skipped(entry.group_entry.group):
                return _skipped_evaluation(solution, entry, testcase, i)
            evaluation = await run_solution_on_testcase(...)  # unchanged
            if gate is not None and abort_on is not None:
                group = _find_group(skeleton_groups, entry.group_entry.group)
                context = AbortContext(
                    solution=solution,
                    group=group,
                    entry=entry.group_entry,
                    expected_outcome=solution.outcome,
                    group_expected_outcome=(solution.outcomePerGroup or {}).get(group.name),
                    evaluation=evaluation,
                )
                if abort_on(context):
                    gate.trip(group.name)
            return evaluation
```

`_run_solution` will need the group skeletons (or the single `GroupSkeleton`
for this call) passed in -- add a parameter rather than reaching for package
state. Verify the exact name of the per-group expectation accessor on
`Solution` (`outcomePerGroup`) before writing it.

4. `_skipped_evaluation` builds a real `Evaluation`, never `None`:

```python
def _skipped_evaluation(solution, entry, testcase, index: int) -> Evaluation:
    return Evaluation(
        result=CheckerResult(
            outcome=Outcome.SKIPPED,
            message='Skipped: an earlier testcase already decided this run.',
        ),
        testcase=TestcaseIO(
            index=index, input=testcase.inputPath, output=testcase.outputPath
        ),
        # No time/memory: this never ran, and the timing consumers must not
        # read a 0 out of it.
        log=TestcaseLog(time=None, wall_time=None, memory=None),
    )
```

**Step 4:** Run → PASS. Then `uv run pytest tests/rbx/box/solutions_test.py -v`
to confirm no regression, and confirm the spy shows fewer sandbox runs.

**Step 5: Commit**

```
feat(solutions): let callers abort a solution's remaining tests
```

---

## Task 6: Persist skipped `.eval` artifacts

`rbx ui` reads `.eval` files off disk, not `StructuredEvaluation`
(`rbx/box/ui/utils/run_ui.py:58-66`), and treats a missing file as "never ran".
Without this the whole solution renders `INCOMPLETE`.

**Files:**
- Modify: `rbx/box/tasks.py:139-147` (extract the path helper), `rbx/box/solutions.py`
- Test: `tests/rbx/box/solutions_test.py`

**Step 1: Write the failing test**

```python
async def test_skipped_testcase_writes_a_readable_eval_artifact(...):
    # after a run that aborts
    path = skeleton.get_solution_entry_prefix(solution, entry).with_suffix('.eval')
    assert path.is_file()
    assert utils.model_from_yaml(Evaluation, path.read_text()).result.outcome == Outcome.SKIPPED
```

**Step 2:** Run → FAIL, file missing.

**Step 3: Implement**

`tasks.py` computes `eval_path` inline in two places (`:147`, `:302`).
Extract a single helper so the skipped path cannot drift from the real one:

```python
def get_eval_path(output_dir, testcase, filestem: Optional[str] = None) -> pathlib.Path:
    ...
```

Use it at `:147`, `:302`, and from `_skipped_evaluation`, writing with
`model_to_yaml` exactly as `tasks.py:199` does. Set
`log.eval_absolute_path` on the skipped evaluation, matching `:194`.

**Verify first:** confirm `SolutionSkeleton.get_entry_prefix`
(`solutions.py:110`) yields the same stem `tasks.py` writes -- see the comment
at `solutions.py:155`. If they differ, use whichever the TUI reads.

**Step 4:** Run → PASS.

**Step 5: Commit**

```
feat(solutions): persist skipped evaluations to disk
```

---

## Task 7: Reporters render `SKIPPED`

**Files:**
- Modify: `rbx/box/solutions.py:2143` (`_render_detailed_group_table`), `:2475`
  (`LiveRunReporter`)
- Test: `tests/rbx/box/solutions_test.py`

Nothing is `None` any more, so the detailed renderer's
`if eval is None or eval.peek() is None` path is not hit and the live
reporter's counters advance normally. **Verify this by test rather than
assuming**, since a frozen `i/..` (indistinguishable from "still running") was
the failure mode we designed against.

**Step 1:** Write a test asserting the detailed table cell for a skipped
testcase shows the `SKIPPED` markup and not `'...'`, and that the live
reporter's `post_evaluated` advances past a skipped test.

**Step 2:** Run → observe the actual behavior; if it already passes, note that
in the commit and move on (no change needed beyond Task 3's styling).

**Step 3-4:** Implement only what the test demands.

**Step 5: Commit**

```
test(solutions): cover reporting of skipped testcases
```

---

## Task 8: Timing consumers ignore skipped evaluations

**This is the trap.** `_diagnose_inference_run` classifies an upper-bound
solution with any non-AC, non-slow outcome as a **fatal** `failed_upper`.
`SKIPPED` is both, so without this guard every abort becomes a hard error.

**Files:**
- Modify: `rbx/box/timing.py:604` (`_timings_per_language`), `:816`
  (`_diagnose_inference_run`), `rbx/box/solutions.py:1984` (`_print_timing`)
- Test: `tests/rbx/box/timing_test.py`

**Step 1: Write the failing tests**

```python
def test_skipped_evaluations_do_not_fail_an_upper_bound_solution():
    # upper solution with evals [AC, TLE, SKIPPED, SKIPPED]
    diagnosis = await _diagnose_inference_run(result)
    assert diagnosis.failed_upper == []
    assert <solution> in diagnosis.dropped_upper


def test_skipped_evaluations_contribute_no_timing():
    # the solution's measured time ignores skipped evals entirely
```

**Step 2:** Run → FAIL: the solution appears in `failed_upper`.

**Step 3: Implement** -- skip `Outcome.SKIPPED` evaluations in all three
functions, with a comment saying why (a skipped test is not evidence of a
failure; it is the *consequence* of one).

**Step 4:** Run → PASS, plus the full `tests/rbx/box/timing_test.py`.

**Step 5: Commit**

```
fix(timing): do not treat skipped evaluations as upper-bound failures
```

---

## Task 9: Abort during time-limit inference

**Files:**
- Modify: `rbx/box/timing.py:1044-1060` (`_run_for_inference`)
- Test: `tests/rbx/box/timing_test.py`

**Step 1: Write the failing test** -- with a cap active and a solution that
hits it, assert `run_solution_on_testcase` is invoked once for that solution
and that the estimated limit is unchanged versus the no-abort behavior.

**Step 2:** Run → FAIL (invoked once per testcase).

**Step 3: Implement**

```python
        result = await run_solutions(
            ...,
            # A solution killed at the cap has its measurement dropped either
            # way, so its remaining tests only cost wall clock.
            abort_on=(
                (lambda ctx: ctx.evaluation.result.outcome.is_slow())
                if cap is not None
                else None
            ),
        )
```

**Step 4:** Run → PASS.

**Step 5: Commit**

```
feat(timing): stop running a solution once it hits the inference timeout
```

---

## Task 10: TUI renders `SKIPPED`

**Files:**
- Modify: `rbx/box/ui/utils/run_ui.py:195-238`,
  `rbx/box/ui/screens/run_test_explorer.py:117-124,199-205`
- Test: `tests/rbx/box/ui/` (follow the existing pattern there)

With Task 6 the `.eval` exists, so the TUI takes its normal path and should
render `SKIPPED` via the styling from Task 3. Verify with a test; a skipped
test must still count as not-AC under the "failing only" filter.

**Step 5: Commit**

```
feat(ui): render skipped testcases
```

---

## Task 11: End-to-end scenario

**Files:**
- Create: `tests/e2e/<fixture>/e2e.rbx.yml` (see `tests/e2e/README.md`)

A package with a hopeless slow solution and a small `inferenceTimeout`: the
estimate matches the pre-abort behavior, and the run is dramatically shorter.
Run with `mise run test-e2e`.

**Step 5: Commit**

```
test(e2e): cover aborting a solution at the inference timeout
```

---

## Final verification

1. `uv run ruff check . && uv run ruff format --check .`
2. `uv run pytest --ignore=tests/rbx/box/cli -n auto`
3. `mise run test-e2e`
4. Compare against the **known pre-existing local failures** recorded in
   memory (C++/sandbox/docker, `walltime_test` 2500 vs 3000,
   `test_header.py::TestGroupVars`, `completion/drift_test`, ~7 e2e). Do not
   claim a clean run without diffing against the base commit's failures.
5. Open the PR against `worktree-kattis-timing-multipliers-design` (**not**
   `main`) so it stays stacked on #643.
