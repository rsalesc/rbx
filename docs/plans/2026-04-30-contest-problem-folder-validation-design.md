# Contest Problem Folder Validation — Design

## Problem

When `contest.rbx.yml` references a problem whose folder does not exist (or exists but is missing `problem.rbx.yml`), the failure currently surfaces lazily, deep inside `find_problem_package_or_die` calls triggered from `get_problems()` or other downstream code. The error message — `"Problem not found in <path>"` — does not name the offending `ContestProblem` entry, so the user has to map the path back to the YAML by hand.

## Goal

Catch missing problem folders and missing `problem.rbx.yml` files at contest-load time and report them clearly, naming each offending `short_name`.

## Non-goals

- Schema-level (Pydantic) validation. Existing tests in `tests/rbx/box/contest/test_contest_schema.py` construct `Contest` objects with synthetic paths. Touching the filesystem from a model validator would break those tests and conflate data validity with environment state.
- Replacing the lazy `find_problem_package_or_die` failure path. Other entry points (e.g. tooling that bypasses `find_contest_package`) still benefit from it.
- Validating the *contents* of `problem.rbx.yml`. That parses lazily through `find_problem_package`.

## Approach

Add two standalone validation helpers in `rbx/box/contest/contest_package.py`, each with a single responsibility, and call both from `find_contest_package` after `model_from_yaml` succeeds.

### `validate_problem_folders_exist(contest, contest_root)`

For each `problem` in `contest.problems`:
- Resolve `problem.get_path()` against `contest_root` if relative; honor it as-is if absolute.
- Collect entries whose resolved path does not exist or is not a directory.

If the collected list is non-empty, print a single multi-line error (one line per problem, naming `short_name` and the missing path) then `raise typer.Exit(1)`.

### `validate_problem_folders_are_packages(contest, contest_root)`

Assumes folder existence has already been checked. For each `problem`:
- Compute `<resolved-folder>/problem.rbx.yml`.
- Collect entries whose folder lacks the YAML.

Same all-at-once error reporting and `typer.Exit(1)` behavior.

### Wiring

In `find_contest_package`, after `utils.model_from_yaml(...)` returns:
1. `validate_problem_folders_exist(contest, contest_yaml_path.parent)`
2. `validate_problem_folders_are_packages(contest, contest_yaml_path.parent)`

Order matters: if a folder doesn't exist, we don't also want to nag about its missing `problem.rbx.yml` — that's redundant noise.

`find_contest_package` is `@functools.cache`'d. `typer.Exit` is an exception, so the cache will not store on failure — the next call re-runs validation. Good.

## Error message shape

Existence check (example):

```
[error]Some contest problems point to folders that do not exist:[/error]
[error]  - A: ./A (resolved: /abs/path/to/contest/A)[/error]
[error]  - C: probs/C (resolved: /abs/path/to/contest/probs/C)[/error]
```

Package-file check:

```
[error]Some contest problem folders are missing problem.rbx.yml:[/error]
[error]  - B: ./B[/error]
```

(Style follows the existing `[error]...[/error]` Rich markup used throughout `contest_package.py`.)

## Tests

New file `tests/rbx/box/contest/test_contest_package.py`:

**Existence checks (unit, on the helper):**
- All folders exist → no error.
- One folder missing → `SystemExit`; printed output names the offending `short_name`.
- Multiple folders missing → all listed in one error.
- `path:` field set to a relative path that exists → ok; resolves under `contest_root`, not cwd.
- `path:` field set to an absolute path that exists → ok.
- `path:` resolves to a regular file → reported as missing.

**Package-file checks (unit, on the helper):**
- Folder exists with `problem.rbx.yml` → ok.
- Folder exists without `problem.rbx.yml` → reported.
- Multiple folders without YAML → all listed.

**Integration through `find_contest_package`:**
- A `tmp_path` contest dir with a valid `contest.rbx.yml` and well-formed problem folders → returns parsed `Contest`.
- Same setup, one problem folder removed → exits.
- Same setup, one problem folder kept but its `problem.rbx.yml` removed → exits.

## Out of scope (deliberately)

- No `issue_stack` integration. The existing parsing-error path already uses `typer.Exit(1)` directly in this file; matching that keeps the validation cohesive.
- No new CLI command. This is implicit on every contest load.
