# Kattis-like Timing Multipliers Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let time limit inference be driven by Kattis-style ratios
(`acToTimeLimit`, `timeLimitToTle`, `timeResolution`) instead of a formula string,
so an estimated limit is bounded from *both* sides and a limit that lets a slow
solution pass becomes an error rather than a silent mistake.

**Architecture:** A new `timing.multipliers` block in `env.rbx.yml`, mutually
exclusive with `timing.formula` and overridable per problem. The pure grouping
layer in `rbx/box/timing_groups.py` stops taking a `(fastest, slowest) -> int`
callback and takes a strategy over the whole `GroupTimings` bundle instead, so
formula mode keeps working byte-for-byte while multipliers mode can also read the
slow-solution measurements. `compute_time_limits` runs slow solutions alongside
accepted ones — capped at `inferenceTimeout` — only when `timeLimitToTle` is set.

**Tech Stack:** Python 3.12+, Pydantic v2, Typer, pytest.

**Design doc:** `docs/plans/2026-08-13-kattis-timing-multipliers-design.md` — read
it first. It records the decisions this plan implements and why.

**Conventions:** single quotes, absolute imports only, `uv run ruff check --fix .
&& uv run ruff format .` before each commit, and commits follow the `/commit`
skill (conventional commits).

**Vocabulary (already in the codebase — reuse, do not reinvent):**
- `ExpectedOutcome.is_slow()` (`rbx/box/schema.py:242`) = `{tle, tle-or-rte}`.
- `solutions.is_fast(solution)` (`rbx/box/solutions.py:217`) = no expectation is slow.
- `solutions._get_evals_time_in_ms` = max time across a solution's testcases.
- `TimingSummary.slowest_good` / `fastest_slow` (`rbx/box/solutions.py:1886`) are
  already exactly the lower- and upper-bound quantities.

---

## Task 1: The `timing.multipliers` model

**Files:**
- Modify: `rbx/box/environment.py:359-395` (`TimingConfig`)
- Test: `tests/rbx/box/test_environment_timing.py` (create)

**Step 1: Write the failing test**

Create `tests/rbx/box/test_environment_timing.py`:

```python
import pytest
from pydantic import ValidationError

from rbx.box.environment import TimingConfig, TimingMultipliers


def test_multipliers_defaults():
    m = TimingMultipliers(acToTimeLimit=2.0)
    assert m.timeLimitToTle is None
    assert m.inferenceTimeout == 10000
    assert m.timeResolution == 100


def test_ac_to_time_limit_is_required():
    with pytest.raises(ValidationError):
        TimingMultipliers(timeLimitToTle=1.5)


def test_ratios_must_be_positive():
    with pytest.raises(ValidationError):
        TimingMultipliers(acToTimeLimit=0)
    with pytest.raises(ValidationError):
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=0)
    with pytest.raises(ValidationError):
        TimingMultipliers(acToTimeLimit=2.0, timeResolution=0)


def test_formula_and_multipliers_are_mutually_exclusive():
    with pytest.raises(ValidationError, match='mutually exclusive'):
        TimingConfig(
            formula='slowest * 2',
            multipliers=TimingMultipliers(acToTimeLimit=2.0),
        )


def test_neither_set_resolves_to_the_legacy_formula():
    config = TimingConfig()
    assert config.multipliers is None
    assert config.resolved_formula() == DEFAULT_TIMING_FORMULA


def test_multipliers_set_leaves_no_formula():
    config = TimingConfig(multipliers=TimingMultipliers(acToTimeLimit=2.0))
    assert config.resolved_formula() is None
```

Add the import of `DEFAULT_TIMING_FORMULA` from `rbx.box.environment` at the top.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_environment_timing.py -v`
Expected: FAIL with `ImportError: cannot import name 'TimingMultipliers'`.

**Step 3: Implement**

In `rbx/box/environment.py`, above `TimingConfig`:

```python
DEFAULT_TIMING_FORMULA = 'step_up(max(fastest * 3, slowest * 1.5), 100)'


class TimingMultipliers(BaseModel):
    model_config = ConfigDict(extra='forbid')

    acToTimeLimit: float = Field(
        gt=0,
        description="""Minimum ratio between the time limit and the slowest solution
used to estimate it from below: `slowest_good * acToTimeLimit <= timeLimit`.""",
    )

    timeLimitToTle: Optional[float] = Field(
        default=None,
        gt=0,
        description="""Minimum ratio between the fastest slow solution and the time
limit: `timeLimit * timeLimitToTle <= fastest_slow`. When omitted, slow solutions
are not run and the time limit is not bounded from above.""",
    )

    inferenceTimeout: int = Field(
        default=10000,
        gt=0,
        description="""Time limit (in milliseconds) enforced on solutions while
estimating. Only used when `timeLimitToTle` is set. A slow solution that hits it
is dropped from the upper bound; an accepted one that hits it is an error.""",
    )

    timeResolution: int = Field(
        default=100,
        gt=0,
        description="""Granularity (in milliseconds) of the estimated time limit.
The estimate is the smallest multiple of this value that is valid.""",
    )
```

Then in `TimingConfig`, replace the `formula` field and add `multipliers`:

```python
    formula: Optional[str] = Field(
        default=None,
        description="""Formula to use to calculate the time limit for the environment.
Mutually exclusive with `multipliers`. When neither is set, a default formula is
used.""",
    )

    multipliers: Optional[TimingMultipliers] = Field(
        default=None,
        description="""Ratios used to infer the time limit from the measured
solutions. Mutually exclusive with `formula`.""",
    )
```

Add to the existing `_validate_disjoint_groups` sibling set a new validator:

```python
    @model_validator(mode='after')
    def _validate_exclusive_strategies(self):
        if self.formula is not None and self.multipliers is not None:
            raise ValueError(
                'timing.formula and timing.multipliers are mutually exclusive; '
                'set exactly one of them.'
            )
        return self

    def resolved_formula(self) -> Optional[str]:
        """The formula to estimate with, or None when multipliers are in use."""
        if self.multipliers is not None:
            return None
        return self.formula or DEFAULT_TIMING_FORMULA
```

**Step 4: Fix the fallout from `formula` becoming optional**

Run: `uv run rg -n 'timing\.formula' rbx tests`

Every read of `env.timing.formula` that expected a `str` must become
`env.timing.resolved_formula()`. Known sites: `rbx/box/timing.py:294`,
`rbx/box/cli.py:590` and `rbx/box/cli.py:616`. Leave the `cli.py` sites returning
`Optional[str]` for now — Task 9 rewrites that menu.

**Step 5: Run the tests**

Run: `uv run pytest tests/rbx/box/test_environment_timing.py tests/rbx/box/test_timing.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/environment.py tests/rbx/box/test_environment_timing.py
git commit -m "feat(timing): add a multipliers block to the timing config"
```

---

## Task 2: Per-problem override of the multipliers

**Files:**
- Modify: `rbx/box/schema.py` (new `PackageTiming`, new `Package.timing` field)
- Create: `rbx/box/timing_config.py`
- Test: `tests/rbx/box/test_timing_config.py`

**Step 1: Write the failing test**

Create `tests/rbx/box/test_timing_config.py`:

```python
import pytest

from rbx.box.environment import TimingConfig, TimingMultipliers
from rbx.box.schema import PackageTiming, TimingMultipliersOverride
from rbx.box.timing_config import ResolutionError, resolve_multipliers


def test_no_override_returns_the_environment_block():
    env = TimingConfig(multipliers=TimingMultipliers(acToTimeLimit=2.0))
    assert resolve_multipliers(env, None) == env.multipliers


def test_override_merges_field_by_field():
    env = TimingConfig(
        multipliers=TimingMultipliers(
            acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100
        )
    )
    pkg = PackageTiming(
        multipliers=TimingMultipliersOverride(inferenceTimeout=120000)
    )
    resolved = resolve_multipliers(env, pkg)
    assert resolved is not None
    assert resolved.inferenceTimeout == 120000
    assert resolved.acToTimeLimit == 2.0
    assert resolved.timeLimitToTle == 1.5
    assert resolved.timeResolution == 100


def test_formula_environment_rejects_a_multipliers_override():
    env = TimingConfig(formula='slowest * 2')
    pkg = PackageTiming(multipliers=TimingMultipliersOverride(acToTimeLimit=3.0))
    with pytest.raises(ResolutionError, match='formula'):
        resolve_multipliers(env, pkg)


def test_formula_environment_without_override_resolves_to_none():
    assert resolve_multipliers(TimingConfig(formula='slowest * 2'), None) is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_config.py -v`
Expected: FAIL with `ImportError`.

**Step 3: Implement the schema side**

In `rbx/box/schema.py`, next to the other small config models:

```python
class TimingMultipliersOverride(BaseModel):
    model_config = ConfigDict(extra='forbid')

    acToTimeLimit: Optional[float] = Field(default=None, gt=0)
    timeLimitToTle: Optional[float] = Field(default=None, gt=0)
    inferenceTimeout: Optional[int] = Field(default=None, gt=0)
    timeResolution: Optional[int] = Field(default=None, gt=0)


class PackageTiming(BaseModel):
    model_config = ConfigDict(extra='forbid')

    multipliers: Optional[TimingMultipliersOverride] = Field(
        default=None,
        description="""Per-problem overrides of the environment's timing
multipliers. Only the declared fields are overridden.""",
    )
```

And on `Package`:

```python
    timing: Optional[PackageTiming] = Field(
        default=None,
        description="""Problem-level overrides for time limit inference.""",
    )
```

**Step 4: Implement the resolution**

Create `rbx/box/timing_config.py`:

```python
from typing import Optional

from rbx.box.environment import TimingConfig, TimingMultipliers
from rbx.box.schema import PackageTiming


class ResolutionError(ValueError):
    pass


def resolve_multipliers(
    env_timing: TimingConfig,
    package_timing: Optional[PackageTiming],
) -> Optional[TimingMultipliers]:
    """The multipliers in effect for this problem, or None in formula mode."""
    override = package_timing.multipliers if package_timing is not None else None
    if env_timing.multipliers is None:
        if override is not None:
            raise ResolutionError(
                'this problem overrides timing.multipliers, but the environment '
                'estimates with a formula; the two are mutually exclusive.'
            )
        return None
    if override is None:
        return env_timing.multipliers
    merged = env_timing.multipliers.model_dump()
    merged.update(override.model_dump(exclude_none=True))
    return TimingMultipliers(**merged)
```

**Step 5: Run the tests**

Run: `uv run pytest tests/rbx/box/test_timing_config.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/schema.py rbx/box/timing_config.py tests/rbx/box/test_timing_config.py
git commit -m "feat(timing): allow problems to override the timing multipliers"
```

---

## Task 3: The `inference` field on solutions

**Files:**
- Modify: `rbx/box/schema.py:663-731` (`Solution`)
- Test: `tests/rbx/box/test_solution_inference.py`

The field accepts `false`, `lower` or `upper`. `true` is rejected: it would mean
nothing distinct from leaving the field unset.

**Step 1: Write the failing test**

Create `tests/rbx/box/test_solution_inference.py`:

```python
import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.schema import ExpectedOutcome, InferenceRole, Solution


def _solution(**kwargs) -> Solution:
    return Solution(path=pathlib.Path('sols/a.cpp'), **kwargs)


def test_inference_defaults_to_unset():
    assert _solution().inference is None


def test_inference_accepts_false_and_roles():
    assert _solution(inference=False).inference is False
    assert _solution(inference='lower').inference == InferenceRole.LOWER
    assert _solution(inference='upper').inference == InferenceRole.UPPER


def test_inference_rejects_true():
    with pytest.raises(ValidationError):
        _solution(inference=True)


def test_lower_role_rejects_a_slow_solution():
    with pytest.raises(ValidationError, match='lower'):
        _solution(outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED, inference='lower')


def test_lower_role_rejects_a_per_group_slow_expectation():
    with pytest.raises(ValidationError, match='lower'):
        _solution(
            outcome=ExpectedOutcome.ACCEPTED,
            outcomePerGroup={'g1': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
            inference='lower',
        )
```

Note: the per-group test needs `scoring: points` context to be constructed
standalone — if `check_scoring_fields` rejects it at the `Solution` level, move
that assertion into a `Package`-level test alongside the existing
`outcomePerGroup` tests instead.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_solution_inference.py -v`
Expected: FAIL with `ImportError: cannot import name 'InferenceRole'`.

**Step 3: Implement**

In `rbx/box/schema.py`, next to `ExpectedOutcome`:

```python
class InferenceRole(AutoEnum):
    LOWER = 'lower'
    UPPER = 'upper'
```

Match the enum style used by `ExpectedOutcome` in this file. On `Solution`:

```python
    inference: Optional[Union[Literal[False], InferenceRole]] = Field(
        default=None,
        description="""Which side of the time limit inference this solution bounds.

When unset, the role follows the expected outcome: a solution expected to be
`accepted` everywhere bounds the limit from below, a solution expected to be slow
anywhere bounds it from above, and anything else -- including `accepted-or-tle` --
bounds neither.

Set to `false` to exclude the solution from inference entirely, or to `lower` /
`upper` to opt it into a side explicitly.
""",
    )

    @model_validator(mode='after')
    def _validate_inference_role(self):
        if self.inference == InferenceRole.LOWER and any(
            outcome.is_slow() for outcome in self.all_expected_outcomes()
        ):
            raise ValueError(
                'a solution expected to be slow cannot bound the time limit from '
                'below; use `inference: upper` or `inference: false`.'
            )
        return self
```

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/box/test_solution_inference.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/schema.py tests/rbx/box/test_solution_inference.py
git commit -m "feat(timing): add an inference role to solutions"
```

---

## Task 4: Classify solutions into inference roles

**Files:**
- Modify: `rbx/box/solutions.py` (next to `is_fast`, around line 217)
- Test: `tests/rbx/box/test_solution_inference.py` (extend)

**Step 1: Write the failing test**

Append to `tests/rbx/box/test_solution_inference.py`:

```python
from rbx.box.solutions import inference_role_of


def test_default_roles_follow_the_expected_outcome():
    assert inference_role_of(_solution(outcome=ExpectedOutcome.ACCEPTED)) == (
        InferenceRole.LOWER
    )
    assert inference_role_of(
        _solution(outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    ) == InferenceRole.UPPER
    assert inference_role_of(_solution(outcome=ExpectedOutcome.TLE_OR_RTE)) == (
        InferenceRole.UPPER
    )
    assert inference_role_of(_solution(outcome=ExpectedOutcome.ACCEPTED_OR_TLE)) is None
    assert inference_role_of(_solution(outcome=ExpectedOutcome.WRONG_ANSWER)) is None


def test_explicit_roles_win():
    assert inference_role_of(
        _solution(outcome=ExpectedOutcome.ACCEPTED, inference=False)
    ) is None
    assert inference_role_of(
        _solution(outcome=ExpectedOutcome.ACCEPTED_OR_TLE, inference='upper')
    ) == InferenceRole.UPPER
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_solution_inference.py -v`
Expected: FAIL with `ImportError: cannot import name 'inference_role_of'`.

**Step 3: Implement**

In `rbx/box/solutions.py`, immediately after `is_fast`:

```python
def inference_role_of(solution: Solution) -> Optional[InferenceRole]:
    """Which bound this solution contributes to during time limit inference.

    Mirrors the classification ``TimingSummary`` already uses: a solution that is
    accepted everywhere bounds from below, a solution expected to be slow
    anywhere bounds from above, and everything else -- notably
    ``accepted-or-tle``, which is neither good nor slow -- bounds neither.
    """
    if solution.inference is False:
        return None
    if solution.inference is not None:
        return solution.inference
    expectations = solution.all_expected_outcomes()
    if all(outcome == ExpectedOutcome.ACCEPTED for outcome in expectations):
        return InferenceRole.LOWER
    if any(outcome.is_slow() for outcome in expectations):
        return InferenceRole.UPPER
    return None


def get_inference_solutions(role: InferenceRole) -> List[Solution]:
    return [
        solution
        for solution in package.get_solutions()
        if inference_role_of(solution) == role
    ]
```

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/box/test_solution_inference.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/solutions.py tests/rbx/box/test_solution_inference.py
git commit -m "feat(timing): classify solutions into inference roles"
```

---

## Task 5: Teach the grouping layer about both bounds

The pure layer currently evaluates `EvalFn = Callable[[int, int], int]` over
`(fastest, slowest)`. Multipliers mode also needs the slow-solution measurement,
so the callback takes the whole `GroupTimings` instead. This task is a pure
refactor plus new fields — no behavior change.

**Files:**
- Modify: `rbx/box/timing_groups.py:90-105` (`GroupTimings`, `EvalFn`), `:161-260`
  (`resolve_groups`)
- Modify: `rbx/box/timing.py:82-83` (the `_eval` closure)
- Test: `tests/rbx/box/test_timing_groups.py` (adjust the existing eval callbacks)

**Step 1: Update the existing tests to the new callback shape**

In `tests/rbx/box/test_timing_groups.py:54` and `:327` the tests define eval
callbacks like `lambda fastest, slowest: max(fastest * 3, slowest * 2)`. Change
them to take a single `GroupTimings`:

```python
def _eval(t):
    return max(t.fastest * 3, t.slowest * 2)
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: FAIL with `TypeError: _eval() takes 1 positional argument but 2 were given`.

**Step 3: Implement**

In `rbx/box/timing_groups.py`:

```python
class GroupTimings(BaseModel):
    fastest: int
    slowest: int
    solution_count: int
    # Upper-bound evidence: the fastest slow solution in this group, and which
    # solution it was. None when the group has no usable slow measurement.
    fastest_slow: Optional[int] = None
    fastest_slow_solution: Optional[str] = None
    slowest_solution: Optional[str] = None
    dropped_upper: List[str] = []


EvalFn = Callable[[GroupTimings], int]
DeriveFn = Callable[[int, Optional[GroupTimings]], int]
```

In `resolve_groups`, change the three call sites from `eval_fn(x.fastest,
x.slowest)` to `eval_fn(x)`, and add an optional `derive_fn: Optional[DeriveFn] =
None` parameter applied to the two `MULTIPLIER` branches:

```python
            tl = int(ref_tl * fb.multiplier + increment)
            if derive_fn is not None:
                tl = derive_fn(tl, timings)
```

(and the same in the `whenEmpty` branch, passing `None` for timings). `derive_fn`
lets multipliers mode quantize and upper-check a limit that was derived from a
reference group rather than estimated. Formula mode passes `None`.

**Step 4: Update the caller**

In `rbx/box/timing.py:82-83`:

```python
    def _eval(timings: timing_groups.GroupTimings) -> int:
        return int(
            safeeval.eval_int(
                formula, {'fastest': timings.fastest, 'slowest': timings.slowest}
            )
        )
```

**Step 5: Run the tests**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py tests/rbx/box/test_timing.py tests/rbx/box/test_timing_preview.py tests/rbx/box/test_timing_estimation.py -v`
Expected: PASS — this refactor must not change a single resolved limit.

**Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing_groups.py rbx/box/timing.py tests/rbx/box/test_timing_groups.py
git commit -m "refactor(timing): pass whole group timings to the estimator"
```

---

## Task 6: The multipliers estimator

**Files:**
- Modify: `rbx/box/timing_groups.py` (new `TimingRangeError`)
- Modify: `rbx/box/timing.py` (new `make_multipliers_eval`)
- Test: `tests/rbx/box/test_timing_multipliers.py` (create)

**Step 1: Write the failing test**

Create `tests/rbx/box/test_timing_multipliers.py`:

```python
import pytest

from rbx.box.environment import TimingMultipliers
from rbx.box.timing import make_multipliers_derive, make_multipliers_eval
from rbx.box.timing_groups import GroupTimings, TimingRangeError


def _timings(**kwargs) -> GroupTimings:
    base = dict(fastest=100, slowest=400, solution_count=2)
    base.update(kwargs)
    return GroupTimings(**base)


def test_lower_bound_rounds_up_to_the_resolution():
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeResolution=100)
    )
    # 400 * 2 = 800, already a multiple of 100.
    assert eval_fn(_timings(slowest=400)) == 800
    # 410 * 2 = 820 -> 900.
    assert eval_fn(_timings(slowest=410)) == 900


def test_no_upper_bound_when_time_limit_to_tle_is_unset():
    eval_fn = make_multipliers_eval(TimingMultipliers(acToTimeLimit=2.0))
    assert eval_fn(_timings(slowest=400, fastest_slow=500)) == 800


def test_upper_bound_accepts_a_limit_inside_the_range():
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5)
    )
    # lower 800, upper 6000/1.5 = 4000.
    assert eval_fn(_timings(slowest=400, fastest_slow=6000)) == 800


def test_empty_range_raises_with_both_binding_solutions():
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5)
    )
    with pytest.raises(TimingRangeError) as exc:
        eval_fn(
            _timings(
                slowest=400,
                slowest_solution='sols/slow_ac.cpp',
                fastest_slow=900,
                fastest_slow_solution='sols/tle.cpp',
            )
        )
    message = str(exc.value)
    assert 'sols/slow_ac.cpp' in message
    assert 'sols/tle.cpp' in message


def test_grid_miss_raises():
    # lower 500 -> rounds to 600, upper 550: non-empty range, no multiple in it.
    eval_fn = make_multipliers_eval(
        TimingMultipliers(acToTimeLimit=1.0, timeLimitToTle=1.0, timeResolution=100)
    )
    with pytest.raises(TimingRangeError):
        eval_fn(_timings(slowest=500, fastest_slow=550))


def test_derive_quantizes_and_upper_checks_a_relative_limit():
    derive_fn = make_multipliers_derive(
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    assert derive_fn(2401, None) == 2500
    with pytest.raises(TimingRangeError):
        derive_fn(2401, _timings(fastest_slow=3000, fastest_slow_solution='s.cpp'))
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_multipliers.py -v`
Expected: FAIL with `ImportError`.

**Step 3: Implement**

In `rbx/box/timing_groups.py`:

```python
class TimingRangeError(GroupValidationError):
    """No time limit satisfies both bounds for some group.

    Subclasses ``GroupValidationError`` so the interactive group picker renders it
    inline for the offending grouping, exactly as it does an invalid partition.
    """
```

In `rbx/box/timing.py`:

```python
def _upper_bound(
    multipliers: environment.TimingMultipliers, timings: timing_groups.GroupTimings
) -> Optional[float]:
    if multipliers.timeLimitToTle is None or timings.fastest_slow is None:
        return None
    return timings.fastest_slow / multipliers.timeLimitToTle


def _check_upper(
    tl: int,
    multipliers: environment.TimingMultipliers,
    timings: Optional[timing_groups.GroupTimings],
) -> int:
    if timings is None:
        return tl
    upper = _upper_bound(multipliers, timings)
    if upper is None or tl <= upper:
        return tl
    lower_hint = (
        f' (bounded below by {timings.slowest} ms in '
        f'{timings.slowest_solution or "an accepted solution"} '
        f'× {multipliers.acToTimeLimit})'
    )
    raise timing_groups.TimingRangeError(
        f'no valid time limit exists: the smallest allowed limit is {tl} ms'
        f'{lower_hint}, but {timings.fastest_slow_solution or "a slow solution"} '
        f'runs in {timings.fastest_slow} ms, which caps it at {int(upper)} ms '
        f'(timeLimitToTle {multipliers.timeLimitToTle}). Speed up the accepted '
        'solution, slow down the slow one, or relax the ratios.'
    )


def make_multipliers_eval(
    multipliers: environment.TimingMultipliers,
) -> timing_groups.EvalFn:
    def _eval(timings: timing_groups.GroupTimings) -> int:
        lower = math.ceil(timings.slowest * multipliers.acToTimeLimit)
        tl = step_up(lower, multipliers.timeResolution)
        return _check_upper(tl, multipliers, timings)

    return _eval


def make_multipliers_derive(
    multipliers: environment.TimingMultipliers,
) -> timing_groups.DeriveFn:
    def _derive(
        tl: int, timings: Optional[timing_groups.GroupTimings]
    ) -> int:
        tl = step_up(tl, multipliers.timeResolution)
        return _check_upper(tl, multipliers, timings)

    return _derive
```

Add `import math` at the top of `rbx/box/timing.py`.

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/box/test_timing_multipliers.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py rbx/box/timing_groups.py tests/rbx/box/test_timing_multipliers.py
git commit -m "feat(timing): implement the multipliers estimator"
```

---

## Task 7: Feed the slow measurements into the profile builder

**Files:**
- Modify: `rbx/box/timing.py:74-118` (`build_timing_profile`), `:156-224`
  (preview renderer and picker prompt), `:242-347` (`estimate_time_limit`)
- Test: `tests/rbx/box/test_timing_estimation.py` (extend)

`build_timing_profile` currently takes one `timing_per_solution_per_language`
map. It gains a second, optional map for slow solutions plus the dropped set, and
picks its estimator from the multipliers rather than always building a formula
closure.

**Step 1: Write the failing test**

Append to `tests/rbx/box/test_timing_estimation.py`:

```python
def test_build_profile_with_multipliers_uses_both_bounds():
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
        formula=None,
        multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
        slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 6000}},
        env_groups=[],
        all_languages=['cpp'],
    )
    assert profile.timeLimit == 800
    assert profile.formula is None
    assert profile.multipliers is not None


def test_build_profile_with_multipliers_rejects_an_empty_range():
    with pytest.raises(TimingRangeError):
        build_timing_profile(
            timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
            formula=None,
            multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
            slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 900}},
            env_groups=[],
            all_languages=['cpp'],
        )
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_estimation.py -v`
Expected: FAIL with `TypeError: unexpected keyword argument 'multipliers'`.

**Step 3: Implement**

Change the signature to take `formula: Optional[str]`, `multipliers:
Optional[TimingMultipliers]`, `slow_timing_per_solution_per_language:
Optional[Dict[str, Dict[str, int]]] = None` and `dropped_upper:
Optional[Dict[str, List[str]]] = None`. Exactly one of `formula`/`multipliers`
must be set — assert it.

Per group, alongside the existing `values` pooling, pool the slow measurements
and record which solution set each bound:

```python
        slow_values: List[Tuple[int, str]] = []
        for lang in group.languages:
            for path, time in (slow_per_language.get(lang) or {}).items():
                slow_values.append((time, path))
        fastest_slow = min(slow_values) if slow_values else None
```

and fill the new `GroupTimings` fields (`fastest_slow`,
`fastest_slow_solution`, `slowest_solution`, `dropped_upper`). Do the same for
the pooled `base`.

Pick the estimator:

```python
    if multipliers is not None:
        eval_fn = make_multipliers_eval(multipliers)
        derive_fn = make_multipliers_derive(multipliers)
    else:
        assert formula is not None
        eval_fn = make_formula_eval(formula)
        derive_fn = None
```

`TimingProfile` gains `multipliers: Optional[TimingMultipliers] = None` and
passes it through `to_limits()` (Task 8 adds the field on `LimitsProfile`).

Thread the same two new arguments through `build_preview_renderer`,
`_prompt_repartition` and `estimate_time_limit`, replacing their `formula: str`
parameters with the pair. In `estimate_time_limit`, replace the
`Using formula: ...` line with a branch that prints the ratios in multipliers
mode.

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/box/test_timing_estimation.py tests/rbx/box/test_timing_preview.py tests/rbx/box/test_timing.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py tests/rbx/box/test_timing_estimation.py
git commit -m "feat(timing): estimate from both bounds in the profile builder"
```

---

## Task 8: Run the slow solutions

**Files:**
- Modify: `rbx/box/timing.py:350-430` (`compute_time_limits`)
- Test: `tests/rbx/box/test_timing.py` (extend)

**Step 1: Write the failing test**

Append to `tests/rbx/box/test_timing.py` — assert on the arguments
`compute_time_limits` passes to `run_solutions`, which is where the whole
behavior of this task lives:

```python
async def test_formula_mode_runs_only_lower_solutions_uncapped(...):
    # env with a formula: tracked_solutions == the accepted solutions,
    # timelimit_override == -1. Identical to today.


async def test_multipliers_without_tle_ratio_runs_only_lower_solutions(...):
    # multipliers without timeLimitToTle: still uncapped, still accepted only.


async def test_multipliers_with_tle_ratio_runs_both_capped(...):
    # tracked_solutions == accepted + slow, timelimit_override == inferenceTimeout.
```

Follow the mocking style already used at `tests/rbx/box/test_timing.py:184`.

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing.py -v`
Expected: FAIL — slow solutions are not tracked and the override is `-1`.

**Step 3: Implement**

In `compute_time_limits`, resolve the multipliers first:

```python
    multipliers = timing_config.resolve_multipliers(
        environment.get_environment().timing,
        package.find_problem_package_or_die().timing,
    )
    formula = formula or (
        None if multipliers is not None
        else environment.get_environment().timing.resolved_formula()
    )
```

An explicit `formula` argument (the CLI's custom-formula escape hatch) forces
formula mode and drops the multipliers.

Then build the tracked set and the override:

```python
    lower_solutions = solutions.get_inference_solutions(InferenceRole.LOWER)
    upper_solutions: List[Solution] = []
    timelimit_override = -1  # unlimited
    if multipliers is not None and multipliers.timeLimitToTle is not None:
        upper_solutions = solutions.get_inference_solutions(InferenceRole.UPPER)
        timelimit_override = multipliers.inferenceTimeout
```

When `timeLimitToTle` is unset, `upper_solutions` stays empty and the run is
byte-for-byte what it is today. Pass `tracked_solutions` as the union, keeping
the existing `OrderedSet` of paths.

Suppress `doubleTL` for this run — it would silently double the cap for exactly
the solutions the cap exists to bound. Verify how `isDoubleTL` is derived
(`rbx/box/limits_info.py:109`, from the verification level) and pass whatever
keeps it false for this pass.

**Step 4: Split the report check**

`print_run_report`'s `ok` currently gates the whole estimation. Upper solutions
are *expected* to hit the cap, so their timeouts must not fail it. Restrict the
existing check to lower solutions, and add the diagnostics from the design:

- upper solution killed at the cap → drop it from the bound, warn naming it,
  record it in `dropped_upper`;
- upper solution that failed for a non-timing reason → error naming it and
  suggesting `inference: false`;
- lower solution killed at the cap → error;
- any drop happened and the resolved limit exceeds
  `inferenceTimeout / timeLimitToTle` → prominent warning that the cap, not the
  solutions, bounded the estimate.

Collect the upper timings the same way the lower ones are collected at
`rbx/box/timing.py:259-279`, keyed by language, and pass them to
`build_timing_profile`.

**Step 5: Run the tests**

Run: `uv run pytest tests/rbx/box/test_timing.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py tests/rbx/box/test_timing.py
git commit -m "feat(timing): run slow solutions when inferring an upper bound"
```

---

## Task 9: Record and render the provenance

**Files:**
- Modify: `rbx/box/schema.py:919-970` (`LimitsProfile`, `TimingGroupReport`)
- Modify: `rbx/box/limits_info.py:266-310` (`build_limits_table_rows`), `:333`
  (`build_limits_table`)
- Test: `tests/rbx/box/test_limits_info.py` (or the existing limits table tests)

**Step 1: Write the failing test**

Assert that a profile estimated with multipliers round-trips its ratios and
bounds through YAML, and that the table shows the bounds:

```python
def test_limits_profile_round_trips_multipliers():
    profile = LimitsProfile(
        timeLimit=2000,
        multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
    )
    reloaded = LimitsProfile(**yaml.safe_load(utils.model_to_yaml(profile)))
    assert reloaded.multipliers == profile.multipliers


def test_table_shows_the_bounds_for_an_estimated_group():
    # A group report carrying lowerBound/upperBound renders both, and the source
    # column names the binding solution.
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_limits_info.py -v`
Expected: FAIL.

**Step 3: Implement**

On `LimitsProfile`, next to `formula`:

```python
    multipliers: Optional[TimingMultipliers] = Field(
        default=None,
        description="""The timing multipliers this profile was estimated with.
Presentation-only; never used for limit resolution.""",
    )
```

On `TimingGroupReport`:

```python
class TimingBound(BaseModel):
    value: int
    solution: Optional[str] = None


    lowerBound: Optional[TimingBound] = None
    upperBound: Optional[TimingBound] = None
    droppedUpper: List[str] = []
```

Fill them in `build_timing_profile` and render them in the limits table —
follow the existing caption pattern in `build_limits_table` for the
dropped-upper note rather than adding a column.

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/box/test_limits_info.py tests/rbx/box/test_timing_preview.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/schema.py rbx/box/limits_info.py tests/rbx/box/test_limits_info.py
git commit -m "feat(timing): record inference bounds in the limits profile"
```

---

## Task 10: The `rbx time` menu

**Files:**
- Modify: `rbx/box/cli.py:508-512` (command help), `:590-660` (the menu)
- Test: covered by the e2e fixture in Task 12

**Step 1: Implement**

The recommended choice currently interpolates the formula. Branch on the
resolved strategy:

```python
    env_timing = environment.get_environment().timing
    multipliers = timing_config.resolve_multipliers(
        env_timing, package.find_problem_package_or_die().timing
    )
    if multipliers is not None:
        recommended = (
            f'Estimate time limits with ratios acToTimeLimit={multipliers.acToTimeLimit}'
        )
        if multipliers.timeLimitToTle is not None:
            recommended += f', timeLimitToTle={multipliers.timeLimitToTle}'
        recommended += ' (recommended)'
    else:
        recommended = (
            f'Estimate time limits based on the formula '
            f'{env_timing.resolved_formula()} (recommended)'
        )
```

Keep `estimate_custom` exactly as it is: entering a custom formula forces formula
mode for that run, which `compute_time_limits` already honors (Task 8). Remove
the now-dead second `formula = ...` read at `cli.py:616`. Update the command
help at `cli.py:511` to stop naming the formula specifically.

**Step 2: Verify**

Run: `uv run pytest tests/rbx/box/cli -v -k time`
Expected: PASS.

**Step 3: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/cli.py
git commit -m "feat(timing): show the inference ratios in the time menu"
```

---

## Task 11: Switch the default preset

**Files:**
- Modify: `rbx/resources/presets/default/env.rbx.yml:3-12`
- Test: existing preset/e2e tests

**Step 1: Implement**

```yaml
timing:
  wallTimeMultiplier: 2.0
  wallTimeIncrement: 500
  multipliers:
    # The estimated limit is at least 2x the slowest accepted solution, at most
    # 1/1.5 of the fastest solution expected to be too slow, and a multiple of
    # 100ms.
    acToTimeLimit: 2.0
    timeLimitToTle: 1.5
    timeResolution: 100
    inferenceTimeout: 10000
  groups:
    # ... unchanged
```

Keep the comments general per the preset-comment convention: they explain the
role of each knob, not this problem's numbers.

**Step 2: Regenerate the published schemas**

Run: `uv run python -m rbx.box.dump_schemas` (confirm the exact entry point in
`rbx/box/dump_schemas.py`) and commit whatever it regenerates.

**Step 3: Run the suite**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: PASS, modulo the pre-existing local failures recorded in
`docs/internal/` and project memory (C++/sandbox/docker).

**Step 4: Commit**

```bash
git add rbx/resources/presets/default/env.rbx.yml
git commit -m "feat(preset): infer time limits from ratios by default"
```

---

## Task 12: End-to-end coverage

**Files:**
- Create: `tests/e2e/testdata/timing-multipliers/` (fixture package + `e2e.rbx.yml`)

Read `tests/e2e/README.md` first for the YAML DSL. Model the fixture on
`tests/e2e/testdata/mixed-solutions/`, which already ships accepted and slow
solutions.

Cover three scenarios:
1. `rbx time --auto` with `timeLimitToTle` set, an accepted and a slow solution
   comfortably apart → succeeds, writes a limit that is a multiple of
   `timeResolution` and sits inside the range.
2. The slow solution made deliberately fast → the empty-range error, and
   `.limits/local.yml` is *not* written.
3. A solution marked `inference: false` → excluded from the bound it would
   otherwise set.

Run: `mise run test-e2e`

**Commit:**

```bash
git add tests/e2e/testdata/timing-multipliers
git commit -m "test(timing): cover multipliers inference end to end"
```

---

## Task 13: Documentation

**Files:**
- Modify: `docs/setters/profiling/index.md` (the `## Time limit formulas` area)
- Modify: `docs/setters/packaging-walkthrough.md:64-90` (the strategy table and
  the default-formula callout)

Keep this terse and at the altitude the pages already sit at — describe the three
ratios, the per-solution `inference` field and the per-problem override as user
knobs. No internals: no group-timings plumbing, no estimator strategies, no
mention of how the run is capped beyond "slow solutions are run with a timeout
you control".

Verify with a non-strict build (`--strict` has ~9 pre-existing unrelated
warnings):

Run: `uv run mkdocs build`

**Commit:**

```bash
git add docs/
git commit -m "docs(timing): document the inference ratios"
```

---

## Follow-up (not in this plan)

Points-scored problems, where a per-group score model makes "the" slow solution
ill-defined, need their own design. Open a separate issue as the original one
asks.
