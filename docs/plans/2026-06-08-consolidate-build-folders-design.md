# Consolidate rbx build folders between contests and problems

Tracking issue: [#353](https://github.com/rsalesc/rbx/issues/353)

## Problem

Problems and contests resolve their build directories inconsistently:

- **Problems** resolve the build root via the configurable `buildDir` setting
  (`environment.get_build_dir()`, default `build`) in `package.get_build_path`,
  and place intermediate statement artifacts under `build/statements/<name>`
  (`package.get_statements_build_path`).
- **Contests** *hardcode* `pathlib.Path('build')` in
  `build_contest_statements.py` (two sites) and place intermediate statement
  artifacts under `build/statement_build/<name>`
  (`get_statement_build_dir`).

This means a contest ignores a custom `buildDir` (e.g. `buildDir: out` redirects
problem artifacts but not contest artifacts), and the intermediate statement
folder is named differently (`statements/` vs `statement_build/`). Final outputs
(`build/<name>.<suffix>`) already match.

The issue text describes an older state (`build.rbx/` for problems). Since then
the problem build dir became the configurable `buildDir` (default `build`), so
both nominally use `build/` today; the two inconsistencies above are what remain.

## Goal

Make the contest build layout match the problem layout:

1. Honor the configurable `buildDir` instead of hardcoding `build`.
2. Rename the contest's intermediate statement folder `statement_build/` →
   `statements/`.

## Design

### Change 1 — `rbx/box/contest/contest_package.py`

Add two cached path helpers mirroring the problem-side helpers in `package.py`:

```python
@functools.cache
def get_contest_build_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    return find_contest(root) / environment.get_build_dir()


@functools.cache
def get_contest_statements_build_path(
    root: pathlib.Path = pathlib.Path(),
) -> pathlib.Path:
    return get_contest_build_path(root) / 'statements'
```

- New import: `from rbx.box import environment` (no import cycle — `environment`
  does not import contest code).
- Returns absolute paths via `find_contest()`, more robust than today's relative
  `Path('build')`.
- Auto-covered by `testing_utils.clear_all_functools_cache` (it already iterates
  `contest_package` for any function exposing `cache_clear`), satisfying the
  test-isolation rule for new `@functools.cache` helpers.

### Change 2 — `rbx/box/contest/build_contest_statements.py`

Rewire the two hardcoded sites to the new helpers:

- `get_statement_build_dir` (intermediate dir):
  `Path('build') / 'statement_build' / name`
  → `contest_package.get_contest_statements_build_path() / statement.name`
- Final output path:
  `Path('build') / name`
  → `contest_package.get_contest_build_path() / statement.name`

Net effect: contests write intermediates to `<buildDir>/statements/<name>` and
final output to `<buildDir>/<name>.<suffix>` — identical convention to problems,
and `buildDir` is now respected.

Both call sites run under the `@within_contest` decorator (cwd = contest root),
so `find_contest()` resolves.

### No migration

`build/` is gitignored and fully regenerable, so no on-disk migration is needed —
only the convention changes going forward.

## Testing

- New unit test (contest package tests): `get_contest_statements_build_path()`
  resolves to `<contest_root>/build/statements`, and overriding `buildDir`
  (e.g. `out`, via mocking `environment.get_build_dir`) redirects it.
- Existing contest statement build tests stay green — the default-case final
  output path `build/<name>.<suffix>` is unchanged.
- `uv run pytest tests/rbx/box/contest tests/rbx/box/statements`.
- `uv run ruff check` / `ruff format` on changed files.

## Risk

Low. Two call sites, both inside `@within_contest`; the build folder is
disposable. The `@functools.cache` keyed by `root` is safe because all contest
variants share the same contest directory (sibling `contest.<id>.rbx.yml` files).
