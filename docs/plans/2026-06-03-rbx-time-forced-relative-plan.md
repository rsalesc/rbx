# Forced Relative Time Limits in `rbx time` Picker — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let `rbx time` users force a group's time limit to be relative to another group (`A·t + B`) directly in the interactive picker, always overriding estimation, with an inline editor and an env-reset hotkey.

**Architecture:** A new `forced_relative` field on `ResolvedGroup` (pure layer in `timing_groups.py`) takes top priority during resolution. The picker (`timing_group_picker.py`) gains a `relatives` map keyed by a string group-key, an inline `r` editor, and an `R` reset. `partition_from_assignment` drops its env-crossing and instead applies picker-supplied relatives; env `whenEmpty` is baked into picker state at init only for groups with no solutions. The resolved profile stores concrete numbers, so nothing round-trips to `env.rbx.yml`.

**Tech Stack:** Python 3.14, Pydantic v2, `prompt_toolkit` (picker UI), pytest (`create_pipe_input`/`DummyOutput` for picker tests). Single quotes, absolute imports, ruff.

**Design doc:** `docs/plans/2026-06-03-rbx-time-forced-relative-design.md`

**Reference — group-key encoding (used everywhere `relatives` is keyed):**
Given the picker `numbers: Dict[str,int]` (N≥1 bucket, 0 leftover, -1 singleton):
- bucket `N≥1` → `f'g{N}'`  (e.g. `'g2'`)
- leftover (`0`) → `'leftover'`
- singleton (`-1`) of language `L` → `f's:{L}'`

The relative spec value type is the existing `environment.LanguageGroupFallback`
(`relativeTo`, `multiplier`, `increment`). `relativeTo` holds a representative
language of the target group, or `None` for "(base estimate)".

---

## Task 1: `forced_relative` field + resolution priority (pure layer)

**Files:**
- Modify: `rbx/box/timing_groups.py` (`ResolvedGroup`, `validate_partition`, `resolve_groups`)
- Test: `tests/rbx/box/test_timing_groups.py`

**Step 1: Write failing tests**

Add to `tests/rbx/box/test_timing_groups.py`:

```python
from rbx.box.environment import LanguageGroupFallback


def _eval(fastest, slowest):
    # simple deterministic formula for tests: just the slowest
    return slowest


def test_forced_relative_wins_over_pooled_timings():
    # group 0 has solutions; group 1 forced relative to group 0
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['python'],
            forced_relative=LanguageGroupFallback(
                relativeTo='cpp', multiplier=2.0, increment=100
            ),
        ),
    ]
    pooled = {
        0: GroupTimings(fastest=100, slowest=200, solution_count=1),
        1: GroupTimings(fastest=500, slowest=900, solution_count=1),
    }
    base = GroupTimings(fastest=100, slowest=900, solution_count=2)
    result = resolve_groups(groups, pooled, base, _eval)
    # group 1 ignores its own timings (would be 900) -> 2.0*200 + 100 = 500
    assert result.reports[1].timeLimit == 500
    assert result.reports[1].origin == TimingGroupOrigin.MULTIPLIER
    assert result.reports[1].relativeToLanguage == 'cpp'
    # solution count of the overridden group is preserved for display
    assert result.reports[1].solutionCount == 1


def test_forced_relative_validates_self_reference():
    groups = [
        ResolvedGroup(
            languages=['cpp'],
            forced_relative=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        )
    ]
    with pytest.raises(GroupValidationError):
        validate_partition(groups)


def test_forced_relative_to_base_estimate():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['python'],
            forced_relative=LanguageGroupFallback(relativeTo=None, multiplier=3.0),
        ),
    ]
    pooled = {0: GroupTimings(fastest=100, slowest=200, solution_count=1)}
    base = GroupTimings(fastest=100, slowest=200, solution_count=1)
    result = resolve_groups(groups, pooled, base, _eval)
    # base_tl = _eval(100, 200) = 200; forced -> 3.0*200 = 600
    assert result.reports[1].timeLimit == 600
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -k forced -v`
Expected: FAIL (`ResolvedGroup` has no `forced_relative`).

**Step 3: Add the field**

In `rbx/box/timing_groups.py`, import is already `from rbx.box.environment import LanguageGroup, LanguageGroupFallback`. Update `ResolvedGroup`:

```python
class ResolvedGroup(BaseModel):
    languages: List[str]
    whenEmpty: Optional[LanguageGroupFallback] = None
    forced_relative: Optional[LanguageGroupFallback] = None
    is_leftover: bool = False
```

**Step 4: Add a fallback-edge helper and update `validate_partition`**

Add near the top of `validate_partition`'s module scope:

```python
def _effective_fallback(group: ResolvedGroup) -> Optional[LanguageGroupFallback]:
    """The fallback whose reference edge matters for validation: a forced
    relative (picker path) takes precedence, else the env whenEmpty."""
    return group.forced_relative or group.whenEmpty
```

In `validate_partition`, replace both `group.whenEmpty` accesses (the reference-existence loop and the `visit` cycle walk) with `_effective_fallback(group)`. Concretely:

```python
    for idx, group in enumerate(groups):
        fb = _effective_fallback(group)
        if fb is None or fb.relativeTo is None:
            continue
        ref = fb.relativeTo
        if ref not in lang_index:
            raise GroupValidationError(
                f'whenEmpty.relativeTo references unknown language {ref!r}.'
            )
        if lang_index[ref] == idx:
            raise GroupValidationError(
                f'whenEmpty.relativeTo {ref!r} points to the same group; it must '
                'reference a different group.'
            )
    ...
    def visit(idx: int) -> None:
        color[idx] = GRAY
        fb = _effective_fallback(groups[idx])
        if fb is not None and fb.relativeTo is not None:
            nxt = lang_index[fb.relativeTo]
            ...
```

**Step 5: Add the forced branch in `resolve_groups`**

In the `resolve(idx)` inner function, insert a new FIRST branch (before `if timings is not None:`). Keep the existing `timings` and `whenEmpty` branches after it:

```python
        group = groups[idx]
        timings = pooled.get(idx)
        if group.forced_relative is not None:
            fb = group.forced_relative
            ref = fb.relativeTo
            ref_tl = base_tl if ref is None else resolve(lang_index[ref])
            increment = fb.increment or 0
            tl = int(ref_tl * fb.multiplier + increment)
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.MULTIPLIER,
                solutionCount=timings.solution_count if timings else 0,
                fastest=timings.fastest if timings else None,
                slowest=timings.slowest if timings else None,
                relativeToLanguage=ref,
                multiplier=fb.multiplier,
                increment=fb.increment,
                isLeftover=group.is_leftover,
            )
        elif timings is not None:
            ...  # unchanged
```

**Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: PASS (new + all existing).

**Step 7: Commit**

```bash
git add rbx/box/timing_groups.py tests/rbx/box/test_timing_groups.py
git commit -m "feat(timing): forced relative spec wins over estimation in resolve_groups"
```

---

## Task 2: `partition_from_assignment` drops env-crossing, applies relatives

**Files:**
- Modify: `rbx/box/timing_groups.py` (`partition_from_assignment`)
- Test: `tests/rbx/box/test_timing_groups.py`

**Step 1: Write failing tests**

```python
def test_partition_applies_forced_relatives_by_group_key():
    groups = partition_from_assignment(
        {'cpp': 1, 'python': 2, 'go': 0, 'rust': -1},
        relatives={
            'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            's:rust': LanguageGroupFallback(relativeTo='cpp', multiplier=3.0),
            'leftover': LanguageGroupFallback(relativeTo='cpp', multiplier=4.0),
        },
    )
    by_lang = {g.languages[0]: g for g in groups}
    assert by_lang['python'].forced_relative.multiplier == 2.0
    assert by_lang['rust'].forced_relative.multiplier == 3.0
    assert by_lang['go'].forced_relative.multiplier == 4.0
    assert by_lang['cpp'].forced_relative is None


def test_partition_no_longer_derives_when_empty_from_env():
    # membership matches an env group, but partition_from_assignment must NOT
    # re-derive whenEmpty anymore (env-crossing dropped).
    groups = partition_from_assignment({'java': 1, 'kotlin': 1})
    assert groups[0].whenEmpty is None
    assert groups[0].forced_relative is None
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -k "partition_applies or no_longer" -v`
Expected: FAIL (`partition_from_assignment` still requires `env_groups`).

**Step 3: Rewrite `partition_from_assignment`**

Replace the signature and body. Add a module-level key helper:

```python
def group_key(state: int, lang: str) -> str:
    """Stable key for the group a language currently belongs to."""
    if state > 0:
        return f'g{state}'
    if state < 0:
        return f's:{lang}'
    return 'leftover'


def partition_from_assignment(
    assignment: Dict[str, int],
    relatives: Optional[Dict[str, LanguageGroupFallback]] = None,
) -> List[ResolvedGroup]:
    """Build groups from a {language: state} map. State per language:
    N>=1 share bucket N; -1 = own singleton group; 0 = the shared leftover pool.
    Optional ``relatives`` maps a group-key (see group_key) to a forced relative
    spec, stamped onto the matching group as ``forced_relative``."""
    relatives = relatives or {}
    buckets: Dict[int, List[str]] = {}
    singletons: List[tuple[str, List[str]]] = []
    leftover: List[str] = []
    for lang, state in assignment.items():
        if state == 0:
            leftover.append(lang)
        elif state < 0:
            singletons.append((f's:{lang}', [lang]))
        else:
            buckets.setdefault(state, []).append(lang)

    result: List[ResolvedGroup] = []
    for number, langs in sorted(buckets.items()):
        result.append(
            ResolvedGroup(
                languages=langs, forced_relative=relatives.get(f'g{number}')
            )
        )
    for key, langs in singletons:
        result.append(
            ResolvedGroup(languages=langs, forced_relative=relatives.get(key))
        )
    if leftover:
        result.append(
            ResolvedGroup(
                languages=leftover,
                is_leftover=True,
                forced_relative=relatives.get('leftover'),
            )
        )
    return result
```

Remove the now-unused `env_when_empty` logic. (The `LanguageGroup` import stays — still used by `build_partition`.)

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py -v`
Expected: PASS.

**Step 5: Find and fix callers**

Run: `uv run python -c "import rbx.box.timing"` then
`grep -rn "partition_from_assignment" rbx tests`.
The only non-test caller is `rbx/box/timing.py:build_timing_profile` (fixed in Task 3). Any existing test passing `env_groups=` positionally must be updated to the new signature.

**Step 6: Commit**

```bash
git add rbx/box/timing_groups.py tests/rbx/box/test_timing_groups.py
git commit -m "refactor(timing): partition_from_assignment applies picker relatives, drops env-crossing"
```

---

## Task 3: Thread `relatives` through `build_timing_profile` + preview

**Files:**
- Modify: `rbx/box/timing.py` (`build_timing_profile`, `build_preview_renderer`)
- Test: `tests/rbx/box/test_timing_preview.py`, `tests/rbx/box/test_timing_estimation.py`

**Step 1: Write a failing preview test**

In `tests/rbx/box/test_timing_preview.py`, add a test that a forced relative changes the previewed table. Mirror the existing tests in that file for fixture shape; assert the rendered ANSI contains the forced group's relative-derived limit (or a `×`/`relative` marker the table emits). Example skeleton:

```python
def test_preview_reflects_forced_relative():
    render = build_preview_renderer(
        timing_per_solution_per_language={'cpp': {'sol.cpp': 200}},
        formula='slowest',
        env_groups=[],
        all_languages=['cpp', 'python'],
    )
    # python forced relative to cpp, x2 -> 400ms must appear
    out = render({'cpp': 1, 'python': 2}, {'g2': LanguageGroupFallback(
        relativeTo='cpp', multiplier=2.0)})
    assert '400' in str(out.value)
```

(Adjust `formula`/assertions to match how `build_limits_table` renders; read the existing passing tests in this file first.)

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/test_timing_preview.py -k forced -v`
Expected: FAIL (`render` takes one arg; `build_timing_profile` has no `relatives`).

**Step 3: Update `build_timing_profile`**

Add a `relatives` parameter and pass it through:

```python
def build_timing_profile(
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    formula: str,
    env_groups: List[environment.LanguageGroup],
    all_languages: List[str],
    repartition: Optional[Dict[str, int]] = None,
    relatives: Optional[Dict[str, environment.LanguageGroupFallback]] = None,
) -> TimingProfile:
    ...
    if repartition is not None:
        groups = timing_groups.partition_from_assignment(repartition, relatives)
    else:
        groups = timing_groups.build_partition(env_groups, all_languages)
```

**Step 4: Update `build_preview_renderer`**

The memoized render must key on relatives too. Change the inner cache + outer `render`:

```python
    @functools.lru_cache(maxsize=None)
    def _render(assignment_items: tuple, relative_items: tuple) -> ANSI:
        assignment = dict(assignment_items)
        relatives = {k: v for k, v in relative_items}
        try:
            profile = build_timing_profile(
                ...,
                repartition=assignment,
                relatives=relatives,
            )
        ...

    def render(
        assignment: Dict[str, int],
        relatives: Optional[Dict[str, environment.LanguageGroupFallback]] = None,
    ) -> ANSI:
        relatives = relatives or {}
        return _render(
            tuple(sorted(assignment.items())),
            tuple(sorted(relatives.items(), key=lambda kv: kv[0])),
        )
```

Note: `LanguageGroupFallback` is a Pydantic model; it is hashable only if frozen. Confirm by running the test — if `lru_cache` raises `unhashable type`, set `model_config = ConfigDict(frozen=True)` on `LanguageGroupFallback` in `environment.py` (it is `extra='forbid'` already and only ever constructed, never mutated). Add that to the same commit if needed.

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_timing_preview.py tests/rbx/box/test_timing_estimation.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add rbx/box/timing.py rbx/box/environment.py tests/rbx/box/test_timing_preview.py
git commit -m "feat(timing): thread forced relatives through profile build and preview"
```

---

## Task 4: Picker state — relatives, group-key, edit lifecycle (pure)

**Files:**
- Modify: `rbx/box/timing_group_picker.py` (`GroupPickerState`)
- Test: `tests/rbx/box/test_timing_group_picker.py`

This task is pure state logic (no `prompt_toolkit` app). All methods are unit-tested directly.

**Step 1: Write failing tests**

```python
from rbx.box.environment import LanguageGroupFallback


def test_group_key_per_state():
    s = GroupPickerState(['cpp', 'py', 'go'], {'cpp': 2, 'py': -1, 'go': 0})
    assert s.group_key('cpp') == 'g2'
    assert s.group_key('py') == 's:py'
    assert s.group_key('go') == 'leftover'


def test_start_edit_seeds_defaults_and_commit():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)  # cursor -> py
    s.start_edit()
    assert s.editing
    s.set_ref('cpp')
    s.set_a('2.5')
    s.set_b('100')
    s.commit_edit()
    assert not s.editing
    assert s.relatives['g2'] == LanguageGroupFallback(
        relativeTo='cpp', multiplier=2.5, increment=100
    )


def test_cancel_edit_discards():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)
    s.start_edit()
    s.set_a('9')
    s.cancel_edit()
    assert not s.editing
    assert 'g2' not in s.relatives


def test_clear_relative_removes_spec():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2},
                         relatives={'g2': LanguageGroupFallback(
                             relativeTo='cpp', multiplier=2.0)})
    s.move(1)
    s.start_edit()
    s.clear_relative()
    assert 'g2' not in s.relatives
    assert not s.editing


def test_invalid_a_keeps_editing(monkeypatch=None):
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)
    s.start_edit()
    s.set_ref('cpp')
    s.set_a('abc')  # not a positive float
    assert s.commit_edit() is False  # rejected
    assert s.editing  # stays in editor


def test_reference_options_exclude_own_group_and_include_base():
    s = GroupPickerState(['cpp', 'py', 'go'], {'cpp': 1, 'py': 2, 'go': 2})
    s.move(1)  # cursor on py (group g2)
    refs = s.reference_options()
    # representative langs of OTHER groups + None for base estimate
    assert None in refs
    assert 'cpp' in refs
    assert 'py' not in refs and 'go' not in refs  # own group excluded


def test_reset_restores_initial_numbers_and_relatives():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2},
                         relatives={'g2': LanguageGroupFallback(
                             relativeTo='cpp', multiplier=2.0)})
    s.set_group(5)  # mutate cpp
    s.move(1)
    s.start_edit(); s.clear_relative()
    s.reset_to_initial()
    assert s.assignment() == {'cpp': 1, 'py': 2}
    assert s.relatives == {'g2': LanguageGroupFallback(
        relativeTo='cpp', multiplier=2.0)}
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -k "group_key or edit or relative or reference_options or reset" -v`
Expected: FAIL.

**Step 3: Extend `GroupPickerState.__init__`**

```python
    def __init__(self, languages, default_number, relatives=None):
        self.languages = list(languages)
        self.numbers = {lang: int(default_number.get(lang, 0)) for lang in self.languages}
        self.cursor = 0
        self.done = False
        self.relatives: Dict[str, LanguageGroupFallback] = dict(relatives or {})
        # immutable snapshot for reset_to_initial
        self._initial_numbers = dict(self.numbers)
        self._initial_relatives = dict(self.relatives)
        # edit-mode scratch state
        self.editing = False
        self._edit_ref: Optional[str] = None
        self._edit_a: str = ''
        self._edit_b: str = ''
```

Add `from typing import ... ` already present; add `from rbx.box.environment import LanguageGroupFallback` at top.

**Step 4: Add the methods**

```python
    def group_key(self, lang: str) -> str:
        state = self.numbers[lang]
        if state > 0:
            return f'g{state}'
        if state < 0:
            return f's:{lang}'
        return 'leftover'

    def current_lang(self) -> Optional[str]:
        return self.languages[self.cursor] if self.languages else None

    def reference_options(self) -> List[Optional[str]]:
        """None (base estimate) + one representative language per OTHER group,
        in language order."""
        own = self.group_key(self.current_lang())
        opts: List[Optional[str]] = [None]
        seen: set = set()
        for lang in self.languages:
            key = self.group_key(lang)
            if key == own or key in seen:
                continue
            seen.add(key)
            opts.append(lang)
        return opts

    def start_edit(self) -> None:
        if not self.languages:
            return
        key = self.group_key(self.current_lang())
        existing = self.relatives.get(key)
        self.editing = True
        self._edit_ref = existing.relativeTo if existing else None
        self._edit_a = str(existing.multiplier) if existing else '1.0'
        self._edit_b = (
            str(existing.increment) if existing and existing.increment else ''
        )

    def set_ref(self, ref: Optional[str]) -> None:
        self._edit_ref = ref

    def cycle_ref(self, delta: int) -> None:
        opts = self.reference_options()
        try:
            i = opts.index(self._edit_ref)
        except ValueError:
            i = 0
        self._edit_ref = opts[(i + delta) % len(opts)]

    def set_a(self, text: str) -> None:
        self._edit_a = text

    def set_b(self, text: str) -> None:
        self._edit_b = text

    def commit_edit(self) -> bool:
        """Validate buffers; on success store the spec and exit edit mode.
        Returns False (and stays editing) on invalid A/B."""
        try:
            a = float(self._edit_a)
        except ValueError:
            return False
        if a <= 0:
            return False
        b: Optional[int] = None
        if self._edit_b.strip():
            try:
                b = int(self._edit_b)
            except ValueError:
                return False
        key = self.group_key(self.current_lang())
        self.relatives[key] = LanguageGroupFallback(
            relativeTo=self._edit_ref, multiplier=a, increment=b
        )
        self.editing = False
        return True

    def cancel_edit(self) -> None:
        self.editing = False

    def clear_relative(self) -> None:
        self.relatives.pop(self.group_key(self.current_lang()), None)
        self.editing = False

    def reset_to_initial(self) -> None:
        self.numbers = dict(self._initial_numbers)
        self.relatives = dict(self._initial_relatives)
        self.editing = False

    def prune_relatives(self) -> Dict[str, LanguageGroupFallback]:
        """Drop specs whose group-key no longer maps to any language."""
        live = {self.group_key(lang) for lang in self.languages}
        return {k: v for k, v in self.relatives.items() if k in live}
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add rbx/box/timing_group_picker.py tests/rbx/box/test_timing_group_picker.py
git commit -m "feat(timing): picker state for forced relative specs (edit/clear/reset)"
```

---

## Task 5: Picker rendering — annotation + inline editor

**Files:**
- Modify: `rbx/box/timing_group_picker.py` (`render_fragments`, `LEGEND_LINES`)
- Test: `tests/rbx/box/test_timing_group_picker.py`

**Step 1: Write failing tests**

```python
def test_render_annotates_relative_group():
    s = GroupPickerState(
        ['cpp', 'py'], {'cpp': 1, 'py': 2},
        relatives={'g2': LanguageGroupFallback(
            relativeTo='cpp', multiplier=2.0, increment=100)},
    )
    text = ''.join(t for _, t in s.render_fragments())
    assert 'py' in text
    # annotation shows reference + A + B
    assert '→ cpp' in text or '-> cpp' in text
    assert '2.0' in text
    assert '100' in text


def test_render_shows_inline_editor_when_editing():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)
    s.start_edit()
    s.set_ref('cpp')
    text = ''.join(t for _, t in s.render_fragments())
    assert 'relative-to' in text
    assert 'A:' in text and 'B:' in text


def test_legend_mentions_relative_and_reset():
    from rbx.box.timing_group_picker import LEGEND_LINES
    text = '\n'.join(LEGEND_LINES)
    assert 'relative' in text
    assert 'reset' in text
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -k "annotat or inline_editor or legend_mentions" -v`
Expected: FAIL.

**Step 3: Update `LEGEND_LINES`**

Replace the last hint line:

```python
    '↑/↓ move · 1-9 group · space/tab [X]/[ ] · 0 clear · r relative · R reset env'
    ' · enter confirm · q cancel',
```

**Step 4: Update `render_fragments`**

After building each language row, append a relative annotation when the language's group carries a spec, and render the inline editor under the cursor row when `self.editing`:

```python
    def _relative_suffix(self, lang: str) -> str:
        spec = self.relatives.get(self.group_key(lang))
        if spec is None:
            return ''
        ref = spec.relativeTo if spec.relativeTo is not None else 'base'
        suffix = f'  → {ref} ×{spec.multiplier:g}'
        if spec.increment:
            suffix += f' +{spec.increment}'
        return suffix

    def _editor_fragments(self):
        ref = self._edit_ref if self._edit_ref is not None else '(base estimate)'
        return [(
            'class:editor',
            f'      relative-to: [{ref}]  A:[{self._edit_a}]  B:[{self._edit_b}]\n'
            '      Tab cycles ref · type A/B · enter ok · esc cancel · c clear\n',
        )]

    def render_fragments(self):
        fragments = []
        for i, lang in enumerate(self.languages):
            number = self.numbers[lang]
            box = str(number) if number > 0 else ('X' if number < 0 else ' ')
            selected = i == self.cursor
            pointer = '❯ ' if selected else '  '
            row_style = 'class:current' if selected else 'class:row'
            box_style = 'class:box-current' if selected else 'class:box'
            fragments.append((row_style, pointer))
            fragments.append((box_style, f'[{box}] '))
            fragments.append((row_style, f'{lang}'))
            fragments.append(('class:relative', self._relative_suffix(lang)))
            fragments.append((row_style, '\n'))
            if selected and self.editing:
                fragments.extend(self._editor_fragments())
        return fragments
```

Add `'editor': 'ansicyan'` and `'relative': 'ansigreen'` to the `Style.from_dict` map in `prompt_group_assignment` (Task 6 touches that function; if not yet present, add the styles there).

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -k "annotat or inline_editor or legend" -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add rbx/box/timing_group_picker.py tests/rbx/box/test_timing_group_picker.py
git commit -m "feat(timing): render relative annotations and inline editor in picker"
```

---

## Task 6: Picker key bindings, edit-mode routing, new return struct

**Files:**
- Modify: `rbx/box/timing_group_picker.py` (`prompt_group_assignment`)
- Modify: `rbx/box/timing.py` (`_prompt_repartition` to consume new return)
- Test: `tests/rbx/box/test_timing_group_picker.py`

**Decision — return type:** `prompt_group_assignment` now returns
`Optional[GroupAssignment]` where `GroupAssignment` is a small Pydantic model:

```python
class GroupAssignment(BaseModel):
    numbers: Dict[str, int]
    relatives: Dict[str, LanguageGroupFallback] = {}
```

This breaks existing assertions like `result == {'cpp': 1}`; update those tests to
`result.numbers == {...}`.

**Step 1: Update existing picker integration tests + add new ones**

Change the three existing `prompt_group_assignment` integration tests to assert on
`result.numbers`. Then add:

```python
async def test_picker_force_relative_flow():
    with create_pipe_input() as inp:
        inp.send_text('1')          # cpp -> group 1
        inp.send_text('\x1b[B')     # down -> py
        inp.send_text('2')          # py -> group 2
        inp.send_text('r')          # open editor on py (g2)
        inp.send_text('\t')         # Tab: ref None -> cpp
        inp.send_text('2.0')        # type A
        # move focus to B is implicit in editor; send Tab? -> see Step 3 routing
        inp.send_text('\r')         # commit edit
        inp.send_text('\r')         # confirm picker
        result = await prompt_group_assignment(
            ['cpp', 'py'], {'cpp': 0, 'py': 0},
            input=inp, output=DummyOutput(),
        )
    assert result.numbers == {'cpp': 1, 'py': 2}
    assert result.relatives['g2'].relativeTo == 'cpp'
    assert result.relatives['g2'].multiplier == 2.0


async def test_picker_reset_restores_env():
    with create_pipe_input() as inp:
        inp.send_text('5')          # mutate cpp -> 5
        inp.send_text('R')          # reset to initial
        inp.send_text('\r')         # confirm
        result = await prompt_group_assignment(
            ['cpp', 'py'], {'cpp': 1, 'py': 2},
            input=inp, output=DummyOutput(),
        )
    assert result.numbers == {'cpp': 1, 'py': 2}
```

(The exact A/B keystroke routing depends on Step 3; adjust the `send_text`
sequence to match the implemented editor input model. Keep the editor input model
SIMPLE: a single focused buffer that A and B share is error-prone — prefer
separate `a`/`b` sub-fields toggled by Tab, or commit A then B via two Enter
presses. Pick one and make the test match.)

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -v`
Expected: FAIL (no `GroupAssignment`, no `r`/`R`/editor bindings).

**Step 3: Implement edit-mode key routing**

Editor input model (chosen for testability): when `state.editing`, keystrokes are
routed to the editor instead of the list. Fields cycle with **Tab**:
`ref → A → B → ref …`. Reuse a `self._edit_field` cursor (`'ref' | 'a' | 'b'`).
- On `ref`: Tab/Left/Right cycle `cycle_ref`.
- On `a`/`b`: digit/`.`/`-` keys append to the buffer; backspace pops.
- **Enter**: `commit_edit()`; if it returns False, stay (invalid).
- **Esc**: `cancel_edit()`. **c** (only meaningful on ref field): `clear_relative()`.

In `prompt_group_assignment`, gate the existing list bindings on
`not state.editing`, and add an editor key handler. `prompt_toolkit` allows a
`filter=Condition(lambda: state.editing)` on bindings. Sketch:

```python
    from prompt_toolkit.filters import Condition
    editing = Condition(lambda: state.editing)
    not_editing = ~editing

    @kb.add('up', filter=not_editing)
    @kb.add('k', filter=not_editing)
    def _(event):
        state.move(-1)
    # ... wrap every existing list binding with filter=not_editing ...

    @kb.add('r', filter=not_editing)
    def _(event):
        state.start_edit()

    @kb.add('R', filter=not_editing)
    def _(event):
        state.reset_to_initial()

    # editor bindings
    @kb.add('tab', filter=editing)
    def _(event):
        state.edit_tab()         # advance _edit_field; on ref, also cycle? keep simple: advance field

    @kb.add('enter', filter=editing)
    def _(event):
        state.commit_edit()      # stays editing if invalid

    @kb.add('escape', filter=editing)
    def _(event):
        state.cancel_edit()

    @kb.add('c', filter=editing)
    def _(event):
        state.clear_relative()

    @kb.add('<any>', filter=editing)
    def _(event):
        state.edit_key(event.data)  # append/cycle based on _edit_field
```

Add the small helpers `edit_tab`, `edit_key` to `GroupPickerState` (with unit
tests in Task 4's file — add them there if you prefer strict TDD ordering; it is
acceptable to add these two helpers here with their own tests since they are
input-routing glue). `edit_key` on the `ref` field maps arrow-like data to
`cycle_ref`; on `a`/`b` appends printable chars / handles backspace.

Update `enter` (confirm) binding (now `filter=not_editing`) to return the struct:

```python
    @kb.add('enter', filter=not_editing)
    def _(event):
        state.done = True
        event.app.exit(result=GroupAssignment(
            numbers=state.assignment(),
            relatives=state.prune_relatives(),
        ))
```

Update the `preview` window call to pass relatives:
`state.preview_text(preview)` → ensure `preview_text` forwards both
`assignment()` and `relatives` to the preview callback. Update `preview_text`:

```python
    def preview_text(self, preview):
        if self.done or preview is None:
            return ''
        return preview(self.assignment(), self.prune_relatives())
```

And in `timing.py` the `preview` passed in is `build_preview_renderer`'s
`render(assignment, relatives)` — already 2-arg after Task 3.

**Step 4: Update `_prompt_repartition` / `estimate_time_limit` (timing.py)**

`_prompt_repartition` returns the picker result. Change its return type to
`Optional[GroupAssignment]` and update `estimate_time_limit`:

```python
    repartition = None
    relatives = None
    if not auto and len(all_languages) > 1:
        picked = await _prompt_repartition(...)
        if picked is None:
            console.print('[error]Time limit estimation cancelled.[/error]')
            return None
        repartition = picked.numbers
        relatives = picked.relatives
    ...
    profile = build_timing_profile(
        ...,
        repartition=repartition,
        relatives=relatives,
    )
```

**Step 5: Run the full picker + timing suite**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py tests/rbx/box/test_timing.py tests/rbx/box/test_timing_estimation.py tests/rbx/box/test_timing_preview.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add rbx/box/timing_group_picker.py rbx/box/timing.py tests/rbx/box/test_timing_group_picker.py
git commit -m "feat(timing): wire forced-relative editor keys and GroupAssignment return"
```

---

## Task 7: Init seeding from env `whenEmpty` for empty groups

**Files:**
- Modify: `rbx/box/timing.py` (`default_assignment` → add `default_relatives`, `_prompt_repartition`)
- Test: `tests/rbx/box/test_timing.py` (or `test_timing_estimation.py`)

**Step 1: Write failing tests**

```python
def test_default_relatives_seeds_only_empty_groups():
    from rbx.box.environment import LanguageGroup, LanguageGroupFallback
    from rbx.box.timing import default_relatives

    env_groups = [
        LanguageGroup(languages=['cpp']),  # has solutions
        LanguageGroup(
            languages=['py'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        ),  # empty -> seed
        LanguageGroup(
            languages=['go'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=3.0),
        ),  # has solutions -> do NOT seed
    ]
    langs_with_solutions = {'cpp', 'go'}
    seeded = default_relatives(env_groups, langs_with_solutions)
    assert set(seeded) == {'g2'}  # only the empty py group (env group #2)
    assert seeded['g2'].multiplier == 2.0
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/test_timing.py -k default_relatives -v`
Expected: FAIL (`default_relatives` undefined).

**Step 3: Implement `default_relatives`**

In `timing.py`, alongside `default_assignment`:

```python
def default_relatives(
    env_groups: List[environment.LanguageGroup],
    langs_with_solutions: set,
) -> Dict[str, environment.LanguageGroupFallback]:
    """Seed picker relatives from env whenEmpty, but only for groups that have
    NO measured solutions (matching env whenEmpty's empty-only semantics at the
    moment of init). Keyed by the picker group-key the env group maps to
    (env group i -> bucket i -> 'g{i}')."""
    seeded: Dict[str, environment.LanguageGroupFallback] = {}
    for i, group in enumerate(env_groups, start=1):
        if group.whenEmpty is None:
            continue
        if any(lang in langs_with_solutions for lang in group.languages):
            continue
        seeded[f'g{i}'] = group.whenEmpty
    return seeded
```

**Step 4: Pass seeds into the picker**

In `_prompt_repartition`, compute and forward:

```python
async def _prompt_repartition(
    all_languages,
    env_groups,
    timing_per_solution_per_language,
    formula,
):
    preview = build_preview_renderer(...)
    langs_with_solutions = {
        lang for lang, per_sol in timing_per_solution_per_language.items() if per_sol
    }
    return await timing_group_picker.prompt_group_assignment(
        all_languages,
        default_assignment(all_languages, env_groups),
        relatives=default_relatives(env_groups, langs_with_solutions),
        preview=preview,
    )
```

Add a `relatives` parameter to `prompt_group_assignment` (defaults to `None`) and
pass it into `GroupPickerState(..., relatives=relatives)`.

**Step 5: Run tests**

Run: `uv run pytest tests/rbx/box/test_timing.py tests/rbx/box/test_timing_group_picker.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add rbx/box/timing.py rbx/box/timing_group_picker.py tests/rbx/box/test_timing.py
git commit -m "feat(timing): seed picker relatives from env whenEmpty for empty groups"
```

---

## Task 8: Docs + full verification

**Files:**
- Modify: `docs/setters/reference/environment/index.md` (note picker can now force a relative limit), and any `rbx time` walkthrough doc that lists picker hotkeys (search `grep -rn "leftover\|singleton\|rbx time" docs`).
- Test: full suite.

**Step 1: Update docs**

In the timing/`whenEmpty` reference section, add a short paragraph: in `rbx time`
the picker lets you force any group's limit to be relative to another group
(`A·t + B`) with `r`, and reset to the env grouping with `R`. Keep it to a few
sentences; mirror surrounding doc tone.

**Step 2: Lint + format**

Run: `uv run ruff check --fix . && uv run ruff format .`
Expected: clean.

**Step 3: Run the full timing-related suite**

Run: `uv run pytest tests/rbx/box/test_timing_groups.py tests/rbx/box/test_timing_group_picker.py tests/rbx/box/test_timing.py tests/rbx/box/test_timing_estimation.py tests/rbx/box/test_timing_preview.py tests/rbx/box/test_limits_table.py -v`
Expected: all PASS.

**Step 4: Run the broader box suite (catch fallout)**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: PASS (modulo the pre-existing C++/sandbox/docker failures noted in
project memory — confirm any failures match that known set, not new ones).

**Step 5: Verify docs build**

Run: `uv run mkdocs build` (non-strict; ~9 pre-existing strict warnings are known
and unrelated per project memory).
Expected: build succeeds.

**Step 6: Commit**

```bash
git add docs
git commit -m "docs(timing): document forced relative limits in rbx time picker"
```

---

## Notes & Edge Cases

- **Hashability for `lru_cache`**: if threading `LanguageGroupFallback` through the
  memoized preview raises `unhashable type`, mark the model `frozen=True`
  (Task 3, Step 4). It is constructed-once, never mutated.
- **Group-key churn**: moving a language out of a relative group changes its
  group-key; `prune_relatives()` drops orphaned specs at confirm/preview time.
  This is the intended "user's responsibility" behavior — `R` reset recovers the
  env grouping.
- **`relativeTo` drift**: the reference stores a representative language; if that
  language is later re-bucketed, the reference follows it. `validate_partition`
  still rejects self-reference and cycles, and the live preview surfaces the error
  inline and blocks confirm.
- **Singletons share state `-1`** in `numbers` but get distinct `s:{lang}` keys —
  this is why relatives are keyed by `group_key`, not by the raw state int.
- **`auto` path unchanged**: `build_partition` + env `whenEmpty` (empty-only) still
  governs non-interactive estimation; forced relatives only exist on the picker path.
```
