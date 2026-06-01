# Configurable per-language wall time limits — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the wall-time limit configurable per language via an `a·x + b` formula (`wallTimeMultiplier`, `wallTimeIncrement`), with defaults in `env.rbx.yml`'s `timing` block and optional per-language overrides, shared by rbx local judging and BOCA packaging.

**Architecture:** Add coefficients to the env-level `TimingConfig` and an optional per-language `LanguageTimingConfig` override on `EnvironmentLanguage`. A pure resolver picks the effective `(multiplier, increment_ms)`; `compute_walltime(cpu_tl_ms, language)` applies the formula where `x` = expanded per-language CPU TL. `tasks.py` uses it for local judging (soft-timeout branch only); the BOCA packager substitutes the resolved coefficients into the run/interactive shell templates, replacing the hardcoded `ttime = $time + 30`.

**Tech Stack:** Python 3, Pydantic v2, Typer, pytest. Single quotes, absolute imports only (ruff). Conventional Commits via the `commit` workflow (`.claude/skills/commit.md`).

**Reference:** Design doc `docs/plans/2026-06-01-configurable-walltime-design.md`.

**Notes for the implementer:**
- The active BOCA packager is the legacy `rbx/box/packaging/boca/packager.py`. `boca_next/` is a stub (CLAUDE.md only) — out of scope.
- `environment.TimingConfig` (env.rbx.yml `timing:`) is the target. Do NOT touch `rbx/box/timing.py` (`TimingProfile`) — that is the unrelated per-problem TL-estimation profile.
- Defaults `multiplier=2.0, increment=0` reproduce today's rbx behavior exactly.
- New `@functools.cache` on module-level `rbx/box/` functions must be registered in `rbx.testing_utils.clear_all_functools_cache` (test isolation rule). The resolver below is a plain function (no cache) to avoid this.
- Run tests with `uv run pytest ...`. Lint with `uv run ruff check --fix . && uv run ruff format .`.

---

### Task 1: Schema — add wall-time coefficients to the environment

**Files:**
- Modify: `rbx/box/environment.py` (`TimingConfig` ~line 276; new `LanguageTimingConfig`; `EnvironmentLanguage` ~line 209)
- Test: `tests/rbx/box/walltime_test.py` (create)

**Step 1: Write the failing test**

Create `tests/rbx/box/walltime_test.py`:

```python
from rbx.box.environment import (
    EnvironmentLanguage,
    ExecutionConfig,
    LanguageTimingConfig,
    TimingConfig,
)


def test_timing_config_walltime_defaults():
    cfg = TimingConfig()
    assert cfg.wallTimeMultiplier == 2.0
    assert cfg.wallTimeIncrement == 0


def test_language_timing_config_optional_fields():
    cfg = LanguageTimingConfig()
    assert cfg.wallTimeMultiplier is None
    assert cfg.wallTimeIncrement is None


def test_environment_language_accepts_timing():
    lang = EnvironmentLanguage(
        name='java',
        extension='java',
        execution=ExecutionConfig(),
        timing=LanguageTimingConfig(wallTimeIncrement=3000),
    )
    assert lang.timing is not None
    assert lang.timing.wallTimeIncrement == 3000
    assert lang.timing.wallTimeMultiplier is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/walltime_test.py -v`
Expected: FAIL (`ImportError: cannot import name 'LanguageTimingConfig'`).

**Step 3: Implement**

In `rbx/box/environment.py`, extend `TimingConfig`:

```python
class TimingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    formula: str = Field(
        default='step_up(max(fastest * 3, slowest * 1.5), 100)',
        description="""Formula to use to calculate the time limit for the environment.""",
    )

    wallTimeMultiplier: float = Field(
        default=2.0,
        description="""Default multiplier `a` in the wall-time formula `a*x + b`, where `x` is the expanded CPU time limit.""",
    )

    wallTimeIncrement: int = Field(
        default=0,
        description="""Default increment `b` (in milliseconds) in the wall-time formula `a*x + b`.""",
    )
```

Add a new model just before `EnvironmentLanguage`:

```python
class LanguageTimingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    wallTimeMultiplier: Optional[float] = Field(
        default=None,
        description="""Overrides the environment wall-time multiplier `a` for this language.""",
    )

    wallTimeIncrement: Optional[int] = Field(
        default=None,
        description="""Overrides the environment wall-time increment `b` (in milliseconds) for this language.""",
    )
```

Add the field to `EnvironmentLanguage` (next to `extensions`/`linters`):

```python
    timing: Optional[LanguageTimingConfig] = Field(
        default=None,
        description="""Per-language overrides for timing configuration (e.g. wall time).""",
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/walltime_test.py -v`
Expected: PASS.

**Step 5: Commit** (use the `.claude/skills/commit.md` workflow)

```
feat(environment): add per-language wall-time coefficients to schema
```

---

### Task 2: Shared resolver + `compute_walltime`

**Files:**
- Modify: `rbx/box/environment.py` (add functions near `get_language_or_nil`, ~line 367)
- Test: `tests/rbx/box/walltime_test.py`

**Step 1: Write the failing test**

Append to `tests/rbx/box/walltime_test.py`:

```python
from rbx.box.environment import (
    apply_walltime_formula,
    resolve_walltime_coeffs,
)


def test_resolve_coeffs_uses_env_default_when_no_language_override():
    env_timing = TimingConfig(wallTimeMultiplier=2.0, wallTimeIncrement=1000)
    lang = EnvironmentLanguage(name='cpp', extension='cpp', execution=ExecutionConfig())
    assert resolve_walltime_coeffs(env_timing, lang) == (2.0, 1000)


def test_resolve_coeffs_language_override_wins_field_by_field():
    env_timing = TimingConfig(wallTimeMultiplier=2.0, wallTimeIncrement=1000)
    lang = EnvironmentLanguage(
        name='java',
        extension='java',
        execution=ExecutionConfig(),
        timing=LanguageTimingConfig(wallTimeIncrement=3000),
    )
    # multiplier falls back to env, increment overridden
    assert resolve_walltime_coeffs(env_timing, lang) == (2.0, 3000)


def test_resolve_coeffs_with_none_language():
    env_timing = TimingConfig(wallTimeMultiplier=3.0, wallTimeIncrement=500)
    assert resolve_walltime_coeffs(env_timing, None) == (3.0, 500)


def test_apply_walltime_formula():
    # wall = 2*x + b
    assert apply_walltime_formula(1000, (2.0, 0)) == 2000
    assert apply_walltime_formula(1000, (2.0, 1000)) == 3000
    assert apply_walltime_formula(1500, (1.5, 250)) == 2500  # int(1500*1.5+250)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/walltime_test.py -v`
Expected: FAIL (`ImportError`).

**Step 3: Implement**

In `rbx/box/environment.py` (after `get_language_or_nil`):

```python
def resolve_walltime_coeffs(
    timing: TimingConfig,
    language: Optional[EnvironmentLanguage],
) -> Tuple[float, int]:
    """Resolves the effective (wall_time_multiplier, wall_time_increment_ms),
    where a per-language override takes precedence field-by-field over the
    environment-level timing defaults."""
    multiplier = timing.wallTimeMultiplier
    increment = timing.wallTimeIncrement
    if language is not None and language.timing is not None:
        if language.timing.wallTimeMultiplier is not None:
            multiplier = language.timing.wallTimeMultiplier
        if language.timing.wallTimeIncrement is not None:
            increment = language.timing.wallTimeIncrement
    return multiplier, increment


def apply_walltime_formula(cpu_tl_ms: int, coeffs: Tuple[float, int]) -> int:
    """Applies wall = a*x + b, where x is the expanded CPU time limit (ms)."""
    multiplier, increment = coeffs
    return int(cpu_tl_ms * multiplier + increment)


def get_walltime_coeffs_for_language(
    language: Optional[str],
) -> Tuple[float, int]:
    """Reads the active environment and resolves wall-time coefficients for the
    given language name (None -> environment defaults)."""
    env = get_environment()
    lang = get_language_or_nil(language) if language is not None else None
    return resolve_walltime_coeffs(env.timing, lang)


def compute_walltime(cpu_tl_ms: int, language: Optional[str]) -> int:
    return apply_walltime_formula(
        cpu_tl_ms, get_walltime_coeffs_for_language(language)
    )
```

Ensure `Tuple` is imported from `typing` (add to the existing typing import if missing).

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/walltime_test.py -v`
Expected: PASS.

**Step 5: Commit**

```
feat(environment): add shared wall-time resolver and formula
```

---

### Task 3: Wire wall-time formula into rbx local judging

**Files:**
- Modify: `rbx/box/tasks.py` (`_get_execution_config` ~lines 188–202; its callers ~line 124 and ~lines 239–240)
- Test: `tests/rbx/box/tasks_test.py` (add) — if environment-dependent wiring is hard to unit test there, add a focused test in `tests/rbx/box/walltime_test.py` patching `environment.compute_walltime`.

**Step 1: Write the failing test**

Add to `tests/rbx/box/walltime_test.py`:

```python
from unittest import mock

from rbx.box import tasks
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
from rbx.grading.limits import Limits


def test_get_execution_config_uses_walltime_formula_for_language():
    limits = Limits(time=1000, memory=256, output=4096)
    with mock.patch.object(
        tasks.environment, 'compute_walltime', return_value=4242
    ) as m:
        cfg = tasks._get_execution_config(limits, StupidSandbox, language='java')
    assert cfg.sandbox is not None
    assert cfg.sandbox.timeLimit == 1000
    assert cfg.sandbox.wallTimeLimit == 4242
    m.assert_called_once_with(1000, 'java')


def test_get_execution_config_doubletl_passes_expanded_tl_as_x():
    limits = Limits(time=1000, memory=256, output=4096, isDoubleTL=True)
    with mock.patch.object(
        tasks.environment, 'compute_walltime', return_value=9999
    ) as m:
        cfg = tasks._get_execution_config(limits, StupidSandbox, language='cpp')
    # x must be the expanded (doubled) CPU TL
    m.assert_called_once_with(2000, 'cpp')
    assert cfg.sandbox.wallTimeLimit == 9999
```

> Note: confirm `tasks.py` imports the `environment` module (it currently imports specific names from `rbx.box.environment`). If not, add `from rbx.box import environment` so the patch target `tasks.environment.compute_walltime` exists. Adjust the test's patch target to match the actual import style.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/walltime_test.py -k execution_config -v`
Expected: FAIL (`_get_execution_config()` got an unexpected keyword `language`).

**Step 3: Implement**

In `rbx/box/tasks.py`, add `from rbx.box import environment` (if not present). Change `_get_execution_config`:

```python
def _get_execution_config(
    limits: Limits,
    sandbox_type: Type[SandboxBase],
    language: Optional[str] = None,
) -> ExecutionConfig:
    sandbox = EnvironmentSandbox()
    sandbox.timeLimit = limits.time
    if limits.isDoubleTL and sandbox.timeLimit is not None:
        # Double TL.
        sandbox.timeLimit = sandbox.timeLimit * 2
    sandbox.wallTimeLimit = sandbox.timeLimit
    if sandbox.timeLimit is not None and sandbox_type.use_soft_timeout():
        sandbox.wallTimeLimit = environment.compute_walltime(
            sandbox.timeLimit, language
        )
    sandbox.memoryLimit = limits.memory
    sandbox.fileSizeLimit = limits.output
    return ExecutionConfig(sandbox=sandbox, problemLimits=limits)
```

Update both call sites to pass the already-computed `language`:
- ~line 124 (batch path): `extra_config = _get_execution_config(limits, sandbox_type, language)`
- ~lines 239–240 (communication path): pass `language` to both `_get_execution_config(...)` calls. The existing interactor-wall-time summation stays as-is (it sums the two computed wall times).

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/box/walltime_test.py -v` then `uv run pytest tests/rbx/box/tasks_test.py -v`
Expected: PASS (and no regression in tasks_test).

**Step 5: Commit**

```
feat(tasks): apply per-language wall-time formula in local judging
```

---

### Task 4: Wire wall-time formula into BOCA packaging

**Files:**
- Modify templates (replace hardcoded `ttime = $time + 30`):
  - `rbx/resources/packagers/boca/run/{c,cpp,java,kt,py2,py3}`
  - `rbx/resources/packagers/boca/interactive/{c,cpp,java,kt,py2,py3}`
- Modify: `rbx/box/packaging/boca/packager.py` (`_replace_common` ~line 193 and/or `_expand_run_script` ~line 319; uses `_get_pkg_timelimit`/`limits_info`)
- Test: `tests/rbx/box/packaging/` (find the existing BOCA packaging test; otherwise add a focused unit test on the substitution helper)

**Step 1: Write the failing test**

First locate an existing BOCA packaging test (`grep -rl "BocaPackager\|_expand_run_script\|run/cpp" tests/`). Add a test asserting the emitted run script no longer contains `+ 30` and substitutes the resolved coefficients. Prefer testing the pure substitution: factor the coefficient→script substitution into a helper, e.g. `_replace_walltime(text, language)`, and unit-test it:

```python
def test_boca_walltime_substitution(...):
    # Given a template containing the {{rbxWallMultiplier}}/{{rbxWallIncrementSec}}
    # placeholders and a language whose coeffs resolve to (2.0, 3000 ms),
    # the substituted script contains 2.0 and ceil(3000/1000)=3, and no '+ 30'.
```

Match the project's existing BOCA test fixtures/patterns (see `tests/e2e/testdata/pkg-boca*`). If the cleanest seam is an e2e snapshot, update the snapshot instead and assert the script content.

**Step 2: Run test to verify it fails**

Run: `uv run pytest <the boca test> -v`
Expected: FAIL (placeholders unsubstituted / `+ 30` still present).

**Step 3: Implement**

Edit each `run/*` and `interactive/*` template, replacing the block:

```bash
time=$3
if [ "$time" -gt "0" ]; then
  let "ttime = $time + 30"
else
  time=1
  ttime=30
fi
```

with (Java/Kotlin/Python templates have the same block at a different line — replace all):

```bash
time=$3
if [ "$time" -gt "0" ]; then
  ttime=$(awk "BEGIN{print int($time * {{rbxWallMultiplier}} + {{rbxWallIncrementSec}} + 0.999)}")
else
  time=1
  ttime={{rbxWallIncrementSec}}
fi
```

In `packager.py`, resolve coefficients per language using the shared resolver and the BOCA CPU TL, and substitute. Add a helper and call it from `_replace_common` (which already runs for run, interactive, compile, checker — only the run/interactive templates contain the placeholders, so substitution is a no-op elsewhere):

```python
import math
from rbx.box import environment

def _replace_walltime(self, text: str, language: BocaLanguage) -> str:
    env = environment.get_environment()
    lang = environment.get_language_or_nil(language)
    multiplier, increment_ms = environment.resolve_walltime_coeffs(
        env.timing, lang
    )
    increment_sec = math.ceil(increment_ms / 1000)
    text = text.replace('{{rbxWallMultiplier}}', f'{multiplier:g}')
    text = text.replace('{{rbxWallIncrementSec}}', str(increment_sec))
    return text
```

> NOTE on the BOCA language identifier: `_replace_common` receives the BOCA template language (e.g. `cc`, `py3`), not the rbx language name (`cpp`, `py`). `get_language_or_nil` expects the rbx name. Map BOCA→rbx before resolving (reuse the existing BOCA language mapping in `boca/utils.py` / `get_boca_template_name`, inverted) so per-language overrides resolve correctly. If a clean inverse mapping is unavailable, resolve from the rbx language at the `_expand_run_script` call site (which is per emitted rbx language) instead of inside `_replace_common`. Choose the seam that lets coefficients resolve from the correct rbx language; verify against the env preset (java increment 3000 → `ttime` uses 3).

Call `self._replace_walltime(text, language)` inside `_replace_common` (or `_expand_run_script`).

**Step 4: Run tests**

Run: `uv run pytest <the boca test> -v`
Expected: PASS. Also `grep -rn "+ 30\|let \"ttime" rbx/resources/packagers/boca/` returns nothing.

**Step 5: Commit**

```
feat(boca): derive wall time from shared per-language formula
```

---

### Task 5: Sensible defaults in the shipped preset

**Files:**
- Modify: `rbx/resources/presets/default/env.rbx.yml`
- Test: an e2e/packaging assertion if one covers preset values; otherwise manual verification.

**Step 1: Edit the preset**

Add the `timing` block and per-language overrides:

```yaml
timing:
  wallTimeMultiplier: 2.0
  wallTimeIncrement: 1000
languages:
  - name: "cpp"
    ...
  - name: "py"
    ...
    timing:
      wallTimeIncrement: 2000
  - name: "java"
    ...
    timing:
      wallTimeIncrement: 3000
  - name: "kt"
    ...
    timing:
      wallTimeIncrement: 3000
```

(Insert `timing:` at the top level alongside `sandbox`, `defaultCompilation`, etc.; add the per-language `timing:` under the existing `py`/`java`/`kt` entries. Keep `cpp`/`c` on the env default.)

**Step 2: Verify the preset loads**

Run: `uv run python -c "from rbx.box.environment import Environment; from rbx.box.yaml_validation import load_yaml_model; import pathlib; e=load_yaml_model(pathlib.Path('rbx/resources/presets/default/env.rbx.yml'), Environment); print(e.timing.wallTimeMultiplier, e.timing.wallTimeIncrement); print({l.name: (l.timing and l.timing.wallTimeIncrement) for l in e.languages})"`
Expected: prints `2.0 1000` and a dict showing `java`/`kt` = 3000, `py` = 2000, others `None`.

**Step 3: Commit**

```
feat(preset): set default per-language wall-time coefficients
```

---

### Task 6: Full verification

**Step 1: Lint/format**

Run: `uv run ruff check --fix . && uv run ruff format .`

**Step 2: Targeted tests**

Run: `uv run pytest tests/rbx/box/walltime_test.py tests/rbx/box/tasks_test.py tests/rbx/box/test_timing.py -v`
Expected: PASS.

**Step 3: Broader suite (excluding slow CLI)**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: PASS (note: per the project memory, some C++/checker/validator/sandbox/docker tests fail pre-existingly on this machine and are unrelated to this change — confirm any failures are in that known set).

**Step 4: BOCA e2e (if environment allows)**

Run: `mise run test-e2e` (or the targeted BOCA e2e fixture). Verify emitted `run/*` scripts contain the substituted formula and no `+ 30`.

**Step 5: Use superpowers:requesting-code-review, then finishing-a-development-branch**

After review, open a PR referencing issue #490.

---

## Risks / things to watch

- **BOCA language mapping**: the substitution must resolve coefficients from the correct rbx language (Task 4 NOTE). Getting this wrong means per-language overrides silently fall back to env defaults — verify java/kt/py emit `ttime` increment 3/3/2.
- **`awk` availability** on BOCA judge hosts: `awk` is part of base BOCA images (the run scripts already use standard coreutils); acceptable. If undesirable, compute integer `ttime` in Python and substitute a literal — but that loses the `$time`-relative formula. Keep `awk`.
- **Regression safety**: default `(2.0, 0)` keeps rbx identical to today; BOCA changes from `+30` to `2*x + 1` (preset). Confirm this is intended (it is — the `+30` was the Maratona-Mineira hack being removed).
- **doubleTL**: `x` is the already-expanded CPU TL — confirmed via Task 3 test.
