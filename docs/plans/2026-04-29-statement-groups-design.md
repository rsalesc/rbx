# Statement Groups Accessor

Resolves [issue #406](https://github.com/rsalesc/rbx/issues/406): expose testgroups (with their names and scores) to statement templates in a way that supports both name-based lookup and ordered iteration.

## Problem

Statement authors want to reference each testgroup by name in the statement (to display per-subtask scores, headings, and any other group-level metadata). Today, `package.testcases` is exposed to templates, but it is a positional list — name-based access requires a manual loop, which is awkward in LaTeX/Jinja templates.

The issue text:

> Ideally, there should be a way of accessing every testgroup in the statement, especially to fetch its name (and from its name fetch its defined vars) and also to fetch its score (to be shown in the statement).

Per-group `vars` are explicitly out of scope (no schema changes); only existing `TestcaseGroup` fields are exposed.

## Design

### Template API

A new `groups` accessor is injected into the per-problem Jinja kwargs alongside `package`, `vars`, `samples`, etc.

```latex
\VAR{problem.groups.subtask1.score}        % attribute lookup by group name
\VAR{problem.groups['subtask1'].name}      % item lookup by group name

%- for g in problem.groups
  \subsection*{\VAR{g.name} — \VAR{g.score} pts}
%- endfor
```

Iteration yields `TestcaseGroup` objects (not keys), in declaration order from `package.testcases`. Missing keys (`problem.groups.bogus`) return a `StrictChainableUndefined` with a clear hint, matching the existing `JinjaDictGetter` behaviour and failing the render with a useful message.

### Implementation

#### `JinjaGroupsGetter` (`rbx/box/statements/latex_jinja.py`)

A small subclass of `JinjaDictGetter` whose only override is `__iter__`, which yields `self.values()` instead of `self.keys()`. Insertion order is preserved by stock `dict`, so iteration order matches the order of construction. `len()`, `in` (by name), `.values()`, `.keys()`, `.items()` keep dict semantics.

#### Wiring (`rbx/box/statements/builders.py`)

`StatementBuilderProblem.build_inner_jinja_kwargs()` adds:

```python
'groups': JinjaGroupsGetter(
    'groups',
    {g.name: g for g in self.package.testcases},
),
```

No new schema fields, no other changes to the build pipeline.

### Scope decisions

- **`samples` is included** in `groups`. It is a real `TestcaseGroup`; statement authors filter it themselves with `g.name != 'samples'` if they don't want it.
- **No schema changes.** Per-group `vars` are out of scope (separate follow-up if needed).
- **Subgroups are not flattened.** `g.subgroups` is already on the model; users who want them have access via the existing field.

### Error handling

- Missing key → `StrictChainableUndefined` with hint `"<name>" was not found in "groups"` (existing pattern).
- Top-level group names and per-parent subgroup names must be unique. Enforced by `is_unique_testcase_group_names` and `is_unique_testcase_subgroup_names` `AfterValidator`s on `Package.testcases` and `TestcaseGroup.subgroups`, so the name-keyed dict cannot silently collapse duplicates.

### Testing

- **Unit test** (new file under `tests/rbx/box/statements/`) for `JinjaGroupsGetter`:
  - iteration yields values in insertion order;
  - attribute / item lookup work;
  - `len`, `in`, `.keys()`, `.values()`, `.items()` behave as expected;
  - missing keys return `StrictChainableUndefined`.
- **Integration test** in the existing statement-builder test layout: a problem package with two scoring groups + a small `.rbx.tex` template that references `\VAR{problem.groups.subtask1.score}` and a `for` loop, asserting the rendered output.

## Out of scope

- Per-group `vars` (no schema changes).
- Exposing groups in contest-level templates (problem-level only — same scope as the issue).
- Flattening subgroups into `groups`.
