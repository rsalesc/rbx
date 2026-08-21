# Box Module (`rbx/box/`)

Core application logic for the rbx CLI. This is the main module containing the build pipeline, solution running, schema definitions, and all major features.

## Schema System (`schema.py`, ~1000 lines)

The central Pydantic model hierarchy defining `problem.rbx.yml`:

### Key Models

- **`Package`** -- Root model. Contains: `name`, `timeLimit`, `memoryLimit`, `solutions`, `testcases`, `checker`, `validator`, `interactor`, `statements`, `vars`, `limitsProfiles`, `scoreType`
- **`Solution`** -- `path`, `outcome` (ExpectedOutcome, matched against the whole testset pooled), `outcomePerGroup` (per-group expectations keyed by top-level group name, `'*'` = default applied to every group individually; an additive second layer, checked on top of `outcome`; **POINTS scoring only** -- a BINARY problem yields one pooled verdict for the whole testset, so `check_scoring_fields` rejects the field there and every consumer may assume the per-group layer implies POINTS), `score`, `doubleTL`, `language`. Resolution helpers: `expected_outcome_for_group()`, `all_expected_outcomes()`
- **`TestcaseGroup`** (extends `TestcaseSubgroup`) -- `name`, `generator`, `generatorScript`, `testcases`, `subgroups`, `validator`, `score`, `deps`, `vars` (per-group overrides of the package `vars`; top-level groups only, since only the top-level group name reaches the validator)
- **`TestcaseSubgroup`** -- `testcases` list, `generator` (GeneratorCall or CodeItem)
- **`Testcase`** -- `inputPath`, `outputPath` (for manual test cases)
- **`GeneratorCall`** -- `name`, `args` (references a generator program)
- **`CodeItem`** -- `path`, `language`, `compilationArgs` (reference to any code file)
- **`LimitsProfile`** -- Per-packager limit overrides with `modifiers` per language, `formula` support; also carries optional `groups` metadata (a `TimingGroupReport` list, presentation-only) recording how languages were grouped during estimation
- **`LimitModifiers`** -- `time`, `timeMultiplier`, `memory` per language
- **`TimingGroupOrigin` / `TimingGroupReport`** -- presentation-only types describing each language group's resolved time limit and its source (estimated / `whenEmpty` multiple / defaulted)

### Vars and per-group overrides

`Package.vars` / `TestcaseGroup.vars` are `RecVars` (nested dicts of primitives, `fields.py`). `expand_vars()` resolves ``py`...`` interpolation and flattens to dotted keys (`AB: {min: 1}` -> `AB.min`).

- `Package.expanded_vars` -- package-level flattened vars.
- `Package.expanded_vars_for_group(name)` -- `merge_recvars(pkg.vars, group.vars)` (deep, leaf-by-leaf, so a partial override keeps its siblings) expanded afterwards, so an override can feed any var interpolated from it. Falls back to the package vars when `name` is `None` or names no declared group (interactive validation, unit tests, samples).
- `package.get_expanded_vars_for_group(name)` -- `@functools.cache`d wrapper; expansion is too costly to redo per testcase. The returned dict is shared -- never mutate it.
- **Reserved names** (`RESERVED_VAR_NAMES`, `check_reserved_var_names`) -- vars go to validators as `--{dotted_key}={value}`, so a *top-level primitive* key named after a flag testlib or rbx consumes (`group`, `testset`, `help`, `testCase`, `testCaseFileName`, `testMarkupFileName`, `testOverviewLogFileName`) is rejected at validation time. Nested keys are fine: they flatten to `--parent.key=...`, which no flag parser matches.
- **Statement-reserved names** (`RESERVED_STATEMENT_VAR_NAMES`, `check_reserved_statement_var_names`, both in `fields.py`) -- vars are also bound into their enclosing statement template namespace (`\VAR{N.max}` == `\VAR{vars.N.max}`, #630), so a top-level key named after anything rbx exposes there (`title`, `name`, `score`, `limits`, `problem`, ...) is rejected. Unlike the testlib check, *every* top-level key is checked, dict or not; the fix is a rename or one level of nesting. Applied to `Package.vars`, `TestcaseGroup.vars` and `Contest.vars` (the latter skips the testlib check -- contest vars never reach a validator).

`header.py` emits the per-group arms into `rbx.h`: for each group declaring `vars` (sorted), one `if (group == "<name>") { ... return std::nullopt; }` arm ahead of the package-level table, per accessor type. An arm carries the group's *whole* resolved var set so a type-changing override cannot leave the package value reachable. `group` comes from `rbx::getGroup()`, which parses `--group` out of the process command line; the preamble and the platform guard are emitted only when some group declares `vars`, so packages without overrides pay nothing. `validators.py` passes `--group <name>` plus the group-resolved vars, and reports hit bounds per group whenever any group declares `validator` or `vars`.

### `ExpectedOutcome` (AutoEnum)

Maps expected solution behavior to verdict matching. Values: `ANY`, `ACCEPTED`, `ACCEPTED_OR_TLE`, `WRONG_ANSWER`, `INCORRECT`, `TIME_LIMIT_EXCEEDED`, `TLE_OR_RTE`, `RUNTIME_ERROR`, `MEMORY_LIMIT_EXCEEDED`, `OUTPUT_LIMIT_EXCEEDED`.

Each has a `match(outcome: Outcome) -> bool` method. `INCORRECT` matches WA/RTE/MLE/OLE/TLE. `ANY` matches everything.

### `ScoreType` / `TaskType`

- `ScoreType`: `BINARY` (ICPC all-or-nothing) or `POINTS` (IOI subtask scoring)
- `TaskType`: `BATCH` (standard) or `COMMUNICATION` (interactive)

## Package Discovery (`package.py`, `cd.py`)

- **`find_package(root)`** in `cd.py` -- Walks up directory tree looking for `problem.rbx.yml`, `contest.rbx.yml`, or `preset.rbx.yml`
- **`within_problem` decorator** in `package.py` -- Guards CLI commands, calls `find_package()`, changes directory, loads the package
- **`find_problem_package_or_die()`** -- Returns loaded `Package` or exits
- Package loading merges `env.rbx.yml` (language/sandbox config) with `problem.rbx.yml`

### Multi-contest mode

`contest.rbx.yml` may be a real Contest, a dispatcher sentinel (`use_variants: true`), or a real Contest that ALSO has sibling `contest.<id>.rbx.yml` variants. In the third case the canonical is the default selection and siblings are additional selectable variants. Dispatcher mode (`use_variants: true`) is purely a permission flag that allows the canonical to be empty (all contests live in siblings). Variant selection comes from `-C <id>` (CLI flag) or `RBX_CONTEST=<id>` env var, materialized into `rbx.box.contest.contest_state.selected_variant_id_var`.

`find_contest_yaml(root, contest_id=None)` consults the contextvar when no explicit `contest_id` is passed. In dispatcher mode without selection, problem-side helpers in `naming.py` walk all variants and auto-pick when the current problem belongs to exactly one. Sites that REQUIRE a deterministic letter use `naming.require_problem_in_contest()` (errors with picker hint) or `naming.get_problem_shortname_or_require()` (lenient when no contest exists).

## Build Pipeline (`builder.py`)

### `build()` function
1. **Generate testcases** -- `generators.generate_testcases()` with progress bar
2. **Validate inputs** -- `validators.validate_testcases()` (if verification > 0)
3. **Generate outputs** -- `generators.generate_outputs_for_testcases()` using main solution
4. **Validate outputs** -- `validators.validate_outputs_from_entries()`
5. **Check manual answers** -- `validators.check_output_from_entries()`
6. **Visualize** -- `visualizers.run_visualizers_for_entries()` (if enabled)

### `verify()` function
Calls `build()` then runs solutions based on verification level:
- `FAST_SOLUTIONS` -- Only solutions marked as "fast"
- `ALL_SOLUTIONS` -- All tracked solutions

## Solution Running (`solutions.py`, ~2185 lines, largest file)

### Execution Flow

1. **`run_solutions()`** -- Main entry point (called from `builder.verify()`)
2. **`_get_report_skeleton()`** -- Compiles solutions, builds `SolutionReportSkeleton`
3. **`_produce_solution_items()`** -- Creates `Deferred[Evaluation]` items per (solution, testcase),
   by asking a **`SolutionRunner`** (see below) for each solution's deferreds
4. **`print_run_report()`** -- Drives deferred execution, displays live results

### Runners (`runners/`)

`run_solutions` decides *what* to run -- which solutions, which testcases, under which
limits. A **`SolutionRunner`** (`runners/base.py`) decides *where*. `LocalRunner`
(`runners/local.py`) is the sandbox on this machine and is the default; a remote judge
reached over its own CLI is the other kind.

The seam is **per solution**: `run_solution()` is handed a solution and its whole
flattened testset in group order, and returns one `Deferred[Evaluation]` per entry. That
grain is deliberate -- a remote judge judges one submission against every test at once, so
a per-testcase seam would force every batch backend to coalesce calls back into a batch.

Two things stay with the orchestrator rather than the backend:

- **Abort/skip policy.** `_gated_evaluation()` wraps each returned deferred when a run asks
  for `abort_on`, so every backend gets `_AbortGate` semantics for free instead of
  re-implementing them. A run without `abort_on` gets the backend's deferreds
  *unwrapped* -- a deliberate guarantee, pinned by a test. So does a backend declaring
  `supports_abort=False`: it has already run the whole submission, so gating it would
  overwrite verdicts the judge really produced with `SKIPPED`.
- **`RunnerCapabilities`.** What a backend can report (memory, artifacts, checker
  messages, repeated runs). Declared rather than sniffed, so a consumer never reads a
  `None` as zero and calls an unmeasured run instantaneous. `_check_capabilities()` runs
  before `prepare()` and raises `RunnerCapabilityError` when the run asks for repeated
  runs, a sanitizer, or an interactor the backend does not support -- refusing by name
  beats silently running something weaker under the same report. Repeats are checked on
  the count `retries.get_retrier_config(nruns)` *resolves* to, not on the raw `nruns`:
  `nruns=0` is every caller's default and means "whatever `repeats.reps` says", which is
  the likelier way a run ends up repeated.

**Choosing one.** `rbx time --runner <name>` (`runners/registry.py`), defaulting to
`local`; an unknown name is refused naming the known ones. A *flag*, deliberately not the
limits profile: a profile is the `limits/<name>.yml` file `rbx time` writes, so binding a
transport to its name would couple an output to a transport and leave no way to estimate
MOJ limits from a machine with no judge access. The registry imports each backend lazily
(naming one must not cost the imports it talks to) and builds a fresh instance per call
(a runner holds a whole run's state). The names themselves live in `runners/names.py`, a
leaf module with no imports, so shell completion can read the same table without pulling
`rich` in behind `RbxException` (~36ms on every TAB). The `env.rbx.yml` `runners:`/`profiles:` block the design
sketches is **not** built: no backend has a reachable knob yet, and the flag is the whole
surface until something needs more.

**Tearing one down.** `await RunSolutionResult.close()` forwards to
`SolutionRunner.close()`, and every consumer of a run awaits it from a `finally` around
the *consumption* of the deferreds -- `builder.verify`, `cli.run` and
`timing._run_for_inference`. It is **not** the `finalize` hook the seam started with and
must not become it: `finalize` fired inside `run_solutions`, which only builds the
deferreds, so it ran before a single result had been fetched. What `close` drops is work
nobody will now ask for -- a backend that dispatched every solution up front still has
jobs in flight when the report stops at the first failure, or when the setter hits
Ctrl-C. It **ends a batch, not the runner**: `prepare` state survives on purpose, so a
second `run_solutions` on the same object (phase 2, re-uploading at `timeLimitToTle x
TL`) reuses the remote problem and hits the fingerprint fast path. It is `async` and
drains: `cancel()` only schedules the `CancelledError`, a job suspended in
`process.communicate()` needs several turns to unwind, and `syncer` stops the loop the
moment the consumer returns -- so `MojRunner.close` awaits `gather(...,
return_exceptions=True)` rather than hoping something pumps it. Cancelling is all rbx
does: a cancelled `moj testrun` goes on running on the judge (outside history and placar,
so nothing needs cleaning up -- `MojRunner.close` says so, once). `LocalRunner.close` is
a no-op, because its work happens inside the deferred the consumer awaits. Awaiting an
*unresolved* deferred after `close` is not supported; a resolved one keeps answering from
its memo, which is what lets `timing` close before the group picker opens.

**Two `moj` trees, different jobs.** `runners/moj/` is the *client*: a typed wrapper
over the judge's `moj` CLI (`problem_id.py`, `cli.py`) that a `MojRunner` drives to
upload, calibrate and testrun. `packaging/moj/` is the *packager* that produces what it
uploads. They meet at one object: `MojPackager(probe=ProbePackage(...))`, the
throwaway package a timing run measures on -- model solution only, one uniform
`TLOVERRIDE`, every testrunnable language whitelisted, no statement build and no
`STOPWHEN_*`. Pair timings back onto testcases with `MojPackager.testcase_names()`,
never by position and never by re-deriving the names.

`MojRunner` (`runners/moj/runner.py`) is that client's `SolutionRunner`. `prepare()`
is the whole of it today: read the login, refuse any `.moj-id` binding that is not an
`rbxt-` one (uploading over a real problem destroys it), resolve the **one** cap the
probe pins (`ctx.timelimit_override` when positive -- it is `-1`, not `None`, when
there is none -- else `timing.multipliers.inferenceTimeout`, else refuse), build the
probe, upload the *directory*, calibrate, and poll `moj check` under a bound. It skips
all of that when the judge reports ready **and** the package it just built fingerprints
equal to the one this machine last uploaded and saw calibrated; the fingerprint is a
local record in the problem cache, so it cannot see an upload from another machine.

`run_solution` submits the solution with `moj testrun` on a **background task** and
returns one `Deferred` per entry over that one shared job -- it must not block, because
`_produce_solution_items` builds every solution's deferreds before the first resolves,
which is how every solution ends up queued while the report prints the first. `Deferred`
memoizes each deferred's *own* result and nothing else, so the task is held by the runner.
Results are paired to entries **by MOJ test name**, out of the mapping `prepare` captured
off the packager that built the uploaded package: the live probe
(`docs/plans/2026-08-21-moj-probe-notes.md`) found the `tests` array is *not ordered*, so
pairing by position would misattribute essentially every timing. That mapping is keyed on
**`subgroup_entry`**, never `group_entry`: `group_entry.index` restarts at 0 per subgroup
while its `group` is the top-level one, so `beta/one/0` and `beta/two/0` collide.
Everything the runner says to the setter is said from `_evaluation_from_job`, on the
consumer's own thread of control -- the polling tasks are silent, because the reporter owns
the console and the `StatusProgress` while they run. `MAX_INFLIGHT_TESTRUNS`
caps how much of the shared judge park a session occupies; the poll is bounded, like
`prepare`'s. `_OUTCOME_BY_MOJ_CODE` maps only the four codes the probe actually saw
(`AC`/`WA`/`RE`/`TLE`) and **refuses an unrecognised one by name** rather than guessing --
a wrong verdict silently corrupts the time limit being estimated. A testcase MOJ did not
report on becomes `SKIPPED` with no timing (never a zero), and only the `.eval` is written,
never an empty `.out`.

Design: `docs/plans/2026-08-20-moj-remote-runner-design.md`.

### Deferred Execution (`deferred.py`)

```python
class Deferred(Generic[T]):
    # Lazy: async function only called on await
    # Cached: result stored after first resolution
    # Peekable: peek() returns cached value without blocking
```

Evaluations are **not truly parallel** -- they are deferred/lazy sequential. The reporter iterates and awaits each deferred in order, updating the live display after each.

### Reporter Hierarchy

- **`TraditionalRunReporter`** -- Base with start/finish lifecycle per solution/group/testcase
- **`LiveRunReporter`** -- One `rich.live.Live` line per group, with compact verdict marks (accepted testcases are omitted). Used whenever more than one solution runs, terminal or not: on a non-terminal console Live finalizes a single frame per group, which is what `--share`'s recorded consoles rely on.
- **`SingleSolutionRunReporter`** -- Verbose per-testcase details (used when only 1 solution)

### Verdict Verification

`_get_verdict_report()` matches actual outcomes against `ExpectedOutcome`:
- Collects bad verdicts (non-AC), partitions into matched/unmatched
- Solution fails if unmatched bad verdicts exist
- For POINTS scoring: group-level dependency checking, score range validation

### Double TL Detection

Solutions expecting TLE run with 2x time limit. Warns if a "TLE" solution passes within 2x TL.

### Key Data Structures

- **`SolutionReportSkeleton`** -- Central metadata: solutions, entries, groups, limits, compiled digests
- **`EvaluationItem`** -- Binds `Solution` + `TestcaseEntry` + `Deferred[Evaluation]`
- **`StructuredEvaluation`** -- 3D dict: `solution_path -> group_name -> [Deferred[Evaluation]]`
- **`SolutionOutcomeReport`** -- Status (OK/UNEXPECTED_SCORE/UNEXPECTED_VERDICTS), expected/actual, scoring

### The published run report (`run_report.py`)

`SolutionOutcomeReport` used to be rendered and discarded, so anything outside
Python that wanted to show a run had to re-derive verdicts from the raw `.eval`
files -- outcome ranking, `ExpectedOutcome.match()` and dependency-gated scoring
all re-implemented, with nothing catching the copies drifting. `run_report.py`
is the on-disk form of that answer, written to `.rbx/runs/report.yml` once per
solution as it finishes (from `TraditionalRunReporter.finish_solution`, the hook
both reporters share, and from the `--detailed` path separately). Writing a new
skeleton clears it, so its absence means "nothing has finished", never "stale".

It is a **published contract**, so three rules hold:

- **Structured, never rendered.** Enum values, seconds, bytes, integers. No
  `AC`, no `120 ms`, no `[70/100 pts]` -- formatting is the client's business.
- **Read off, never recomputed.** Every field comes from the existing
  `SolutionOutcomeReport`; the scores come from `gotScorePerGroup`, which has
  already applied the `_check_deps` gate. Recomputing anything defeats the point.
  Note `gotVerdicts` holds only the verdicts that *offended* the expectation, so
  the published `outcome` is the worst over `evals` instead.
- **Versioned.** Bump `REPORT_VERSION` when a change would make an older reader
  misread the file. Readers ignore versions they do not know.

Lean on purpose: `SolutionOutcomeReport` embeds the solution, its limits and
every evaluation, which either live on disk already or are internal shape that
must not harden into a contract. Consumed by `vscode/src/rbx/report.ts`; see
`docs/plans/2026-08-16-run-report-artifact-design.md`.

## Test Generation (`generators.py`, `generation_schema.py`, `stressing/generator_script_parser.py`)

### Generator Types
- **Generator programs** -- Compiled programs that write test input to stdout. Called with args from `GeneratorCall`.
- **Generator scripts** -- DSL files parsed by Lark grammar. Syntax:
  ```
  gen_name arg1 arg2              // generator call
  @copy path/to/file.in           // copy existing test
  @input "literal content"        // inline test content
  @input { multiline content }    // block syntax
  @testgroup group_name { ... }   // group tests
  ```
- **Manual testcases** -- Files referenced by `inputPath` in `problem.rbx.yml`

### Output Generation
`generate_outputs_for_testcases()` runs the main (first accepted) solution on all inputs to produce expected outputs.

## Checking (`checkers.py`)

### Check Pipeline
1. **`_check_pre_output()`** -- Evaluates sandbox run log BEFORE checking output. Maps exit statuses to outcomes (TLE, RTE, MLE). Handles "soft TLE" where wall time exceeds limit but exit was clean.
2. **`check()`** -- Runs checker binary (testlib convention: `checker input output answer`), processes exit code: 0=AC, 1/2=WA, 3=JUDGE_FAILED.
3. **`check_communication()`** -- Complex multi-step checking for interactive problems with 6+ priority levels.

### Soft TLE
`_convert_tle()` converts a non-TLE verdict to TLE if wall time exceeded the limit. Stores original verdict in `no_tle_outcome` for reporting.

## Stress Testing (`stresses.py`, `stressing/`)

Runs randomized testing to find edge cases:
- Generates random inputs using a generator
- Runs solution(s) against them
- Detects failures (WA, RTE, etc.)
- `finder_parser.py` -- Parses generator/finder configurations
- `whitespace.py` -- Whitespace normalization for inline test content

## Environment (`environment.py`)

Manages language configurations from `env.rbx.yml`:
- Compiler paths, flags, runtime commands per language
- Sandbox configuration (memory limits, address space)
- `VerificationLevel` enum: `NONE`, `VALIDATE`, `FAST_SOLUTIONS`, `ALL_SOLUTIONS`, `FULL`
- `timing.groups` defines language groups for time-limit estimation; the pure grouping logic lives in `rbx/box/timing_groups.py`

## Code Compilation (`code.py`)

Bridge between box-level code items and the grading engine:
- `compile_item()` -- Resolves language, builds compilation command, calls `grading/steps.compile_item()`. Takes an optional `kind: AssetKind` param; when omitted it is inferred from the `CodeItem` subclass (validators are bare `CodeItem`s, so their kind is passed explicitly by `validators.py`). Runs configured linters (see below) on the raw source before compiling, on every build.
- `run_item()` -- Resolves limits, calls `grading/steps.run_item()`
- Language detection from file extension or explicit configuration

## Linters (`linters/`)

Per-language built-in linters, configured under `EnvironmentLanguage.linters` in `env.rbx.yml` and run during `compile_item()`. Structure:
- `linter.py` -- `Linter` ABC (with `name`, `applies_to`), `LinterMessage`, `LinterSeverity`. Linters run for whatever language entry they're configured under in `env.rbx.yml`.
- `registry.py` -- name→instance registry (`@register` decorator, `get_linter`).
- `asset_kind.py` -- `AssetKind` enum + `infer_asset_kind(code)`.
- `runner.py` -- `run_linters()` (routes WARNINGs to the warning stack, ERRORs to a `RbxException`) and the pure `run_linters_for_messages()`. `is_linter_suppressed(name, source)` lets a file opt out of a linter via a `// <name>-linter: disable` comment directive (e.g. `// testlib-linter: disable`).
- `cpp/testlib.py` -- first linter (tree-sitter-cpp); `TestlibLinter` (`name='testlib'`, generators only) flags calls passing 2+ side-effecting arguments (e.g. `f(rnd.next(), rnd.next())`).
- `cpp/rbx_header.py` -- `RbxHeaderLinter` (`name='rbx-header'`, generators only, ERROR severity) flags a direct `#include "rbx.h"` / `<rbx.h>`. Reading constraints via `getVar` in a generator makes its tests change silently when a constraint changes (#386). Disable per-include with `// rbx-header-linter: disable` on the include line, or remove `rbx-header` from a language's `linters` in `env.rbx.yml`. Enabled for `cpp` by default in the bundled preset env.

Lazy imports break the `code` ↔ `linters.runner` cycle; `__init__.py` imports `cpp.testlib` and `cpp.rbx_header` so they self-register.

## Global State (`global_package.py`)

Singleton factories (via `@functools.cache`) for shared resources:
- `get_global_file_cacher()` -- Shared `FileCacher` instance
- `get_global_sandbox()` -- Shared `StupidSandbox` instance
- `get_global_dependency_cache()` -- Shared `DependencyCache`
- Cache versioning via `CACHE_STEP_VERSION` -- incremented when cache format changes
- `clear_global_cache()` -- Nukes the cache directory (used by `rbx clear`)

**Test isolation rule:** `rbx.testing_utils.clear_all_functools_cache` holds a list of *modules* and clears every attribute of each that exposes `cache_clear`. So a new `@functools.cache` (or `@async_lru.alru_cache`) on a module-level function in `rbx/box/` is covered automatically **if its module is already in that list** -- add the module if it is not (individual functions are never registered). The autouse `_isolate_global_state` fixture in `tests/rbx/conftest.py` calls this between every test; uncovered caches will leak path-resolved state across tests and surface as flaky cross-test failures (#423). `global_package` is excluded on purpose -- see the function's docstring.
