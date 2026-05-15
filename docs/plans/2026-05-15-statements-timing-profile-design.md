# Timing profile flag for statement builds

GitHub issue: [#456](https://github.com/rsalesc/rbx/issues/456)

## Goal

Let users build statements against a specific timing profile, so that the time
limits shown in the rendered statement reflect the profile rather than the
package defaults. Cover both the problem-level command (`rbx st b`) and the
contest-level command (`rbx contest st b`).

## Motivation

A problem package may declare multiple timing profiles in `.limits/<name>.yml`
(e.g. `local`, `judge`, `icpc`). The statement builder already exposes
`problem.limits.timelimit_for_language(language)` to rbxTeX templates, and that
expression already respects the active profile contextvar set by the global
`rbx -p <profile>` flag. Two gaps make the current behaviour unsafe for
publishing statements:

- **Silent fallback.** If `-p <profile>` names a profile that does not exist
  for a given problem, `get_limits_profile(..., fallback_to_package_profile=True)`
  silently returns the package defaults. The rendered PDF looks plausible but
  ships the wrong time limits.
- **No way to opt out per-problem in a contest build.** A contest typically has
  problems with heterogeneous profiles (e.g. only a subset has an `icpc`
  profile). Today the build either silently uses package defaults for the
  missing ones, or the user has to build per-problem.

## Design

### CLI surface

Add `--profile, -p TEXT` to both commands:

- `rbx/box/statements/build_statements.py:476` — problem-level `build()`.
- `rbx/box/contest/statements.py:30` — contest-level `build()`.

The subcommand-level flag is a convenience alias for the existing global
`rbx -p <profile>` flag; it sets the same `profile_var` contextvar via
`limits_info.use_profile(...)`. When both are supplied, the subcommand value
wins (last set).

### Problem-level semantics (`rbx st b -p <profile>`)

Strict. If `.limits/<profile>.yml` does not exist in the current problem
package, exit with status 1 and the same error message
`get_limits_profile(profile, fallback_to_package_profile=False)` already prints
today (`limits_info.py:140-143`). The validation is performed once at the start
of `build()`, before any work; the rest of the pipeline runs unchanged inside
`use_profile(profile)`.

### Contest-level semantics (`rbx contest st b -p <profile>`)

Skip-with-warn. For each problem in the contest:

1. Probe `limits_info.get_saved_limits_profile(profile, root=problem_path)`.
2. If `None`, print a warning and exclude the problem from this contest
   statement build. Use the existing `StatementBuildIssue` channel so the
   skip surfaces consistently with other per-problem failures.
3. Otherwise include the problem; the inner `build_statement_bytes` call is
   wrapped in `use_profile(profile)`.

If **zero** problems remain after skipping, exit with status 1 — a contest PDF
with no problems is almost certainly a mistake and we should not produce one
silently.

The same eligible-problem subset is computed once and used for both the
sample-collection loop (`contest/statements.py:93-112`) and the per-problem
build loop (`contest/build_contest_statements.py:191-229`), so the final
statement does not reference samples for problems that were excluded.

### Data flow

```
CLI flag (-p) → limits_info.use_profile(profile) ctxmgr
              → profile_var contextvar
              → build_statement_bytes() reads via get_active_profile()
              → StatementBuilderProblem.limits = get_limits_profile(active)
              → exposed to Jinja as problem.limits.timelimit_for_language(...)
```

No changes to `StatementBuilderProblem`, the Jinja/rbxTeX layer, or any
template.

### Error handling matrix

| Scenario                                                  | Behaviour                          |
|-----------------------------------------------------------|------------------------------------|
| `rbx st b -p missing`                                     | exit 1, error message              |
| `rbx st b -p ok`                                          | builds against profile             |
| `rbx contest st b -p ok` (all problems have profile)      | builds normally                    |
| `rbx contest st b -p partial` (some problems missing)     | warn + skip those, build the rest  |
| `rbx contest st b -p missing` (no problem has profile)    | exit 1                             |

### Testing

- `tests/rbx/box/statements/test_build_statements.py` — two tests: profile
  applies (assert the rendered statement reflects the profile's time limit), and
  missing profile exits 1.
- `tests/rbx/box/contest/test_statement_overriding.py` (or a sibling) — three
  tests: all-have-profile builds normally, mixed-availability skips the
  missing ones (assert the warning and that the missing problem is absent from
  the output), all-missing exits 1.
- Reuse `cleandir_with_testdata` fixtures; add a small `.limits/<profile>.yml`
  to the chosen fixture package.

## Out of scope

- Changing the semantics of the global `-p` flag for commands other than
  statement build.
- Introducing additional profile-validation primitives — the existing
  `fallback_to_package_profile=False` path in `get_limits_profile` is enough.
- Surfacing the active profile in the statement footer or metadata.
