# Language Groups for Time-Limit Estimation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let related languages share an estimated time-limit bucket so languages without a solution inherit a sibling's limit (or a configured multiplier) instead of silently defaulting to a tight base TL, and surface a per-group TL table after `rbx time` and at BOCA package build.

**Architecture:** Approach A — groups are an *estimation-time* abstraction defined in `env.rbx.yml` (`timing.groups`). `rbx time` pools accepted-solution timings per group, estimates per-group TLs, resolves empty groups via a `whenEmpty` multiplier rule (or base TL + loud warning), then **compiles down** to the existing per-language `modifiers[lang].time` entries the rest of the system already consumes. A new optional `groups` metadata list on `LimitsProfile` records the resolved grouping so a shared table renderer can present it (live after `rbx time`, and from the saved profile at BOCA build). No consumer (`timelimit_for_language`, BOCA packager) changes resolution behavior.

**Tech Stack:** Python 3, Pydantic v2, Typer, `questionary` (interactive prompts), `rich` (tables), pytest. Single quotes, absolute imports only (ruff `TID`).

**Design doc:** `docs/plans/2026-06-01-language-groups-timing-design.md`

**Reference commands:**
- Run a test: `uv run pytest tests/path/test.py::test_name -v`
- Lint+format before each commit: `uv run ruff check --fix . && uv run ruff format .`
- Commits MUST follow Conventional Commits (commitizen). Use the `.claude/skills/commit.md` workflow: stage by name, HEREDOC message, append `Co-Authored-By: Claude <noreply@anthropic.com>`. Never amend; on hook rejection make a NEW commit.

**Pre-existing test caveat (from memory):** some C++/checker/validator/sandbox/docker tests fail on this machine regardless of our changes — do not treat those as regressions. Our new tests must be pure-Python and not depend on the sandbox.

---

## Task 1: Env schema — `LanguageGroup` / `LanguageGroupFallback` + `TimingConfig.groups`

**Files:**
- Modify: `rbx/box/environment.py` (add models near `TimingConfig` at line 276; extend `TimingConfig`)
- Test: `tests/rbx/box/test_environment_groups.py` (create)

**Step 1: Write the failing test**

```python
import pytest
from pydantic import ValidationError

from rbx.box.environment import (
    LanguageGroup,
    LanguageGroupFallback,
    TimingConfig,
)


def test_timing_config_defaults_to_no_groups():
    cfg = TimingConfig()
    assert cfg.groups == []


def test_language_group_with_when_empty_parses():
    cfg = TimingConfig.model_validate(
        {
            'groups': [
                {'languages': ['c', 'cpp']},
                {
                    'languages': ['java', 'kotlin'],
                    'whenEmpty': {'relativeTo': 'cpp', 'multiplier': 2.0},
                },
            ]
        }
    )
    assert cfg.groups[0].languages == ['c', 'cpp']
    assert cfg.groups[1].whenEmpty == LanguageGroupFallback(
        relativeTo='cpp', multiplier=2.0
    )


def test_language_cannot_appear_in_two_groups():
    with pytest.raises(ValidationError, match='cpp'):
        TimingConfig.model_validate(
            {'groups': [{'languages': ['c', 'cpp']}, {'languages': ['cpp']}]}
        )


def test_when_empty_requires_multiplier():
    with pytest.raises(ValidationError):
        LanguageGroupFallback.model_validate({'relativeTo': 'cpp'})
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_environment_groups.py -v`
Expected: FAIL with ImportError (`LanguageGroup` not defined).

**Step 3: Implement the models**

In `rbx/box/environment.py`, immediately before `class TimingConfig` (line 276):

```python
class LanguageGroupFallback(BaseModel):
    model_config = ConfigDict(extra='forbid')

    relativeTo: Optional[str] = Field(
        default=None,
        description="""A language name whose group's estimated TL this empty group is
relative to. If omitted, the multiplier is applied to the base estimate.""",
    )
    multiplier: float = Field(
        description="""Multiplier applied when this group has no solutions.""",
    )


class LanguageGroup(BaseModel):
    model_config = ConfigDict(extra='forbid')

    languages: List[str] = Field(
        description="""rbx language names that share a single estimated time limit.""",
    )
    whenEmpty: Optional[LanguageGroupFallback] = Field(
        default=None,
        description="""How to derive a TL for this group when it has no solutions.""",
    )
```

Extend `TimingConfig` (add field after `formula`):

```python
    groups: List[LanguageGroup] = Field(
        default_factory=list,
        description="""Groups of related languages that share an estimated time limit.""",
    )

    @model_validator(mode='after')
    def _validate_disjoint_groups(self):
        seen: set[str] = set()
        for group in self.groups:
            for lang in group.languages:
                if lang in seen:
                    raise ValueError(
                        f'Language {lang!r} appears in more than one timing group; '
                        'groups must be disjoint.'
                    )
                seen.add(lang)
        return self
```

Ensure `model_validator` is imported from `pydantic` at the top of the file (check existing imports; add to the existing `from pydantic import ...` line if missing). `Optional`, `List`, `Field`, `ConfigDict` are already imported (used by surrounding models).

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_environment_groups.py -v`
Expected: PASS (4 tests).

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/environment.py tests/rbx/box/test_environment_groups.py
# commit: feat(timing): add language group config to env schema
```

---

## Task 2: `LimitsProfile` group metadata models

**Files:**
- Modify: `rbx/box/schema.py` (add `TimingGroupOrigin`, `TimingGroupReport` near `LimitModifiers` line 630; add `groups` field to `LimitsProfile` ~line 797)
- Test: `tests/rbx/box/test_limits_profile_groups.py` (create)

**Step 1: Write the failing test**

```python
from rbx.box.schema import LimitsProfile, TimingGroupOrigin, TimingGroupReport


def test_limits_profile_groups_defaults_to_none():
    profile = LimitsProfile(timeLimit=1000)
    assert profile.groups is None


def test_limits_profile_round_trips_group_metadata():
    profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['c', 'cpp'],
                timeLimit=1000,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=2,
                fastest=280,
                slowest=600,
            ),
            TimingGroupReport(
                languages=['java', 'kotlin'],
                timeLimit=4000,
                origin=TimingGroupOrigin.MULTIPLIER,
                relativeToLanguage='cpp',
                multiplier=4.0,
            ),
        ],
    )
    reloaded = LimitsProfile.model_validate(profile.model_dump())
    assert reloaded.groups is not None
    assert reloaded.groups[1].origin == TimingGroupOrigin.MULTIPLIER
    assert reloaded.groups[1].relativeToLanguage == 'cpp'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_limits_profile_groups.py -v`
Expected: FAIL with ImportError.

**Step 3: Implement the models**

In `rbx/box/schema.py`, after `class LimitModifiers` (line 639). Confirm `enum` is importable; the file already imports many stdlib types — add `import enum` at top if absent, or reuse the existing AutoEnum/str-Enum pattern used by `ExpectedOutcome`. Use a plain `str, enum.Enum`:

```python
class TimingGroupOrigin(str, enum.Enum):
    ESTIMATED = 'estimated'
    MULTIPLIER = 'multiplier'
    DEFAULTED = 'defaulted'


class TimingGroupReport(BaseModel):
    model_config = ConfigDict(extra='forbid')

    languages: List[str]
    timeLimit: int
    origin: TimingGroupOrigin
    solutionCount: int = 0
    fastest: Optional[int] = None
    slowest: Optional[int] = None
    relativeToLanguage: Optional[str] = None
    multiplier: Optional[float] = None
```

In `class LimitsProfile`, after the `formula` field (line ~797), add:

```python
    groups: Optional[List[TimingGroupReport]] = Field(
        default=None,
        description="""
Metadata describing the language grouping used when this profile was estimated.
Presentation-only; never used for limit resolution.
""",
    )
```

`extra='forbid'` on `LimitsProfile` (line 764) means older files without `groups` still load (absent optional field is fine), and unknown keys still error as before.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_limits_profile_groups.py -v`
Expected: PASS (2 tests).

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/schema.py tests/rbx/box/test_limits_profile_groups.py
# commit: feat(timing): add optional group metadata to LimitsProfile
```

---

## Task 3: Pure partition builder

A new module holds all pure grouping logic so it is unit-testable without the sandbox.

**Files:**
- Create: `rbx/box/timing_groups.py`
- Test: `tests/rbx/box/test_timing_groups.py` (create)

**Step 1: Write the failing test**

```python
from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.timing_groups import ResolvedGroup, build_partition


def test_implicit_singletons_for_unlisted_languages():
    groups = build_partition(
        env_groups=[LanguageGroup(languages=['c', 'cpp'])],
        all_languages=['c', 'cpp', 'python'],
    )
    # one explicit group + one implicit singleton, order preserved
    assert [g.languages for g in groups] == [['c', 'cpp'], ['python']]
    assert groups[0].whenEmpty is None


def test_partition_preserves_when_empty():
    groups = build_partition(
        env_groups=[
            LanguageGroup(
                languages=['java', 'kotlin'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            )
        ],
        all_languages=['java', 'kotlin'],
    )
    assert groups[0].whenEmpty.multiplier == 2.0
```

`ResolvedGroup` is a small dataclass/BaseModel: `languages: List[str]`, `whenEmpty: Optional[LanguageGroupFallback]`.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: FAIL with ImportError.

**Step 3: Implement**

```python
from typing import Dict, List, Optional

from pydantic import BaseModel

from rbx.box.environment import LanguageGroup, LanguageGroupFallback


class ResolvedGroup(BaseModel):
    languages: List[str]
    whenEmpty: Optional[LanguageGroupFallback] = None


def build_partition(
    env_groups: List[LanguageGroup],
    all_languages: List[str],
) -> List[ResolvedGroup]:
    """Build a disjoint partition: explicit env groups first (in order), then an
    implicit singleton for every language not covered by an explicit group."""
    grouped: set[str] = set()
    result: List[ResolvedGroup] = []
    for group in env_groups:
        result.append(
            ResolvedGroup(languages=list(group.languages), whenEmpty=group.whenEmpty)
        )
        grouped.update(group.languages)
    for lang in all_languages:
        if lang not in grouped:
            result.append(ResolvedGroup(languages=[lang]))
            grouped.add(lang)
    return result
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing_groups.py tests/rbx/box/test_timing_groups.py
# commit: feat(timing): add pure language-group partition builder
```

---

## Task 4: Pure group resolution → reports + per-language TLs

This is the heart: given per-group pooled timings and a formula evaluator, produce the base TL, the per-group `TimingGroupReport`s, and the expanded `lang -> tl` modifier map. Empty groups resolve via `whenEmpty` (transitively, acyclic).

**Files:**
- Modify: `rbx/box/timing_groups.py`
- Test: `tests/rbx/box/test_timing_groups.py` (extend)

**Step 1: Write the failing tests**

```python
from rbx.box.schema import TimingGroupOrigin
from rbx.box.timing_groups import GroupTimings, resolve_groups


def _eval(fastest, slowest):
    # simple deterministic formula for tests: max(fastest*3, slowest*2)
    return max(fastest * 3, slowest * 2)


def test_resolves_estimated_and_multiplier_and_default_groups():
    groups = [
        ResolvedGroup(languages=['c', 'cpp']),
        ResolvedGroup(
            languages=['java', 'kotlin'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=4.0),
        ),
        ResolvedGroup(languages=['go']),  # empty, no whenEmpty -> DEFAULTED
        ResolvedGroup(languages=['python']),
    ]
    timings = {
        'cpp': GroupTimings(fastest=100, slowest=200, solution_count=2),
        'python': GroupTimings(fastest=500, slowest=500, solution_count=1),
    }
    # keyed by GROUP INDEX -> pooled timings of that group (only non-empty groups present)
    pooled = {0: timings['cpp'], 3: timings['python']}
    base = GroupTimings(fastest=100, slowest=500, solution_count=3)

    result = resolve_groups(groups, pooled, base, _eval)

    assert result.base_time_limit == _eval(100, 500)  # 1000
    by_lang = result.time_limit_per_language
    # cpp group estimated
    assert by_lang['cpp'] == _eval(100, 200)  # 400
    assert by_lang['c'] == 400
    # jvm group: multiplier of cpp's TL
    assert by_lang['java'] == int(400 * 4.0)
    assert by_lang['kotlin'] == int(400 * 4.0)
    # go defaulted to base -> NO modifier emitted (uses base TL)
    assert 'go' not in by_lang
    # python estimated
    assert by_lang['python'] == _eval(500, 500)  # 1500

    origins = {tuple(r.languages): r.origin for r in result.reports}
    assert origins[('c', 'cpp')] == TimingGroupOrigin.ESTIMATED
    assert origins[('java', 'kotlin')] == TimingGroupOrigin.MULTIPLIER
    assert origins[('go',)] == TimingGroupOrigin.DEFAULTED
    assert result.defaulted_languages == ['go']


def test_multiplier_relative_to_base_when_relative_to_omitted():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['java'],
            whenEmpty=LanguageGroupFallback(multiplier=3.0),
        ),
    ]
    pooled = {0: GroupTimings(fastest=100, slowest=100, solution_count=1)}
    base = GroupTimings(fastest=100, slowest=100, solution_count=1)
    result = resolve_groups(groups, pooled, base, _eval)
    assert result.time_limit_per_language['java'] == int(result.base_time_limit * 3.0)


def test_multiplier_chain_through_another_empty_group():
    # jvm relativeTo cpp; mobile relativeTo java -> resolves transitively
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['java'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        ),
        ResolvedGroup(
            languages=['dart'],
            whenEmpty=LanguageGroupFallback(relativeTo='java', multiplier=2.0),
        ),
    ]
    pooled = {0: GroupTimings(fastest=100, slowest=100, solution_count=1)}
    base = GroupTimings(fastest=100, slowest=100, solution_count=1)
    result = resolve_groups(groups, pooled, base, _eval)
    cpp_tl = result.time_limit_per_language['cpp']
    assert result.time_limit_per_language['java'] == cpp_tl * 2
    assert result.time_limit_per_language['dart'] == cpp_tl * 2 * 2
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: FAIL with ImportError (`GroupTimings`, `resolve_groups`).

**Step 3: Implement**

Add to `rbx/box/timing_groups.py`:

```python
from typing import Callable

from rbx.box.schema import TimingGroupOrigin, TimingGroupReport


class GroupTimings(BaseModel):
    fastest: int
    slowest: int
    solution_count: int


class ResolutionResult(BaseModel):
    base_time_limit: int
    reports: List[TimingGroupReport]
    time_limit_per_language: Dict[str, int]
    defaulted_languages: List[str]


EvalFn = Callable[[int, int], int]


def _lang_to_group_index(groups: List[ResolvedGroup]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for idx, group in enumerate(groups):
        for lang in group.languages:
            out[lang] = idx
    return out


def resolve_groups(
    groups: List[ResolvedGroup],
    pooled: Dict[int, GroupTimings],  # group index -> pooled timings (non-empty only)
    base: GroupTimings,
    eval_fn: EvalFn,
) -> ResolutionResult:
    base_tl = eval_fn(base.fastest, base.slowest)
    lang_index = _lang_to_group_index(groups)

    resolved_tl: Dict[int, int] = {}
    resolved_report: Dict[int, TimingGroupReport] = {}
    resolving: set[int] = set()  # cycle guard (validation should prevent cycles)

    def resolve(idx: int) -> int:
        if idx in resolved_tl:
            return resolved_tl[idx]
        if idx in resolving:
            # Acyclic is guaranteed by env validation; fall back defensively.
            return base_tl
        resolving.add(idx)
        group = groups[idx]
        timings = pooled.get(idx)
        if timings is not None:
            tl = eval_fn(timings.fastest, timings.slowest)
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=timings.solution_count,
                fastest=timings.fastest,
                slowest=timings.slowest,
            )
        elif group.whenEmpty is not None:
            ref = group.whenEmpty.relativeTo
            ref_tl = base_tl if ref is None else resolve(lang_index[ref])
            tl = int(ref_tl * group.whenEmpty.multiplier)
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.MULTIPLIER,
                solutionCount=0,
                relativeToLanguage=ref,
                multiplier=group.whenEmpty.multiplier,
            )
        else:
            tl = base_tl
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.DEFAULTED,
                solutionCount=0,
            )
        resolving.discard(idx)
        resolved_tl[idx] = tl
        resolved_report[idx] = report
        return tl

    for idx in range(len(groups)):
        resolve(idx)

    reports = [resolved_report[i] for i in range(len(groups))]
    tl_per_language: Dict[str, int] = {}
    defaulted: List[str] = []
    for idx, group in enumerate(groups):
        report = resolved_report[idx]
        if report.origin == TimingGroupOrigin.DEFAULTED:
            defaulted.extend(group.languages)
            continue  # uses base TL -> no modifier
        for lang in group.languages:
            tl_per_language[lang] = report.timeLimit
    return ResolutionResult(
        base_time_limit=base_tl,
        reports=reports,
        time_limit_per_language=tl_per_language,
        defaulted_languages=defaulted,
    )
```

Note: DEFAULTED groups emit no modifier (they intentionally use the base TL); this is the "loud warning" case surfaced via `defaulted_languages`.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: PASS (all tests).

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing_groups.py tests/rbx/box/test_timing_groups.py
# commit: feat(timing): resolve per-group time limits with empty-group fallback
```

---

## Task 5: env-side `whenEmpty.relativeTo` validation

`relativeTo` must name a known group language and resolve to a *different* group, and `whenEmpty` chains must be acyclic. This needs the full env (all languages), so validate it in a helper called during `rbx time` rather than inside `TimingConfig` (which doesn't know all env languages). Add a pure validator to `timing_groups.py`.

**Files:**
- Modify: `rbx/box/timing_groups.py`
- Test: `tests/rbx/box/test_timing_groups.py` (extend)

**Step 1: Write the failing tests**

```python
import pytest

from rbx.box.timing_groups import GroupValidationError, validate_partition


def test_relative_to_unknown_language_errors():
    groups = build_partition(
        env_groups=[
            LanguageGroup(
                languages=['java'],
                whenEmpty=LanguageGroupFallback(relativeTo='rust', multiplier=2.0),
            )
        ],
        all_languages=['java'],
    )
    with pytest.raises(GroupValidationError, match='rust'):
        validate_partition(groups)


def test_relative_to_same_group_errors():
    groups = build_partition(
        env_groups=[
            LanguageGroup(
                languages=['java', 'kotlin'],
                whenEmpty=LanguageGroupFallback(relativeTo='kotlin', multiplier=2.0),
            )
        ],
        all_languages=['java', 'kotlin'],
    )
    with pytest.raises(GroupValidationError, match='same group'):
        validate_partition(groups)


def test_cyclic_when_empty_errors():
    groups = build_partition(
        env_groups=[
            LanguageGroup(
                languages=['a'],
                whenEmpty=LanguageGroupFallback(relativeTo='b', multiplier=2.0),
            ),
            LanguageGroup(
                languages=['b'],
                whenEmpty=LanguageGroupFallback(relativeTo='a', multiplier=2.0),
            ),
        ],
        all_languages=['a', 'b'],
    )
    with pytest.raises(GroupValidationError, match='cycle'):
        validate_partition(groups)


def test_valid_partition_passes():
    groups = build_partition(
        env_groups=[
            LanguageGroup(languages=['cpp']),
            LanguageGroup(
                languages=['java'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            ),
        ],
        all_languages=['cpp', 'java'],
    )
    validate_partition(groups)  # no raise
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: FAIL with ImportError.

**Step 3: Implement**

```python
class GroupValidationError(ValueError):
    pass


def validate_partition(groups: List[ResolvedGroup]) -> None:
    lang_index = _lang_to_group_index(groups)
    # reference target existence + not-self
    for idx, group in enumerate(groups):
        if group.whenEmpty is None or group.whenEmpty.relativeTo is None:
            continue
        ref = group.whenEmpty.relativeTo
        if ref not in lang_index:
            raise GroupValidationError(
                f'whenEmpty.relativeTo references unknown language {ref!r}.'
            )
        if lang_index[ref] == idx:
            raise GroupValidationError(
                f'whenEmpty.relativeTo {ref!r} points to the same group; it must '
                'reference a different group.'
            )
    # cycle detection over group-to-group reference edges
    WHITE, GRAY, BLACK = 0, 1, 2
    color = [WHITE] * len(groups)

    def visit(idx: int) -> None:
        color[idx] = GRAY
        group = groups[idx]
        if group.whenEmpty is not None and group.whenEmpty.relativeTo is not None:
            nxt = lang_index[group.whenEmpty.relativeTo]
            if color[nxt] == GRAY:
                raise GroupValidationError(
                    'whenEmpty.relativeTo forms a cycle between timing groups.'
                )
            if color[nxt] == WHITE:
                visit(nxt)
        color[idx] = BLACK

    for idx in range(len(groups)):
        if color[idx] == WHITE:
            visit(idx)
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing_groups.py tests/rbx/box/test_timing_groups.py
# commit: feat(timing): validate whenEmpty references and reject cycles
```

---

## Task 6: Shared limits table renderer

A single renderer used by both `rbx time` and the BOCA packager so the table is identical. Reads a `LimitsProfile`; uses `groups` metadata when present, else degrades to per-language/base rows.

**Files:**
- Modify: `rbx/box/limits_info.py` (add `render_limits_table`)
- Test: `tests/rbx/box/test_limits_table.py` (create)

**Step 1: Write the failing test** (assert on the structured rows, not exact rich formatting)

```python
from rbx.box.limits_info import build_limits_table_rows
from rbx.box.schema import (
    LimitsProfile,
    LimitModifiers,
    TimingGroupOrigin,
    TimingGroupReport,
)


def test_rows_from_group_metadata():
    profile = LimitsProfile(
        timeLimit=2000,
        modifiers={'cpp': LimitModifiers(time=1000)},
        groups=[
            TimingGroupReport(
                languages=['c', 'cpp'],
                timeLimit=1000,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=2,
                fastest=280,
                slowest=600,
            ),
            TimingGroupReport(
                languages=['go'],
                timeLimit=2000,
                origin=TimingGroupOrigin.DEFAULTED,
            ),
        ],
    )
    rows = build_limits_table_rows(profile)
    assert rows[0].languages == 'c, cpp'
    assert rows[0].time_limit_ms == 1000
    assert rows[0].solutions == 2
    assert 'estimated' in rows[0].source.lower()
    assert rows[1].defaulted is True
    assert 'default' in rows[1].source.lower()


def test_rows_degrade_without_group_metadata():
    profile = LimitsProfile(
        timeLimit=2000, modifiers={'python': LimitModifiers(time=5000)}
    )
    rows = build_limits_table_rows(profile)
    # one base row + one per-language modifier row, in some defined order
    langs = {r.languages for r in rows}
    assert 'python' in langs
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_limits_table.py -v`
Expected: FAIL with ImportError.

**Step 3: Implement**

In `rbx/box/limits_info.py` add a small row model + builder + renderer. Keep `build_limits_table_rows` pure (testable); `render_limits_table` wraps it in a `rich.table.Table`.

```python
from pydantic import BaseModel  # add if not present
from rbx.box.schema import TimingGroupOrigin  # add to existing schema import


class LimitsTableRow(BaseModel):
    languages: str
    solutions: Optional[int]
    time_limit_ms: int
    source: str
    defaulted: bool = False


def build_limits_table_rows(profile: LimitsProfile) -> list[LimitsTableRow]:
    rows: list[LimitsTableRow] = []
    if profile.groups:
        for report in profile.groups:
            if report.origin == TimingGroupOrigin.ESTIMATED:
                source = f'estimated (fastest {report.fastest} / slowest {report.slowest})'
            elif report.origin == TimingGroupOrigin.MULTIPLIER:
                ref = report.relativeToLanguage or 'base'
                source = f'×{report.multiplier} of {ref}'
            else:
                source = 'DEFAULTED to base'
            rows.append(
                LimitsTableRow(
                    languages=', '.join(report.languages),
                    solutions=report.solutionCount,
                    time_limit_ms=report.timeLimit,
                    source=source,
                    defaulted=report.origin == TimingGroupOrigin.DEFAULTED,
                )
            )
        return rows
    # Degraded view: base row + each per-language modifier override.
    base = profile.timeLimit or 0
    rows.append(
        LimitsTableRow(
            languages='(base)', solutions=None, time_limit_ms=base, source='base'
        )
    )
    for lang, mod in sorted(profile.modifiers.items()):
        if mod.time is not None:
            rows.append(
                LimitsTableRow(
                    languages=lang,
                    solutions=None,
                    time_limit_ms=mod.time,
                    source='override',
                )
            )
    return rows


def render_limits_table(profile: LimitsProfile, title: str = 'Time limits') -> None:
    import rich.table

    table = rich.table.Table(title=title, show_lines=False)
    table.add_column('Languages')
    table.add_column('Solutions', justify='right')
    table.add_column('Time Limit', justify='right')
    table.add_column('Source')
    for row in build_limits_table_rows(profile):
        sols = '' if row.solutions is None else str(row.solutions)
        tl = f'{row.time_limit_ms} ms'
        if row.defaulted:
            table.add_row(
                f'[warning]{row.languages}[/warning]',
                sols,
                f'[warning]{tl}[/warning]',
                f'[warning]⚠ {row.source}[/warning]',
            )
        else:
            table.add_row(row.languages, sols, tl, row.source)
    console.console.print(table)
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_limits_table.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/limits_info.py tests/rbx/box/test_limits_table.py
# commit: feat(timing): add shared per-group limits table renderer
```

---

## Task 7: Interactive repartition helper

A pure helper that turns a `{language: group_number}` map into a partition, applying the `whenEmpty` preservation rule (carry over env `whenEmpty` only for groups whose membership is byte-identical to an env group). The `questionary` prompt is a thin wrapper added in Task 8.

**Files:**
- Modify: `rbx/box/timing_groups.py`
- Test: `tests/rbx/box/test_timing_groups.py` (extend)

**Step 1: Write the failing tests**

```python
from rbx.box.timing_groups import partition_from_assignment


def test_assignment_zero_makes_singletons():
    env_groups = [LanguageGroup(languages=['c', 'cpp'])]
    groups = partition_from_assignment(
        assignment={'c': 0, 'cpp': 0, 'python': 0},
        env_groups=env_groups,
    )
    assert sorted(g.languages for g in groups) == [['c'], ['cpp'], ['python']]


def test_identical_membership_preserves_when_empty():
    env_groups = [
        LanguageGroup(
            languages=['java', 'kotlin'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        )
    ]
    # user kept java+kotlin together as group 1
    groups = partition_from_assignment(
        assignment={'java': 1, 'kotlin': 1, 'cpp': 2},
        env_groups=env_groups,
    )
    jvm = next(g for g in groups if set(g.languages) == {'java', 'kotlin'})
    assert jvm.whenEmpty is not None and jvm.whenEmpty.multiplier == 2.0


def test_changed_membership_drops_when_empty():
    env_groups = [
        LanguageGroup(
            languages=['java', 'kotlin'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        )
    ]
    # user added scala to the jvm bucket -> membership changed -> drop whenEmpty
    groups = partition_from_assignment(
        assignment={'java': 1, 'kotlin': 1, 'scala': 1},
        env_groups=env_groups,
    )
    jvm = next(g for g in groups if 'java' in g.languages)
    assert jvm.whenEmpty is None
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: FAIL with ImportError.

**Step 3: Implement**

```python
def partition_from_assignment(
    assignment: Dict[str, int],
    env_groups: List[LanguageGroup],
) -> List[ResolvedGroup]:
    """Build groups from a {language: number} map. 0 = own singleton; N>=1 share a
    bucket. Carries over an env group's whenEmpty only when the resulting membership
    is identical to that env group."""
    # number -> languages (preserve insertion order of assignment for stability)
    buckets: Dict[int, List[str]] = {}
    singletons: List[List[str]] = []
    for lang, number in assignment.items():
        if number == 0:
            singletons.append([lang])
        else:
            buckets.setdefault(number, []).append(lang)

    env_when_empty = {
        frozenset(g.languages): g.whenEmpty for g in env_groups
    }
    result: List[ResolvedGroup] = []
    for _, langs in sorted(buckets.items()):
        when_empty = env_when_empty.get(frozenset(langs))
        result.append(ResolvedGroup(languages=langs, whenEmpty=when_empty))
    result.extend(ResolvedGroup(languages=s) for s in singletons)
    return result
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing_groups.py tests/rbx/box/test_timing_groups.py
# commit: feat(timing): build partition from interactive group assignment
```

---

## Task 8: Rewrite `estimate_time_limit` to be group-aware

Replace the per-language selection block (`timing.py` lines 150–181) with grouping. Build the partition from env groups + all env languages, validate it, optionally run the interactive repartition prompt (skipped under `--auto`), pool timings per group, resolve, populate `TimingProfile` with `timeLimitPerLanguage` (= resolved modifiers) and the new `groups` reports, and print the DEFAULTED warning.

**Files:**
- Modify: `rbx/box/timing.py` (`TimingProfile` lines 25–38; `estimate_time_limit` lines 60–181)
- Test: `tests/rbx/box/test_timing_estimation.py` (create) — drive `estimate_time_limit` with a fabricated `RunSolutionResult`, OR refactor the timing-collection and resolution into a thin seam and test the seam. **Prefer** extracting a pure `_build_timing_profile(timing_per_solution_per_language, formula_eval, env_groups, all_languages, repartition=None)` so it is unit-testable without sandbox/questionary.

**Step 1: Write the failing test (against the extracted pure seam)**

```python
from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import TimingGroupOrigin
from rbx.box.timing import build_timing_profile


def test_build_timing_profile_groups_languages():
    # per-language -> {solution_path: max_timing_ms}
    timings = {
        'cpp': {'a.cpp': 100, 'b.cpp': 150},
        'python': {'p.py': 500},
    }
    profile = build_timing_profile(
        timing_per_solution_per_language=timings,
        formula='max(fastest * 3, slowest * 2)',
        env_groups=[
            LanguageGroup(languages=['c', 'cpp']),
            LanguageGroup(
                languages=['java', 'kotlin'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=4.0),
            ),
        ],
        all_languages=['c', 'cpp', 'java', 'kotlin', 'python'],
    )
    limits = profile.to_limits()
    assert limits.modifiers['java'].time == limits.modifiers['cpp'].time * 4
    assert limits.modifiers['c'].time == limits.modifiers['cpp'].time
    assert limits.groups is not None
    origins = {tuple(r.languages): r.origin for r in limits.groups}
    assert origins[('java', 'kotlin')] == TimingGroupOrigin.MULTIPLIER
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_estimation.py -v`
Expected: FAIL with ImportError (`build_timing_profile`).

**Step 3: Implement**

1. Extend `TimingProfile` (timing.py lines 25–38) to carry reports and wire them into `to_limits()`:

```python
class TimingProfile(BaseModel):
    timeLimit: int
    formula: Optional[str] = None
    timeLimitPerLanguage: Dict[str, int] = Field(default_factory=dict)
    groups: Optional[List[schema.TimingGroupReport]] = None

    def to_limits(self):
        return schema.LimitsProfile(
            timeLimit=self.timeLimit,
            formula=self.formula,
            modifiers={
                lang: schema.LimitModifiers(time=tl)
                for lang, tl in self.timeLimitPerLanguage.items()
            },
            groups=self.groups,
        )
```

2. Add the pure seam `build_timing_profile(...)`:

```python
from rbx.box import timing_groups


def build_timing_profile(
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    formula: str,
    env_groups,  # List[environment.LanguageGroup]
    all_languages,  # List[str]
    repartition: Optional[Dict[str, int]] = None,
) -> TimingProfile:
    def _eval(fastest: int, slowest: int) -> int:
        return int(
            safeeval.eval_int(formula, {'fastest': fastest, 'slowest': slowest})
        )

    if repartition is not None:
        groups = timing_groups.partition_from_assignment(repartition, env_groups)
    else:
        groups = timing_groups.build_partition(env_groups, all_languages)
    timing_groups.validate_partition(groups)

    # Pool timings per group index.
    pooled: Dict[int, timing_groups.GroupTimings] = {}
    all_values = []
    for idx, group in enumerate(groups):
        values = []
        count = 0
        for lang in group.languages:
            per_sol = timing_per_solution_per_language.get(lang, {})
            values.extend(per_sol.values())
            count += len(per_sol)
        if values:
            pooled[idx] = timing_groups.GroupTimings(
                fastest=min(values), slowest=max(values), solution_count=count
            )
            all_values.extend(values)

    base = timing_groups.GroupTimings(
        fastest=min(all_values), slowest=max(all_values), solution_count=len(all_values)
    )
    result = timing_groups.resolve_groups(groups, pooled, base, _eval)
    return TimingProfile(
        timeLimit=result.base_time_limit,
        formula=formula,
        timeLimitPerLanguage=result.time_limit_per_language,
        groups=result.reports,
    )
```

3. Rewrite `estimate_time_limit` (lines 150–181 region) to: build `all_languages = [l.name for l in environment.get_environment().languages]` and `env_groups = environment.get_environment().timing.groups`; when not `auto` AND more than one group would be non-trivial, run the interactive repartition prompt (Step 3b) to get an `assignment`; call `build_timing_profile(...)`; if `result`/profile has DEFAULTED languages, print a loud warning. Then `return profile`. Remove the old `questionary.checkbox` block (lines 162–175) and the `final_estimated_tls_per_language` logic.

   Keep the existing fastest/slowest **run report** prints (lines 99–148) — they are still useful — but the per-language TL decision now comes from grouping.

**Step 3b: Interactive repartition prompt** (only when `not auto`). Add a helper in `timing.py`:

```python
async def _prompt_repartition(
    all_languages: List[str], env_groups
) -> Optional[Dict[str, int]]:
    # Prepopulate numbers from env groups: group #1 -> 1, ...; unlisted -> 0.
    default_number: Dict[str, int] = {lang: 0 for lang in all_languages}
    for i, group in enumerate(env_groups, start=1):
        for lang in group.languages:
            default_number[lang] = i
    assignment: Dict[str, int] = {}
    for lang in all_languages:
        answer = await questionary.text(
            f'Group number for {lang} (0 = its own group)',
            default=str(default_number[lang]),
            validate=lambda x: x.isdigit(),
        ).ask_async()
        if answer is None:
            return None
        assignment[lang] = int(answer)
    return assignment
```

(Only prompt for languages that actually have solutions plus those listed in env groups — to avoid prompting for every exotic language. Filter `all_languages` to `set(langs_with_timings) | set(env-grouped langs)` before prompting. Document this filter in a comment.)

DEFAULTED warning (after building the profile):

```python
defaulted = [
    lang
    for report in (profile.groups or [])
    if report.origin == schema.TimingGroupOrigin.DEFAULTED
    for lang in report.languages
]
if defaulted:
    console.print(
        '[warning]⚠ The following languages have no solution and no whenEmpty rule, '
        f'so they fall back to the base time limit of {profile.timeLimit} ms: '
        f'{", ".join(defaulted)}.[/warning]'
    )
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_estimation.py -v`
Expected: PASS.
Then full timing module: `uv run pytest tests/rbx/box -k 'timing or limits or group' -v`.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py tests/rbx/box/test_timing_estimation.py
# commit: feat(timing): estimate time limits per language group
```

---

## Task 9: `rbx time` always renders the table

After `compute_time_limits` writes the profile (`timing.py` lines 238–244), render the shared table (always, regardless of `--detailed`).

**Files:**
- Modify: `rbx/box/timing.py` (`compute_time_limits`, after line 244)
- Test: covered by Task 8 unit tests + a light CLI smoke is optional (CLI tests are slow/excluded). Add an assertion-light test only if a fast fixture exists; otherwise verify manually (Step 4).

**Step 1–3: Implement**

After writing `limits_path` in `compute_time_limits`, add:

```python
from rbx.box import limits_info

limits_info.render_limits_table(
    estimated_tl.to_limits(), title=f'Time limits ({profile})'
)
```

Replace the raw `console.console.print(estimated_tl, highlight=True)` (line 242) with the table for the estimate strategy (keep the "Writing the following timing profile to ..." line). Keep `pretty_print_profile` for `inherit`/`custom` paths.

**Step 4: Manual verification**

In a fixture problem with multi-language accepted solutions and an `env.rbx.yml` defining `timing.groups`, run:
`uv run rbx time -p boca --auto` and confirm the table prints with one row per group, DEFAULTED rows highlighted.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/timing.py
# commit: feat(timing): always show per-group table after rbx time
```

---

## Task 10: BOCA packager prints the table last

Render the same table from the saved `.limits/boca.yml` at the END of `BocaPackager.package()`, after all scripts are written (so DEFAULTED warnings are the final output). No error on DEFAULTED.

**Files:**
- Modify: `rbx/box/packaging/boca/packager.py` (`package()`, return statement region after line 403; add the render just before `return`)
- Test: `tests/rbx/box/packaging/test_boca_limits_table.py` (create) — call `build_limits_table_rows` against a constructed `boca` profile to assert the rows the packager would show. (Full packaging e2e is heavy; keep the unit test on the renderer + a check that `package()` calls it.)

**Step 1: Write the failing test**

```python
from rbx.box.limits_info import build_limits_table_rows
from rbx.box.schema import LimitsProfile, TimingGroupOrigin, TimingGroupReport


def test_boca_table_flags_defaulted_language():
    profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['java'],
                timeLimit=2000,
                origin=TimingGroupOrigin.DEFAULTED,
            )
        ],
    )
    rows = build_limits_table_rows(profile)
    assert rows[0].defaulted is True
```

**Step 2: Run to verify it fails / passes**

Run: `uv run pytest tests/rbx/box/packaging/test_boca_limits_table.py -v`
(This passes already if Task 6 is done; it documents the BOCA expectation. The behavioral wiring is verified manually in Step 4.)

**Step 3: Implement**

At the end of `package()` (just before `return ...`), add:

```python
from rbx.box import limits_info

boca_profile = limits_info.get_saved_limits_profile('boca')
if boca_profile is not None:
    limits_info.render_limits_table(
        boca_profile, title='BOCA time limits (per language group)'
    )
```

Place this as the last statement before the method returns its path, so it is the final console output of the packaging step.

**Step 4: Manual verification**

`uv run rbx package boca` on a fixture with a `boca` profile; confirm the table is the last thing printed and DEFAULTED rows are highlighted, with no error raised.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/packaging/boca/packager.py tests/rbx/box/packaging/test_boca_limits_table.py
# commit: feat(boca): print per-group time-limit table at end of packaging
```

---

## Task 11: Documentation + module guides

**Files:**
- Modify: `rbx/box/CLAUDE.md` (Schema System: note `TimingGroupReport`/`TimingGroupOrigin`; Environment: note `timing.groups`)
- Modify: any user-facing docs for `env.rbx.yml` / `rbx time` under `docs/` (search for existing timing docs: `grep -rl "rbx time\|timeLimit\|env.rbx.yml" docs`)
- Test: docs build — `uv run mkdocs build` (non-strict; per memory, ~9 pre-existing strict warnings are unrelated — do not chase them).

**Steps:**
1. Document `timing.groups`, `whenEmpty.relativeTo`/`multiplier`, implicit singletons, and the DEFAULTED warning behavior.
2. Add a short example matching the design doc's `env.rbx.yml` snippet.
3. Build docs non-strict to confirm no new errors.
4. Commit: `docs: document language groups for time-limit estimation`.

---

## Final verification (before finishing the branch)

Run the full non-CLI suite plus our new tests:

```bash
uv run pytest --ignore=tests/rbx/box/cli -k 'timing or limits or group or environment or boca' -v
uv run pytest --ignore=tests/rbx/box/cli -n auto
uv run ruff check . && uv run ruff format --check .
```

Expected: our new tests pass; any failures are limited to the known pre-existing C++/checker/validator/sandbox/docker cases on this machine (see memory). Then use superpowers:finishing-a-development-branch to integrate.

## Notes / decisions baked in
- **DRY:** all grouping math lives in `timing_groups.py`; the table renderer is shared by `rbx time` and BOCA.
- **YAGNI:** no memory/output grouping; no first-class group resolution in `LimitsProfile`; `groups` metadata is presentation-only.
- **Backward compat:** `LimitsProfile.groups` is optional; old `.limits/*.yml` load unchanged; `timelimit_for_language` and BOCA resolution paths are untouched.
- **DEFAULTED languages** intentionally emit no per-language modifier (they use base TL) and are surfaced via a loud warning + highlighted table rows.
