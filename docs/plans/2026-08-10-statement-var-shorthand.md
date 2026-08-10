# Statement var shorthand (#630) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let statement templates write `\VAR{N.max}` instead of `\VAR{vars.N.max}`, in every namespace that carries a `vars` block, without letting a var silently shadow rbx's own template names.

**Architecture:** The keys of a `vars` block are bound into the namespace that contains it (root, `problem`, `contest`, `problems[i]`, each group), while `vars` itself stays. All lifting happens in `rbx/box/statements/context.py`. Collisions are impossible by construction: a new reserved-name list, enforced as a Pydantic `AfterValidator` on `Package.vars`, `TestcaseGroup.vars` and `Contest.vars`, rejects them at load time, and a drift test keeps the hand-written list in sync with the real namespace surface.

**Tech Stack:** Python 3, Pydantic v2 (`AfterValidator`, `PydanticCustomError`), Jinja2 (LaTeX-flavored env in `latex_jinja.py`), pytest.

**Design doc:** `docs/plans/2026-08-10-statement-var-shorthand-design.md`

**Read first:** `rbx/box/statements/CLAUDE.md` (template namespaces table), `rbx/box/CLAUDE.md` (vars and per-group overrides).

**Conventions:** single quotes, absolute imports only, `uv run` for everything. Commit with the `/commit` skill's conventional-commit format (see `.claude/skills/commit.md`); every commit message ends with the `Co-Authored-By: Claude <noreply@anthropic.com>` trailer. Never `git add -A`.

---

## Task 1: Reserved statement var names

The list and its validator go in `rbx/box/fields.py`, not `schema.py`, because
`rbx/box/contest/schema.py` needs them and does *not* import `rbx.box.schema`
today. `fields.py` imports only `rbx.box.safeeval`, so nothing can cycle.

**Files:**
- Modify: `rbx/box/fields.py`
- Test: `tests/rbx/box/test_fields.py` (create if absent)

**Step 1: Write the failing test**

Create/append to `tests/rbx/box/test_fields.py`:

```python
import pytest
from pydantic_core import PydanticCustomError

from rbx.box.fields import (
    RESERVED_STATEMENT_VAR_NAMES,
    check_reserved_statement_var_names,
)


class TestReservedStatementVarNames:
    """Vars are bound into their enclosing statement namespace, so a top-level
    var named after one of rbx's own template names would shadow it."""

    @pytest.mark.parametrize('name', sorted(RESERVED_STATEMENT_VAR_NAMES))
    def test_reserved_primitive_name_is_rejected(self, name: str):
        with pytest.raises(PydanticCustomError, match=f'"{name}" collides with'):
            check_reserved_statement_var_names({name: 1})

    @pytest.mark.parametrize('name', sorted(RESERVED_STATEMENT_VAR_NAMES))
    def test_reserved_dict_name_is_rejected(self, name: str):
        # Unlike the testlib check, nesting *under* the reserved name does not
        # help: the top-level key is what gets bound into the namespace.
        with pytest.raises(PydanticCustomError, match=f'"{name}" collides with'):
            check_reserved_statement_var_names({name: {'max': 1}})

    def test_nesting_the_name_one_level_down_is_accepted(self):
        vars = {'limits': {'score': 1}}
        assert check_reserved_statement_var_names(vars) is vars

    def test_ordinary_names_are_accepted(self):
        vars = {'N': {'max': 100}, 'MAXN': 5}
        assert check_reserved_statement_var_names(vars) is vars
```

**Step 2: Run it to verify it fails**

Run: `uv run pytest tests/rbx/box/test_fields.py -v`
Expected: FAIL — `ImportError: cannot import name 'RESERVED_STATEMENT_VAR_NAMES'`.

**Step 3: Implement**

Append to `rbx/box/fields.py` (it already defines `RecVars`; add the
`Annotated`/`AfterValidator`/`PydanticCustomError` imports it needs):

```python
# Names rbx itself binds into a statement template namespace. Vars are bound
# into their enclosing namespace too (`\VAR{N.max}` == `\VAR{vars.N.max}`), so a
# top-level var with one of these names would shadow rbx's own value.
#
# One union, checked in every position: package vars reach the root, the
# `problem` namespace and every group, so a per-scope list would only relax the
# contest case. Kept honest by the drift test in
# tests/rbx/box/statements/test_context.py.
RESERVED_STATEMENT_VAR_NAMES = frozenset(
    [
        # Root scope (context._common + the two kwargs builders).
        'contest',
        'keyed_languages',
        'lang',
        'languages',
        'params',
        'problem',
        'problems',
        'vars',
        # `problem` namespace (ProblemRenderContext.namespace).
        'blocks',
        'groups',
        'import_dir',
        'import_file',
        'limits',
        'profiles',
        'samples',
        'short_name',
        'title',
        # `contest` namespace (ContestRenderContext.namespace).
        'date',
        'location',
        # Group scope (TestcaseGroup model fields, proxied by GroupView).
        'deps',
        'extraValidators',
        'generatorScript',
        'generators',
        'model_solution',
        'name',
        'outputValidators',
        'score',
        'solutionVisualizer',
        'subgroups',
        'testcaseGlob',
        'testcases',
        'validator',
        'visualizer',
    ]
)


def check_reserved_statement_var_names(vars: RecVars) -> RecVars:
    """Reject top-level var names that collide with a statement template name.

    Every top-level key is checked, dict or primitive: unlike the testlib flag
    check, nesting *under* the reserved name does not help, since the top-level
    key is the one bound into the namespace.
    """
    for key in vars:
        if key in RESERVED_STATEMENT_VAR_NAMES:
            raise PydanticCustomError(
                'RESERVED_STATEMENT_VAR_NAME',
                'Variable "{key}" collides with a name rbx exposes to statement '
                'templates. Vars are bound directly into the enclosing template '
                'namespace, so this variable would shadow rbx\'s own "{key}". '
                'Rename the variable, or nest it under another key (as in '
                '"limits.{key}"). Reserved names: {reserved}.',
                {
                    'key': key,
                    'reserved': ', '.join(sorted(RESERVED_STATEMENT_VAR_NAMES)),
                },
            )
    return vars


CheckedStatementRecVars = Annotated[
    RecVars, AfterValidator(check_reserved_statement_var_names)
]
```

**Step 4: Run it to verify it passes**

Run: `uv run pytest tests/rbx/box/test_fields.py -v`
Expected: PASS (72+ parametrized cases).

**Step 5: Commit**

```bash
git add rbx/box/fields.py tests/rbx/box/test_fields.py
git commit -m "$(cat <<'EOF'
feat(statements): reserve template names for statement vars

Refs #630

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire the check onto the three vars fields

**Files:**
- Modify: `rbx/box/schema.py:112` (the `CheckedRecVars` alias)
- Modify: `rbx/box/contest/schema.py:322` (`Contest.vars`)
- Test: `tests/rbx/box/test_schema.py` (extend the existing reserved-name class, ~line 795)

**Step 1: Write the failing tests**

Append to `tests/rbx/box/test_schema.py`, next to the existing
`RESERVED_VAR_NAMES` class:

```python
class TestReservedStatementVarNamesOnModels:
    def test_reserved_package_var_is_rejected(self):
        from rbx.box.schema import Package

        with pytest.raises(ValidationError, match='"title" collides with'):
            Package(name='problem', timeLimit=1000, memoryLimit=256, vars={'title': 'x'})

    def test_reserved_group_var_is_rejected(self):
        from rbx.box.schema import TestcaseGroup

        with pytest.raises(ValidationError, match='"score" collides with'):
            TestcaseGroup(name='main', vars={'score': 1})

    def test_reserved_contest_var_is_rejected(self):
        from rbx.box.contest.schema import Contest

        with pytest.raises(ValidationError, match='"problems" collides with'):
            Contest(name='contest', vars={'problems': 1})

    def test_testlib_reserved_name_still_rejected(self):
        # Task 2 must not drop the pre-existing testlib check.
        from rbx.box.schema import Package

        with pytest.raises(ValidationError, match=r'--group=<value>'):
            Package(name='problem', timeLimit=1000, memoryLimit=256, vars={'group': 1})

    def test_ordinary_vars_still_accepted(self):
        from rbx.box.schema import Package

        package = Package(
            name='problem', timeLimit=1000, memoryLimit=256, vars={'N': {'max': 100}}
        )
        assert package.expanded_vars == {'N.max': 100}
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_schema.py -k ReservedStatementVarNamesOnModels -v`
Expected: FAIL — the reserved names are accepted, so no `ValidationError` is raised.

**Step 3: Implement**

In `rbx/box/schema.py`, import `check_reserved_statement_var_names` from
`rbx.box.fields` and chain it into the existing alias:

```python
CheckedRecVars = Annotated[
    RecVars,
    AfterValidator(check_reserved_var_names),
    AfterValidator(check_reserved_statement_var_names),
]
```

In `rbx/box/contest/schema.py`, import `CheckedStatementRecVars` from
`rbx.box.fields` and change `Contest.vars` from `RecVars` to
`CheckedStatementRecVars`. Leave the field's `Field(...)` description alone.
Contest vars keep skipping the testlib check — they never reach a validator.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_schema.py -v`
Expected: PASS, including the pre-existing `RESERVED_VAR_NAMES` cases.

Then check nothing else in the suite used a now-reserved name:

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto -x -q`
Expected: PASS. If a fixture package in `testdata/` uses a reserved var name,
rename it there — that is the migration this change asks of users, and the
fixture should demonstrate the new rule rather than dodge it. Note that
`tests/rbx/box/cli` and the `e2e`/`slow`/`docker` markers are excluded by
default; see the pre-existing local failures noted in `CLAUDE.md` before
blaming this change for a C++/sandbox failure.

**Step 5: Commit**

```bash
git add rbx/box/schema.py rbx/box/contest/schema.py tests/rbx/box/test_schema.py
git commit -m "$(cat <<'EOF'
feat(statements): validate statement-reserved names on package and contest vars

BREAKING CHANGE: a top-level var named after a statement template name
(title, name, score, limits, ...) is now rejected; rename it or nest it
one level down.

Refs #630

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Lift vars into the root scope

**Files:**
- Modify: `rbx/box/statements/context.py` (`_wrap` area, `problem_jinja_kwargs`, `contest_jinja_kwargs`)
- Test: `tests/rbx/box/statements/test_context.py` (class `TestProblemNamespaces` and neighbours)

**Step 1: Write the failing test**

Append to `tests/rbx/box/statements/test_context.py`:

```python
class TestVarShorthand:
    def test_problem_root_binds_var_keys_directly(self):
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(vars={'N.max': 100, 'MAXV': 7}),
            contest=_contest_ctx(),
        )

        assert kwargs['N']['max'] == 100
        assert kwargs['MAXV'] == 7
        # The long form keeps working.
        assert kwargs['vars']['N']['max'] == 100

    def test_contest_root_binds_var_keys_directly(self):
        kwargs = context.contest_jinja_kwargs(
            lang='en',
            languages=_langs(),
            contest=_contest_ctx(vars={'year': 2026}),
            problems=[],
        )

        assert kwargs['year'] == 2026
        assert kwargs['vars']['year'] == 2026

    def test_real_root_names_win_over_vars(self):
        # The schema rejects this, but the merge must not depend on that.
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(vars={'lang': 'nope'}),
            contest=_contest_ctx(),
        )

        assert kwargs['lang'] == 'en'

    def test_shorthand_miss_keeps_the_var_hint(self):
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(vars={'N.max': 100}),
            contest=_contest_ctx(),
        )

        with pytest.raises(jinja2.UndefinedError) as exc_info:
            str(kwargs['N']['mim'])
        message = str(exc_info.value)
        assert 'N.mim' in message
        assert 'vars' in message
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_context.py -k TestVarShorthand -v`
Expected: FAIL — `KeyError: 'N'`.

**Step 3: Implement**

In `rbx/box/statements/context.py`, add next to `_wrap`:

```python
def _lift(namespace: Dict[str, Any], vars: Vars, key: str) -> Dict[str, Any]:
    """Bind a var block's keys into the namespace that contains it (#630).

    `\\VAR{N.max}` is shorthand for `\\VAR{vars.N.max}`. Real namespace keys are
    merged last so they win: the schema already rejects a colliding var name,
    and this ordering means a namespace key added without updating
    RESERVED_STATEMENT_VAR_NAMES loses the shorthand rather than being shadowed
    by user data.
    """
    wrapper = _wrap(vars, key)
    return {**wrapper, **namespace, 'vars': wrapper}
```

`JinjaDictWrapper.from_dict` already rebuilds dotted keys into nested wrappers,
so `{**wrapper}` yields `N` as a wrapper carrying `prefix='N'` — that is what
keeps the `"N.mim" was not found in "vars"` hint working through the shorthand.

Then in `problem_jinja_kwargs`, replace the `'vars': _wrap(...)` entry so the
update reads:

```python
    res.update(
        {
            'params': _wrap(problem.params, 'params'),
            'contest': contest.namespace(),
            'problem': problem.namespace(),
        }
    )
    return _lift(res, problem.vars, 'vars')
```

Note `_common`'s keys (`lang`, `languages`, `keyed_languages`) are already in
`res` before the lift, so they win. Do the same in `contest_jinja_kwargs` with
`contest.vars`.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/test_context.py -v`
Expected: PASS (existing namespace tests included).

**Step 5: Commit**

```bash
git add rbx/box/statements/context.py tests/rbx/box/statements/test_context.py
git commit -m "$(cat <<'EOF'
feat(statements): bind vars into the root template scope

Refs #630

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Lift vars into the `problem` and `contest` namespaces

**Files:**
- Modify: `rbx/box/statements/context.py` (`ProblemRenderContext.namespace`, `ContestRenderContext.namespace`)
- Test: `tests/rbx/box/statements/test_context.py` (class `TestVarShorthand`)

**Step 1: Write the failing test**

Append to `TestVarShorthand`:

```python
    def test_problem_namespace_binds_var_keys(self):
        ns = _problem_ctx(vars={'N.max': 100}).namespace()

        assert ns['N']['max'] == 100
        assert ns['vars']['N']['max'] == 100

    def test_contest_namespace_binds_var_keys(self):
        ns = _contest_ctx(vars={'year': 2026}).namespace()

        assert ns['year'] == 2026
        assert ns['vars']['year'] == 2026

    def test_join_member_problems_bind_var_keys(self):
        kwargs = context.contest_jinja_kwargs(
            lang='en',
            languages=_langs(),
            contest=_contest_ctx(),
            problems=[_problem_ctx(vars={'N.max': 100})],
        )

        assert kwargs['problems'][0]['N']['max'] == 100

    def test_real_namespace_names_win_in_problem(self):
        ns = _problem_ctx(title='Real', vars={'title': 'nope'}).namespace()

        assert ns['title'] == 'Real'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_context.py -k TestVarShorthand -v`
Expected: FAIL — `KeyError: 'N'` from `namespace()`.

**Step 3: Implement**

In both `namespace()` methods, keep building `res` exactly as today (including
the conditional `location`/`date`/`blocks`/`short_name`/`import_*` entries) and
return `_lift(res, self.vars, <key>)` instead of `res`. Use the same wrapper
keys the code uses today so error hints do not change: `'vars'` for
`ProblemRenderContext`, `'contest.vars'` for `ContestRenderContext`. Delete the
now-duplicated `'vars': _wrap(...)` entries from the dict literals — `_lift`
re-adds them.

Because `problems[i]` in a contest join is just `ProblemRenderContext.namespace()`,
the join case falls out for free.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/test_context.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/statements/context.py tests/rbx/box/statements/test_context.py
git commit -m "$(cat <<'EOF'
feat(statements): bind vars into the problem and contest namespaces

Refs #630

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Group shorthand on `GroupView`

**Files:**
- Modify: `rbx/box/statements/context.py:70-74` (`GroupView.__getattr__`)
- Test: `tests/rbx/box/statements/test_context.py` (class `TestGroupViews`)

**Step 1: Write the failing test**

Append to the existing `TestGroupViews` class (it already has the `_group_views()`
helper with `sub1`/`sub2`/`sub3` and package vars `AB.min`/`AB.max`):

```python
    def test_group_var_shorthand_resolves_the_group_set(self):
        groups = _group_views()

        # The override wins through the shorthand...
        assert groups['sub2'].AB['min'] == 100
        # ...and inherited keys still resolve, exactly as g.vars does.
        assert groups['sub2'].AB['max'] == 200
        assert groups['sub1'].AB['max'] == 10

    def test_model_fields_win_over_shorthand(self):
        from rbx.box.schema import TestcaseGroup

        # The schema rejects a var named `score`; the view must not depend on it.
        view = GroupView(TestcaseGroup(name='sub1', score=40), {'score': 999})
        assert view.score == 40

    def test_unknown_group_attribute_keeps_the_var_hint(self):
        groups = _group_views()

        with pytest.raises(jinja2.UndefinedError) as exc_info:
            str(groups['sub2'].NOPE)
        message = str(exc_info.value)
        assert 'NOPE' in message
        assert 'groups.sub2.vars' in message
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/test_context.py -k TestGroupViews -v`
Expected: FAIL — `AttributeError: 'TestcaseGroup' object has no attribute 'AB'`.

**Step 3: Implement**

Rewrite `GroupView.__getattr__`:

```python
    def __getattr__(self, name: str) -> Any:
        # Guard dunders so copy/pickle probes do not recurse through the proxy.
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        try:
            return getattr(self._group, name)
        except AttributeError:
            # Group var shorthand (#630): `g.N.max` == `g.vars.N.max`. Model
            # fields win; a miss returns the wrapper's strict undefined, which
            # carries the `groups.<name>.vars` hint.
            return self.vars[name]
```

Extend the class docstring with a sentence naming the shorthand and the
model-wins precedence.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/test_context.py -v`
Expected: PASS, including `test_dunder_probes_do_not_recurse`.

**Step 5: Commit**

```bash
git add rbx/box/statements/context.py tests/rbx/box/statements/test_context.py
git commit -m "$(cat <<'EOF'
feat(statements): bind group vars onto the group template view

Refs #630

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Drift test for the reserved list

This is the test that keeps a hand-written list honest. It must fail loudly the
day someone adds a key to a namespace builder without reserving its name.

**Files:**
- Test: `tests/rbx/box/statements/test_context.py` (new class at the end)

**Step 1: Write the test**

```python
class TestReservedListCoversTheNamespaceSurface:
    """RESERVED_STATEMENT_VAR_NAMES is hand-written; this proves it still covers
    every name a var could shadow. If this fails, add the new key to the
    frozenset in rbx/box/fields.py (and to the docs table)."""

    def _root_keys(self):
        from rbx.box.fields import RESERVED_STATEMENT_VAR_NAMES  # noqa: F401

        problem_kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(vars={}),
            contest=_contest_ctx(vars={}),
        )
        contest_kwargs = context.contest_jinja_kwargs(
            lang='en',
            languages=_langs(),
            contest=_contest_ctx(vars={}),
            problems=[],
        )
        return set(problem_kwargs) | set(contest_kwargs)

    def _namespace_keys(self):
        problem_ns = _problem_ctx(
            vars={},
            short_name='A',
            import_dir='.problems/A',
            import_file='statement.tex',
            blocks={'legend': 'x'},
        ).namespace()
        contest_ns = _contest_ctx(
            vars={}, location='Somewhere', date='2026', blocks={'foo': 'x'}
        ).namespace()
        return set(problem_ns) | set(contest_ns)

    def test_every_namespace_key_is_reserved(self):
        from rbx.box.fields import RESERVED_STATEMENT_VAR_NAMES
        from rbx.box.schema import TestcaseGroup

        surface = (
            self._root_keys() | self._namespace_keys() | set(TestcaseGroup.model_fields)
        )
        assert surface <= RESERVED_STATEMENT_VAR_NAMES, (
            'unreserved template names: ' f'{sorted(surface - RESERVED_STATEMENT_VAR_NAMES)}'
        )

    def test_no_stale_reservations(self):
        # The other direction, so the list does not accumulate dead names.
        from rbx.box.fields import RESERVED_STATEMENT_VAR_NAMES
        from rbx.box.schema import TestcaseGroup

        surface = (
            self._root_keys() | self._namespace_keys() | set(TestcaseGroup.model_fields)
        )
        assert RESERVED_STATEMENT_VAR_NAMES <= surface, (
            'reserved but no longer exposed: '
            f'{sorted(RESERVED_STATEMENT_VAR_NAMES - surface)}'
        )
```

**Step 2: Run it**

Run: `uv run pytest tests/rbx/box/statements/test_context.py -k ReservedListCovers -v`
Expected: PASS. If `test_no_stale_reservations` fails, the frozenset in Task 1
lists a name the builders no longer emit — remove it rather than loosening the
assertion. `problems` is only emitted by the contest builder and `problem` only
by the problem builder, which is why both kwargs builders are unioned.

**Step 3: Commit**

```bash
git add tests/rbx/box/statements/test_context.py
git commit -m "$(cat <<'EOF'
test(statements): assert reserved var names cover the template surface

Refs #630

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: End-to-end render through a real template

Unit tests prove the context dict; this proves a template actually renders the
shorthand through the real Jinja env.

**Files:**
- Test: `tests/rbx/box/statements/test_render.py` (or `test_engine.py` — pick whichever already renders a problem template with a package fixture; follow its existing fixture style, do not invent a new harness)

**Step 1: Read the neighbours first**

Run: `uv run pytest tests/rbx/box/statements/test_render.py -q` and read the file
to find the smallest existing test that renders a template string with
`problem_jinja_kwargs`. Reuse its fixtures (`pkg_from_testdata`, `testing_pkg`,
`mock_pdflatex` as appropriate — see `tests/rbx/box/conftest.py`).

**Step 2: Write the failing test**

Render a template containing all three forms and assert on the output:

```latex
N=\VAR{N.max} G=\VAR{problem.groups.sub1.AB.max} L=\VAR{vars.N.max}
```

Expected output: the shorthand and the long form produce identical values, and
the group shorthand yields the group-resolved value (`10` for `sub1` in the
existing fixture shape), not the package default.

**Step 3: Run to verify it fails, then passes**

Run: `uv run pytest tests/rbx/box/statements/test_render.py -k shorthand -v`
Expected: FAIL before Tasks 3-5 are in place; PASS after. If the render path
already works because Tasks 3-5 landed, verify the test is real by temporarily
reverting `_lift` to return `namespace` unchanged and watching it fail.

**Step 4: Commit**

```bash
git add tests/rbx/box/statements/test_render.py
git commit -m "$(cat <<'EOF'
test(statements): render var shorthand through a real template

Refs #630

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Docs

**Files:**
- Modify: `docs/setters/statements/templates.md` (the "{{rbx}}-provided variables" section, ~line 33)

**Step 1: Write the docs**

Add a "Shorthand for vars" subsection after the provided-variables list:

- State the rule once: every `vars` block's keys are also available directly in
  the namespace holding it, so `\VAR{N.max}` == `\VAR{vars.N.max}`,
  `\VAR{g.N.max}` == `\VAR{g.vars.N.max}`, `\VAR{contest.N}` ==
  `\VAR{contest.vars.N}`.
- Show one before/after snippet of a constraints block.
- Add the reserved-name table, with the rule that a colliding name is rejected
  when the package loads and the fix is a rename or one level of nesting
  (`limits.score`). Sort the names as in the frozenset.

Note this page still documents some v1-era YAML (`path`/`configure`); do not
rewrite it here — the restructure is tracked separately (#570). Add the new
section in the page's existing voice.

**Step 2: Verify the docs build**

Run: `uv run mkdocs build 2>&1 | tail -20`
Expected: builds. Per `CLAUDE.md` notes, `--strict` fails on ~9 pre-existing
unrelated warnings; use the non-strict build and confirm no *new* warning
mentions `templates.md`.

**Step 3: Commit**

```bash
git add docs/setters/statements/templates.md
git commit -m "$(cat <<'EOF'
docs(statements): document the var shorthand and reserved names

Refs #630

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Full verification

**Step 1: Lint and format**

```bash
uv run ruff check . && uv run ruff format --check .
```
Expected: clean. Fix with `uv run ruff check --fix .` / `uv run ruff format .`.

**Step 2: Full suite**

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto -q
```
Expected: PASS except the pre-existing local failures documented in `CLAUDE.md`
(C++/sandbox/docker). Compare against `git stash`-ed baseline before attributing
any failure to this branch.

**Step 3: Statement e2e**

```bash
uv run pytest tests/rbx/box/statements -q
```
Expected: PASS.

**Step 4: Sanity-check by hand**

Build a statement in a scratch package that uses `\VAR{N.max}` in a block, and
confirm the PDF/TeX carries the value. `mise run test-e2e` covers the DSL
scenarios if a fixture is worth adding there.

**Step 5: Final commit / PR**

Push the branch and open a PR referencing #630. Call out the breaking change in
the PR body: top-level vars named after a statement template name are now
rejected, with rename-or-nest as the migration.
