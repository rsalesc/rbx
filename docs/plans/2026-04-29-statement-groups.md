# Statement Groups Accessor — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose `package.testcases` to statement templates as a `groups` accessor that supports name-based lookup *and* in-order iteration over `TestcaseGroup` objects, resolving issue #406.

**Architecture:** A new `JinjaGroupsGetter` (subclass of the existing `JinjaDictGetter`) overrides `__iter__` to yield values instead of keys, while preserving stock `dict` semantics elsewhere. `StatementBuilderProblem.build_inner_jinja_kwargs()` injects an instance keyed by group name, in declaration order. No schema changes.

**Tech Stack:** Python 3.12+, Pydantic v2, Jinja2 (LaTeX-flavoured), pytest, ruff, commitizen.

**Reference docs:**
- Design: `docs/plans/2026-04-29-statement-groups-design.md`
- Statements module guide: `rbx/box/statements/CLAUDE.md`
- Box module guide: `rbx/box/CLAUDE.md`
- Commit format: `.claude/skills/commit.md` (`docs(statements): …`, `feat(statements): …`, `test(statements): …` — pre-commit `commitizen check` will reject non-compliant messages)

**Test invocation note:** This repo uses `uv`. All `pytest` commands below run as `uv run pytest …`. The default test runs exclude `tests/rbx/box/cli`; the tests we add are under `tests/rbx/box/statements/` and are fast unit tests.

**Files at a glance:**
- Modify: `rbx/box/statements/latex_jinja.py` — add `JinjaGroupsGetter` after `JinjaDictGetter` (around line 225).
- Modify: `rbx/box/statements/builders.py` — import `JinjaGroupsGetter`; inject `groups` in `StatementBuilderProblem.build_inner_jinja_kwargs()` (line 117).
- Modify: `tests/rbx/box/statements/test_builders.py` — extend `TestStatementBuilderProblem` and add an integration test in `TestrbxTeXBuilder`.
- Create: `tests/rbx/box/statements/test_latex_jinja.py` — unit tests for `JinjaGroupsGetter` (file does not exist today).

---

## Task 1: Unit tests for `JinjaGroupsGetter`

**Files:**
- Create: `tests/rbx/box/statements/test_latex_jinja.py`

**Step 1: Write the failing tests**

Create `tests/rbx/box/statements/test_latex_jinja.py`:

```python
from rbx.box.statements.latex_jinja import JinjaGroupsGetter, StrictChainableUndefined


def _make(items):
    """Helper: build a JinjaGroupsGetter with insertion-ordered keys."""
    return JinjaGroupsGetter('groups', dict(items))


class TestJinjaGroupsGetter:
    def test_iter_yields_values_in_insertion_order(self):
        groups = _make([('samples', 'S'), ('subtask1', '1'), ('subtask2', '2')])

        assert list(groups) == ['S', '1', '2']

    def test_getitem_returns_value_by_name(self):
        groups = _make([('subtask1', 'A'), ('subtask2', 'B')])

        assert groups['subtask1'] == 'A'
        assert groups['subtask2'] == 'B'

    def test_missing_key_returns_undefined_with_hint(self):
        groups = _make([('subtask1', 'A')])

        result = groups['bogus']

        assert isinstance(result, StrictChainableUndefined)

    def test_contains_checks_keys(self):
        groups = _make([('subtask1', 'A')])

        assert 'subtask1' in groups
        assert 'bogus' not in groups

    def test_len_counts_entries(self):
        groups = _make([('a', 1), ('b', 2), ('c', 3)])

        assert len(groups) == 3

    def test_keys_values_items_preserve_order(self):
        groups = _make([('a', 1), ('b', 2), ('c', 3)])

        assert list(groups.keys()) == ['a', 'b', 'c']
        assert list(groups.values()) == [1, 2, 3]
        assert list(groups.items()) == [('a', 1), ('b', 2), ('c', 3)]
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/rbx/box/statements/test_latex_jinja.py -v
```

Expected: FAIL with `ImportError: cannot import name 'JinjaGroupsGetter' from 'rbx.box.statements.latex_jinja'`.

**Step 3: Commit failing tests**

```bash
git add tests/rbx/box/statements/test_latex_jinja.py
git commit -m "test(statements): add failing tests for JinjaGroupsGetter"
```

---

## Task 2: Implement `JinjaGroupsGetter`

**Files:**
- Modify: `rbx/box/statements/latex_jinja.py`

**Step 1: Add the class**

Insert immediately after the existing `JinjaDictGetter` class (currently ending at line 224):

```python
class JinjaGroupsGetter(JinjaDictGetter):
    """A name-keyed accessor whose iteration yields values in insertion order.

    Used to expose testgroups to statement templates so that ``for g in groups``
    naturally iterates over group objects, while ``groups['subtask1']`` and
    ``groups.subtask1`` still resolve by name.
    """

    def __iter__(self):
        return iter(self.values())
```

(One short docstring is fine; do not add inline comments.)

**Step 2: Run tests to verify they pass**

```bash
uv run pytest tests/rbx/box/statements/test_latex_jinja.py -v
```

Expected: all 6 tests PASS.

**Step 3: Lint and format**

```bash
uv run ruff check rbx/box/statements/latex_jinja.py tests/rbx/box/statements/test_latex_jinja.py
uv run ruff format rbx/box/statements/latex_jinja.py tests/rbx/box/statements/test_latex_jinja.py
```

Expected: no errors.

**Step 4: Commit**

```bash
git add rbx/box/statements/latex_jinja.py
git commit -m "feat(statements): add JinjaGroupsGetter for name-keyed group access"
```

---

## Task 3: Wire `groups` into `StatementBuilderProblem`

**Files:**
- Modify: `rbx/box/statements/builders.py`
- Modify: `tests/rbx/box/statements/test_builders.py`

**Step 1: Write the failing test**

Append a new test method to the existing `TestStatementBuilderProblem` class in `tests/rbx/box/statements/test_builders.py` (the class starts at line 85). Use the existing `sample_package`, `sample_statement`, and `sample_limits` fixtures and add a fresh package with multiple groups inline so we don't have to touch shared fixtures:

```python
    def test_build_inner_jinja_kwargs_exposes_groups(
        self, sample_statement, sample_limits
    ):
        from rbx.box.schema import TestcaseGroup
        from rbx.box.statements.latex_jinja import (
            JinjaGroupsGetter,
            StrictChainableUndefined,
        )

        package = Package(
            name='test-problem',
            timeLimit=1000,
            memoryLimit=256,
            testcases=[
                TestcaseGroup(name='samples'),
                TestcaseGroup(name='subtask1', score=30),
                TestcaseGroup(name='subtask2', score=70),
            ],
        )
        problem = StatementBuilderProblem(
            package=package, statement=sample_statement, limits=sample_limits
        )

        kwargs = problem.build_inner_jinja_kwargs()

        groups = kwargs['groups']
        assert isinstance(groups, JinjaGroupsGetter)
        assert [g.name for g in groups] == ['samples', 'subtask1', 'subtask2']
        assert groups['subtask1'].score == 30
        assert groups['subtask2'].score == 70
        assert isinstance(groups['bogus'], StrictChainableUndefined)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/rbx/box/statements/test_builders.py::TestStatementBuilderProblem::test_build_inner_jinja_kwargs_exposes_groups -v
```

Expected: FAIL with `KeyError: 'groups'` (kwargs dict has no `groups` entry yet).

**Step 3: Wire the kwarg**

In `rbx/box/statements/builders.py`:

1. Add `JinjaGroupsGetter` to the import block at lines 19–25:

```python
from rbx.box.statements.latex_jinja import (
    JinjaDictGetter,
    JinjaDictWrapper,
    JinjaGroupsGetter,
    render_latex_template,
    render_latex_template_blocks,
    render_markdown_template_blocks,
)
```

2. Inside `StatementBuilderProblem.build_inner_jinja_kwargs()` (starts at line 117), add a `'groups'` entry to the `kwargs.update({...})` call alongside `'profiles'` (line 133). Final addition:

```python
                'profiles': JinjaDictGetter('profiles', **self.profiles),
                'groups': JinjaGroupsGetter(
                    'groups',
                    {g.name: g for g in self.package.testcases},
                ),
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/rbx/box/statements/test_builders.py::TestStatementBuilderProblem -v
```

Expected: the new test PASSES, and all previously-existing `TestStatementBuilderProblem` tests still PASS.

**Step 5: Lint and format**

```bash
uv run ruff check rbx/box/statements/builders.py tests/rbx/box/statements/test_builders.py
uv run ruff format rbx/box/statements/builders.py tests/rbx/box/statements/test_builders.py
```

Expected: no errors.

**Step 6: Commit**

```bash
git add rbx/box/statements/builders.py tests/rbx/box/statements/test_builders.py
git commit -m "feat(statements): expose groups accessor in problem jinja kwargs"
```

---

## Task 4: End-to-end rbxTeX integration test

This proves the full Jinja render path picks up the new accessor — name lookup + ordered iteration — in a real rbxToTeX build.

**Files:**
- Modify: `tests/rbx/box/statements/test_builders.py`

**Step 1: Write the failing test**

Append to the `TestrbxTeXBuilder` class (starts at line 602). It reuses the `builder` fixture (line 605), constructs its own template + problem item with multi-group testcases, and asserts the rendered output:

```python
    def test_build_renders_groups_accessor(self, builder, tmp_path):
        from rbx.box.schema import TestcaseGroup

        template_file = tmp_path / 'template.tex'
        template_file.write_text(
            r'\documentclass{article}\begin{document}'
            r'\VAR{groups.subtask1.score}|\VAR{groups.subtask2.score}|'
            r'%- for g in groups\n\VAR{g.name}=\VAR{g.score};\n%- endfor\n'
            r'\end{document}'.replace('\\n', '\n')
        )
        params = rbxToTeX(
            type=ConversionType.rbxToTex, template=pathlib.Path('template.tex')
        )
        context = StatementBuilderContext(
            lang='en', languages=[], params=params, root=tmp_path
        )
        package = Package(
            name='test-problem',
            timeLimit=1000,
            memoryLimit=256,
            testcases=[
                TestcaseGroup(name='samples'),
                TestcaseGroup(name='subtask1', score=30),
                TestcaseGroup(name='subtask2', score=70),
            ],
        )
        statement = Statement(
            name='statement',
            path=pathlib.Path('statement.rbx.tex'),
            type=StatementType.rbxTeX,
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)
        problem_item = StatementBuilderProblem(
            package=package, statement=statement, limits=limits
        )

        result = builder.build(b'%- block legend\nignored\n%- endblock\n', context, problem_item)

        text = result.decode()
        assert '30|70|' in text
        assert 'samples=0;' in text
        assert 'subtask1=30;' in text
        assert 'subtask2=70;' in text
        assert text.index('samples=') < text.index('subtask1=') < text.index('subtask2=')
```

Note: `scoring` defaults to `BINARY`, where non-zero `score` is rejected. We construct groups with explicit `score` *only* for non-`samples` groups, but the schema also rejects non-zero scores under `BINARY`. To satisfy that, set `scoring=ScoreType.POINTS` on the package — update the `package = Package(...)` block to:

```python
        from rbx.box.schema import ScoreType
        package = Package(
            name='test-problem',
            timeLimit=1000,
            memoryLimit=256,
            scoring=ScoreType.POINTS,
            testcases=[
                TestcaseGroup(name='samples'),
                TestcaseGroup(name='subtask1', score=30),
                TestcaseGroup(name='subtask2', score=70),
            ],
        )
```

Apply that revision before running.

**Step 2: Run test to verify it fails before the implementation existed**

(Implementation already exists from Task 3, so this will pass on the first run. Run anyway to confirm wiring end-to-end.)

```bash
uv run pytest tests/rbx/box/statements/test_builders.py::TestrbxTeXBuilder::test_build_renders_groups_accessor -v
```

Expected: PASS.

**Step 3: Run the full statements test module to confirm no regressions**

```bash
uv run pytest tests/rbx/box/statements -v
```

Expected: all tests pass.

**Step 4: Lint and format**

```bash
uv run ruff check rbx/box/statements tests/rbx/box/statements
uv run ruff format rbx/box/statements tests/rbx/box/statements
```

Expected: no errors.

**Step 5: Commit**

```bash
git add tests/rbx/box/statements/test_builders.py
git commit -m "test(statements): cover groups accessor in rbxTeX render"
```

---

## Task 5: Final verification + close out the issue

**Step 1: Run the full default test suite**

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto
```

Expected: all tests pass, no new failures introduced.

**Step 2: Run repo-wide lint**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: clean.

**Step 3: Confirm `git log` shows the expected commit chain**

```bash
git log --oneline origin/main..HEAD
```

Expected: 4 commits, in this order (older → newer):

```
test(statements): add failing tests for JinjaGroupsGetter
feat(statements): add JinjaGroupsGetter for name-keyed group access
feat(statements): expose groups accessor in problem jinja kwargs
test(statements): cover groups accessor in rbxTeX render
```

**Step 4: Update issue / open PR**

This step is left to the human operator at the end of the worktree session — see the finishing-a-development-branch skill flow.

---

## Out of scope (do not implement here)

- Per-group `vars` field on `TestcaseGroup` / `TestcaseSubgroup`.
- Exposing `groups` to contest-level templates.
- Flattening subgroups into `groups`.

These would each warrant a separate design + plan if requested.
