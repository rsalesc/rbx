# Leftover-Group Visibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the leftover pool obvious — mark it with a persisted flag, render it first in the time-limits table with an asterisk + footer, and teach the three states (grouped / singleton / leftover) via a static legend in the picker.

**Architecture:** Add `is_leftover` to `ResolvedGroup` and `isLeftover` to `TimingGroupReport`; both partition builders set it and `resolve_groups` propagates it into the saved metadata. The table renderer reorders the leftover row first, prefixes its Languages cell with `* `, and adds a caption when present. The picker's header becomes a static legend driven by a module-level constant.

**Tech Stack:** Python 3, Pydantic v2, rich (table), prompt_toolkit (picker), pytest.

**Design:** `docs/plans/2026-06-02-leftover-group-visibility-design.md`

**Conventions:** Single quotes; absolute imports; commit per task with conventional-commit messages + trailer `Co-Authored-By: Claude <noreply@anthropic.com>` (pre-commit runs ruff + commitizen; if ruff-format rewrites a file and aborts the commit, re-stage and commit again). Run tests with `uv run pytest`. Stage files by name, never `git add -A`.

Locked terminology: `[N]` **grouped** · `[X]` **singleton** · `[ ]` **leftover**.

---

## Task 1: Persist the leftover marker

**Files:**
- Modify: `rbx/box/schema.py` (`TimingGroupReport`)
- Modify: `rbx/box/timing_groups.py` (`ResolvedGroup`, `build_partition`, `partition_from_assignment`, `resolve_groups`)
- Test: `tests/rbx/box/test_timing_groups.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/box/test_timing_groups.py`:

```python
def test_build_partition_marks_leftover():
    groups = build_partition(
        env_groups=[LanguageGroup(languages=['c', 'cpp'])],
        all_languages=['c', 'cpp', 'python', 'go'],
    )
    assert groups[0].is_leftover is False  # explicit env group
    assert groups[1].languages == ['python', 'go']
    assert groups[1].is_leftover is True  # the leftover pool


def test_partition_from_assignment_marks_leftover():
    groups = partition_from_assignment(
        assignment={'cpp': 1, 'python': -1, 'go': 0, 'rust': 0},
        env_groups=[],
    )
    leftover = [g for g in groups if g.is_leftover]
    assert len(leftover) == 1
    assert leftover[0].languages == ['go', 'rust']
    # grouped + singleton groups are not marked
    assert all(not g.is_leftover for g in groups if not g.is_leftover or g is leftover[0])
    non_leftover = [g for g in groups if not g.is_leftover]
    assert {tuple(g.languages) for g in non_leftover} == {('cpp',), ('python',)}


def test_resolve_propagates_is_leftover():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(languages=['go', 'java'], is_leftover=True),
    ]
    pooled = {0: GroupTimings(fastest=100, slowest=100, solution_count=1)}
    base = GroupTimings(fastest=100, slowest=100, solution_count=1)
    result = resolve_groups(groups, pooled, base, _eval)
    by_leftover = {tuple(r.languages): r.isLeftover for r in result.reports}
    assert by_leftover[('cpp',)] is False
    assert by_leftover[('go', 'java')] is True
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -k "leftover" -v`
Expected: FAIL (`ResolvedGroup` has no `is_leftover`; `TimingGroupReport` has no `isLeftover`).

**Step 3: Implement**

(a) In `rbx/box/schema.py`, add a field to `TimingGroupReport` (after `multiplier`, before the closing of the class at line 659):

```python
    multiplier: Optional[float] = None
    isLeftover: bool = False
```

(b) In `rbx/box/timing_groups.py`, add the field to `ResolvedGroup`:

```python
class ResolvedGroup(BaseModel):
    languages: List[str]
    whenEmpty: Optional[LanguageGroupFallback] = None
    is_leftover: bool = False
```

(c) In `build_partition`, mark the leftover group:

```python
    leftover = [lang for lang in all_languages if lang not in grouped]
    if leftover:
        result.append(ResolvedGroup(languages=leftover, is_leftover=True))
    return result
```

(d) In `partition_from_assignment`, mark the leftover group:

```python
    if leftover:
        result.append(ResolvedGroup(languages=leftover, is_leftover=True))
    return result
```

(e) In `resolve_groups`, add `isLeftover=group.is_leftover` to ALL THREE `TimingGroupReport(...)` constructors (the ESTIMATED, MULTIPLIER, and DEFAULTED branches). For each, add the keyword argument, e.g.:

```python
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=timings.solution_count,
                fastest=timings.fastest,
                slowest=timings.slowest,
                isLeftover=group.is_leftover,
            )
```

and the same `isLeftover=group.is_leftover` line in the MULTIPLIER and DEFAULTED `TimingGroupReport(...)` blocks.

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: PASS (all tests).

**Step 5: Commit**

```bash
git add rbx/box/schema.py rbx/box/timing_groups.py tests/rbx/box/test_timing_groups.py
git commit -m "$(cat <<'EOF'
feat(timing): persist a leftover-group marker

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Render the leftover row first, with asterisk + footer

**Files:**
- Modify: `rbx/box/limits_info.py` (`LimitsTableRow`, `build_limits_table_rows`, `build_limits_table`)
- Test: `tests/rbx/box/test_limits_table.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/box/test_limits_table.py`:

```python
def test_leftover_row_is_first_and_marked():
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
                languages=['go', 'java'],
                timeLimit=2000,
                origin=TimingGroupOrigin.DEFAULTED,
                isLeftover=True,
            ),
        ],
    )
    rows = build_limits_table_rows(profile)
    # leftover pulled to the top, marked with a leading asterisk
    assert rows[0].is_leftover is True
    assert rows[0].languages.startswith('* ')
    assert 'go, java' in rows[0].languages
    # the rest keep their original order
    assert rows[1].languages == 'c, cpp'


def test_no_asterisk_when_no_leftover():
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
        ],
    )
    rows = build_limits_table_rows(profile)
    assert rows[0].is_leftover is False
    assert not rows[0].languages.startswith('*')


def test_caption_present_only_with_leftover():
    from rbx.box.limits_info import build_limits_table

    leftover_profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['go', 'java'],
                timeLimit=2000,
                origin=TimingGroupOrigin.DEFAULTED,
                isLeftover=True,
            ),
        ],
    )
    plain_profile = LimitsProfile(
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
        ],
    )
    assert 'leftover' in (build_limits_table(leftover_profile).caption or '')
    assert build_limits_table(plain_profile).caption is None
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/test_limits_table.py -k "leftover or asterisk or caption" -v`
Expected: FAIL (`LimitsTableRow` has no `is_leftover`; no reorder/asterisk/caption yet).

**Step 3: Implement**

(a) Add the field to `LimitsTableRow` in `rbx/box/limits_info.py`:

```python
class LimitsTableRow(BaseModel):
    languages: str
    solutions: Optional[int]
    time_limit_ms: int
    source: str
    defaulted: bool = False
    is_leftover: bool = False
```

(b) In `build_limits_table_rows`, inside the `if profile.groups:` branch, set the asterisk + flag and reorder leftover-first. Replace the existing `rows.append(LimitsTableRow(...))` (the group-metadata one) and the `return rows` after the loop with:

```python
            languages = ', '.join(report.languages)
            if report.isLeftover:
                languages = f'* {languages}'
            rows.append(
                LimitsTableRow(
                    languages=languages,
                    solutions=report.solutionCount,
                    time_limit_ms=report.timeLimit,
                    source=source,
                    defaulted=report.origin == TimingGroupOrigin.DEFAULTED,
                    is_leftover=report.isLeftover,
                )
            )
        # Leftover group is shown first; stable sort keeps the rest in order.
        rows.sort(key=lambda r: not r.is_leftover)
        return rows
```

(c) In `build_limits_table`, compute rows once, add a caption when a leftover row exists. Replace the `table = rich.table.Table(...)` construction and the row loop header:

```python
    rows = build_limits_table_rows(profile)
    caption = None
    if any(row.is_leftover for row in rows):
        caption = (
            '* leftover: languages not assigned to a group, '
            'estimated together (default).'
        )
    table = rich.table.Table(
        title=title,
        title_style='bold bright_white',
        header_style='bold bright_white',
        caption=caption,
        caption_style='bright_black',
        show_lines=False,
    )
```

and change the row loop from `for row in build_limits_table_rows(profile):` to `for row in rows:`.

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/test_limits_table.py -v`
Expected: PASS (all tests, including the pre-existing ones, which have no leftover and so keep their order/asterisk-free cells).

**Step 5: Commit**

```bash
git add rbx/box/limits_info.py tests/rbx/box/test_limits_table.py
git commit -m "$(cat <<'EOF'
feat(timing): show leftover group first with asterisk and footer

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Static legend in the picker

**Files:**
- Modify: `rbx/box/timing_group_picker.py`
- Test: `tests/rbx/box/test_timing_group_picker.py`

**Step 1: Write the failing test**

Append to `tests/rbx/box/test_timing_group_picker.py`:

```python
def test_legend_describes_three_states():
    from rbx.box.timing_group_picker import LEGEND_LINES

    text = '\n'.join(LEGEND_LINES)
    assert '[N]' in text and 'grouped' in text
    assert '[X]' in text and 'singleton' in text
    assert '[ ]' in text and 'leftover' in text
    # key hint still present
    assert 'confirm' in text and 'cancel' in text
```

The existing picker tests (`test_picker_assigns_and_confirms`, etc.) must continue to pass unchanged.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -k legend -v`
Expected: FAIL (`LEGEND_LINES` does not exist).

**Step 3: Implement**

(a) At the top of `rbx/box/timing_group_picker.py`, after the imports, add the module-level constant:

```python
LEGEND_LINES = [
    'Assign each language to a time-limit bucket:',
    '',
    '  [N] grouped    shares one estimated limit with same-numbered langs',
    '  [X] singleton  its own estimated limit',
    '  [ ] leftover   pooled with all other unmarked langs (default)',
    '',
    '1-9 group · space/tab [X]/[ ] · 0 clear · enter confirm · q cancel',
]
```

(b) Replace the `header = FormattedTextControl(...)` block (currently the title + hint, lines ~73-86) with a legend-driven control:

```python
    def _header_fragments():
        fragments = []
        last = len(LEGEND_LINES) - 1
        for i, line in enumerate(LEGEND_LINES):
            if i == 0:
                style = 'class:header'
            elif i == last:
                style = 'class:hint'
            else:
                style = 'class:legend'
            fragments.append((style, line + '\n'))
        return fragments

    header = FormattedTextControl(_header_fragments)
```

(c) Update the header `Window` height from `height=2` to the legend's length:

```python
                Window(
                    content=header, height=len(LEGEND_LINES), always_hide_cursor=True
                ),
```

(d) Add a `legend` style to the `Style.from_dict({...})` mapping (alongside `header`/`hint`):

```python
            'header': 'bold',
            'hint': 'ansibrightblack',
            'legend': '',
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -v`
Expected: PASS (all picker tests, including the unchanged interactive ones).

**Step 5: Commit**

```bash
git add rbx/box/timing_group_picker.py tests/rbx/box/test_timing_group_picker.py
git commit -m "$(cat <<'EOF'
feat(timing): static three-state legend in the group picker

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Docs

**Files:**
- Modify: `docs/setters/reference/environment/index.md`

**Step 1: Update the docs**

In the per-group table paragraph of the `### Language groups` section (the part describing the table printed after `rbx time` / `rbx package boca`), add a sentence: the **leftover** group is listed **first**, marked with a leading asterisk (`*`) and explained in a footer beneath the table. Keep terminology "leftover".

**Step 2: Verify the docs build**

Run: `uv run mkdocs build` (non-strict; ignore the ~pre-existing unrelated warnings — see memory). Expected: build succeeds. Do NOT commit any auto-regenerated `docs/setters/reference/cli.md` — if it changes, `git checkout -- docs/setters/reference/cli.md` before committing.

**Step 3: Commit**

```bash
git add docs/setters/reference/environment/index.md
git commit -m "$(cat <<'EOF'
docs: note leftover group is shown first with an asterisk

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Full verification

**Step 1: Run the full relevant suite**

Run:
```bash
uv run pytest tests/rbx/box/test_timing_groups.py \
  tests/rbx/box/test_timing_group_picker.py \
  tests/rbx/box/test_timing_estimation.py \
  tests/rbx/box/test_timing.py \
  tests/rbx/box/test_limits_table.py \
  tests/rbx/box/test_environment_groups.py \
  tests/rbx/box/test_limits_profile_groups.py \
  tests/rbx/box/packaging/test_boca_limits_table.py -v
```
Expected: all PASS. (Per memory, checker/validator/sandbox/docker suites fail pre-existingly on this machine and are unrelated.)

**Step 2: Lint & format**

Run: `uv run ruff check rbx/box/schema.py rbx/box/timing_groups.py rbx/box/limits_info.py rbx/box/timing_group_picker.py && uv run ruff format --check rbx/box/schema.py rbx/box/timing_groups.py rbx/box/limits_info.py rbx/box/timing_group_picker.py`
Expected: clean.

**Step 3: Confirm no stale `.limits` round-trip break** — sanity check `test_limits_profile_groups.py` still passes (it round-trips `groups` through YAML; the new `isLeftover` field must serialize/deserialize cleanly with `extra='forbid'`).

---

## Notes for the implementer

- `TimingGroupReport` has `model_config = ConfigDict(extra='forbid')`; the new `isLeftover` field is a normal model field so old files (without it) still load via the default, and new files serialize it. No migration needed.
- Only the *table* reorders the leftover to the top; the *picker* keeps env order and the *saved* `groups` metadata keeps partition order.
- At most one leftover row ever exists, so the stable `sort(key=lambda r: not r.is_leftover)` simply lifts it to the front.
