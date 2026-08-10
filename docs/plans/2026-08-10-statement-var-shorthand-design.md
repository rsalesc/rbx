# Shorter syntax for vars in statements (#630)

## Problem

Before v1, a statement could write `\VAR{N.max}`. v2 namespaced the template
context (#561), so the same value is now `\VAR{vars.N.max}` — repetitive in the
place it is used most, a constraints block that mentions a dozen vars.

The reason v2 namespaced it is real: the root scope holds `problem`, `contest`,
`params` and friends, and any var lifted into that scope can collide with them.
This design brings the shorthand back and makes those collisions loud instead of
silent.

## The rule

The keys of a `vars` block are also bound into the namespace that contains it.
`vars` itself stays, so every existing template keeps working.

| Scope | Today | Shorthand |
|---|---|---|
| problem render root | `\VAR{vars.N.max}` | `\VAR{N.max}` |
| contest render root | `\VAR{vars.N}` | `\VAR{N}` |
| `problem` / `problems[i]` | `\VAR{p.vars.N.max}` | `\VAR{p.N.max}` |
| `contest` | `\VAR{contest.vars.N}` | `\VAR{contest.N}` |
| group | `\VAR{g.vars.N.max}` | `\VAR{g.N.max}` |

Group shorthand resolves against the **group-resolved** var set, the same one
`g.vars` already exposes — package vars with that group's overrides applied — so
a subtasks table reading `\VAR{g.N.max}` renders inherited values for groups
that override nothing.

## Mechanics

Everything lands in `rbx/box/statements/context.py`. No changes in `render.py`,
`engine.py`, or any template.

A `_lift(namespace, vars, key)` helper wraps the var dict as today
(`JinjaDictWrapper.from_dict`) and merges its top-level entries *under* the real
namespace keys, so a real name wins at merge time. That precedence is belt and
braces: the schema check below rejects the collision before a render ever sees
it. It exists so a future namespace key added without updating the reserved list
degrades to "shorthand unavailable for that name" rather than "the template
namespace is shadowed by user data".

Call sites: `problem_jinja_kwargs`, `contest_jinja_kwargs`,
`ProblemRenderContext.namespace()`, `ContestRenderContext.namespace()`.

`GroupView` is the one non-dict scope. Its `__getattr__` tries the underlying
`TestcaseGroup` model first and, on `AttributeError`, falls back to
`self.vars[name]`.

Error messages come along for free. `JinjaDictWrapper.from_dict` already rebuilds
dotted keys into nested wrappers, so lifting the top-level entry `N` yields a
wrapper with `prefix='N'`; `\VAR{N.typo}` still reports `"N.typo" was not found
in "vars"`, and the group fallback still reports
`"N.typo" was not found in "groups.sub1.vars"`. Only a *root-level* unknown
(`\VAR{TYPO}`) degrades to Jinja's plain `'TYPO' is undefined`, which is the same
message any other undefined root name produces today.

## Reserved names

`rbx/box/schema.py`, beside the existing testlib check:

- `RESERVED_STATEMENT_VAR_NAMES` — a hand-written frozenset, the union over
  every scope a var can be lifted into:
  - root: `lang`, `languages`, `keyed_languages`, `params`, `vars`, `contest`,
    `problem`, `problems`
  - `problem.*`: `title`, `limits`, `profiles`, `groups`, `samples`, `blocks`,
    `short_name`, `import_dir`, `import_file`
  - `contest.*`: `title`, `location`, `date`, `blocks`
  - group (`TestcaseGroup` fields): `name`, `score`, `deps`, `testcases`,
    `subgroups`, `generators`, `generatorScript`, `validator`,
    `extraValidators`, `outputValidators`, `testcaseGlob`, `visualizer`,
    `solutionVisualizer`, `model_solution`
- `check_reserved_statement_var_names` — an `AfterValidator`, folded into the
  existing `CheckedRecVars` alias (covering `Package.vars` and
  `TestcaseGroup.vars`) and applied newly to `Contest.vars`.

One union checked in every position, rather than a per-scope list. Package vars
reach all three of root, `problem.*` and every group anyway, so per-scope lists
would only relax the contest case — not worth a second table for users to learn
or for us to keep in sync.

Two differences from the existing testlib check:

- It checks **all** top-level keys, dict or primitive. The testlib check skips
  dicts because a nested var is emitted as `--parent.key=`, which no flag parser
  matches; here a var named `problem` collides with the namespace whether its
  value is a dict or not.
- `Contest.vars` is covered. It keeps skipping the testlib check — contest vars
  never reach a validator.

The escape hatch is unchanged: nest one level (`limits.score`), which moves the
top-level key to `limits`.

This is a breaking change for a package whose vars use one of those names, and it
bites on any command, not only statement builds — same as today's testlib check.
The fix is a rename or one level of nesting, and the error says so.

## Errors, docs, tests

The error mirrors the testlib one: it names the key, says it collides with a
statement template name, suggests rename-or-nest, and lists the reserved set.

Docs get a shorthand section and the reserved-name table on the statements page.

Tests:

- Unit coverage of lifting in all five scopes, and of real-name precedence.
- A **drift test** asserting every key emitted by `problem_jinja_kwargs`,
  `contest_jinja_kwargs`, both `namespace()` builders and
  `TestcaseGroup.model_fields` is in the frozenset. This is what keeps a
  hand-written list honest as the template surface grows.
- Schema tests: reserved name rejected on `Package.vars`, `TestcaseGroup.vars`
  and `Contest.vars`; nested use accepted.
- One e2e rendering `\VAR{N.max}` and `\VAR{g.N.max}`.

## Notes

- No JSON-schema regeneration: no field shapes change, and the constraint is not
  expressible in JSON Schema anyway.
- The bundled preset templates stay on the explicit `vars.` form. The shorthand
  is for user templates; the shipped chrome has no repetition problem to solve.

## Rejected alternatives

- **Lazy fallback, real names win silently.** Resolve `\VAR{N}` only when `N` is
  not a real root name. Never breaks an existing package, but a var named
  `problem` becomes silently unreachable through the shorthand — precisely the
  "thrown under the bus" failure the issue asks us to avoid.
- **Warning now, error later.** Leaves the shorthand genuinely ambiguous for a
  release cycle for no lasting benefit.
- **Deriving the reserved list from the models.** Cannot drift, but a renamed
  field then silently changes which var names are legal, and the error message
  becomes dynamic. The drift test buys the same protection with a stable,
  readable list.
