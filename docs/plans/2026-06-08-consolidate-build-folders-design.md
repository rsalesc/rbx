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

### Change 3 — other contest sites that hardcoded `build`

A thorough sweep found three more contest sites that hardcoded `build` and so
ignored a custom `buildDir`. All are routed through the configurable build dir:

- `rbx/box/packaging/contest_main.py` — the contest package **output dir** (where
  the final contest `.zip` is written) was `pathlib.Path('build')`; now
  `contest_package.get_contest_build_path()`.
- `rbx/box/stats.py` — `_get_build_path` returned `root / 'build'` for contests
  (the `rbx stats` build-size report); now `root / environment.get_build_dir()`.
  Resolved against the package root directly (not via `find_contest`) to avoid
  contest-variant lookups in a read-only reporting path.
- `rbx/box/cli.py` — `rbx clear` cleaned a hardcoded `build`; the contest branch
  now also cleans `get_contest_build_path()` so a custom `buildDir` is removed.

### Change 4 — preset-tree cleanup honors the preset's own buildDir

When a preset (or a problem/contest created from one) is copied, build artifacts
are stripped so they don't leak into the generated tree. This used the hardcoded
`build`. It must instead use the **preset's own** `env.rbx.yml` `buildDir` (not the
user's active environment), so a preset with a custom `buildDir` is cleaned
correctly. `rbx/box/presets/__init__.py`:

- New `get_preset_build_dir(env_path)` reads just the `buildDir` field from the
  preset's `env.rbx.yml` via raw YAML (robust to stub/partial envs — the preset
  env is not always a fully-valid `Environment`), falling back to `build`.
- `clean_copied_contest_dir` / `clean_copied_problem_dir` gain a `build_dir`
  parameter (default `build`, so existing callers/tests are unaffected).
- `install_preset_from_dir` resolves the build dir from `dest / preset.env`;
  `install_contest` / `install_problem` resolve it from
  `get_preset_environment_path(dest_pkg)`.

**Deliberately left as-is**:

- `rbx/box/testing/testing_package.py` — a test-only helper that builds expected
  paths under the default `build`; tests run with the default environment.

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
