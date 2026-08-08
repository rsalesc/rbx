# Per-group expected outcomes for solutions — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let a solution declare an expected outcome per testcase group via a new
`outcomePerGroup` field, and surface per-group expectation results in the run
report.

**Architecture:** `Solution.outcome` keeps its exact current meaning — one
expectation checked against all evaluations pooled together.
`Solution.outcomePerGroup` adds an **independent second layer**: a map from
top-level group name to `ExpectedOutcome`, with a reserved `'*'` key acting as
the default for every group individually. Both layers must hold. In
`rbx/box/solutions.py`, `_get_verdict_report` is already parameterized by an
expectation, so the work is calling it per group, carrying the results on
`SolutionOutcomeReport`, and rendering them.

**Design doc:** [`docs/plans/2026-08-07-per-group-expected-outcome-design.md`](2026-08-07-per-group-expected-outcome-design.md)

**Tech Stack:** Python 3.14, Pydantic v2, Rich (console markup), pytest +
pytest-asyncio, ruff (single quotes, absolute imports only).

**Conventions you must follow:**
- Single quotes for strings. Absolute imports only — relative imports are banned.
- Run `uv run ruff format .` and `uv run ruff check --fix .` before every commit.
- Commits follow Conventional Commits (commitizen pre-commit hook rejects
  otherwise). Read `.claude/skills/commit.md` and use the `/commit` skill.
- **Known-bad locally:** C++ checker/validator/sandbox/docker tests fail on this
  machine for unrelated reasons. Do not chase them; only run the test files this
  plan names.

---

### Task 0: Read the ground you are standing on

No code. Read these before touching anything, they are the whole surface area:

- `rbx/box/schema.py:84-232` — the `ExpectedOutcome` enum. Note `match()`,
  `get_matches()`, `intersect()`, `is_slow()`, `matches_tle_and_is_incorrect()`,
  and that `__str__` returns `.name` (via `rbx/autoenum.py:109`), so
  `f'{outcome}'` renders `TIME_LIMIT_EXCEEDED`.
- `rbx/box/schema.py:589-628` — the `Solution` model.
- `rbx/box/schema.py:1005-1090` — the `Package` `model_validator`s
  (`check_scoring_fields`, `check_deps`) you will add siblings to.
- `rbx/box/solutions.py:1296-1420` — `SolutionOutcomeStatus`,
  `SolutionOutcomeReport`, `VerdictReport`.
- `rbx/box/solutions.py:1422-1636` — `_get_verdict_report`,
  `_get_evals_per_group`, `get_solution_outcome_report`. This is the core.
- `rbx/box/solutions.py:2212-2429` — the three reporters
  (`FullRunReporter`, `LiveRunReporter`, `SingleSolutionRunReporter`) and their
  three near-identical `render_group_end` bodies.
- `tests/rbx/box/solutions_test.py:128-350` — the `mock_skeleton` /
  `make_evaluation` unit-test harness you will extend.

Key facts that shape the implementation:

1. **Groups are top-level only.** `_get_report_skeleton` builds `GroupSkeleton`s
   from `pkg.testcases` (`rbx/box/solutions.py:494-505`); subgroup tests are
   folded into their parent group's entries. So map keys are top-level group
   names, `samples` included.
2. **`_get_evals_per_group` zips `evals` with `skeleton.entries`**
   (`rbx/box/solutions.py:1514`). It works even when `skeleton.groups` is empty,
   which is what the unit-test fixture does.
3. **Reporters call `get_solution_outcome_report` mid-run**, with only the evals
   collected so far. A group that has not run yet has zero evals — and a group
   with a *bad* expectation and zero evals would spuriously fail the "at least
   one bad verdict must exist" rule. Hence: **skip groups with no evals.**

---

### Task 1: `outcomePerGroup` field and resolution helpers

**Files:**
- Modify: `rbx/box/schema.py:589-628` (the `Solution` model)
- Test: `tests/rbx/box/test_schema.py` (append a new test class)

**Step 1: Write the failing tests**

Append to `tests/rbx/box/test_schema.py`:

```python
class TestSolutionOutcomePerGroup:
    def test_no_per_group_outcomes_resolves_to_none(self):
        from rbx.box.schema import ExpectedOutcome, Solution

        solution = Solution(path='sol.cpp', outcome=ExpectedOutcome.ACCEPTED)

        assert solution.outcomePerGroup == {}
        assert solution.expected_outcome_for_group('group1') is None
        assert solution.all_expected_outcomes() == {ExpectedOutcome.ACCEPTED}

    def test_explicit_group_takes_precedence_over_wildcard(self):
        from rbx.box.schema import ExpectedOutcome, Solution

        solution = Solution(
            path='sol.cpp',
            outcome=ExpectedOutcome.INCORRECT,
            outcomePerGroup={
                '*': ExpectedOutcome.ACCEPTED,
                'group3': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
            },
        )

        assert (
            solution.expected_outcome_for_group('group3')
            == ExpectedOutcome.TIME_LIMIT_EXCEEDED
        )
        # Everything else, samples included, falls back to the wildcard.
        assert (
            solution.expected_outcome_for_group('samples')
            == ExpectedOutcome.ACCEPTED
        )
        assert (
            solution.expected_outcome_for_group('group1') == ExpectedOutcome.ACCEPTED
        )
        assert solution.all_expected_outcomes() == {
            ExpectedOutcome.INCORRECT,
            ExpectedOutcome.ACCEPTED,
            ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        }

    def test_without_wildcard_unlisted_groups_have_no_expectation(self):
        from rbx.box.schema import ExpectedOutcome, Solution

        solution = Solution(
            path='sol.cpp',
            outcome=ExpectedOutcome.INCORRECT,
            outcomePerGroup={'group2': ExpectedOutcome.WRONG_ANSWER},
        )

        assert (
            solution.expected_outcome_for_group('group2')
            == ExpectedOutcome.WRONG_ANSWER
        )
        assert solution.expected_outcome_for_group('group1') is None

    def test_outcome_names_are_parsed_from_yaml_aliases(self):
        from rbx.box.schema import ExpectedOutcome, Solution

        solution = Solution.model_validate(
            {'path': 'sol.cpp', 'outcome': 'incorrect', 'outcomePerGroup': {'*': 'ac', 'g': 'tle'}}
        )

        assert solution.outcomePerGroup == {
            '*': ExpectedOutcome.ACCEPTED,
            'g': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        }
```

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_schema.py::TestSolutionOutcomePerGroup -v`
Expected: FAIL — `Solution` has `extra='forbid'`, so
`outcomePerGroup` is rejected with "Extra inputs are not permitted", and
`expected_outcome_for_group` does not exist.

**Step 3: Implement**

In `rbx/box/schema.py`, inside `class Solution(CodeItem)`, right after the
existing `outcome` field, add the constant and the field:

```python
PER_GROUP_OUTCOME_WILDCARD = '*'
```

Put that module-level constant next to the other module-level definitions (above
`class Solution`), then in the model:

```python
    outcomePerGroup: Dict[str, ExpectedOutcome] = Field(
        default={},
        description="""The expected outcome of this solution for each testcase group,
keyed by group name.

The reserved key `*` sets a default that applies to every group *individually*.
An entry for a specific group takes precedence over `*`. Groups that match
neither are not checked individually.

This is an extra layer of expectations, checked *in addition* to `outcome`:
`outcome` keeps being matched against the whole testset at once, while each
entry here is matched against that group's tests alone. A solution fails if
either layer fails.

```yaml
solutions:
  - path: 'sols/partial.cpp'
    outcome: incorrect  # fails somewhere in the testset
    outcomePerGroup:
      '*': accepted     # ...but is correct on every group
      group3: tle       # ...except group3, where it must time out
```
""",
    )

    def expected_outcome_for_group(self, group: str) -> Optional[ExpectedOutcome]:
        """The expectation for a single group, or None if the group has none."""
        if group in self.outcomePerGroup:
            return self.outcomePerGroup[group]
        return self.outcomePerGroup.get(PER_GROUP_OUTCOME_WILDCARD)

    def all_expected_outcomes(self) -> Set[ExpectedOutcome]:
        """Every expectation this solution declares, pooled and per-group.

        Consumers that ask a coarse question about a solution ("is it expected
        to be slow?") must consider all of them, not just ``outcome``.
        """
        return {self.outcome} | set(self.outcomePerGroup.values())
```

Check the imports at the top of `schema.py`: `Dict`, `Optional` and `Set` must
all be imported from `typing` (add whichever is missing).

**Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_schema.py::TestSolutionOutcomePerGroup -v`
Expected: 4 passed.

**Step 5: Verify nothing else broke**

Run: `uv run pytest tests/rbx/box/test_schema.py tests/rbx/box/test_yaml_validation.py -q`
Expected: all pass.

**Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/schema.py tests/rbx/box/test_schema.py
git commit -m "feat(schema): add Solution.outcomePerGroup with a '*' default"
```

---

### Task 2: Package-level validation

Group names only exist at `Package` level, so these are `Package`
`model_validator(mode='after')` methods, alongside `check_deps`.

**Files:**
- Modify: `rbx/box/schema.py` (`Package`, after `check_deps`)
- Test: `tests/rbx/box/test_schema.py`

**Step 1: Write the failing tests**

```python
class TestPackageOutcomePerGroupValidation:
    def _package(self, **solution_kwargs):
        from rbx.box.schema import Package, Solution, TestcaseGroup

        return Package(
            name='p',
            timeLimit=1000,
            memoryLimit=256,
            testcases=[
                TestcaseGroup(name='samples'),
                TestcaseGroup(name='group1'),
                TestcaseGroup(name='group2'),
            ],
            solutions=[
                Solution(path='sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED),
                Solution(path='sols/other.cpp', **solution_kwargs),
            ],
        )

    def test_unknown_group_key_is_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match='typo'):
            self._package(
                outcome=ExpectedOutcome.INCORRECT,
                outcomePerGroup={'typo': ExpectedOutcome.WRONG_ANSWER},
            )

    def test_known_group_and_wildcard_keys_are_accepted(self):
        package = self._package(
            outcome=ExpectedOutcome.INCORRECT,
            outcomePerGroup={
                '*': ExpectedOutcome.ACCEPTED,
                'samples': ExpectedOutcome.ACCEPTED,
                'group2': ExpectedOutcome.WRONG_ANSWER,
            },
        )

        assert len(package.solutions) == 2

    def test_main_solution_cannot_expect_a_non_ac_group(self):
        from pydantic import ValidationError

        from rbx.box.schema import Package, Solution, TestcaseGroup

        with pytest.raises(ValidationError, match='first solution'):
            Package(
                name='p',
                timeLimit=1000,
                memoryLimit=256,
                testcases=[TestcaseGroup(name='samples'), TestcaseGroup(name='group1')],
                solutions=[
                    Solution(
                        path='sols/main.cpp',
                        outcome=ExpectedOutcome.ACCEPTED,
                        outcomePerGroup={'group1': ExpectedOutcome.WRONG_ANSWER},
                    ),
                ],
            )

    def test_group_expectation_contradicting_the_pooled_one_is_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match='cannot be satisfied'):
            # Pooled ACCEPTED forbids any bad verdict, group2 demands a WA.
            self._package(
                outcome=ExpectedOutcome.ACCEPTED,
                outcomePerGroup={'group2': ExpectedOutcome.WRONG_ANSWER},
            )

    def test_all_groups_accepted_contradicts_a_bad_pooled_outcome(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match='cannot be satisfied'):
            # Every group must be fully AC, yet the testset must fail somewhere.
            self._package(
                outcome=ExpectedOutcome.INCORRECT,
                outcomePerGroup={'*': ExpectedOutcome.ACCEPTED},
            )

    def test_compatible_layers_are_accepted(self):
        package = self._package(
            outcome=ExpectedOutcome.INCORRECT,
            outcomePerGroup={'*': ExpectedOutcome.ACCEPTED, 'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
        )

        assert package.solutions[1].outcomePerGroup['group2'] == (
            ExpectedOutcome.TIME_LIMIT_EXCEEDED
        )
```

Make sure `ExpectedOutcome` is imported at the top of the test module (the file
currently imports only `LimitsProfile`/`LimitModifiers`; other classes there
import inside the test bodies — follow whichever style the file already uses in
the neighbouring classes).

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/test_schema.py::TestPackageOutcomePerGroupValidation -v`
Expected: FAIL — nothing validates yet, so the `pytest.raises` cases fail with
"DID NOT RAISE".

**Step 3: Implement**

In `rbx/box/schema.py`, add to `Package` after `check_deps`:

```python
    @model_validator(mode='after')
    def check_outcome_per_group(self):
        group_names = set(group.name for group in self.testcases)
        for solution in self.solutions:
            for group_name in solution.outcomePerGroup:
                if group_name == PER_GROUP_OUTCOME_WILDCARD:
                    continue
                if group_name not in group_names:
                    raise PydanticCustomError(
                        'UNKNOWN_OUTCOME_GROUP',
                        'Solution "{path}" declares an expected outcome for group '
                        '"{group}", which is not a testcase group of this package.',
                        {'path': str(solution.path), 'group': group_name},
                    )
        return self

    @model_validator(mode='after')
    def check_outcome_per_group_is_satisfiable(self):
        for solution in self.solutions:
            if not solution.outcomePerGroup:
                continue
            for group_name, expected in solution.outcomePerGroup.items():
                if expected.match(Outcome.ACCEPTED):
                    # The group admits a fully accepted run, which never
                    # conflicts with the pooled expectation.
                    continue
                # The group demands a bad verdict; the pooled expectation must
                # admit at least one of the verdicts that would satisfy it.
                if not solution.outcome.intersect(expected):
                    raise PydanticCustomError(
                        'CONTRADICTORY_OUTCOME',
                        'Solution "{path}" expects "{expected}" on "{group}", which '
                        'cannot be satisfied together with the expected outcome '
                        '"{outcome}" for the whole testset.',
                        {
                            'path': str(solution.path),
                            'expected': expected.name,
                            'group': group_name,
                            'outcome': solution.outcome.name,
                        },
                    )

            if solution.outcome.match(Outcome.ACCEPTED):
                continue
            # The pooled expectation demands a bad verdict *somewhere*. If every
            # group is individually pinned to an outcome that admits none, there
            # is nowhere for it to happen.
            resolved = [
                solution.expected_outcome_for_group(group.name)
                for group in self.testcases
            ]
            if any(expected is None for expected in resolved):
                continue
            has_room = False
            for expected in resolved:
                assert expected is not None
                for verdict in expected.get_matches():
                    if verdict == Outcome.ACCEPTED:
                        continue
                    if solution.outcome.match(verdict):
                        has_room = True
            if not has_room:
                raise PydanticCustomError(
                    'CONTRADICTORY_OUTCOME',
                    'Solution "{path}" expects "{outcome}" for the whole testset, '
                    'but every group is pinned to an outcome that cannot produce '
                    'it, so the expectation cannot be satisfied.',
                    {'path': str(solution.path), 'outcome': solution.outcome.name},
                )
        return self

    @model_validator(mode='after')
    def check_main_solution_outcome_per_group(self):
        if not self.solutions:
            return self
        main = self.solutions[0]
        for group_name, expected in main.outcomePerGroup.items():
            if not expected.match(Outcome.ACCEPTED):
                raise PydanticCustomError(
                    'MAIN_SOLUTION_NOT_ACCEPTED',
                    'The first solution in the package generates the reference '
                    'outputs, so it must be accepted everywhere, but it expects '
                    '"{expected}" on "{group}".',
                    {'expected': expected.name, 'group': group_name},
                )
        return self
```

`Outcome` is already imported in `schema.py` (it is used at line 1016);
`PydanticCustomError` and `model_validator` are already imported too.

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/test_schema.py -v -k OutcomePerGroup`
Expected: all pass.

**Step 5: Verify no existing package trips the new validators**

Run: `uv run pytest tests/rbx/box/test_schema.py tests/rbx/box/test_yaml_validation.py tests/rbx/box/test_package_loading.py tests/rbx/box/presets -q`
Expected: all pass.

**Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/schema.py tests/rbx/box/test_schema.py
git commit -m "feat(schema): validate outcomePerGroup group names and satisfiability"
```

---

### Task 3: Per-group verdict reports in `get_solution_outcome_report`

The heart of the change. Also fixes a live bug.

**Files:**
- Modify: `rbx/box/solutions.py:1308-1325` (`SolutionOutcomeReport` fields)
- Modify: `rbx/box/solutions.py:1545-1636` (`get_solution_outcome_report`)
- Test: `tests/rbx/box/solutions_test.py`

**Step 1: Extend the unit-test harness**

`mock_skeleton` (`tests/rbx/box/solutions_test.py:151-175`) puts every entry in a
single group named `test`. Give it an optional per-group spec, keeping the
existing signature working:

```python
@pytest.fixture
def mock_skeleton(tmp_path, mock_limits):
    """Create a minimal skeleton for testing."""

    def _create_skeleton(
        solutions: List[Solution],
        num_entries: int = 5,
        entries_per_group: Optional[Dict[str, int]] = None,
        scores_per_group: Optional[Dict[str, int]] = None,
    ) -> SolutionReportSkeleton:
        if entries_per_group is None:
            entries_per_group = {'test': num_entries}
        entries = [
            make_generation_entry(group, i, tmp_path)
            for group, count in entries_per_group.items()
            for i in range(count)
        ]
        groups = [
            GroupSkeleton(
                name=group,
                score=(scores_per_group or {}).get(group, 0),
                deps=[],
                testcases=[
                    entry.metadata.copied_to
                    for entry in entries
                    if entry.group_entry.group == group
                ],
            )
            for group in entries_per_group
        ]
        return SolutionReportSkeleton(
            solutions=[
                SolutionSkeleton(**sol.model_dump(), runs_dir=tmp_path / f'run_{i}')
                for i, sol in enumerate(solutions)
            ],
            entries=entries,
            groups=groups,
            limits={'cpp': mock_limits},
            compiled_solutions={
                str(sol.path): f'digest_{i}' for i, sol in enumerate(solutions)
            },
            verification=VerificationLevel.FULL,
        )

    return _create_skeleton
```

Note this now populates `groups` where it used to pass `[]`. Add `Dict` to the
module's `typing` imports.

**Step 2: Run the existing tests to confirm the harness change is safe**

Run: `uv run pytest tests/rbx/box/solutions_test.py -q -k "not test_solutions and not test_get_solution_outcome_report"`
Expected: all pass (the two excluded tests need a real package and are slow /
compile C++; run them only in CI).

**Step 3: Write the failing tests**

```python
def test_per_group_outcome_fails_while_pooled_outcome_passes(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """group2 is expected to TLE but is fully accepted: the solution fails even
    though the pooled INCORRECT expectation is satisfied by group1's WA."""
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton(
        [solution], entries_per_group={'group1': 2, 'group2': 2}
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    assert report.pooledStatus == SolutionOutcomeStatus.OK
    assert report.failedGroups == ['group2']
    assert set(report.perGroup) == {'group2'}
    assert report.perGroup['group2'] == GroupOutcomeReport(
        expectedOutcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        gotVerdicts={Outcome.ACCEPTED},
        status=SolutionOutcomeStatus.UNEXPECTED_VERDICTS,
        runUnderDoubleTl=False,
        doubleTlVerdicts=set(),
    )


def test_per_group_outcome_all_satisfied(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            '*': ExpectedOutcome.ACCEPTED,
            'group2': ExpectedOutcome.WRONG_ANSWER,
        },
    )
    skeleton = mock_skeleton(
        [solution], entries_per_group={'group1': 2, 'group2': 2}
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.ACCEPTED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.failedGroups == []
    # The wildcard covers group1 too.
    assert {
        name: group.expectedOutcome for name, group in report.perGroup.items()
    } == {
        'group1': ExpectedOutcome.ACCEPTED,
        'group2': ExpectedOutcome.WRONG_ANSWER,
    }


def test_wildcard_expectation_is_checked_per_group(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """'*': wa demands a WA in EVERY group; group1 being clean is a failure."""
    solution = Solution(
        path=tmp_path / 'wa.cpp',
        outcome=ExpectedOutcome.WRONG_ANSWER,
        outcomePerGroup={'*': ExpectedOutcome.WRONG_ANSWER},
    )
    skeleton = mock_skeleton(
        [solution], entries_per_group={'group1': 2, 'group2': 2}
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.WRONG_ANSWER),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    assert report.failedGroups == ['group1']


def test_groups_without_evaluations_are_not_checked(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Mid-run, later groups have no evals yet. A bad expectation on them must
    not fail the report, or the live reporters would flash spurious failures."""
    solution = Solution(
        path=tmp_path / 'tle.cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        outcomePerGroup={'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton(
        [solution], entries_per_group={'group1': 2, 'group2': 2}
    )
    # Only group1 has run.
    evals = [make_evaluation(Outcome.ACCEPTED), make_evaluation(Outcome.ACCEPTED)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert 'group2' not in report.perGroup
    assert report.failedGroups == []


def test_report_evals_are_not_clobbered_by_the_per_group_loop(tmp_path, mock_skeleton):
    """Regression: the POINTS loop used to rebind `evals`, so the report's
    Time/Memory line only saw the last group's evaluations."""
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'group1': 2, 'group2': 2},
        scores_per_group={'group1': 50, 'group2': 50},
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=900),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
    ]

    with patch(
        'rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS
    ):
        report = get_solution_outcome_report(
            solution, skeleton, evals, VerificationLevel.FULL
        )

    # The report must carry every eval, not just the last group's -- the first
    # one, deliberately the slowest, is what the Time line reports.
    assert report.evals == evals
    assert report.evals[0].log is not None
    assert report.evals[0].log.time == 0.9
    assert report.gotScore == 100
```

Also cover, in the same file: that a solution with **no** `outcomePerGroup` gets
`perGroup == {}`, `failedGroups == []` and `status == pooledStatus` (the
neutrality guarantee); the mirror of the first test (pooled fails while every
group passes); and per-group double TL, asserting both `runUnderDoubleTl` and
`doubleTlVerdicts` on the records and that the aggregate is their union.

**Step 4: Run to verify failure**

Run: `uv run pytest tests/rbx/box/solutions_test.py -v -k "per_group or wildcard or clobbered"`
Expected: FAIL — `pooledStatus` / `failedGroups` / `perGroup` don't exist, and
`report.evals` has length 2 in the last test.

**Step 5: Implement — new report fields**

Next to `SolutionOutcomeReport`, add one record per group:

```python
class GroupOutcomeReport(BaseModel):
    """How one testcase group fared against its own expected outcome."""

    expectedOutcome: ExpectedOutcome
    gotVerdicts: Set[Outcome]
    status: SolutionOutcomeStatus
    runUnderDoubleTl: bool
    doubleTlVerdicts: Set[Outcome]
```

and in `SolutionOutcomeReport` (`rbx/box/solutions.py:1308`), after
`expectedOutcome`/`gotVerdicts` (which stay the *pooled* layer's values):

```python
    # Status of the pooled ``outcome`` layer on its own.
    pooledStatus: SolutionOutcomeStatus
    # Only groups that carry an expectation AND were evaluated appear here, in
    # testset order.
    perGroup: Dict[str, GroupOutcomeReport] = {}

    @property
    def failedGroups(self) -> List[str]:
        return [
            name for name, report in self.perGroup.items() if not report.status.ok()
        ]
```

`pooledStatus` is required, not defaulted: a forgotten default would silently
claim the pooled layer passed. `failedGroups` is a derived property so it cannot
drift from the per-group statuses. There is no `doubleTlGroups` summary —
consumers read `perGroup`, since "passed within 2x TL" and "had other soft-TLE
verdicts" are different conditions and a name list conflates them. Give
`SolutionOutcomeReport` a class docstring naming the two layers and explaining
why only `status` is prefixed as `pooledStatus`.

**Step 6: Implement — rewrite `get_solution_outcome_report`**

Replace the body from the `verdict_report = ...` line through the `return` with:

```python
    verdict_report = _get_verdict_report(
        skeleton, evals, solution, solution.outcome, subset, verification
    )
    pooled_status = (
        SolutionOutcomeStatus.OK
        if verdict_report.ok
        else SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    )
    message: Optional[Tuple[GenerationTestcaseEntry, str]] = None
    for eval, entry in zip(evals, skeleton.entries):
        if eval.result.outcome in [
            Outcome.WRONG_ANSWER,
            Outcome.JUDGE_FAILED,
        ]:
            message = (entry, eval.result.message)
            break

    evals_per_group = _get_evals_per_group(evals, skeleton)

    # Per-group expectation layer, for groups that both carry an expectation and
    # have at least one evaluation. The empty-evals guard only keeps a group that
    # has not started from failing the "at least one bad verdict must exist"
    # rule; a partially evaluated group IS checked, so per-group status is only
    # meaningful once the group is complete and should be rendered at group end.
    per_group_expectation_reports: Dict[str, VerdictReport] = {
        name: _get_verdict_report(
            skeleton, group_evals, solution, expected, subset, verification
        )
        for name, group_evals in evals_per_group.items()
        if group_evals
        and (expected := solution.expected_outcome_for_group(name)) is not None
    }
    per_group = {
        name: GroupOutcomeReport(
            expectedOutcome=report.expected_outcome,
            gotVerdicts=report.got_verdicts,
            status=SolutionOutcomeStatus.OK
            if report.ok
            else SolutionOutcomeStatus.UNEXPECTED_VERDICTS,
            runUnderDoubleTl=report.run_under_double_tl,
            doubleTlVerdicts=report.double_tl_verdicts,
        )
        for name, report in per_group_expectation_reports.items()
    }
    failed_groups = [
        name for name, report in per_group.items() if not report.status.ok()
    ]

    has_unmatched_slow_verdict = verdict_report.has_unmatched_slow_verdict() or any(
        report.has_unmatched_slow_verdict()
        for report in per_group_expectation_reports.values()
    )
    status = (
        SolutionOutcomeStatus.OK
        if pooled_status.ok() and not failed_groups
        else SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    )

    run_under_double_tl = verdict_report.run_under_double_tl or any(
        report.run_under_double_tl
        for report in per_group_expectation_reports.values()
    )
    double_tl_verdicts = set(verdict_report.double_tl_verdicts)
    for report in per_group_expectation_reports.values():
        double_tl_verdicts |= report.double_tl_verdicts

    max_score = 0
    got_score = 0
    got_score_per_group = {}
    if scoring == ScoreType.POINTS:
        # ``passed()`` only inspects bad verdicts, never the expectation, so a
        # report computed for the per-group layer is reusable here as-is.
        verdict_report_per_group: Dict[str, VerdictReport] = {}
        for group in skeleton.groups:
            max_score += group.score
            group_report = per_group_expectation_reports.get(group.name)
            if group_report is None:
                group_report = _get_verdict_report(
                    skeleton,
                    evals_per_group.get(group.name, []),
                    solution,
                    solution.outcome,
                    subset,
                    verification,
                )
                has_unmatched_slow_verdict = (
                    has_unmatched_slow_verdict
                    or group_report.has_unmatched_slow_verdict()
                )
            verdict_report_per_group[group.name] = group_report

        def _check_deps(group: GroupSkeleton):
            for dep in group.deps:
                dep_group = skeleton.find_group_skeleton(dep)
                if dep_group is None:
                    return False
                if not _check_deps(dep_group):
                    return False
            return verdict_report_per_group[group.name].passed()

        for group in skeleton.groups:
            if _check_deps(group):
                got_score += group.score
                got_score_per_group[group.name] = group.score

        if expected_score is not None and not fulfills_expected_score(
            expected_score, got_score
        ):
            status = SolutionOutcomeStatus.UNEXPECTED_SCORE

    limits = skeleton.get_solution_limits(solution)
    if limits.profile is None and has_unmatched_slow_verdict:
        issue_stack.add_issue(TimingIssue())

    return SolutionOutcomeReport(
        solution=solution,
        limits=limits,
        evals=evals,
        status=status,
        pooledStatus=pooled_status,
        message=message,
        expectedOutcome=verdict_report.expected_outcome,
        gotVerdicts=verdict_report.got_verdicts,
        perGroup=per_group,
        expectedScore=expected_score,
        gotScore=got_score,
        gotScorePerGroup=got_score_per_group,
        maxScore=max_score,
        runUnderDoubleTl=run_under_double_tl,
        doubleTlVerdicts=double_tl_verdicts,
        sanitizerWarnings=verdict_report.has_sanitizer_warnings,
        verification=verification,
        scoring=scoring,
    )
```

Three things to notice about this rewrite:
1. The old code shadowed the `evals` parameter inside the POINTS loop
   (`evals = evals_per_group.get(...)`), which is why `report.evals` was wrong.
   Nothing rebinds `evals` any more.
2. `evals_per_group` is now computed unconditionally, for both layers.
3. `_get_evals_per_group` returns a plain dict built in entry order, so
   `perGroup` -- and therefore `failedGroups` -- comes out in testset order.

**Step 7: Run to verify pass**

Run: `uv run pytest tests/rbx/box/solutions_test.py -v -k "per_group or wildcard or clobbered"`
Expected: all pass.

**Step 8: Run the whole non-compiling test file plus the UI consumer's tests**

Run: `uv run pytest tests/rbx/box/solutions_test.py tests/rbx/box/ui -q -k "not test_solutions and not test_get_solution_outcome_report"`
Expected: all pass. (`rbx/box/ui/utils/run_ui.py` constructs
`SolutionOutcomeReport`s through this function, so a missing default would break
here.)

**Step 9: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/solutions.py tests/rbx/box/solutions_test.py
git commit -m "$(cat <<'EOF'
feat(solutions): check expected outcomes per testcase group

Adds a per-group expectation layer to the solution outcome report, checked
independently of the pooled `outcome`. Also stops the POINTS scoring loop from
rebinding `evals`, which made the report's Time/Memory line reflect only the
last group.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Verdict markup — attribute failures to groups

**Files:**
- Modify: `rbx/box/solutions.py:1326-1394` (`get_verdict_markup`,
  `get_verdict_markup_with_warnings`)
- Test: `tests/rbx/box/solutions_test.py`

**Step 1: Write the failing tests**

```python
def test_verdict_markup_attributes_failure_to_the_group(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 1, 'group2': 1})
    evals = [make_evaluation(Outcome.WRONG_ANSWER), make_evaluation(Outcome.ACCEPTED)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )
    markup = report.get_verdict_markup()

    assert 'FAILED' in markup
    assert 'group2' in markup
    assert 'TIME_LIMIT_EXCEEDED' in markup
    assert 'ACCEPTED' in markup
    # The pooled layer passed, so it must not be reported as the culprit.
    assert 'Expected: INCORRECT' not in markup


def test_verdict_markup_lists_every_failed_group(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            '*': ExpectedOutcome.ACCEPTED,
            'group2': ExpectedOutcome.WRONG_ANSWER,
        },
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 1, 'group2': 1})
    # group1 was supposed to be clean, group2 was supposed to fail.
    evals = [make_evaluation(Outcome.WRONG_ANSWER), make_evaluation(Outcome.ACCEPTED)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )
    markup = report.get_verdict_markup()

    assert markup.count('FAILED') == 2
    assert 'group1' in markup and 'group2' in markup


def test_verdict_markup_hides_group_lines_when_incomplete(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 1, 'group2': 1})
    evals = [make_evaluation(Outcome.WRONG_ANSWER), make_evaluation(Outcome.ACCEPTED)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert 'group2' not in report.get_verdict_markup(incomplete=True)
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/solutions_test.py -v -k verdict_markup`
Expected: FAIL — no group information in the markup, and `Expected: INCORRECT`
is currently printed even though the pooled layer passed.

**Step 3: Implement**

In `SolutionOutcomeReport`, add a private helper and rework
`get_verdict_markup`:

```python
    def _group_failure_lines(self) -> List[str]:
        lines = []
        for name, group in self.perGroup.items():
            if group.status.ok():
                continue
            got = ' '.join(sorted(v.name for v in group.gotVerdicts))
            line = (
                f'[item]{utils.escape_markup(name)}[/item]: '
                f'expected {group.expectedOutcome}'
            )
            if got:
                line += f', got: {got}'
            lines.append(line)
        return lines

    def get_verdict_markup(self, incomplete: bool = False, subset: bool = False) -> str:
        success_str = '[success]OK[/success] '
        if subset:
            success_str = ''
        if not self.status:
            success_str = '[ierror]FAILED[/ierror] '
        if incomplete:
            success_str = '[iwarning]INCOMPLETE[/iwarning] '

        gotVerdicts = self.gotVerdicts if not incomplete else {}

        got_verdict_names = ' '.join(v.name for v in self.gotVerdicts)
        verdict_str = ''
        if self.scoring == ScoreType.POINTS:
            if self.expectedScore is not None:
                verdict_str = (
                    f'Expected score {get_expected_score_markup(self.expectedScore)}, '
                    f'got {get_solution_score_markup(self.gotScore, self.maxScore, pts=True)}'
                )
            else:
                verdict_str = f'Got {get_solution_score_markup(self.gotScore, self.maxScore, pts=True)}'

        # Only speak for the pooled layer when the pooled layer is what failed;
        # otherwise "Expected: X" would accuse an expectation that was met.
        if (
            self.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
            and not self.pooledStatus.ok()
        ):
            if self.expectedOutcome != ExpectedOutcome.ANY:
                verdict_str = f'Expected: {self.expectedOutcome}'
                if gotVerdicts:
                    verdict_str += f', got: {got_verdict_names}'
            elif gotVerdicts:
                verdict_str = f'Got: {got_verdict_names}'

        group_lines = [] if incomplete else self._group_failure_lines()
        if not verdict_str and group_lines:
            # Fold the first group into the FAILED line instead of leaving it bare.
            verdict_str = group_lines.pop(0)
        res = f'{success_str}{verdict_str}'
        for line in group_lines:
            res += f'\n[ierror]FAILED[/ierror] {line}'
        return res
```

And name the groups in the double-TL warning, in
`get_verdict_markup_with_warnings`:

```python
        if self.runUnderDoubleTl:
            # Name only the groups that passed *within* 2x TL. Groups that had
            # other soft-TLE verdicts are reported by ``doubleTlVerdicts``
            # instead, and the two conditions are mutually exclusive per group.
            where = ''
            double_tl_groups = [
                name
                for name, group in self.perGroup.items()
                if group.runUnderDoubleTl
            ]
            if double_tl_groups:
                groups = ' '.join(
                    utils.escape_markup(name) for name in double_tl_groups
                )
                where = f' on [item]{groups}[/item]'
            if self.doubleTlVerdicts:
                res += f'\n[warning]WARNING[/warning] The solution still passed in double TL{where}, but failed with [item]{" ".join(v.name for v in self.doubleTlVerdicts)}[/item].'
            else:
                res += f'\n[warning]WARNING[/warning] The solution still passed in double TL{where}.'
```

`utils` is already imported in `solutions.py` (used at line 1393).

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/solutions_test.py -v -k "verdict_markup or per_group or wildcard"`
Expected: all pass.

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/solutions.py tests/rbx/box/solutions_test.py
git commit -m "feat(solutions): name the failing group in the outcome report"
```

---

### Task 5: Group-line rendering in the three reporters

**Files:**
- Modify: `rbx/box/solutions.py` — add a module-level helper near
  `get_solution_score_markup` (~line 1283), a method on
  `TraditionalRunReporter` (~line 2097), and the three `render_group_end` /
  `_update_live` bodies (lines 2239, 2323, 2390)
- Test: `tests/rbx/box/solutions_test.py`

**Step 1: Write the failing test**

```python
def test_group_expectation_markup(tmp_path, mock_skeleton, mock_binary_scoring):
    from rbx.box.solutions import get_group_expectation_markup

    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            '*': ExpectedOutcome.ACCEPTED,
            'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        },
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 1, 'group2': 1})
    evals = [make_evaluation(Outcome.ACCEPTED), make_evaluation(Outcome.ACCEPTED)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    # Met expectation: a check, no noise.
    assert '✓' in get_group_expectation_markup(report, 'group1')
    # Unmet: the expectation and what actually happened.
    unmet = get_group_expectation_markup(report, 'group2')
    assert '✗' in unmet
    assert 'TIME_LIMIT_EXCEEDED' in unmet
    assert 'ACCEPTED' in unmet
    # A group with no expectation renders nothing at all, so packages that do
    # not use outcomePerGroup look exactly as before.
    assert get_group_expectation_markup(report, 'nonexistent') == ''
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/solutions_test.py -v -k group_expectation_markup`
Expected: FAIL with ImportError on `get_group_expectation_markup`.

**Step 3: Implement the helper**

```python
def get_group_expectation_markup(
    report: SolutionOutcomeReport, group_name: str
) -> str:
    """Inline marker for a group that carries a per-group expectation.

    Returns the empty string when the group declares no expectation or was not
    evaluated, so group lines are untouched for packages that do not use
    ``outcomePerGroup``.
    """
    group = report.perGroup.get(group_name)
    if group is None:
        return ''
    if group.status.ok():
        return ' [success]✓[/success]'
    got = ' '.join(sorted(v.name for v in group.gotVerdicts))
    res = f' [ierror]✗[/ierror] [warning]expected {group.expectedOutcome}[/warning]'
    if got:
        res += f'[warning], got {got}[/warning]'
    return res
```

**Step 4: De-duplicate the report lookup on the reporter base class**

The three reporters each build a `partial_report` inside `render_group_end`,
guarded by `if group.score > 0`. Add to `TraditionalRunReporter`:

```python
    def get_partial_report(
        self, group: GroupSkeleton
    ) -> Optional[SolutionOutcomeReport]:
        """The solution's report so far, or None when no renderer needs it.

        Computed only when something will actually be displayed from it: POINTS
        scoring for this group, or a per-group expectation on this solution.
        """
        if self.current_solution is None:
            return None
        if group.score <= 0 and not self.current_solution.outcomePerGroup:
            return None
        return get_solution_outcome_report(
            self.current_solution,
            self.result.skeleton,
            self.current_solution_evals,
            verification=self.verification,
        )
```

**Step 5: Wire the three renderers**

`FullRunReporter.render_group_end` (line 2239) becomes:

```python
    def render_group_end(self, group: GroupSkeleton):
        bracketed = f'{get_capped_evals_formatted_time(self.get_current_limits(), self.current_group_evals, self.verification)}, {get_evals_formatted_memory(self.current_group_evals)}'
        self.console.print(
            f'[info]({bracketed})[/info]',
            end='',
        )
        partial_report = self.get_partial_report(group)
        if partial_report is not None:
            if group.score > 0:
                got_score = partial_report.gotScorePerGroup.get(group.name, 0)
                self.console.print(
                    f' {get_solution_score_markup(got_score, group.score, pts=True)}',
                    end='',
                )
            self.console.print(
                get_group_expectation_markup(partial_report, group.name), end=''
            )
        self.console.print()
```

`SingleSolutionRunReporter.render_group_end` (line 2390): same shape — keep its
`  [status]{group.name}[/status]` prefix and its two trailing `print()`s, and
replace the `if group.score > 0:` block with the `partial_report` block above.

`LiveRunReporter._update_live` (line 2323): replace

```python
        if finished and self.current_group.score > 0:
```

with a `partial_report` lookup gated on `finished`, appending both the score
markup (only when `score > 0`) and the expectation markup as
`rich.text.Text.from_markup(..., end='')`, mirroring the existing appends.

**Step 6: Run the tests**

Run: `uv run pytest tests/rbx/box/solutions_test.py -q -k "not test_solutions and not test_get_solution_outcome_report"`
Expected: all pass.

**Step 7: Sanity-check the rendering by hand**

The three reporters are driven by `rbx run`, which needs a compiled solution, so
verify on a real package rather than in a unit test:

```bash
cd /tmp && rm -rf pgtest && uv run --project /Users/rsalesc/Dev/robox.io rbx create pgtest
```

Then, in `pgtest/problem.rbx.yml`, give a non-main solution an
`outcomePerGroup` entry that is deliberately wrong (e.g.
`outcomePerGroup: {'*': tle}` on an accepted solution) and run
`uv run --project /Users/rsalesc/Dev/robox.io rbx run`. Confirm the group lines
carry `✗ expected TIME_LIMIT_EXCEEDED, got ACCEPTED` and the summary ends with a
`FAILED <group>: ...` line. If C++ compilation fails on this machine, note it in
the final report and rely on CI instead — do not chase it.

**Step 8: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/solutions.py tests/rbx/box/solutions_test.py
git commit -m "feat(solutions): show per-group expectation results on group lines"
```

---

### Task 6: Derived behaviors

Three sites read `solution.outcome` to answer a coarse question about the
solution; they must consider every declared expectation.

**Files:**
- Modify: `rbx/box/solutions.py:217-219` (`is_fast`)
- Modify: `rbx/box/solutions.py:1815-1830` (the timing summary buckets)
- Test: `tests/rbx/box/solutions_test.py`

The double-TL half of this was already done in Tasks 3 and 4.

**Step 1: Write the failing tests**

```python
def test_is_fast_considers_per_group_expectations(tmp_path):
    from rbx.box.solutions import is_fast

    fast = Solution(path=tmp_path / 'ac.cpp', outcome=ExpectedOutcome.ACCEPTED)
    slow_group = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            '*': ExpectedOutcome.ACCEPTED,
            'group3': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        },
    )

    assert is_fast(fast)
    # Expected to time out on group3, so it is not a fast solution.
    assert not is_fast(slow_group)
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/solutions_test.py -v -k is_fast_considers`
Expected: FAIL — `is_fast` returns True because `INCORRECT.is_slow()` is False.

**Step 3: Implement**

```python
def is_fast(solution: Solution) -> bool:
    # A solution expected to be slow anywhere -- for the whole testset or for a
    # single group -- is not a fast solution.
    return not any(
        outcome.is_slow() for outcome in solution.all_expected_outcomes()
    )
```

And in `_print_timing` (`rbx/box/solutions.py:1815-1830`), replace the three
`solution.outcome` checks:

```python
        language = find_language_name(solution)
        # Consider every expectation the solution declares, pooled and
        # per-group. Without ``outcomePerGroup`` this is exactly the previous
        # behavior, since the set is then just ``{solution.outcome}``.
        expectations = solution.all_expected_outcomes()
        # Get solution timings.
        if all(outcome == ExpectedOutcome.ACCEPTED for outcome in expectations):
            summary.add_good(solution_time, solution)
            summary_per_language[language].add_good(solution_time, solution)
        if all(
            outcome
            in [
                ExpectedOutcome.ACCEPTED,
                ExpectedOutcome.ACCEPTED_OR_TLE,
            ]
            for outcome in expectations
        ):
            summary.add_pass(solution_time, solution)
            summary_per_language[language].add_pass(solution_time, solution)
        if any(outcome.is_slow() for outcome in expectations):
            summary.add_slow(solution_time, solution)
            summary_per_language[language].add_slow(solution_time, solution)
```

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/box/solutions_test.py tests/rbx/box/test_timing.py tests/rbx/box/walltime_test.py -q -k "not test_solutions and not test_get_solution_outcome_report"`
Expected: all pass, except the known-bad
`test_compute_walltime_uses_active_environment` (fails on `main` for unrelated
reasons — leave it).

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/solutions.py tests/rbx/box/solutions_test.py
git commit -m "feat(solutions): fold per-group expectations into is_fast and timing buckets"
```

---

### Task 7: Test-package builder support

`rbx/box/testing/testing_package.py` is the fixture builder used by package-level
tests; `add_solution` cannot express the new field.

**Files:**
- Modify: `rbx/box/testing/testing_package.py:146-157`

**Step 1: Implement**

```python
    def add_solution(
        self,
        path: PathOrStr,
        outcome: ExpectedOutcome,
        language: Optional[str] = None,
        outcome_per_group: Optional[Dict[str, ExpectedOutcome]] = None,
    ):
        self.yml.solutions = self.yml.solutions + [
            Solution(
                path=pathlib.Path(path),
                language=language,
                outcome=outcome,
                outcomePerGroup=outcome_per_group or {},
            )
        ]
        self.save()
        return self.add_file(path)
```

`Dict` is already imported there (used by `add_checker_unit_test`); confirm.

**Step 2: Verify the builder still round-trips through YAML**

Run: `uv run pytest tests/rbx/box/test_package_loading.py tests/rbx/box/unit_test.py -q`
Expected: all pass.

**Step 3: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/testing/testing_package.py
git commit -m "test(testing): let add_solution declare per-group outcomes"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/setters/reference/package/index.md` (around lines 205-225, the
  solutions section)
- Modify: `rbx/box/CLAUDE.md` (the `Solution` bullet under "Key Models")

**Step 1: Package reference**

After the existing outcome example and the "For a full list of expected
outcomes" line, add:

```markdown
### Expected outcomes per testgroup

`outcome` is matched against the **whole testset at once**: `outcome: wa` means
the solution gets a wrong answer *somewhere*. To pin down *where*, add
`outcomePerGroup`, which is matched against each group's tests **individually**.
The reserved key `*` sets a default for every group, and an entry for a specific
group takes precedence over it.

```yaml
solutions:
  - path: 'sols/main.cpp'
    outcome: accepted
  - path: 'sols/quadratic.cpp'
    outcome: tle           # times out somewhere in the testset...
    outcomePerGroup:
      '*': accepted        # ...while being correct on every group...
      big: tle             # ...except on `big`, where it must time out
```

Both layers are checked, and the solution fails if either does. Without
`outcomePerGroup`, a `tle` solution keeps passing verification as long as it
times out on *some* test — including after a refactor makes it time out on the
small groups it was supposed to solve. Pinning the expectation per group turns
that into a failure.

Groups named here must exist in `testcases`, and `samples` counts as a group
like any other, so `*` applies to it too unless you override it.
```

Note the docs use `mkdocstrings`, so the field's own docstring already shows up
in `docs/setters/reference/package/schema.md`; nothing to regenerate (the JSON
schemas under `site/` are built by mkdocs and git-ignored).

**Step 2: Update the module guide**

In `rbx/box/CLAUDE.md`, change the `Solution` line to:

```markdown
- **`Solution`** -- `path`, `outcome` (ExpectedOutcome, matched against the whole
  testset pooled), `outcomePerGroup` (per-group expectations, `'*'` = default for
  every group individually; an additive second layer), `score`, `doubleTL`,
  `language`
```

**Step 3: Verify the docs build**

Run: `uv run mkdocs build 2>&1 | tail -20`
Expected: builds. Per project history there are ~9 pre-existing unrelated
warnings; `--strict` fails on `main` already, so use the non-strict build.

**Step 4: Commit**

```bash
git add docs/setters/reference/package/index.md rbx/box/CLAUDE.md
git commit -m "docs(package): document outcomePerGroup"
```

---

### Task 9: Full test sweep

**Step 1: Run the suite the way CI does**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto -q`

Expected: the only failures are the ones known to fail on `main` on this machine
— C++ checker/validator/sandbox/docker tests,
`test_compute_walltime_uses_active_environment`, and the completion drift test.
**Verify** by stashing and re-running any unfamiliar failure against `main`
before assuming it is pre-existing.

**Step 2: Lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

**Step 3: Commit anything the sweep fixed**, then report.

---

### Task 10: File the follow-up issue for the uncovered sites

Everything else that reads `solution.outcome` keeps ignoring `outcomePerGroup`.
File one issue with this inventory so it can be assessed later. The user asked
for this explicitly; do not skip it.

**Note:** `gh` is broken on this machine in two ways (see the notes below) —
`api.github.com` resolves to a dead IP, so use
`curl --resolve api.github.com:443:140.82.112.6` with the token from
`gh auth token`. Verify the issue URL comes back before reporting success.

Title: `outcomePerGroup: sites that still only read the pooled solution.outcome`

Body — one section per site, with the assessment:

| Site | What it does today | Assessment |
|---|---|---|
| `rbx/box/package.py:462-466` `get_main_solution` | picks the first solution with `outcome == ACCEPTED` | Guarded instead by the new main-solution validator; revisit if the guard is ever relaxed |
| `rbx/box/schema.py:1014-1024` | "first solution must be ACCEPTED" checks only the pooled outcome | Consistent with the guard above; low risk |
| `rbx/box/solutions.py:222-243` `get_matching_solutions` / `get_exact_matching_solutions` | `rbx run --outcome`, `rbx irun --outcome` (`cli.py:397-404`, `cli.py:757-764`), `rbx time` (`timing.py:370`), `cli.py:450/788` | `--outcome tle` will not select a solution that only expects TLE on one group. Wants a decision on whether filtering should union the layers |
| `rbx/box/summary.py:69-107, 320-332` | `rbx summary` counts and groups solutions by pooled outcome | Display only; per-group detail is invisible in the summary |
| `rbx/box/packaging/polygon/upload.py:87-100` | maps the pooled outcome to a Polygon solution tag | Polygon tags are per-solution, so per-group expectations have no representation; the pooled outcome is the only sensible tag |
| `rbx/box/packaging/moj/packager.py:124-133` | good / slow / wrong directory per solution | Same shape as Polygon: format has no per-group notion |
| `rbx/box/packaging/pkg/packager.py:51-57` | copies only `outcome == ACCEPTED` solutions | Fine today, but a solution that is AC per-group and non-AC pooled is silently excluded |
| `rbx/box/tooling/boca/submitter.py:79` | submits and compares against `simplify_rbx_expected_outcome(solution.outcome)` | BOCA judges the whole submission, so pooled is right; worth confirming |
| `rbx/box/ui/screens/run.py:34` and `SolutionReportScreen` | badge shows the pooled outcome only | `SolutionOutcomeReport` now carries `perGroup` (a `GroupOutcomeReport` per group); the TUI can adopt it (`run_ui.py:129-153` already renders group headers) |
| `rbx/box/schema.py:627-628` `Solution.href()` | colours the path by the pooled outcome | Cosmetic |
| `rbx/box/solutions.py:1907-2022` `_render_detailed_group_table` | `rbx run --detailed` group cells show verdicts, not expectation mismatches | Would benefit from the new report fields |
| `rbx/box/stresses.py:265`, `stressing/finder_parser.py` | stress expectations | Intentionally excluded — stress runs have no groups |
| `rbx/box/unit.py` | `rbx unit` expectations | Intentionally excluded — separate expectation system, no groups |

Close with: "Filed from
`docs/plans/2026-08-07-per-group-expected-outcome-design.md`; the design
deliberately scoped these out."

---

## Notes for the executing engineer

- **`gh` is broken here.** `api.github.com` DNS resolves to a dead IP; use
  `curl --resolve api.github.com:443:140.82.112.6 -H "Authorization: bearer $(gh auth token)"`.
  And `gh pr edit` / `gh pr view` fail on a classic-Projects GraphQL error — use
  `gh api -X PATCH repos/rsalesc/rbx/pulls/N` (through the same curl workaround).
- **Do not add an e2e scenario.** `tests/e2e` compiles C++, which is broken on
  this machine, so an added scenario could not be verified locally. The unit
  tests above cover the logic; the manual check in Task 5 Step 7 covers the
  rendering.
- **Do not touch** `_get_verdict_report`'s rules. Every behavior change in this
  plan comes from *which evals and which expectation* get passed to it.
