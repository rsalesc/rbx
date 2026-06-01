# Configurable per-language wall time limits (issue #490)

## Problem

Wall time limit is too tight for slow languages (Java/Kotlin/Python), where
interpreter/JVM startup eats into the wall-clock budget even when CPU time is
fine. Today the wall time is hardcoded and not configurable per language:

- **rbx local judging** (`rbx/box/tasks.py:_get_execution_config`, lines 188–202):
  `wallTimeLimit = expanded_cpu_TL × 2` for every language (the stupid sandbox
  always uses a soft timeout).
- **BOCA packaging**: wall time is hardcoded in each per-language run/interactive
  shell script as `ttime = cpu_time_seconds + 30`
  (`rbx/resources/packagers/boca/run/*`, `.../interactive/*`). This was `× 4`
  until commit `dc88cd8` flipped it to `+30` as an ad-hoc hack for Maratona
  Mineira — direct evidence that the formula needs to be configurable rather
  than periodically re-tweaked.

## Goal

Support a configurable `wall = a·x + b` formula per language, where:

- `a` = `wallTimeMultiplier`
- `b` = `wallTimeIncrement` (milliseconds)
- `x` = the **expanded per-language CPU time limit** (after `timeMultiplier` /
  `doubleTL` is applied)

Defaults live in the environment (`env.rbx.yml`), with optional per-language
overrides, and a single shared implementation is used by both rbx and BOCA.

## Design

### 1. Schema (`rbx/box/environment.py`)

Env-level defaults go on the existing `TimingConfig` (already wired into
`Environment.timing`, line 316):

```python
class TimingConfig(BaseModel):
    formula: str = ...                    # existing
    wallTimeMultiplier: float = 2.0       # a
    wallTimeIncrement: int = 0            # b, in milliseconds
```

Per-language override is a new optional sub-model on `EnvironmentLanguage`:

```python
class LanguageTimingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    wallTimeMultiplier: Optional[float] = None
    wallTimeIncrement: Optional[int] = None

class EnvironmentLanguage(BaseModel):
    ...
    timing: Optional[LanguageTimingConfig] = None
```

**Resolution:** per-language value when set, otherwise the env `timing` default.
Increment is in **milliseconds** everywhere (rbx's native unit); BOCA converts to
seconds at emit time.

### 2. Shared computation (single source of truth)

```python
def resolve_walltime_coeffs(language: Optional[str]) -> tuple[float, int]:
    """Returns (multiplier, increment_ms), language override over env default."""

def compute_walltime(cpu_tl_ms: int, language: Optional[str]) -> int:
    a, b = resolve_walltime_coeffs(language)
    return int(cpu_tl_ms * a + b)
```

Both rbx and BOCA call `compute_walltime` / `resolve_walltime_coeffs`. Lives in
`rbx/box/environment.py` (or `limits_info.py`) so it can read the active
environment.

### 3. rbx local judging (`rbx/box/tasks.py`)

Thread `language` into `_get_execution_config` and replace the hardcoded `× 2`:

```python
sandbox.wallTimeLimit = sandbox.timeLimit
if sandbox.timeLimit is not None and sandbox_type.use_soft_timeout():
    sandbox.wallTimeLimit = compute_walltime(sandbox.timeLimit, language)
```

`x = sandbox.timeLimit` is already the expanded CPU TL (after `doubleTL`).
With defaults `a=2.0, b=0` this reproduces today's behavior exactly — zero
regression. The non-soft-timeout branch (real sandboxes that enforce CPU
directly) keeps `wall = cpu` and the formula does **not** apply there.

Callers (`_run_communication_solution_on_testcase` and the batch equivalent)
already compute `language = find_language_name(solution)` and pass it in. The
interactive path that sums solution + interactor wall times keeps summing the
two computed values.

### 4. BOCA (`rbx/box/packaging/boca/packager.py` + templates)

Remove the hardcoded `let "ttime = $time + 30"` from the `run/*` and
`interactive/*` templates. Substitute the per-language coefficients in
`_expand_run_script` / `_replace_common`, using `awk` for the float multiply
(bash `let` is integer-only):

```bash
time=$3
if [ "$time" -gt "0" ]; then
  ttime=$(awk "BEGIN{print int($time * {{rbxWallMultiplier}} + {{rbxWallIncrementSec}} + 0.999)}")
else
  time=1
  ttime={{rbxWallIncrementSec}}
fi
```

`{{rbxWallIncrementSec}} = ceil(b_ms / 1000)`. BOCA's `$time` is the per-language
CPU TL in integer seconds (aggregated over `nruns`), which matches `x`. This
deletes the Maratona-Mineira hack and makes rbx and BOCA agree by construction,
since both derive from the same coefficients.

### 5. Sensible defaults in the shipped preset (`rbx/resources/presets/default/env.rbx.yml`)

```yaml
timing:
  wallTimeMultiplier: 2.0
  wallTimeIncrement: 1000        # 1s headroom
languages:
  - name: java
    timing: { wallTimeIncrement: 3000 }   # JVM startup
  - name: kt
    timing: { wallTimeIncrement: 3000 }
  - name: py
    timing: { wallTimeIncrement: 2000 }   # interpreter startup
```

Conservative defaults (small increments), not the old flat `+30s` cushion.

### 6. Testing

- Unit: `resolve_walltime_coeffs` (env default, per-language override, fallback)
  and `compute_walltime`.
- `tasks.py`: wall time uses the resolved per-language coefficients.
- BOCA: emitted run/interactive scripts substitute the correct coefficients
  (update existing packaging snapshot/tests).

## Decisions (confirmed)

1. **Config home:** `env.rbx.yml` — env-level default in `timing`, optional
   per-language override.
2. **`x`:** expanded per-language CPU TL.
3. **BOCA integration:** compute in Python, substitute `a`/`b` into scripts.
4. **Default increment:** conservative (1s global, 2–3s for slow languages).
5. **Increment unit:** milliseconds at the config level.
6. **Scope:** formula applies only in the soft-timeout (stupid sandbox) branch.
