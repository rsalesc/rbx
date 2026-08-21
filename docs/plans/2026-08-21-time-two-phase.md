# Two-Phase `rbx time` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split `rbx time` into a phase that estimates the time limit from accepted solutions and a phase that validates the estimate against the solutions expected to be too slow.

**Architecture:** Phase 1 runs only `inference: lower` solutions under `inferenceTimeout` and produces a candidate `TimingProfile`. Phase 2 runs each `inference: upper` solution at `ceil(TL_lang * timeLimitToTle)`, where a TLE confirms the solution is too slow and a finish is a violation carrying an exact measurement. A violation re-opens the language-group picker with those measurements; the user re-picks, forces the current limit through, or cancels. The profile is written once, after that loop settles.

**Tech Stack:** Python 3, Pydantic v2, Typer, prompt_toolkit, pytest, `uv run`.

**Design doc:** [`docs/plans/2026-08-21-time-two-phase-design.md`](2026-08-21-time-two-phase-design.md)

**Background reading before starting:** `rbx/box/CLAUDE.md`, `rbx/grading/CLAUDE.md`, and the design doc above. The whole feature lives in `rbx/box/timing.py` (1248 lines) plus small changes in five other modules; read `timing.py` end to end before Task 4.

**Conventions that apply to every task:**
- Single quotes. Absolute imports only. `uv run ruff check --fix . && uv run ruff format .` before every commit.
- Commit with the `/commit` skill's conventional-commit format (`.claude/skills/commit.md`), always with the `Co-Authored-By: Claude <noreply@anthropic.com>` trailer.
- Run tests with `uv run pytest`. Never run `tests/docker/`.
- Never mock private functions of the module under test. Prefer asserting over whole objects.

---

### Task 1: Per-language time limit override in `run_solutions`

Phase 2 needs a different enforced limit per language, because each language group gets its own estimated limit. Today `timelimit_override` is a single `int` threaded from `run_solutions` down to `tasks.get_limits_for_language`. Widen it to accept a `{language: limit}` mapping, resolved at the two places that already know the language.

**Files:**
- Modify: `rbx/box/solutions.py` (`_get_report_skeleton:706`, `_produce_solution_items:795`, `_run_solution:563`, `run_solutions:872`)
- Test: `tests/rbx/box/test_solutions_timelimit_override.py` (create)

**Step 1: Write the failing test**

```python
"""The enforced time limit may vary per language within one run."""

from typing import Optional

import pytest

from rbx.box import solutions


@pytest.mark.parametrize(
    ('override', 'lang', 'expected'),
    [
        (None, 'cpp', None),
        (1000, 'cpp', 1000),
        (1000, None, 1000),
        ({'cpp': 1500, 'py': 4000}, 'cpp', 1500),
        ({'cpp': 1500, 'py': 4000}, 'py', 4000),
        # A language the mapping does not mention keeps the profile's own limit.
        ({'cpp': 1500}, 'java', None),
        # A mapping cannot be resolved without knowing the language.
        ({'cpp': 1500}, None, None),
    ],
)
def test_resolve_timelimit_override(override, lang: Optional[str], expected):
    assert solutions.resolve_timelimit_override(override, lang) == expected
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_solutions_timelimit_override.py -v`
Expected: FAIL, `AttributeError: module 'rbx.box.solutions' has no attribute 'resolve_timelimit_override'`

**Step 3: Write minimal implementation**

In `rbx/box/solutions.py`, near the top-level type aliases:

```python
# The enforced time limit for a run: one limit for every language, or one per
# language. The per-language form exists because a time-limit estimate assigns a
# different limit to each language group (see `rbx/box/timing.py`).
TimelimitOverride = Union[int, Mapping[str, int]]


def resolve_timelimit_override(
    override: Optional[TimelimitOverride],
    lang: Optional[str],
) -> Optional[int]:
    """The limit this language runs under, or None to keep the profile's own.

    A mapping that does not mention the language -- or a language that could not
    be identified at all -- resolves to None rather than to some other language's
    limit.
    """
    if override is None or isinstance(override, int):
        return override
    if lang is None:
        return None
    return override.get(lang)
```

Add `Mapping` and `Union` to the `typing` import if absent.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/test_solutions_timelimit_override.py -v`
Expected: PASS

**Step 5: Thread the wider type through**

Change the annotation `timelimit_override: Optional[int]` to `timelimit_override: Optional[TimelimitOverride]` in `run_solutions`, `_get_report_skeleton`, `_produce_solution_items`, and `_run_solution`. Then resolve at the two sites that know the language:

In `_get_report_skeleton` (around `solutions.py:728`):

```python
    limits = {
        lang: get_limits_for_language(
            lang, verification, resolve_timelimit_override(timelimit_override, lang)
        )
        for lang in langs
        if lang is not None
    }
```

In `_run_solution`, resolve once before the entry loop and pass the scalar down, since `run_solution_on_testcase` takes an `int`:

```python
    groups_by_name = {group.name: group for group in groups}
    # Resolved once per solution: the language cannot change between its testcases.
    solution_timelimit = resolve_timelimit_override(
        timelimit_override, find_language_name(solution)
    )
```

and inside `run_fn`, pass `timelimit_override=solution_timelimit`.

**Step 6: Verify nothing regressed**

Run: `uv run pytest tests/rbx/box -k 'solutions or timing' -v`
Expected: PASS (no behavior change — every existing caller passes an `int` or `None`)

**Step 7: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/solutions.py tests/rbx/box/test_solutions_timelimit_override.py
git commit  # feat(solutions): allow a per-language time limit override
```

---

### Task 2: Record the upper-bound validation outcome in the profile

`TimingGroupReport.droppedUpper` means "expected to be too slow but still running at `inferenceTimeout`, so it bounds nothing". After the split, a slow solution that hits its probe limit is *confirmed* rather than dropped, and one that finishes is a *violation*. Replace the field, keeping the old name parseable so profiles already on disk still load (`TimingGroupReport` is `extra='forbid'`).

**Files:**
- Modify: `rbx/box/schema.py:963-995`
- Test: `tests/rbx/box/test_timing_upper_validation.py` (create)

**Step 1: Write the failing test**

```python
"""The limits profile records what phase 2 learned about each slow solution."""

from rbx.box import schema


def test_upper_validation_defaults_to_absent():
    report = schema.TimingGroupReport(
        languages=['cpp'], timeLimit=1000, origin=schema.TimingGroupOrigin.ESTIMATED
    )
    assert report.upperValidation is None


def test_upper_validation_round_trips():
    validation = schema.TimingGroupUpperValidation(
        confirmed=['sols/slow.cpp'],
        violating=[schema.TimingBound(value=1200, solution='sols/nearly.cpp')],
        skipped=['sols/unrun.cpp'],
    )
    report = schema.TimingGroupReport(
        languages=['cpp'],
        timeLimit=1000,
        origin=schema.TimingGroupOrigin.ESTIMATED,
        upperValidation=validation,
    )
    assert (
        schema.TimingGroupReport.model_validate(report.model_dump()).upperValidation
        == validation
    )


def test_a_profile_written_before_the_split_still_parses():
    # `droppedUpper` is deprecated but must not make an existing
    # `.limits/<profile>.yml` unparseable.
    report = schema.TimingGroupReport.model_validate(
        {
            'languages': ['cpp'],
            'timeLimit': 1000,
            'origin': 'estimated',
            'droppedUpper': ['sols/slow.cpp'],
        }
    )
    assert report.upperValidation is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_upper_validation.py -v`
Expected: FAIL, `AttributeError: module 'rbx.box.schema' has no attribute 'TimingGroupUpperValidation'`

**Step 3: Write minimal implementation**

In `rbx/box/schema.py`, after `TimingBound`:

```python
class TimingGroupUpperValidation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    confirmed: List[str] = Field(
        default=[],
        description="""Solutions of this group expected to be too slow that were
confirmed to be so: they were still running when the estimated time limit times
`timeLimitToTle` elapsed. Presentation-only.""",
    )

    violating: List[TimingBound] = Field(
        default=[],
        description="""Solutions of this group expected to be too slow that finished
within the estimated time limit times `timeLimitToTle`, so they do not respect the
upper bound. `value` is the time the solution actually took. Presentation-only.""",
    )

    skipped: List[str] = Field(
        default=[],
        description="""Solutions of this group expected to be too slow that were not
run, either because `timeLimitToTle` is unset or because the validation phase was
skipped. Presentation-only.""",
    )
```

Then on `TimingGroupReport`, replace `droppedUpper` with:

```python
    upperValidation: Optional[TimingGroupUpperValidation] = Field(
        default=None,
        description="""What checking this group's slow solutions against its estimated
time limit found. Absent when the group has no slow solutions. Presentation-only.""",
    )

    droppedUpper: List[str] = Field(
        default=[],
        deprecated=True,
        exclude=True,
        description="""Deprecated: replaced by `upperValidation`. Accepted so that a
limits profile written before the estimation was split into two phases still parses;
never written.""",
    )
```

`exclude=True` keeps it out of every profile rbx writes while `extra='forbid'` still accepts it on the way in.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_upper_validation.py -v`
Expected: PASS

**Step 5: Update the readers**

`droppedUpper` is read in three places. Point them at `upperValidation`, keeping the rendering shape (`limits_info._LimitsRow.dropped_upper` and the warning at `limits_info.py:427-433`) but rewording it: the warning currently tells the setter to raise `inferenceTimeout`, which is no longer the reason a slow solution goes unmeasured.

- `rbx/box/timing_groups.py:203-208` — writes the field from `measured.upper.dropped_upper`. Task 7 revisits this; for now write `upperValidation=TimingGroupUpperValidation(confirmed=list(measured.upper.dropped_upper))`.
- `rbx/box/limits_info.py:319-345` — read `report.upperValidation.confirmed` (guarding `None`).
- `rbx/box/limits_info.py:427-433` — reword: these solutions are confirmed too slow, which is the desired outcome, so this should read as information rather than a warning.
- `rbx/box/timing.py:932-941` — the preview key includes `report.droppedUpper`; use the confirmed list.

**Step 6: Run the affected suites**

Run: `uv run pytest tests/rbx/box -k 'timing or limits' -v`
Expected: PASS. Fix any test asserting on `droppedUpper` by moving it to `upperValidation.confirmed`.

**Step 7: Regenerate schemas and commit**

Schemas under `docs/schemas` are generated at import (see `rbx/box/dump_schemas.py`) and are not checked in — no action needed, but confirm `uv run rbx --help` still starts.

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/schema.py rbx/box/limits_info.py rbx/box/timing_groups.py rbx/box/timing.py tests/
git commit  # feat(timing): record upper-bound validation in the limits profile
```

---

### Task 3: Probe limits and the slow-solution knowledge cache

Pure arithmetic and bookkeeping, with no I/O, so it is worth pinning precisely before anything runs it. Two pieces:

- the probe limit for a language: `ceil(TL_lang * timeLimitToTle)` in exact `Fraction` arithmetic, matching how `compute_bounds` reads the ratio the setter typed;
- a per-solution record of what is already known, so the picker loop re-runs only what it must.

**Files:**
- Create: `rbx/box/timing_validation.py`
- Test: `tests/rbx/box/test_timing_validation.py`

**Step 1: Write the failing test**

```python
"""Probe limits and the knowledge that lets the picker loop skip re-runs."""

import pytest

from rbx.box import timing_validation


@pytest.mark.parametrize(
    ('time_limit', 'ratio', 'expected'),
    [
        (1000, 1.5, 1500),
        # 1.1 is not exactly representable in binary floating point; the ratio the
        # setter typed is what must be used, as in `timing.compute_bounds`.
        (1000, 1.1, 1100),
        # Rounded up: a solution that finishes at exactly the rounded-down value
        # would be under the real bound.
        (333, 1.5, 500),
        (1, 1.5, 2),
    ],
)
def test_probe_limit_is_the_bound_rounded_up_exactly(time_limit, ratio, expected):
    assert timing_validation.probe_limit(time_limit, ratio) == expected


def test_an_unmeasured_solution_must_run():
    knowledge = timing_validation.SlowKnowledge()
    assert knowledge.needs_run('sols/slow.cpp', 1500)


def test_a_solution_that_timed_out_covers_any_lower_probe():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 1500)
    assert not knowledge.needs_run('sols/slow.cpp', 1500)
    assert not knowledge.needs_run('sols/slow.cpp', 900)
    # A higher probe demands more than what is known.
    assert knowledge.needs_run('sols/slow.cpp', 1600)


def test_a_measured_solution_never_runs_again():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_time('sols/slow.cpp', 1200)
    assert not knowledge.needs_run('sols/slow.cpp', 99999)
    assert knowledge.measured_time('sols/slow.cpp') == 1200


def test_a_measurement_supersedes_an_earlier_timeout():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 900)
    knowledge.record_time('sols/slow.cpp', 1200)
    assert not knowledge.needs_run('sols/slow.cpp', 99999)
    assert knowledge.measured_time('sols/slow.cpp') == 1200


def test_a_timeout_never_weakens_what_is_known():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 1500)
    knowledge.record_timeout('sols/slow.cpp', 900)
    assert not knowledge.needs_run('sols/slow.cpp', 1500)


def test_a_confirmed_solution_reports_no_measurement():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 1500)
    assert knowledge.measured_time('sols/slow.cpp') is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_validation.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'rbx.box.timing_validation'`

**Step 3: Write minimal implementation**

```python
"""What is known about the solutions expected to be too slow.

Validating an estimated time limit asks one question per slow solution: does it
take at least ``timeLimit * timeLimitToTle``? Running it under exactly that limit
answers the question without measuring it -- a solution killed at the limit
cleared the bound, and one that finished did not, and hands us its real time on
the way out.

The answer is monotone, which is what makes the picker loop cheap: a solution
killed at ``L`` is also killed at any lower limit, and a solution that finished
is answered by arithmetic forever after.
"""

import dataclasses
import math
from fractions import Fraction
from typing import Dict, Optional


def probe_limit(time_limit: int, time_limit_to_tle: float) -> int:
    """The limit a slow solution must survive for ``time_limit`` to hold.

    Rounded up, and computed from the ratio the setter typed rather than from its
    binary approximation, so it agrees with `timing.compute_bounds` on the
    boundary case where a solution takes exactly ``time_limit * ratio``.
    """
    return math.ceil(time_limit * Fraction(str(time_limit_to_tle)))


@dataclasses.dataclass
class _SolutionKnowledge:
    # Its real time, once it finished under some probe limit.
    time: Optional[int] = None
    # The highest limit it was killed at, so its time exceeds this.
    survived: Optional[int] = None


@dataclasses.dataclass
class SlowKnowledge:
    """What each slow solution has already told us, across probe limits."""

    _per_solution: Dict[str, _SolutionKnowledge] = dataclasses.field(
        default_factory=dict
    )

    def _entry(self, solution: str) -> _SolutionKnowledge:
        return self._per_solution.setdefault(solution, _SolutionKnowledge())

    def record_time(self, solution: str, time: int) -> None:
        """It finished under its probe limit, in ``time`` ms."""
        self._entry(solution).time = time

    def record_timeout(self, solution: str, limit: int) -> None:
        """It was still running at ``limit`` ms."""
        entry = self._entry(solution)
        entry.survived = max(entry.survived or 0, limit)

    def measured_time(self, solution: str) -> Optional[int]:
        """Its real time, or None if it has only ever been killed."""
        return self._per_solution.get(solution, _SolutionKnowledge()).time

    def needs_run(self, solution: str, limit: int) -> bool:
        """Whether answering the question at ``limit`` requires running it."""
        entry = self._per_solution.get(solution)
        if entry is None:
            return True
        if entry.time is not None:
            # A real measurement answers every limit by arithmetic.
            return False
        return entry.survived is None or entry.survived < limit
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_validation.py -v`
Expected: PASS

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing_validation.py tests/rbx/box/test_timing_validation.py
git commit  # feat(timing): add probe limits and slow-solution knowledge
```

---

### Task 4: Phase 1 runs only the lower-bound solutions

`_run_for_inference` (`timing.py:1036`) already runs only the lower solutions when `timeLimitToTle` is unset. Make that the only behavior, and delete the machinery whose sole purpose was to explain the cap's effect on the upper side.

**Files:**
- Modify: `rbx/box/timing.py:791-1122` (`_InferenceCap`, `_diagnose_inference_run`, `_report_inference_diagnosis`, `_warn_if_the_cap_bounded_the_estimate`, `_InferenceRun`, `_run_for_inference`)
- Test: `tests/rbx/box/test_timing_inference_run.py`

**Step 1: Update the tests to describe one phase-1 run**

`test_timing_inference_run.py` asserts against `run_solutions.call_args`. Rewrite the affected cases so they pin phase 1's contract:

- `test_multipliers_with_tle_ratio_runs_both_capped` becomes `test_the_estimation_run_only_runs_lower_solutions`: with `timeLimitToTle` set, `tracked_solutions` still contains only the lower solutions, and `timelimit_override` is `inferenceTimeout`.
- `test_an_upper_solution_at_the_cap_is_dropped_with_a_warning` is deleted; no upper solution runs in phase 1. Its replacement lands in Task 7.
- `test_formula_mode_runs_only_lower_solutions_under_the_cap`, `test_multipliers_without_tle_ratio_runs_only_lower_solutions`, `test_the_estimation_run_never_doubles_the_time_limit`, and `test_only_lower_solutions_gate_the_run_report` stay as they are — they already describe the new behavior.

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing_inference_run.py -v`
Expected: FAIL — the run still tracks the upper solutions.

**Step 3: Make phase 1 lower-only**

In `_run_for_inference`, delete the `upper_solutions` block (`timing.py:1053-1058`) and every use of it: `tracked_solutions` becomes the lower solutions, the status message is always `'Running ACCEPTED solutions...'`, and `gating_solutions` covers every solution that ran.

`_InferenceCap` loses `time_limit_to_tle` and `largest_bounded_limit`; it is now just the timeout, so collapse it into a plain `int` on `_InferenceRun` and delete the dataclass. `_diagnose_inference_run` loses `dropped_upper` and `failed_upper` — with no upper solution in the run, only `truncated_lower` remains, which is the fatal case. Delete `_warn_if_the_cap_bounded_the_estimate` (`timing.py:957-995`), `_failed_upper_message` (`:868`), and `_InferenceRun.dropped_upper_per_language` (`:1009`), along with their call sites in `compute_time_limits` (`:1148-1158`).

**Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_timing_inference_run.py tests/rbx/box/test_timing.py -v`
Expected: PASS. `estimate_time_limit` already tolerates an empty upper side — `_upper_timings` returns `None`, `compute_bounds` leaves `upper=None`, and `TimingBounds.fits` is then trivially true — so at this point `rbx time` produces an unvalidated estimate. That is the intended intermediate state.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py tests/rbx/box/test_timing_inference_run.py
git commit  # refactor(timing): run only accepted solutions while estimating
```

---

### Task 5: Let the profile record a violated upper bound instead of raising

`_check_bounds` (`timing.py:226`) raises `TimingRangeError` when the quantized limit exceeds the upper bound. The "proceed anyway" exit and the no-picker path both need to build that profile regardless, with the violation recorded.

**Files:**
- Modify: `rbx/box/timing.py:226-303` (`_check_bounds`, `make_multipliers_eval`, `make_multipliers_derive`), `rbx/box/timing.py:349-415` (`build_timing_profile`)
- Test: `tests/rbx/box/test_timing_bounds.py`

**Step 1: Write the failing test**

Add to `tests/rbx/box/test_timing_bounds.py`:

```python
def test_a_forced_estimate_keeps_the_limit_that_violates_the_upper_bound():
    multipliers = schema.TimingMultipliers(
        acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100
    )
    measured = timing_groups.GroupMeasurements(
        lower=timing_groups.GroupTimings(
            fastest=500, slowest=500, solution_count=1, slowest_solution='sols/ac.cpp'
        ),
        upper=timing_groups.UpperTimings(
            fastest_slow=1100, fastest_slow_solution='sols/slow.cpp'
        ),
    )
    # acToTimeLimit puts the limit at 1000 ms; timeLimitToTle caps it at 733 ms.
    with pytest.raises(timing_groups.TimingRangeError):
        timing.make_multipliers_eval(multipliers)(measured)

    forced = timing.make_multipliers_eval(multipliers, force=True)(measured)
    assert forced.time_limit == 1000
    assert forced.upper_bound == schema.TimingBound(
        value=733, solution='sols/slow.cpp'
    )
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_bounds.py -k forced -v`
Expected: FAIL, `TypeError: make_multipliers_eval() got an unexpected keyword argument 'force'`

**Step 3: Write minimal implementation**

Give `_check_bounds` a `force` parameter that returns the limit instead of raising, and thread it through both factories and `build_timing_profile`:

```python
def _check_bounds(
    bounds: TimingBounds,
    multipliers: schema.TimingMultipliers,
    measured: timing_groups.GroupMeasurements,
    force: bool = False,
) -> int:
    """Return the quantized limit if the group's slow solutions allow it, else
    raise naming the binding solution on each side and the knob to turn.

    ``force`` keeps the limit anyway. The violation is not swallowed: it stays
    visible in the group's recorded bounds, and the caller is responsible for
    telling the setter about it.
    """
    if bounds.fits or force:
        return bounds.time_limit
```

The rest of the function is unchanged. `make_multipliers_eval(multipliers, force=False)` and `make_multipliers_derive(multipliers, force=False)` pass it on, and `build_timing_profile(..., force: bool = False)` passes it to both factories.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_bounds.py -v`
Expected: PASS

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py tests/rbx/box/test_timing_bounds.py
git commit  # feat(timing): allow forcing a limit past a violated upper bound
```

---

### Task 6: Extract an estimation context so the picker can be re-entered

The picker currently runs inside `estimate_time_limit` (`timing.py:739-754`), which measures, prompts, and builds in one pass. The loop needs to prompt and build repeatedly against measurements that change between iterations. Split the function without changing behavior yet.

**Files:**
- Modify: `rbx/box/timing.py:654-788`
- Test: `tests/rbx/box/test_timing.py`, `tests/rbx/box/test_timing_estimation.py`

**Step 1: Introduce the context**

Extract everything `estimate_time_limit` does *before* the picker into a dataclass built by a new coroutine:

```python
@dataclasses.dataclass
class _EstimationContext:
    """Phase 1's measurements, ready to be estimated from repeatedly.

    The picker may be re-entered once phase 2 has something to say, so the parts
    that do not change between iterations are computed once.
    """

    strategy: timing_config.TimingStrategy
    env_groups: List[environment.LanguageGroup]
    all_languages: List[str]
    lower_timings: Dict[str, Dict[str, int]]
    upper_solutions: List[Solution]

    @property
    def can_prompt(self) -> bool:
        """Whether there is a grouping decision for the setter to make."""
        return len(self.all_languages) > 1
```

`build_estimation_context(console, result, strategy)` performs the current work of `timing.py:663-736`: keying the evaluations, splitting by `inference_role_of`, measuring the lower side with `_timings_per_language`, printing the "Time report" rule and the headline measurements, resolving the strategy and `all_languages`. Note that `relevant_languages_for_estimation` currently pools the slow and dropped languages into `timing_languages` (`:730-737`); keep that, sourcing the slow languages from `upper_solutions` via `find_language_name`, so a language present only on the slow side still gets a group.

`estimate_time_limit` keeps its signature and becomes: build the context, prompt once if `not auto and ctx.can_prompt`, build the profile. Every existing test of it must still pass untouched.

**Step 2: Run the tests**

Run: `uv run pytest tests/rbx/box/test_timing.py tests/rbx/box/test_timing_estimation.py -v`
Expected: PASS with no test changes. This task is a pure refactor; if a test needs changing, the extraction changed behavior and is wrong.

**Step 3: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py
git commit  # refactor(timing): extract the estimation context from the estimate
```

---

### Task 7: Phase 2 — validate the estimate against the slow solutions

**Files:**
- Modify: `rbx/box/timing.py`, `rbx/box/timing_validation.py`
- Test: `tests/rbx/box/test_timing_phase_two.py` (create)

**Step 1: Write the failing test**

```python
"""Phase 2 checks the estimated limit against the solutions expected to be slow."""

# Follow the mocking setup of `tests/rbx/box/test_timing_inference_run.py::_compute`:
# patch `rbx.box.timing.run_solutions`, `print_run_report`,
# `consume_and_key_evaluation_items`, `find_language_name` and
# `rbx.box.environment.get_environment`.


async def test_each_language_is_probed_at_its_own_limit(...):
    # profile: timeLimit 1000, timeLimitPerLanguage {'cpp': 1000, 'py': 4000},
    # timeLimitToTle 1.5
    # -> run_solutions gets timelimit_override={'cpp': 1500, 'py': 6000}
    ...


async def test_a_slow_solution_that_times_out_is_confirmed(...):
    # TLE at the probe limit -> confirmed, contributes no measurement,
    # the profile validates
    ...


async def test_a_slow_solution_that_finishes_violates_the_bound(...):
    # finished at 1200 ms under a 1500 ms probe -> violation carrying 1200 ms
    ...


async def test_only_the_solutions_whose_probe_grew_are_re_run(...):
    # knowledge already holds a timeout at 1500; re-validating at 1200 runs nothing,
    # re-validating at 1600 runs it again
    ...


async def test_the_validation_run_never_doubles_the_time_limit(...):
    # verification stays ALL_SOLUTIONS, so isDoubleTL is off and the probe limit
    # is enforced as computed
    ...
```

Fill these in against the real signatures as you implement; the assertions above are the contract.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing_phase_two.py -v`
Expected: FAIL — the driver does not exist.

**Step 3: Write the driver**

In `rbx/box/timing.py`:

```python
@dataclasses.dataclass
class _ValidationOutcome:
    """What checking a candidate profile's upper bound found."""

    # Slow solutions confirmed too slow, keyed by language.
    confirmed_per_language: Dict[str, List[str]]
    # Slow solutions that finished, with their real time, keyed by language.
    violating_per_language: Dict[str, Dict[str, int]]

    @property
    def ok(self) -> bool:
        return not any(self.violating_per_language.values())


async def _validate_upper_bound(
    profile: TimingProfile,
    upper_solutions: List[Solution],
    knowledge: timing_validation.SlowKnowledge,
    check: bool,
    detailed: bool,
    runs: int,
) -> _ValidationOutcome:
    """Run each slow solution at its language's probe limit and say what it proved.

    Only the solutions whose answer is not already known are run: `knowledge`
    carries what earlier iterations of the picker loop established, and a lower
    limit never needs re-asking.
    """
```

The body:

1. `multipliers = profile.multipliers`; assert `multipliers.timeLimitToTle is not None` (the caller checks).
2. Per solution, `lang = find_language_name(solution)`, `tl = profile.timeLimitPerLanguage.get(lang, profile.timeLimit)`, `limit = timing_validation.probe_limit(tl, multipliers.timeLimitToTle)`.
3. Partition into solutions that `knowledge.needs_run(path, limit)` and those that do not.
4. If any need running, call `run_solutions` with `tracked_solutions` set to just those, `timelimit_override={lang: limit}` built from step 2, `verification=_INFERENCE_VERIFICATION`, `nruns=runs`, `check=check`, and `abort_on=lambda ctx: ctx.evaluation.result.outcome.is_slow()` — the first TLE settles that solution, so the remaining testcases only cost wall clock.
5. Print the run report under a `'Run report (upper-bound validation)'` rule with `gating_solutions` set to the slow solutions: here a TLE is the expected verdict, so the ordinary report machinery already flags a solution that finished.
6. Feed the outcome into `knowledge`: a solution whose evaluations contain a slow outcome gets `record_timeout(path, limit)`; otherwise `record_time(path, max_time)` using `_timings_per_language`.
7. Build `_ValidationOutcome` from `knowledge` over *all* the slow solutions, not just the ones that ran this round.

The violating measurements are exactly what `build_timing_profile` already takes as `slow_timing_per_solution_per_language`, and the confirmed list is what `dropped_upper_per_language` used to carry — so the existing plumbing into `timing_groups` and `TimingGroupReport` works unchanged, with `timing_groups.py:203-208` writing `upperValidation` from Task 2.

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/box/test_timing_phase_two.py -v`
Expected: PASS

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py rbx/box/timing_validation.py tests/rbx/box/test_timing_phase_two.py
git commit  # feat(timing): validate the estimated limit against slow solutions
```

---

### Task 8: A "proceed anyway" exit in the group picker

**Files:**
- Modify: `rbx/box/timing_group_picker.py:10-24` (`GroupAssignment`, `LEGEND_LINES`), `:300-478` (`prompt_group_assignment`)
- Test: `tests/rbx/box/test_timing_group_picker.py`

**Step 1: Write the failing test**

Follow the existing `create_pipe_input` + `DummyOutput` harness in that file:

```python
async def test_f_accepts_the_current_assignment_despite_a_violation():
    with create_pipe_input() as inp:
        inp.send_text('f')
        result = await timing_group_picker.prompt_group_assignment(
            ['cpp', 'py'], {'cpp': 0, 'py': 0}, allow_force=True,
            input=inp, output=DummyOutput(),
        )
    assert result is not None
    assert result.force


async def test_f_does_nothing_when_there_is_nothing_to_override():
    # Without a violation the key is inert, so the picker is still open and the
    # following enter is what confirms it.
    with create_pipe_input() as inp:
        inp.send_text('f\r')
        result = await timing_group_picker.prompt_group_assignment(
            ['cpp', 'py'], {'cpp': 0, 'py': 0}, input=inp, output=DummyOutput(),
        )
    assert result is not None
    assert not result.force
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -k force -v`
Expected: FAIL, `TypeError: prompt_group_assignment() got an unexpected keyword argument 'allow_force'`

**Step 3: Write minimal implementation**

Add `force: bool = False` to `GroupAssignment`. Give `prompt_group_assignment` an `allow_force: bool = False` parameter, and bind the key behind a `Condition`:

```python
    forcing = Condition(lambda: allow_force)

    @kb.add('f', filter=not_editing & forcing)
    def _(event):
        state.done = True
        event.app.exit(
            result=GroupAssignment(
                numbers=state.assignment(),
                relatives=state.prune_relatives(),
                force=True,
            )
        )
```

`LEGEND_LINES` is a module constant, so make the hint line depend on `allow_force`: turn the last line into a function of the flag, or append `' · f keep this limit anyway'` to it when the flag is set. Keep the legend's existing width discipline.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -v`
Expected: PASS

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing_group_picker.py tests/rbx/box/test_timing_group_picker.py
git commit  # feat(timing): let the group picker keep a violating limit
```

---

### Task 9: The loop, and `--skip-slow`

**Files:**
- Modify: `rbx/box/timing.py` (`estimate_time_limit`, `compute_time_limits`), `rbx/box/cli.py:549-709`
- Test: `tests/rbx/box/test_timing.py`, `tests/rbx/box/test_timing_cli.py`

**Step 1: Write the failing tests**

In `tests/rbx/box/test_timing.py`:

```python
async def test_a_violation_reopens_the_picker_and_the_repick_is_written(...):
    # phase 2 finds a violation; the picker returns a new assignment; phase 2
    # revalidates and passes; exactly one profile is written, carrying the
    # re-picked limits
    ...


async def test_forcing_past_a_violation_writes_the_violating_limit(...):
    # picker returns force=True; no further validation runs; the profile is
    # written with `upperValidation.violating` recording the offending solution
    ...


async def test_cancelling_the_picker_writes_nothing(...):
    # picker returns None -> compute_time_limits returns None, no file on disk
    ...


async def test_a_violation_with_no_picker_warns_and_writes(...):
    # auto=True -> the profile is written, the violation is recorded, and
    # compute_time_limits returns the profile rather than None
    ...


async def test_skip_slow_stops_after_the_estimate(...):
    # run_solutions is called exactly once; the slow solutions are recorded as
    # skipped in the profile
    ...
```

In `tests/rbx/box/test_timing_cli.py`, assert `--skip-slow` reaches `compute_time_limits`.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing.py tests/rbx/box/test_timing_cli.py -v`
Expected: FAIL

**Step 3: Write the loop**

`compute_time_limits` gains `skip_slow: bool = False` and becomes:

```python
    run = await _run_for_inference(check=check, detailed=detailed, runs=runs, formula=formula)
    if run is None:
        return None

    ctx = await build_estimation_context(console.console, run.result, run.strategy)
    knowledge = timing_validation.SlowKnowledge()

    multipliers = ctx.strategy.multipliers
    validates = (
        not skip_slow
        and multipliers is not None
        and multipliers.timeLimitToTle is not None
        and bool(ctx.upper_solutions)
    )

    violation: Optional[_ValidationOutcome] = None
    while True:
        picked = await ctx.prompt(
            auto=auto,
            knowledge=knowledge,
            allow_force=violation is not None,
        )
        if picked is None:
            console.console.print('[error]Time limit estimation cancelled.[/error]')
            return None

        profile = ctx.build(picked, knowledge=knowledge, force=picked.force)
        if profile is None:
            return None

        if not validates or picked.force:
            break

        outcome = await _validate_upper_bound(
            profile, ctx.upper_solutions, knowledge,
            check=check, detailed=detailed, runs=runs,
        )
        if outcome.ok:
            break

        violation = outcome
        _report_violation(outcome)
        if auto or not ctx.can_prompt:
            # Nothing to re-pick: record it, say so loudly, and write anyway.
            profile = ctx.build(picked, knowledge=knowledge, force=True)
            break
```

then the existing write-the-profile block, unchanged.

`ctx.prompt(auto, knowledge, allow_force)` returns a default `GroupAssignment` without prompting when `auto or not self.can_prompt`, and otherwise calls `_prompt_repartition`, passing `allow_force` down to the picker and the knowledge-derived slow measurements into `build_preview_renderer`. Build a fresh preview renderer each call: its `lru_cache` closes over the measurements, which change between iterations.

`ctx.build(picked, knowledge, force)` calls `build_timing_profile` with `slow_timing_per_solution_per_language` and the confirmed/skipped lists derived from `knowledge`, catching `TimingRangeError` only when `force` is false — an un-forced range error at this point means the *preview* was infeasible, which the picker already showed, so print it and return `None`.

`_report_violation` prints, per offending solution, its measured time, the limit its group got, and the bound `timeLimitToTle` implies — reusing the wording of `_check_bounds`.

**Step 4: Add the CLI flag**

In `rbx/box/cli.py`, add to the `time` command:

```python
    skip_slow: bool = typer.Option(
        False,
        '--skip-slow',
        help='Skip the phase that checks the estimated limit against the solutions '
        'expected to be too slow. The limit is estimated and written with its upper '
        'bound unchecked.',
    ),
```

and pass `skip_slow=skip_slow` to `compute_time_limits`.

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_timing.py tests/rbx/box/test_timing_cli.py -v`
Expected: PASS

**Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py rbx/box/cli.py tests/
git commit  # feat(timing): split rbx time into estimation and validation phases
```

---

### Task 10: Docs, CLI spec, and the full sweep

**Files:**
- Modify: `docs/` (wherever `inferenceTimeout` and `timeLimitToTle` are documented), `rbx/box/completion/_spec.py` if the new flag must be registered
- Verify: the whole suite

**Step 1: Find the docs that describe the old one-step behavior**

Run: `grep -rn 'inferenceTimeout\|timeLimitToTle' docs/`
Update the prose: slow solutions are no longer run under `inferenceTimeout`, so raising it no longer helps them, and `inferenceTimeout` now caps only the accepted solutions. Document `--skip-slow` and the two phases.

**Step 2: Check the completion spec**

Run: `uv run pytest tests/rbx/box/completion -v`
If a drift test fails on the new `--skip-slow` flag, regenerate the spec as that test's message directs. Note the pre-existing drift recorded for the `tut`/`tutorials` command — do not "fix" that here.

**Step 3: Run the full suite**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: PASS except the pre-existing local failures (C++/sandbox-dependent tests, `test_compute_walltime_uses_active_environment`, the completion drift). Compare against `git stash`-free baseline on `main` if anything looks new.

Run: `uv run pytest tests/rbx/box/cli -v`
Expected: PASS

**Step 4: Exercise it for real**

Build a fixture package that has both an accepted solution and one expected to be too slow, and run `uv run rbx time` in it. Confirm the console shows two run reports, that the second enforces the probe limit, and that `.limits/local.yml` carries `upperValidation`.

**Step 5: Lint, then commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add docs/ rbx/
git commit  # docs(timing): document the two-phase time limit estimation
```

---

### Task 11: Open the PR

```bash
git push -u origin worktree-time-two-phase
gh pr create --draft --title 'feat(timing): split rbx time into estimation and validation phases' --body '...'
```

The body should explain the two phases, the picker loop and its three exits, `--skip-slow`, the `upperValidation` profile field replacing `droppedUpper`, and that `--auto` warns rather than fails on a violated upper bound. Close with `Closes #693`.

Note: `gh pr edit`/`gh pr view` fail against this repo with a classic-Projects GraphQL error; use `gh api -X PATCH repos/rsalesc/rbx/pulls/N` to amend the PR afterwards.
