# Dynamic Completers Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the dynamic shell completers from issue #575 (solutions, outcome, verification-level, profile, testgroup, contest-variant, contest-problem) and a file-union mechanism so `rbx run`/`stress` solution positions complete registered solutions + `@`-prefixes + files.

**Architecture:** Light completers in `rbx/box/completion/completers.py` (read package YAML via `peek`, hardcode enum tables guarded by consistency tests). Wire them to Typer params via `rbx.annotations._adapt(key)`. Extend the spec/engine/parity-test trio so a completer value may also hand off to shell file-completion (`file` flag) and so variadic arguments re-offer their completer. Regenerate the committed `_spec.py`.

**Tech Stack:** Python 3.13, Typer 0.21 / Click 8.3, pytest, ruff, `uv`/`mise`.

**Design doc:** `docs/plans/2026-06-09-completers-design.md`

**Conventions:** single quotes; absolute imports; completers MUST stay light (no `schema`/`environment`/`remote`/`contest`/`cli` imports). Commit with the `/commit` skill (conventional commits, `Co-Authored-By: Claude <noreply@anthropic.com>`). Run tests with `uv run pytest`.

---

## Phase A — File-union + variadic infrastructure

### Task A1: `_adapt(key, *, file=False)` carries a file flag

**Files:**
- Modify: `rbx/annotations.py` (the `_adapt` function, ~line 16-39)
- Test: `tests/rbx/box/completion/annotations_light_test.py`

**Step 1: Write the failing test** (append to `annotations_light_test.py`)

```python
def test_adapt_file_flag_tags_callback():
    from rbx import annotations

    cb = annotations._adapt('solutions', file=True)  # noqa: SLF001
    assert cb._completer_key == 'solutions'  # noqa: SLF001
    assert cb._completer_file == 'file'  # noqa: SLF001


def test_adapt_without_file_flag_has_no_file_attr():
    from rbx import annotations

    cb = annotations._adapt('language')  # noqa: SLF001
    assert getattr(cb, '_completer_file', None) is None
```

**Step 2: Run, expect FAIL**

`uv run pytest tests/rbx/box/completion/annotations_light_test.py -q`
Expected: FAIL (`_adapt() got an unexpected keyword argument 'file'`).

**Step 3: Implement.** Change the signature and tag the closure:

```python
def _adapt(key: str, *, file: bool = False):
    """Typer autocompletion callback that delegates to the registry completer `key`.

    Builds the same CompletionContext the fast engine builds, so real-Typer and
    fast-path completions agree. Returns plain string values (Typer wraps them).

    When `file=True`, the param's value position should ALSO hand off to the
    shell's default file completion after the dynamic candidates. Typer's callback
    contract cannot emit a file directive, so we only TAG the callback here; the
    spec generator records the flag and the fast engine appends the directive.
    """

    def _cb(incomplete: str = ''):
        from rbx.box.completion import (
            completers,  # noqa: F401  (registers keys)
            context,
        )
        from rbx.box.completion.registry import CompletionContext, load_completer

        ctx = CompletionContext(
            args=[],
            command=(),
            option_values={},
            package_root=context.find_package_root(),
        )
        return [item.value for item in load_completer(key)(ctx, incomplete)]

    _cb._completer_key = key  # noqa: SLF001  read by the spec generator to recover the key
    if file:
        _cb._completer_file = 'file'  # noqa: SLF001  read by the spec generator
    return _cb
```

**Step 4: Run, expect PASS.** Same command.

**Step 5: Commit**

```bash
git add rbx/annotations.py tests/rbx/box/completion/annotations_light_test.py
# /commit -> feat(completion): let _adapt tag a file-union completer
```

---

### Task A2: generator records `variadic` args and the `file` value flag

**Files:**
- Modify: `rbx/box/completion/generate.py` (`_value_spec` ~line 95-108, `_param_spec` ~line 111-124)
- Test: `tests/rbx/box/completion/generate_test.py`

**Step 1: Write failing tests** (append to `generate_test.py`)

```python
def test_variadic_argument_flagged():
    from typing import List, Optional

    app = typer.Typer()

    @app.command()
    def run(
        names: Optional[List[str]] = typer.Argument(None),
    ):
        pass

    spec = build_spec(_cli(app), name='run')
    arg = next(p for p in spec['params'] if p['kind'] == 'argument')
    assert arg['variadic'] is True


def test_file_union_completer_value_flagged():
    @registry.register_completer('gen_sol')
    def _gen_sol(ctx, incomplete):
        return []

    cb = _gen_sol
    cb._completer_file = 'file'  # noqa: SLF001  emulate _adapt(file=True)

    app = typer.Typer()

    @app.command()
    def run(
        sols: Annotated[str, typer.Argument(autocompletion=cb)] = '',
    ):
        pass

    spec = build_spec(_cli(app), name='run')
    arg = next(p for p in spec['params'] if p['kind'] == 'argument')
    assert arg['value'] == {'kind': 'completer', 'completer': 'gen_sol', 'file': 'file'}
```

**Step 2: Run, expect FAIL.**
`uv run pytest tests/rbx/box/completion/generate_test.py -q`
Expected: FAIL (`KeyError: 'variadic'` / missing `'file'`).

**Step 3: Implement.**

In `_value_spec`, after computing `key`:

```python
def _value_spec(param: click.Parameter) -> Dict[str, Any]:
    key = _completer_key(param)
    if key is not None:
        spec: Dict[str, Any] = {'kind': 'completer', 'completer': key}
        file_flag = _completer_file(param)
        if file_flag is not None:
            spec['file'] = file_flag
        return spec
    ...  # unchanged
```

Add the probe helper next to `_completer_key`:

```python
def _completer_file(param: click.Parameter) -> Optional[str]:
    """Return the file-union flag ('file'/'dir') a completer callback was tagged
    with via `_adapt(file=...)`, or None. Mirrors `_completer_key`'s candidate
    probe so it survives Typer's wrapper chain."""
    for fn in _completer_candidates(param):
        flag = getattr(fn, '_completer_file', None)
        if flag is not None:
            return flag
    return None
```

In `_param_spec`, add `variadic` for arguments (`nargs == -1`):

```python
def _param_spec(param: click.Parameter) -> Dict[str, Any]:
    is_opt = isinstance(param, click.Option)
    is_flag = bool(getattr(param, 'is_flag', False))
    names = list(param.opts) + list(getattr(param, 'secondary_opts', []))
    spec: Dict[str, Any] = {
        'kind': 'option' if is_opt else 'argument',
        'names': names if is_opt else [],
        'takes_value': not is_flag,
        'multiple': bool(getattr(param, 'multiple', False)),
        'help': getattr(param, 'help', None) if is_opt else None,
        'value': {'kind': 'none'} if is_flag else _value_spec(param),
    }
    if not is_opt and getattr(param, 'nargs', 1) == -1:
        spec['variadic'] = True
    return spec
```

Also update the module docstring `Param = {...}` block to mention the optional
`'variadic'` key and the value's optional `'file'` key.

**Step 4: Run, expect PASS.**
`uv run pytest tests/rbx/box/completion/generate_test.py -q`

**Step 5: Commit**
```bash
git add rbx/box/completion/generate.py tests/rbx/box/completion/generate_test.py
# /commit -> feat(completion): generate variadic + file-union spec flags
```

---

### Task A3: engine appends FILE for the file flag and re-offers variadic args

**Files:**
- Modify: `rbx/box/completion/engine.py` (`_value_items` ~line 100-110, `resolve` positional block ~line 213-216)
- Test: `tests/rbx/box/completion/engine_test.py`

**Step 1: Write failing tests** (append to the synthetic section of `engine_test.py`)

```python
def test_completer_with_file_flag_appends_file_directive():
    module_name = 'tests.rbx.box.completion._fixture_completer'
    registry.register_completer_path('engine_fu', f'{module_name}:fixture_completer')
    spec = _leaf(
        [
            {
                'kind': 'argument',
                'names': [],
                'takes_value': True,
                'help': None,
                'variadic': True,
                'value': {'kind': 'completer', 'completer': 'engine_fu', 'file': 'file'},
            }
        ]
    )
    items = resolve(spec, [], '')
    assert _values(items) == ['from-fixture', '']
    assert items[-1].type == 'file'


def test_variadic_argument_reoffered_on_later_positionals():
    module_name = 'tests.rbx.box.completion._fixture_completer'
    registry.register_completer_path('engine_fu2', f'{module_name}:fixture_completer')
    spec = _leaf(
        [
            {
                'kind': 'argument',
                'names': [],
                'takes_value': True,
                'help': None,
                'variadic': True,
                'value': {'kind': 'completer', 'completer': 'engine_fu2'},
            }
        ]
    )
    # Two positionals already consumed, but the (only) argument is variadic, so
    # the completer is still offered.
    items = resolve(spec, ['a', 'b'], '')
    assert _values(items) == ['from-fixture']
```

**Step 2: Run, expect FAIL.**
`uv run pytest tests/rbx/box/completion/engine_test.py -q`

**Step 3: Implement.**

`_value_items` — append the directive when `file` is set:

```python
def _value_items(
    value: Dict[str, Any], ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    kind = value.get('kind')
    if kind == 'choice':
        return [CompletionItem(c) for c in value['choices'] if c.startswith(incomplete)]
    if kind == 'completer':
        items = list(load_completer(value['completer'])(ctx, incomplete))
        file_flag = value.get('file')
        if file_flag == 'dir':
            items = items + DIR
        elif file_flag == 'file':
            items = items + FILE
        return items
    if kind == 'path':
        return DIR if value.get('path') == 'dir' else FILE
    return FILE  # 'none'/unknown -> shell default file completion
```

`resolve` positional block — clamp to the last argument when it is variadic:

```python
        arguments = [p for p in node['params'] if p['kind'] == 'argument']
        if positional < len(arguments):
            return _value_items(arguments[positional]['value'], ctx, incomplete)
        if arguments and arguments[-1].get('variadic'):
            # A variadic last argument keeps consuming positionals, so the real CLI
            # re-offers its completer at every position past it.
            return _value_items(arguments[-1]['value'], ctx, incomplete)
        return FILE
```

**Step 4: Run, expect PASS.** Same command. Also run the full engine + robustness suite:
`uv run pytest tests/rbx/box/completion/engine_test.py tests/rbx/box/completion/robustness_test.py -q`

**Step 5: Commit**
```bash
git add rbx/box/completion/engine.py tests/rbx/box/completion/engine_test.py
# /commit -> feat(completion): engine file-union directive + variadic re-offer
```

---

### Task A4: differential-test exemption for file-union positions

**Files:**
- Modify: `tests/rbx/box/completion/differential_test.py`

**Step 1: Add a helper + branch.** After `_is_command_name_position`, add a resolver
for the value the cursor sits on, then exempt file-union positions.

```python
def _cursor_value(args, incomplete):
    """The spec 'value' dict the cursor is completing, or None (option-name,
    group, or past-the-end position)."""
    node, _cmd, _opts, pending, positional, _seen = _walk(_spec.SPEC, list(args))
    if pending is not None:
        return pending['value']
    if incomplete.startswith('-') and '=' in incomplete:
        name = incomplete.split('=', 1)[0]
        for p in node['params']:
            if p['kind'] == 'option' and name in p['names'] and p['takes_value']:
                return p['value']
        return None
    if incomplete.startswith('-') or node.get('is_group'):
        return None
    arguments = [p for p in node['params'] if p['kind'] == 'argument']
    if positional < len(arguments):
        return arguments[positional]['value']
    if arguments and arguments[-1].get('variadic'):
        return arguments[-1]['value']
    return None
```

In `test_engine_matches_typer`, right after computing `ours` and BEFORE the
command-name branch, add:

```python
    value = _cursor_value(args, incomplete)
    if value is not None and value.get('kind') == 'completer' and value.get('file'):
        # File-union: the engine intentionally appends a shell file/dir directive
        # that Typer's callback contract can never emit. Assert the dynamic part
        # matches Typer exactly and that the directive IS appended.
        gold = _pairs(typer_completions(args, incomplete))
        non_dir = [p for p in ours if p not in _DIRECTIVES]
        assert non_dir == gold, f'args={args} inc={incomplete!r}: {non_dir} vs {gold}'
        assert set(ours) & _DIRECTIVES, f'args={args} inc={incomplete!r}: no file directive'
        return
```

**Step 2: Run** the differential test now (no file-union completer is wired yet,
so the new branch is dormant but must not break existing parity):
`uv run pytest tests/rbx/box/completion/differential_test.py -q`
Expected: PASS (unchanged behavior).

**Step 3: Commit**
```bash
git add tests/rbx/box/completion/differential_test.py
# /commit -> test(completion): exempt file-union positions from strict parity
```

---

## Phase B — The completers (light; in `completers.py`)

> All completers go in `rbx/box/completion/completers.py` with `@register_completer`.
> Unit tests go in `tests/rbx/box/completion/completers_test.py` using the existing
> `_ctx(**kw)` helper. Consistency tests (allowed to import the heavy app) go in a
> NEW file `tests/rbx/box/completion/enum_consistency_test.py`.

### Task B1: `solutions` completer

**Files:** Modify `rbx/box/completion/completers.py`; test `completers_test.py`.

**Step 1: Write failing test**

```python
def test_solutions_completer_lists_paths_with_outcome_help_and_prefixes(tmp_path):
    (tmp_path / 'problem.rbx.yml').write_text(
        'solutions:\n'
        '  - path: sols/main.cpp\n'
        '    outcome: ac\n'
        '  - path: sols/wa.cpp\n'
        '    outcome: wa\n'
    )
    items = completers.complete_solutions(_ctx(package_root=tmp_path), '')
    by_value = {i.value: i for i in items}
    assert 'sols/main.cpp' in by_value
    assert by_value['sols/main.cpp'].help == 'ac'
    assert '@main' in by_value
    assert '@boca/' in by_value


def test_solutions_completer_without_package_offers_prefixes(tmp_path):
    values = {i.value for i in completers.complete_solutions(_ctx(package_root=None), '')}
    assert {'@main', '@boca/'} <= values
```

**Step 2: Run, expect FAIL.**
`uv run pytest tests/rbx/box/completion/completers_test.py -q`

**Step 3: Implement** (add to `completers.py`):

```python
# Built-in solution-path expanders (kept in sync with rbx/box/remote.py via
# enum_consistency_test.py). @boca needs a run id we cannot enumerate, so we
# offer only the prefix.
_SOLUTION_PREFIXES = (
    ('@main', 'first accepted solution'),
    ('@boca/', 'download a BOCA submission, e.g. @boca/123'),
)


@register_completer('solutions')
def complete_solutions(
    ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    items: List[CompletionItem] = []
    root = ctx.package_root
    if root is not None:
        data = peek.peek(Path(root) / 'problem.rbx.yml')
        for sol in data.get('solutions', []):
            if isinstance(sol, dict) and sol.get('path'):
                outcome = sol.get('outcome')
                help_text = str(outcome) if outcome is not None else None
                items.append(CompletionItem(str(sol['path']), help=help_text))
    items += [CompletionItem(v, help=h) for v, h in _SOLUTION_PREFIXES]
    return items
```

**Step 4: Run, expect PASS.**

**Step 5: Commit**
```bash
git add rbx/box/completion/completers.py tests/rbx/box/completion/completers_test.py
# /commit -> feat(completion): solutions completer (paths + outcomes + @prefixes)
```

---

### Task B2: `outcome` completer + consistency test

**Files:** Modify `completers.py`; tests in `completers_test.py` and new `enum_consistency_test.py`.

**Step 1: Write failing tests**

In `completers_test.py`:

```python
def test_outcome_completer_offers_canonical_tokens():
    values = {i.value for i in completers.complete_outcome(_ctx(), '')}
    assert {'ac', 'wa', 'tle', 'any'} <= values
    helps = {i.value: i.help for i in completers.complete_outcome(_ctx(), '')}
    assert helps['ac']  # has descriptive help
```

In NEW `tests/rbx/box/completion/enum_consistency_test.py`:

```python
from rbx.box.completion import completers


def test_outcome_table_matches_expected_outcome_enum():
    from rbx.box.schema import ExpectedOutcome

    tokens = [v for v, _ in completers._OUTCOME_TABLE]  # noqa: SLF001
    # Every offered token parses to a valid ExpectedOutcome...
    parsed = {ExpectedOutcome(t) for t in tokens}
    # ...and every enum member is represented exactly once.
    assert parsed == set(ExpectedOutcome)
    assert len(tokens) == len(set(tokens)) == len(set(ExpectedOutcome))
```

**Step 2: Run, expect FAIL** (both files).

**Step 3: Implement** (add to `completers.py`):

```python
# (token, human description). Kept complete vs ExpectedOutcome by
# enum_consistency_test.py -- exactly one token per enum member.
_OUTCOME_TABLE = (
    ('any', 'matches any verdict'),
    ('ac', 'accepted'),
    ('ac/tle', 'accepted or time limit exceeded'),
    ('wa', 'wrong answer'),
    ('incorrect', 'any incorrect verdict (WA/RTE/MLE/OLE/TLE)'),
    ('rte', 'runtime error'),
    ('tle', 'time limit exceeded'),
    ('mle', 'memory limit exceeded'),
    ('ole', 'output limit exceeded'),
    ('tle/rte', 'time limit exceeded or runtime error'),
    ('jf', 'judge failed'),
    ('ce', 'compilation error'),
)


@register_completer('outcome')
def complete_outcome(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    return [CompletionItem(v, help=h) for v, h in _OUTCOME_TABLE]
```

**Step 4: Run, expect PASS.** If the consistency test fails because a token maps
to the wrong/duplicate member, adjust the token to the canonical alias for that
member (see `rbx/box/schema.py` `ExpectedOutcome`). Do NOT import the enum into
`completers.py`.

**Step 5: Commit**
```bash
git add rbx/box/completion/completers.py tests/rbx/box/completion/completers_test.py tests/rbx/box/completion/enum_consistency_test.py
# /commit -> feat(completion): outcome completer with descriptive help
```

---

### Task B3: `verification_level` completer + consistency test

**Files:** Modify `completers.py`; tests in `completers_test.py` + `enum_consistency_test.py`.

**Step 1: Write failing tests**

`completers_test.py`:

```python
def test_verification_level_completer_offers_int_values_with_names():
    items = completers.complete_verification_level(_ctx(), '')
    by_value = {i.value: i.help for i in items}
    assert by_value['0'] == 'NONE'
    assert by_value['4'] == 'FULL'
```

`enum_consistency_test.py`:

```python
def test_verification_table_matches_verification_level_enum():
    from rbx.box.environment import VerificationLevel

    table = dict(completers._VERIFICATION_TABLE)  # noqa: SLF001
    expected = {str(level.value): level.name for level in VerificationLevel}
    assert table == expected
```

**Step 2: Run, expect FAIL.**

**Step 3: Implement** (add to `completers.py`):

```python
# (value, level name). Kept in sync with environment.VerificationLevel by
# enum_consistency_test.py.
_VERIFICATION_TABLE = (
    ('0', 'NONE'),
    ('1', 'VALIDATE'),
    ('2', 'FAST_SOLUTIONS'),
    ('3', 'ALL_SOLUTIONS'),
    ('4', 'FULL'),
)


@register_completer('verification_level')
def complete_verification_level(
    ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    return [CompletionItem(v, help=h) for v, h in _VERIFICATION_TABLE]
```

**Step 4: Run, expect PASS.**

**Step 5: Commit**
```bash
git add rbx/box/completion/completers.py tests/rbx/box/completion/completers_test.py tests/rbx/box/completion/enum_consistency_test.py
# /commit -> feat(completion): verification-level completer
```

---

### Task B4: `profile` completer

**Files:** Modify `completers.py`; test `completers_test.py`.

**Step 1: Write failing test**

```python
def test_profile_completer_lists_limits_files(tmp_path):
    limits = tmp_path / '.limits'
    limits.mkdir()
    (limits / 'local.yml').write_text('')
    (limits / 'codeforces.yml').write_text('')
    (limits / 'notes.txt').write_text('')  # ignored
    values = {i.value for i in completers.complete_profile(_ctx(package_root=tmp_path), '')}
    assert values == {'local', 'codeforces'}
```

**Step 2: Run, expect FAIL.**

**Step 3: Implement**

```python
@register_completer('profile')
def complete_profile(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    root = ctx.package_root
    if root is None:
        return []
    limits_dir = Path(root) / '.limits'
    if not limits_dir.is_dir():
        return []
    return _items(p.stem for p in limits_dir.glob('*.yml'))
```

**Step 4: Run, expect PASS.**

**Step 5: Commit**
```bash
git add rbx/box/completion/completers.py tests/rbx/box/completion/completers_test.py
# /commit -> feat(completion): profile completer from .limits/*.yml
```

---

### Task B5: `testgroup` completer

**Files:** Modify `completers.py`; test `completers_test.py`.

**Step 1: Write failing test**

```python
def test_testgroup_completer_lists_group_names(tmp_path):
    (tmp_path / 'problem.rbx.yml').write_text(
        'testcases:\n'
        '  - name: samples\n'
        '  - name: main\n'
        '  - name: edge\n'
    )
    values = {i.value for i in completers.complete_testgroup(_ctx(package_root=tmp_path), '')}
    assert {'samples', 'main', 'edge'} <= values
```

**Step 2: Run, expect FAIL.**

**Step 3: Implement**

```python
@register_completer('testgroup')
def complete_testgroup(
    ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    root = ctx.package_root
    if root is None:
        return []
    data = peek.peek(Path(root) / 'problem.rbx.yml')
    names = {
        g.get('name')
        for g in data.get('testcases', [])
        if isinstance(g, dict)
    }
    return _items(n for n in names if n)
```

**Step 4: Run, expect PASS.**

**Step 5: Commit**
```bash
git add rbx/box/completion/completers.py tests/rbx/box/completion/completers_test.py
# /commit -> feat(completion): testgroup completer
```

---

### Task B6: `contest_variant` completer

**Files:** Modify `completers.py`; test `completers_test.py`.

**Step 1: Write failing test**

```python
def test_contest_variant_completer_lists_sibling_ids(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text('name: c\n')
    (tmp_path / 'contest.div1.rbx.yml').write_text('name: d1\n')
    (tmp_path / 'contest.div2.rbx.yml').write_text('name: d2\n')
    values = {
        i.value
        for i in completers.complete_contest_variant(_ctx(package_root=tmp_path), '')
    }
    assert values == {'div1', 'div2'}


def test_contest_variant_completer_walks_up_from_problem_dir(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text('name: c\n')
    (tmp_path / 'contest.div1.rbx.yml').write_text('name: d1\n')
    prob = tmp_path / 'A'
    prob.mkdir()
    (prob / 'problem.rbx.yml').write_text('name: A\n')
    values = {
        i.value
        for i in completers.complete_contest_variant(_ctx(package_root=prob), '')
    }
    assert values == {'div1'}
```

**Step 2: Run, expect FAIL.**

**Step 3: Implement**

```python
_CONTEST_PREFIX = 'contest.'
_CONTEST_SUFFIX = '.rbx.yml'


def _find_contest_root(start: Optional[Path]) -> Optional[Path]:
    """Nearest ancestor (incl. start) holding a contest.rbx.yml. Light, no load."""
    if start is None:
        return None
    cur = Path(start)
    for d in [cur, *cur.parents]:
        if (d / 'contest.rbx.yml').exists():
            return d
    return None


@register_completer('contest_variant')
def complete_contest_variant(
    ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    root = _find_contest_root(ctx.package_root)
    if root is None:
        return []
    ids = []
    for p in root.glob(f'{_CONTEST_PREFIX}*{_CONTEST_SUFFIX}'):
        name = p.name[len(_CONTEST_PREFIX) : -len(_CONTEST_SUFFIX)]
        if name:
            ids.append(name)
    return _items(ids)
```

Add `Optional` to the existing `typing` import in `completers.py` if not present.

**Step 4: Run, expect PASS.**

**Step 5: Commit**
```bash
git add rbx/box/completion/completers.py tests/rbx/box/completion/completers_test.py
# /commit -> feat(completion): contest-variant completer
```

---

### Task B7: extend `problem` completer with aliases

**Files:** Modify `completers.py` (`complete_problem`); test `completers_test.py`.

**Step 1: Write failing test**

```python
def test_problem_completer_includes_aliases(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text(
        'problems:\n'
        '  - short_name: A\n'
        '    aliases: [apple, alpha]\n'
        '  - short_name: B\n'
    )
    values = {
        i.value for i in completers.complete_problem(_ctx(package_root=tmp_path), '')
    }
    assert {'A', 'B', 'apple', 'alpha'} <= values
```

**Step 2: Run, expect FAIL.**

**Step 3: Implement.** Replace the body of `complete_problem`:

```python
@register_completer('problem')
def complete_problem(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    root = ctx.package_root
    if root is None:
        return []
    data = peek.peek(Path(root) / 'contest.rbx.yml')
    names = set()
    for p in data.get('problems', []):
        if not isinstance(p, dict):
            continue
        if p.get('short_name'):
            names.add(p['short_name'])
        for alias in p.get('aliases', []) or []:
            if alias:
                names.add(alias)
    return _items(names)
```

**Step 4: Run, expect PASS.** Also rerun the existing problem test:
`uv run pytest tests/rbx/box/completion/completers_test.py -q`

**Step 5: Commit**
```bash
git add rbx/box/completion/completers.py tests/rbx/box/completion/completers_test.py
# /commit -> feat(completion): include problem aliases in problem completer
```

---

## Phase C — Wiring, regen, and guards

> After wiring (Tasks C1-C5) regenerate the spec ONCE (Task C6). Wiring before
> regen makes `drift_test.py` red — that is expected until C6.

### Task C1: wire `rbx run` / `rbx irun` (solutions, outcome)

**Files:** Modify `rbx/box/cli.py` (run ~311-325, irun ~646-689).

Add `from rbx import annotations` import if not already present (it likely is —
check the top of `cli.py`).

- `solutions` argument (both `run` and `irun`): add
  `autocompletion=annotations._adapt('solutions', file=True)` to the
  `typer.Argument(...)`.
- `outcome` option (both): add `autocompletion=annotations._adapt('outcome')`.

Example (run's `solutions`):

```python
    solutions: Annotated[
        Optional[List[str]],
        PackagePath,
        typer.Argument(
            help='Path to solutions to run. If not specified, will run all solutions.',
            autocompletion=annotations._adapt('solutions', file=True),  # noqa: SLF001
        ),
    ] = None,
```

Example (run's `outcome`):

```python
    outcome: Optional[str] = typer.Option(
        None,
        '--outcome',
        '-o',
        help='Include only solutions whose expected outcomes intersect with this.',
        autocompletion=annotations._adapt('outcome'),  # noqa: SLF001
    ),
```

**Verify import light:** `_adapt` is in `rbx/annotations.py` (light). Calling it
at module import returns a closure; no heavy import triggered.

**Test:** none yet (spec not regen'd). Just ensure `uv run rbx run --help` works:
`uv run rbx run --help | head -3` → no error.

**Commit**
```bash
git add rbx/box/cli.py
# /commit -> feat(completion): wire run/irun solutions + outcome completers
```

---

### Task C2: wire `irun -t` and `stress` (finder, fuzz-on, reference)

**Files:** Modify `rbx/box/cli.py` (irun `testcase` ~682-689, stress ~849-943).

- `testcase` option (irun): `autocompletion=annotations._adapt('testgroup')`.
- `finder` (stress): `autocompletion=annotations._adapt('solutions', file=True)`.
- `fuzz_on` (stress): `autocompletion=annotations._adapt('testgroup')`.
- `reference_solution` (stress `--reference`):
  `autocompletion=annotations._adapt('solutions', file=True)`.

**Test:** `uv run rbx stress --help | head -3` and `uv run rbx irun --help | head -3`
→ no error.

**Commit**
```bash
git add rbx/box/cli.py
# /commit -> feat(completion): wire testcase + stress finder/fuzz-on/reference
```

---

### Task C3: wire `--verification-level` (shared `VerificationParam`)

**Files:** Modify `rbx/box/environment.py` (`VerificationParam` ~42-51).

```python
VerificationParam = Annotated[
    int,
    typer.Option(
        '--verification-level',
        '--verification',
        '-v',
        help='Verification level to use when building package.',
        default_factory=lambda: VerificationLevel.FULL.value,
        autocompletion=_verification_autocompletion(),
    ),
]
```

To keep `environment.py`'s import light AND avoid a circular import, define a
tiny local indirection at the top of `environment.py`:

```python
def _verification_autocompletion():
    from rbx import annotations

    return annotations._adapt('verification_level')  # noqa: SLF001
```

(Importing `rbx.annotations` is light; it does not import `rbx.config` — see
`annotations_light_test.py`.) If `environment.py` already imports `rbx.annotations`
elsewhere, call `annotations._adapt('verification_level')` directly instead.

**Test:** `uv run rbx build --help | head -3` → no error. This wires all 9 sites.

**Commit**
```bash
git add rbx/box/environment.py
# /commit -> feat(completion): wire verification-level completer everywhere
```

---

### Task C4: wire `--profile` (4 sites) and `-C/--contest` (2 sites)

**Files:** Modify
- `rbx/box/cli.py` (global `--profile` ~153-160, `time --profile` ~527-532; global `-C` ~166-177)
- `rbx/box/statements/build_statements.py` (`--profile` ~326-333)
- `rbx/box/contest/statements.py` (`--profile` ~68-75)
- `rbx/box/contest/main.py` (`-C` callback ~38-46)

For each `--profile` `typer.Option(...)` add `autocompletion=annotations._adapt('profile')`.
For each `-C/--contest` `typer.Option(...)` add `autocompletion=annotations._adapt('contest_variant')`.

Ensure each of those four files imports `rbx.annotations` (light). Check the file
header; add `from rbx import annotations` if missing.

**Test:** `uv run rbx time --help | head -3`, `uv run rbx --help | head -3`,
`uv run rbx statements build --help | head -3` → no error.

**Commit**
```bash
git add rbx/box/cli.py rbx/box/statements/build_statements.py rbx/box/contest/statements.py rbx/box/contest/main.py
# /commit -> feat(completion): wire profile + contest-variant completers
```

---

### Task C5: wire `rbx on` first positional (cli.py + contest/main.py)

**Files:** Modify `rbx/box/cli.py` (`on` ~239) and `rbx/box/contest/main.py` (`on` ~377).

Wrap the bare `problems: str` in an Annotated Argument with the completer.

`cli.py`:

```python
def on(
    ctx: typer.Context,
    problems: Annotated[
        str, typer.Argument(autocompletion=annotations._adapt('problem'))  # noqa: SLF001
    ],
) -> None:
    contest.on(ctx, problems)
```

`contest/main.py` (`on`): same wrapping of its `problems: str` param. Ensure
`from rbx import annotations` and `from typing_extensions import Annotated` are
imported in both files (check headers).

**Test:** `uv run rbx on --help | head -3` → no error.

**Commit**
```bash
git add rbx/box/cli.py rbx/box/contest/main.py
# /commit -> feat(completion): wire rbx on problem completer
```

---

### Task C6: regenerate the committed spec

**Files:** Modify `rbx/box/completion/_spec.py` (generated).

**Step 1:** `mise run gen-completion-spec`
(equivalently `uv run python -m rbx.box.completion.serialize`).

**Step 2:** Verify the new keys/completers landed:

```bash
uv run python - <<'PY'
from rbx.box.completion import _spec
print('COMPLETERS:', sorted(_spec.COMPLETERS))
PY
```

Expected `COMPLETERS` includes: `checker, contest_variant, language, outcome,
problem, profile, solutions, testgroup, verification_level`.

**Step 3:** Drift test passes:
`uv run pytest tests/rbx/box/completion/drift_test.py -q` → PASS.

**Step 4: Commit**
```bash
git add rbx/box/completion/_spec.py
# /commit -> feat(completion): regenerate spec with new completers
```

---

### Task C7: differential parity + firewall guards

**Files:** Modify `tests/rbx/box/completion/firewall_test.py`.

**Step 1: Run the full differential test** against the regenerated spec — this now
exercises the file-union exemption and every new completer at `incomplete=''`:
`uv run pytest tests/rbx/box/completion/differential_test.py -q` → PASS.

If a file-union position mismatches: confirm `_cursor_value` detects it and the
engine appends exactly one directive. If a plain completer mismatches: the
completer's no-package output must equal what `_adapt` returns (same function) —
check for stray `type`/filtering differences.

**Step 2: Extend the firewall probe** to hit the new completers. Parametrize the
existing test so each scenario stays light:

```python
import pytest

SCENARIOS = [
    ('rbx ', '1'),
    ('rbx run ', '2'),           # solutions completer
    ('rbx run --outcome ', '3'), # outcome completer
    ('rbx irun --testcase ', '3'),  # testgroup completer
    ('rbx build --verification-level ', '3'),  # verification_level
    ('rbx time --profile ', '3'),  # profile
    ('rbx stress --finder ', '3'),  # solutions (file-union)
]


def _modules_after_completion(comp_args: str, cword: str) -> set:
    probe = (
        'import os, sys\n'
        "os.environ['_RBX_COMPLETE'] = 'complete_bash'\n"
        f"os.environ['_TYPER_COMPLETE_ARGS'] = {comp_args!r}\n"
        f"os.environ['COMP_WORDS'] = {comp_args!r}\n"
        f"os.environ['COMP_CWORD'] = {cword!r}\n"
        'from rbx.box import main\n'
        'try:\n'
        '    main.app()\n'
        'except SystemExit:\n'
        '    pass\n'
        "sys.stderr.write('MODULES_START\\n')\n"
        'sys.stderr.write(chr(10).join(sorted(sys.modules)))\n'
    )
    out = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True)
    _, _, mods = out.stderr.partition('MODULES_START\n')
    return set(mods.splitlines())


@pytest.mark.parametrize('comp_args,cword', SCENARIOS)
def test_completion_path_imports_nothing_heavy(comp_args, cword):
    mods = _modules_after_completion(comp_args, cword)
    leaked = [m for m in DENYLIST if any(x == m or x.startswith(m + '.') for x in mods)]
    assert not leaked, f'{comp_args!r} imported heavy modules: {leaked}'
```

Keep `DENYLIST` and the `_PROBE`-replaced helper; remove the now-unused old
single-scenario `_PROBE`/`_modules_after_completion` if replaced.

**Step 3: Run** `uv run pytest tests/rbx/box/completion/firewall_test.py -q` → PASS.

**Step 4: Commit**
```bash
git add tests/rbx/box/completion/firewall_test.py
# /commit -> test(completion): probe new completers stay import-light
```

---

### Task C8: wiring assertion test

**Files:** Create `tests/rbx/box/completion/wiring_test.py`.

**Step 1: Write the test** — assert every issue param resolves to its completer in
the committed spec.

```python
import pytest

from rbx.box.completion import _spec


def _node(path):
    node = _spec.SPEC
    for token in path:
        node = next(
            c for c in node['children']
            if token in [s.strip() for s in c['name'].split(',')]
        )
    return node


def _arg_value(node):
    return next(p for p in node['params'] if p['kind'] == 'argument')['value']


def _opt_value(node, name):
    return next(p for p in node['params'] if p['kind'] == 'option' and name in p['names'])['value']


WIRINGS = [
    (['run'], 'arg', None, 'solutions', 'file'),
    (['irun'], 'arg', None, 'solutions', 'file'),
    (['run'], 'opt', '--outcome', 'outcome', None),
    (['irun'], 'opt', '--testcase', 'testgroup', None),
    (['build'], 'opt', '--verification-level', 'verification_level', None),
    (['time'], 'opt', '--profile', 'profile', None),
    (['stress'], 'opt', '--finder', 'solutions', 'file'),
    (['stress'], 'opt', '--fuzz-on', 'testgroup', None),
    (['stress'], 'opt', '--reference', 'solutions', 'file'),
    (['on'], 'arg', None, 'problem', None),
]


@pytest.mark.parametrize('path,kind,name,completer,file_flag', WIRINGS)
def test_param_wired_to_completer(path, kind, name, completer, file_flag):
    node = _node(path)
    value = _arg_value(node) if kind == 'arg' else _opt_value(node, name)
    assert value.get('kind') == 'completer'
    assert value.get('completer') == completer
    assert value.get('file') == file_flag


def test_contest_variant_flag_wired():
    value = _opt_value(_spec.SPEC, '-C')
    assert value.get('completer') == 'contest_variant'
```

**Step 2: Run, expect PASS** (spec already regenerated):
`uv run pytest tests/rbx/box/completion/wiring_test.py -q`

If a path/name does not match the registered command/option name, adjust the
`WIRINGS` entry to the real spec (inspect with the snippet from C6).

**Step 3: Commit**
```bash
git add tests/rbx/box/completion/wiring_test.py
# /commit -> test(completion): assert issue #575 params wired to completers
```

---

### Task C9: full verification + docs

**Step 1: Full completion suite + lint**

```bash
uv run pytest tests/rbx/box/completion -q
uv run ruff check rbx tests && uv run ruff format --check rbx tests
```

Expected: all PASS. (Benchmark `mise run bench-completion` is informational; run
it to confirm `<tab>` latency hasn't regressed materially.)

**Step 2: Update the module guide.** In `rbx/box/completion/CLAUDE.md`, replace the
final "Gotchas" bullet ("Today only `--language` is wired…") with the new reality:
list the wired completers, note the file-union mechanism (`file` value flag +
engine FILE directive + `variadic` arg re-offer + differential exemption), and
the hardcoded-table + consistency-test pattern for `outcome`/`verification_level`.

**Step 3: Commit**
```bash
git add rbx/box/completion/CLAUDE.md
# /commit -> docs(completion): document the new completers and file-union
```

**Step 4: Manual smoke (optional).** In a real problem package:
`rbx run <tab>` lists solutions + `@main`/`@boca/` + files; `rbx run --outcome <tab>`
lists outcome tokens; `rbx build -v <tab>` lists `0`-`4`.

---

## Done criteria

- All `tests/rbx/box/completion` pass (differential, firewall, drift, wiring,
  enum-consistency, completers, engine).
- `_spec.py` regenerated and committed; drift test green.
- `ruff check` + `ruff format --check` clean.
- Every param in issue #575 resolves to its completer (wiring_test).
