# Three-State Language Bucketing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the implicit-singleton default for unconfigured languages in `rbx time` with three explicit states — explicit group `[N]`, singleton `[X]`, and unbucketed `[ ]` (a single shared leftover pool, the new default) — and make all env languages participate.

**Architecture:** Pure grouping logic stays in `timing_groups.py` (partition builders) and the interactive picker in `timing_group_picker.py`. The assignment map encodes state per language as an int: `N≥1` = group N, `0` = unbucketed, `-1` = singleton. `partition_from_assignment` / `build_partition` collapse all unbucketed languages into one `ResolvedGroup`. `resolve_groups` and the table renderer are unchanged. `timing.relevant_languages_for_estimation` widens scope to all env languages.

**Tech Stack:** Python 3, Pydantic v2, prompt_toolkit (picker), pytest (`uv run pytest`).

**Design:** `docs/plans/2026-06-01-three-state-language-bucketing-design.md`

**Conventions:** Single quotes; absolute imports; commit via the `commit` skill workflow (`.claude/skills/commit.md`) — conventional commits, append `Co-Authored-By: Claude <noreply@anthropic.com>`. Run tests with `uv run pytest`.

---

## Task 1: Leftover pool in `build_partition`

**Files:**
- Modify: `rbx/box/timing_groups.py` (`build_partition`)
- Test: `tests/rbx/box/test_timing_groups.py`

**Step 1: Update the failing tests**

In `tests/rbx/box/test_timing_groups.py`, replace `test_implicit_singletons_for_unlisted_languages` and `test_build_partition_with_no_env_groups_makes_all_singletons` with:

```python
def test_leftover_pool_for_unlisted_languages():
    groups = build_partition(
        env_groups=[LanguageGroup(languages=['c', 'cpp'])],
        all_languages=['c', 'cpp', 'python', 'go'],
    )
    # one explicit group + ONE leftover pool of all unlisted languages, in order
    assert [g.languages for g in groups] == [['c', 'cpp'], ['python', 'go']]
    assert groups[0].whenEmpty is None
    assert groups[1].whenEmpty is None


def test_build_partition_with_no_env_groups_makes_one_leftover_pool():
    groups = build_partition(env_groups=[], all_languages=['c', 'cpp', 'python'])
    assert [g.languages for g in groups] == [['c', 'cpp', 'python']]


def test_build_partition_no_leftover_when_all_grouped():
    groups = build_partition(
        env_groups=[LanguageGroup(languages=['c', 'cpp'])],
        all_languages=['c', 'cpp'],
    )
    assert [g.languages for g in groups] == [['c', 'cpp']]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -k "leftover or no_leftover or no_env_groups" -v`
Expected: FAIL (current code emits one singleton group per unlisted language).

**Step 3: Implement**

Replace the trailing per-language loop in `build_partition` (`rbx/box/timing_groups.py`) so unlisted languages collapse into one group:

```python
def build_partition(
    env_groups: List[LanguageGroup],
    all_languages: List[str],
) -> List[ResolvedGroup]:
    """Build a disjoint partition: explicit env groups first (in order), then a
    single leftover pool holding every language not covered by an explicit group."""
    grouped: set[str] = set()
    result: List[ResolvedGroup] = []
    for group in env_groups:
        result.append(
            ResolvedGroup(languages=list(group.languages), whenEmpty=group.whenEmpty)
        )
        grouped.update(group.languages)
    leftover = [lang for lang in all_languages if lang not in grouped]
    if leftover:
        result.append(ResolvedGroup(languages=leftover))
    return result
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: PASS (all tests in the file).

**Step 5: Commit**

```bash
git add rbx/box/timing_groups.py tests/rbx/box/test_timing_groups.py
git commit -m "$(cat <<'EOF'
feat(timing): collapse unlisted languages into one leftover pool

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Three states in `partition_from_assignment`

**Files:**
- Modify: `rbx/box/timing_groups.py` (`partition_from_assignment`)
- Test: `tests/rbx/box/test_timing_groups.py`

**Step 1: Write the failing test**

Append to `tests/rbx/box/test_timing_groups.py`:

```python
def test_partition_from_assignment_three_states():
    # 1/2 = shared groups, -1 = singleton, 0 = unbucketed leftover pool
    groups = partition_from_assignment(
        assignment={
            'c': 1,
            'cpp': 1,
            'java': 2,
            'kotlin': 2,
            'python': -1,
            'go': 0,
            'rust': 0,
        },
        env_groups=[],
    )
    langs = [g.languages for g in groups]
    assert ['c', 'cpp'] in langs
    assert ['java', 'kotlin'] in langs
    assert ['python'] in langs          # singleton -> own group
    assert ['go', 'rust'] in langs      # unbucketed -> ONE leftover pool
    # numbered groups first (sorted), then singletons, then the leftover pool
    assert langs[-1] == ['go', 'rust']


def test_partition_from_assignment_no_leftover_group_when_none_unbucketed():
    groups = partition_from_assignment(
        assignment={'cpp': 1, 'python': -1},
        env_groups=[],
    )
    assert [g.languages for g in groups] == [['cpp'], ['python']]


def test_partition_from_assignment_preserves_when_empty_on_exact_match():
    groups = partition_from_assignment(
        assignment={'java': 1, 'kotlin': 1},
        env_groups=[
            LanguageGroup(
                languages=['java', 'kotlin'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            ),
        ],
    )
    assert groups[0].whenEmpty is not None
    assert groups[0].whenEmpty.multiplier == 2.0
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -k "three_states or no_leftover_group or preserves_when_empty_on_exact" -v`
Expected: FAIL (current code treats `0` as singleton and has no `-1`/leftover handling).

**Step 3: Implement**

Replace `partition_from_assignment` in `rbx/box/timing_groups.py`:

```python
def partition_from_assignment(
    assignment: Dict[str, int],
    env_groups: List[LanguageGroup],
) -> List[ResolvedGroup]:
    """Build groups from a {language: state} map. State per language:
    N>=1 share bucket N; -1 = own singleton group; 0 = the shared leftover pool.
    Carries over an env group's whenEmpty only when the resulting membership is
    identical to that env group."""
    buckets: Dict[int, List[str]] = {}
    singletons: List[List[str]] = []
    leftover: List[str] = []
    for lang, state in assignment.items():
        if state == 0:
            leftover.append(lang)
        elif state < 0:
            singletons.append([lang])
        else:
            buckets.setdefault(state, []).append(lang)

    env_when_empty = {frozenset(g.languages): g.whenEmpty for g in env_groups}
    result: List[ResolvedGroup] = []
    for _, langs in sorted(buckets.items()):
        when_empty = env_when_empty.get(frozenset(langs))
        result.append(ResolvedGroup(languages=langs, whenEmpty=when_empty))
    result.extend(ResolvedGroup(languages=s) for s in singletons)
    if leftover:
        result.append(ResolvedGroup(languages=leftover))
    return result
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/timing_groups.py tests/rbx/box/test_timing_groups.py
git commit -m "$(cat <<'EOF'
feat(timing): three-state partition (group/singleton/leftover)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Three-state picker UI

**Files:**
- Modify: `rbx/box/timing_group_picker.py`
- Test: `tests/rbx/box/test_timing_group_picker.py`

**Step 1: Update / add failing tests**

In `tests/rbx/box/test_timing_group_picker.py`:

Replace `test_render_fragments_marks_cursor_and_numbers` and add new tests:

```python
def test_render_fragments_shows_three_states():
    # cpp -> group 3, java -> unbucketed (0), python -> singleton (-1)
    s = GroupPickerState(['cpp', 'java', 'python'], {'cpp': 3, 'python': -1})
    text = ''.join(t for _, t in s.render_fragments())
    assert '[3] cpp' in text
    assert '[ ] java' in text
    assert '[X] python' in text
    assert text.count('❯') == 1


def test_toggle_singleton_cycles():
    s = GroupPickerState(['cpp'], {'cpp': 0})
    s.toggle_singleton()
    assert s.assignment() == {'cpp': -1}  # unbucketed -> singleton
    s.toggle_singleton()
    assert s.assignment() == {'cpp': 0}  # singleton -> unbucketed


def test_toggle_singleton_from_group_goes_to_singleton():
    s = GroupPickerState(['cpp'], {'cpp': 2})
    s.toggle_singleton()
    assert s.assignment() == {'cpp': -1}


async def test_picker_toggle_and_group_then_confirm():
    with create_pipe_input() as inp:
        inp.send_text('1')         # cpp -> group 1
        inp.send_text('\x1b[B')    # down -> java
        inp.send_text(' ')         # space -> java singleton [X]
        inp.send_text('\x1b[B')    # down -> python (stays unbucketed [ ])
        inp.send_text('\r')        # enter -> confirm
        result = await prompt_group_assignment(
            ['cpp', 'java', 'python'],
            {'cpp': 0, 'java': 0, 'python': 0},
            input=inp,
            output=DummyOutput(),
        )
    assert result == {'cpp': 1, 'java': -1, 'python': 0}
```

Keep `test_state_move_clamps`, `test_state_set_group_and_assignment`, `test_picker_assigns_and_confirms`, `test_picker_cancel_returns_none` as-is (they remain valid: default `0` still means unbucketed/blank box).

**Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -k "three_states or toggle or toggle_and_group" -v`
Expected: FAIL (`toggle_singleton` undefined; `[X]` not rendered).

**Step 3: Implement**

In `rbx/box/timing_group_picker.py`:

Add the toggle method to `GroupPickerState` (next to `set_group`):

```python
    def toggle_singleton(self) -> None:
        if not self.languages:
            return
        lang = self.languages[self.cursor]
        # toggle between singleton (-1) and unbucketed (0); a numbered language
        # goes to singleton on the first press.
        self.numbers[lang] = 0 if self.numbers[lang] == -1 else -1
```

Update `render_fragments` box computation:

```python
            number = self.numbers[lang]
            if number > 0:
                box = str(number)
            elif number < 0:
                box = 'X'
            else:
                box = ' '
```

Update the header hint text in `prompt_group_assignment`:

```python
            (
                'class:hint',
                '↑/↓ or j/k move · 1-9 set group · space/tab toggle '
                'singleton [X] / unbucketed [ ] · Enter confirm · q cancel\n',
            ),
```

Bind the digits to groups `1-9` only (group 0 is meaningless) and add the toggle keys. Replace the digit-binding loop and add bindings:

```python
    for _digit in '123456789':

        @kb.add(_digit)
        def _(event, _digit=_digit):
            state.set_group(int(_digit))

    @kb.add('0')
    def _(event):
        # explicit clear to unbucketed
        state.set_group(0)

    @kb.add('space')
    @kb.add('tab')
    def _(event):
        state.toggle_singleton()
```

(Leave the existing `enter` = submit and `c-c`/`q` = cancel bindings unchanged. `set_group(0)` works because `set_group` already writes the raw number; `0` lands as unbucketed.)

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -v`
Expected: PASS (all tests).

**Step 5: Commit**

```bash
git add rbx/box/timing_group_picker.py tests/rbx/box/test_timing_group_picker.py
git commit -m "$(cat <<'EOF'
feat(timing): three-state language group picker

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Widen estimation scope to all env languages

**Files:**
- Modify: `rbx/box/timing.py` (`relevant_languages_for_estimation`)
- Test: `tests/rbx/box/test_timing_estimation.py`

**Step 1: Update the failing tests**

In `tests/rbx/box/test_timing_estimation.py`, replace the two `relevant_languages_*` tests:

```python
def test_relevant_languages_includes_all_env_languages():
    result = relevant_languages_for_estimation(
        env_languages=['c', 'cpp', 'java', 'kotlin', 'python', 'go'],
        timing_languages=['python'],
        env_groups=[
            LanguageGroup(
                languages=['java', 'kotlin'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            ),
        ],
    )
    # every env language is now in scope, ordered by env order
    assert result == ['c', 'cpp', 'java', 'kotlin', 'python', 'go']


def test_relevant_languages_appends_unknown_timing_langs():
    result = relevant_languages_for_estimation(
        env_languages=['cpp', 'python'],
        timing_languages=['python', 'rust'],  # rust not in env list
        env_groups=[],
    )
    assert result == ['cpp', 'python', 'rust']
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing_estimation.py -k relevant -v`
Expected: FAIL (current code excludes env languages with no solution / no group, e.g. `go`, `c`, and `cpp` in the second test).

**Step 3: Implement**

Replace the body of `relevant_languages_for_estimation` in `rbx/box/timing.py` (keep the signature, including `env_groups`, for call-site/back-compat stability even though it is no longer read):

```python
def relevant_languages_for_estimation(
    env_languages: List[str],
    timing_languages: List[str],
    env_groups: List[environment.LanguageGroup],
) -> List[str]:
    """Languages that participate in the partition during estimation: every
    environment language (so unrepresented ones land in the picker and the
    leftover pool / DEFAULTED warning), followed by any timing language not
    declared in the environment. Ordered by the environment's language order."""
    del env_groups  # no longer needed; all env languages are in scope
    ordered = list(env_languages)
    for lang in timing_languages:
        if lang not in ordered:
            ordered.append(lang)
    return ordered
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/test_timing_estimation.py -v`
Expected: PASS (including the unchanged `test_build_timing_profile_groups_languages`).

**Step 5: Commit**

```bash
git add rbx/box/timing.py tests/rbx/box/test_timing_estimation.py
git commit -m "$(cat <<'EOF'
feat(timing): include all env languages in estimation scope

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: End-to-end leftover-pool behavior test

**Files:**
- Test: `tests/rbx/box/test_timing_estimation.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/box/test_timing_estimation.py`:

```python
def test_unrepresented_languages_inherit_leftover_pool():
    # cpp has solutions and is unbucketed; go/java are unbucketed with no
    # solutions -> they share cpp's pooled estimate via the leftover pool.
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'a.cpp': 100, 'b.cpp': 150}},
        formula='max(fastest * 3, slowest * 2)',
        env_groups=[],
        all_languages=['cpp', 'go', 'java'],
    )
    limits = profile.to_limits()
    # one leftover pool: cpp's estimate applies to all members
    assert limits.modifiers['cpp'].time == limits.modifiers['go'].time
    assert limits.modifiers['go'].time == limits.modifiers['java'].time
    assert profile.groups is not None
    origins = {tuple(sorted(r.languages)): r.origin for r in profile.groups}
    assert origins[('cpp', 'go', 'java')] == TimingGroupOrigin.ESTIMATED


def test_empty_leftover_pool_defaults_to_base():
    # No solutions for any leftover language other than the represented one in
    # its own group; the leftover pool is empty -> DEFAULTED to base, no modifier.
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'a.cpp': 100, 'b.cpp': 150}},
        formula='max(fastest * 3, slowest * 2)',
        env_groups=[LanguageGroup(languages=['cpp'])],
        all_languages=['cpp', 'go', 'java'],
    )
    limits = profile.to_limits()
    # leftover pool (go, java) has no solutions -> DEFAULTED, no modifiers
    assert 'go' not in limits.modifiers
    assert 'java' not in limits.modifiers
    assert profile.groups is not None
    defaulted = {
        tuple(sorted(r.languages)): r
        for r in profile.groups
        if r.origin == TimingGroupOrigin.DEFAULTED
    }
    assert ('go', 'java') in defaulted
```

**Step 2: Run to verify pass**

Run: `uv run pytest tests/rbx/box/test_timing_estimation.py -k "leftover" -v`
Expected: PASS (logic already implemented in Tasks 1-2; these lock in the behavior).

**Step 3: Commit**

```bash
git add tests/rbx/box/test_timing_estimation.py
git commit -m "$(cat <<'EOF'
test(timing): cover leftover-pool inherit and DEFAULTED behavior

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Docs

**Files:**
- Modify: `docs/setters/reference/environment/index.md`
- Read first: the existing `timing.groups` section to match tone.

**Step 1: Update the docs**

In the `timing.groups` section of `docs/setters/reference/environment/index.md`, update the description of how unlisted languages behave: change any wording that says unlisted languages become "implicit singletons" to describe the new behavior — unlisted languages join a single shared **leftover pool** (so an unrepresented language inherits a represented sibling's estimate when the pool has solutions, or DEFAULTs to base with a warning when it does not). Mention that `rbx time`'s interactive picker lets you place each language into a numbered group, a singleton `[X]`, or leave it unbucketed `[ ]` (the default).

**Step 2: Verify the docs build**

Run: `uv run mkdocs build` (non-strict; the ~9 pre-existing strict warnings are unrelated — see memory).
Expected: build succeeds.

**Step 3: Commit**

```bash
git add docs/setters/reference/environment/index.md
git commit -m "$(cat <<'EOF'
docs: describe leftover pool and three-state picker

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Full verification

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

Run: `uv run ruff check rbx/box/timing_groups.py rbx/box/timing_group_picker.py rbx/box/timing.py && uv run ruff format --check rbx/box/timing_groups.py rbx/box/timing_group_picker.py rbx/box/timing.py`
Expected: clean.

**Step 3: Sanity-check `test_timing.py`** for any remaining assumption that unlisted languages are singletons; if a test asserts old behavior, update it to the leftover-pool expectation and re-run.

---

## Notes for the implementer

- The assignment-map encoding (`N≥1`/`0`/`-1`) is internal to the picker + `partition_from_assignment`; no persisted file format changes (`.limits/*.yml` is untouched).
- `_prompt_repartition` in `timing.py` already prepopulates `{lang: 0}` then overwrites env-grouped languages with their group index. Since `0` now means *unbucketed*, the default is already correct — **do not change it**. Verify by reading `_prompt_repartition` before touching it.
- `resolve_groups` and `limits_info.render_limits_table` need NO changes — a leftover pool is just an ordinary multi-language group.
