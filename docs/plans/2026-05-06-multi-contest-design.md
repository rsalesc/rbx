# Multi-contest packages

**Issue:** [#431](https://github.com/rsalesc/rbx/issues/431) — Allow for multiple contests in a single contest directory.

## Problem

A single physical directory often hosts several logical contests: divisions of an
informatics olympiad, ICPC variants with overlapping problems, warmup vs. main
contests sharing a tree. Today, each contest needs its own folder, which forces
duplication of statement templates, common configuration, and sometimes problem
packages themselves.

We want one directory to back many `contest.rbx.yml` configurations sharing the
underlying filesystem (statement templates, assets, problem packages).

## Scope

In:

- Multiple contest definitions co-located in one directory.
- A way to select one of them (`-C`/`--contest`/env var) for any contest-scoped
  command.
- Sentinel mode where no contest is the default; consumers that need contest
  context error out clearly.
- Auto-selection when a problem belongs to exactly one variant.

Out (deferred):

- YAML inheritance / `extends:` between variants. Variants share files on disk;
  YAML duplication is accepted for now (re-evaluate when it becomes painful).
- `rbx contest add_variant` scaffolding command. Tracked as a follow-up issue.

## File layout

`contest.rbx.yml` is **always required** to mark a directory as a contest dir.
It has two modes:

1. **Real-contest mode** (today's behavior). The file is a normal `Contest`.
   It is the default contest. Sibling `contest.<id>.rbx.yml` files MAY also
   exist; they are additional selectable variants. The canonical is the
   default selection (used when no `-C`/`RBX_CONTEST` is set).
2. **Dispatcher mode**. The file is a sentinel:
   ```yaml
   use_variants: true
   ```
   No other fields are validated. There is no default contest. All variants
   live in sibling files matching `contest.<id>.rbx.yml`. `use_variants` is
   purely a permission flag that allows the canonical to be empty.

Variant id rules: `^[A-Za-z][A-Za-z0-9_-]*$`. Variant discovery is purely
filesystem-driven (`glob('contest.*.rbx.yml')`); the dispatcher does not list
variants.

## Schema changes

`rbx/box/contest/schema.py`:

- Add an optional `use_variants: bool = False` field on `Contest`. When
  `use_variants` is `true`, validation of the rest of the model is relaxed
  (probably via a `model_validator(mode='before')` that fills in safe defaults
  for `name`, `problems`, `statements`).
- Helper `Contest.is_dispatcher` property.

A separate `ContestDispatcher` model was considered and rejected to keep
discovery code from branching on which model loaded.

## Selection mechanism

### Flag

- Long: `--contest <id>`.
- Short: `-C` (capital). `-c` stays `--cache`.
- Env var fallback: `RBX_CONTEST=<id>`.

The flag is registered on **two** Typer callbacks:

- Root `rbx/box/cli.py:main` — for problem-level commands that implicitly
  consult contest context (`rbx package build`, `rbx statements build`, BOCA
  tooling).
- Contest sub-app `rbx/box/contest/main.py` — for `rbx contest *` commands.

### Resolver

A new `rbx/box/contest/contest_state.py` exposes a `ContextVar[Optional[str]]`
holding the explicit selection. Set by each callback in the order:

1. CLI flag value, if provided.
2. `os.environ['RBX_CONTEST']`, if set.
3. `None` (no explicit selection).

### `find_contest_yaml(root, contest_id=None)`

Updated signature. Algorithm:

1. Walk up from `root` until a directory containing `contest.rbx.yml` is found,
   or root reaches `/`. (Same as today.) Save this as `contest_root`.
2. Load `contest.rbx.yml`. Determine mode:
   - Real contest → mode = `single`.
   - `use_variants: true` → mode = `dispatcher`.
3. Resolve effective `contest_id`: parameter > contextvar > `None`.
4. Discover variants. Real-contest mode yields `{None: canonical, **siblings}`;
   dispatcher mode yields `{**siblings}` only.
5. Decide:
   - No `contest_id` → return `variants.get(None)`. That is the canonical
     in real-contest mode (default selection), or `None` in dispatcher mode.
   - `contest_id` set and present in `variants` → return that path. (Real
     contests with siblings can resolve `-C <sibling>` to the sibling path.)
   - `contest_id` set but unknown → error with picker (`Available: [...]`).

`find_contest_package(root)` then loads the path returned, or returns `None`
when the resolver returned `None`. Both functions remain `@functools.cache`d,
keyed on `(root, contest_id)`. Both stay registered in
`rbx.testing_utils.clear_all_functools_cache` per the test isolation rule.

### `find_contest_package_or_die`

Errors with a picker message when called in dispatcher mode without a
selection:

```
Multiple contests are defined in this directory. Pass -C <id> or set
RBX_CONTEST=<id>. Available contests: div1, div2.
```

## Implicit consumers and their behavior

The following sites resolve "the contest" implicitly today; each gets a
defined behavior under dispatcher mode.

| Consumer | Dispatcher, no selection |
|---|---|
| `naming.get_problem_entry_in_contest` | Walk **all** variants. If problem appears in exactly one, return that entry. If in zero, return `None` (today's standalone path). If in ≥2, return `None`; consumers requiring `short_name` then fail. |
| `naming.get_problem_shortname` / `get_problem_index` | Defer to above. Return `None` when ambiguous. |
| `naming.get_contest_title` | Same: pick the single containing variant; otherwise `None`. |
| `statement_overriding.get_inheritance_overrides` | Hard error in ambiguous mode: "Statement `<name>` extends contest, but multiple contests are defined. Pass `-C <id>`." |
| `statement_overriding.get_statement_builder_contest_for_problem` | Returns `None` when ambiguous (problem statement builds without contest context). |
| `packaging/*/packager.py` | Each call site that uses `get_problem_shortname` switches to a new helper `naming.require_problem_in_contest()` that errors with the picker message when ambiguous. Packaging *requires* a letter; refusing is correct. |
| `packaging/contest_main.py` | Errors via `find_contest_package_or_die` (already resolves through the chain). |
| `tooling/boca/*` | Same as packaging — uses `require_problem_in_contest`. |
| `cli.py:751` (`rbx ui` from problem) | Show variant picker before launching contest UI when ambiguous. |
| `stats.py` | Iterates all reachable contests; in dispatcher mode iterates all variants. |

`within_contest` decorator: resolves the selection and `cd`s into the contest
directory (still shared across variants). The decorator records the resolved
id on the contextvar for downstream calls.

## CLI surface

Existing `rbx contest` commands keep working:

- `rbx contest each|on|summary|edit|add|remove|package|statements`: all use
  `within_contest`, so they pick up `-C` automatically. In dispatcher mode
  without `-C`, they error.
- `rbx contest add` writes to the selected variant file. `rbx contest remove`
  same.

New:

- `rbx contest list` — prints every variant id (or "default" for single mode),
  marks the active selection.

Deferred (separate follow-up issue):

- `rbx contest add_variant <id>` — scaffolds `contest.<id>.rbx.yml` from a
  template.

## Testing

- Unit tests for `find_contest_yaml` covering: single mode, dispatcher mode +
  `-C`, dispatcher mode + env var, dispatcher mode + no selection (returns
  `None`), invalid id (`-C bogus`).
- Unit tests for `naming.get_problem_entry_in_contest` covering: problem in
  zero/one/many variants under dispatcher mode.
- E2E (`tests/e2e/`) fixture: a directory with `contest.rbx.yml` (sentinel) +
  `contest.div1.rbx.yml` + `contest.div2.rbx.yml`, sharing a problem and a
  statement template. Cases:
  - `rbx contest each rbx run` errors without `-C`.
  - `rbx -C div1 contest each rbx run` succeeds.
  - `rbx -C div1 package build` produces a div1-letter-named package.
  - `rbx -C div2 package build` produces a div2-letter-named package for the
    same problem (different letter).
  - Building a problem statement that `extends:` contest works under each
    variant; errors without `-C` when problem is in both variants.

## Migration

None. All existing single-contest packages keep working without changes —
their `contest.rbx.yml` continues to be a real contest, no `use_variants` flag,
no variant siblings. The dispatcher pattern is purely opt-in.

## Follow-ups

- YAML inheritance between variants (`extends:`) — defer until duplication is
  reported as painful.
- `rbx contest add_variant <id>` — scaffolds variant yaml from a template.
- Consider whether a problem appearing in multiple variants should produce
  multiple packages on a single `rbx package build` invocation (one per
  membership). Currently we error and require `-C`.
