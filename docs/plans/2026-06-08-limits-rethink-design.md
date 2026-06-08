# Rethinking the `get_solution_limits` family (#351)

## Problem

Issue #351 (`bug`, `timing`) flags that the cluster of "get the limits" helpers is
confusing and bug-prone. The concrete smells:

1. **Two overlapping skeleton methods** on `SolutionReportSkeleton`
   (`rbx/box/solutions.py`):
   - `get_solution_limits(solution)` — looks up a **pre-computed, cached**
     `Limits` from `self.limits` (keyed by language), built once at skeleton
     creation via `get_limits_for_language`.
   - `get_solution_limits_from_disk(solution)` — **re-reads the profile YAML
     from disk** and recomputes a fresh `Limits`, bootstrapping off the cached
     variant just to learn the profile name.

2. **The disk-reload dance** at the timing-report call site:

   ```python
   limits = skeleton.get_solution_limits(solution)
   if limits.time is None:                                # cached time was stripped...
       limits = skeleton.get_solution_limits_from_disk(solution)  # ...reload to recover it
   assert limits.time is not None
   ```

   `get_limits_for_language` (`tasks.py`) deliberately nulls `Limits.time` to
   signal "don't enforce a TL for this run" (`use_timelimit=False`, or
   `time <= 0`). That destroys the *declared* time limit that the reporting code
   wants to display, forcing a round-trip back to disk.

3. **Name confusion** in `limits_info.*` (out of scope here, but the reason the
   family is "weird"): `get_limits` / `get_package_limits` return `Limits` while
   `get_limits_profile` / `get_package_limits_profile` return `LimitsProfile`.
   This already shipped a real type bug (a `LimitsProfile`-returning function was
   used where a `Limits` was expected; fixed in `cf67eaa`).

## Root cause

`Limits.time` is overloaded: it means both *the configured/declared* time limit
**and** *the enforced* time limit. Nulling it to express "not enforced" loses the
declared value, so display code can't recover it without re-reading from disk.

## Design (focused scope)

Separate the two meanings on the `Limits` model. Keep `limits_info.*` names
as-is (a deliberate scope cut — see "Out of scope").

### 1. `rbx/grading/limits.py`

- Add `configuredTime: Optional[int] = None` — the declared TL, regardless of
  whether it is enforced for a given run.
- Add `display_time() -> Optional[int]` — returns `configuredTime` if set, else
  falls back to `time`.
- `time` keeps its current meaning exactly: the **enforced** limit (`None` = no
  enforcement). The sandbox (`_get_execution_config`), checkers (soft-TLE /
  `get_expanded_tl`), and packaging continue to read `time` unchanged.

### 2. `rbx/box/limits_info.py`

- In `_get_limits_from_profile`, populate `configuredTime` with the same resolved
  value as `time`. Every `Limits` produced from a profile (which is all of the
  factories) then carries the declared TL.

### 3. `rbx/box/tasks.py` — `get_limits_for_language`

- When applying `timelimit_override`, set both `time` and `configuredTime` to the
  override (the override is the effective declared TL for that run).
- When nulling `time` (`use_timelimit=False` or `time <= 0`), leave
  `configuredTime` intact, so enforcement-off runs still know their declared TL.

### 4. `rbx/box/solutions.py`

- Delete `get_solution_limits_from_disk`.
- Keep `get_solution_limits` as the single resolver.
- Replace the disk-reload block with `display_time()`:

  ```python
  limits = skeleton.get_solution_limits(solution)
  display_tl = limits.display_time()
  assert display_tl is not None
  tl = display_tl
  expanded_tl = display_tl * 2 if limits.isDoubleTL else display_tl
  ```

## Behavior preservation

- **Sandbox**: `_get_execution_config` reads `limits.time` — unchanged.
- **Checkers / soft-TLE / double-TL**: read `limits.time` / `get_expanded_tl()` —
  unchanged. `get_expanded_tl()` stays keyed off the enforced `time`, so an
  enforcement-off run never spuriously gains a TL to compare against.
- **Packaging (boca/polygon)**: build via `limits_info.get_limits` and read
  `.time`, which equals `configuredTime` there — unchanged.
- **Reporting (measured branch)**: still reads `eval.log.metadata.limits.time`
  (the enforced value actually applied). Old cached `.eval`/`.log` logs lack
  `configuredTime`, but that branch never reads it, and `display_time()` falls
  back to `time`.
- **Cache**: the run cache key uses `params.get_cacheable_params()` (sandbox
  params), not the `Limits`/metadata object, so the new field does not perturb
  caching. Old logs deserialize via the field default.

## Edge cases

- Configured TL `<= 0` (effectively no limit): `configuredTime` carries that
  value (e.g. `0`), matching today's `get_solution_limits_from_disk` behavior;
  the assertion still holds.
- Solution with no detected language: `get_solution_limits` falls back to
  `get_package_limits` (unchanged), which now also carries `configuredTime`.

## Out of scope

Renaming the `limits_info.*` family (`get_limits` vs `get_package_limits` vs
`get_limits_profile` vs `get_package_limits_profile`). That is the broader half of
the "rethink" but has a large blast radius (packaging, statements, UI) and is
deferred.

## Tests

- `display_time()` returns `configuredTime` when `time` is nulled; equals `time`
  otherwise.
- `get_limits_for_language(use_timelimit=False)` keeps `configuredTime` while
  nulling `time`; `timelimit_override` sets both.
- Re-run `tests/rbx/box/limits_info_test.py` and the solutions tests.
