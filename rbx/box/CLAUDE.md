# Box Module (`rbx/box/`)

Core application logic for the rbx CLI. This is the main module containing the build pipeline, solution running, schema definitions, and all major features.

## Schema System (`schema.py`, ~1000 lines)

The central Pydantic model hierarchy defining `problem.rbx.yml`:

### Key Models

- **`Package`** -- Root model. Contains: `name`, `timeLimit`, `memoryLimit`, `solutions`, `testcases`, `checker`, `validator`, `interactor`, `statements`, `vars`, `limitsProfiles`, `scoreType`
- **`Solution`** -- `path`, `outcome` (ExpectedOutcome), `score`, `doubleTL`, `language`
- **`TestcaseGroup`** (extends `TestcaseSubgroup`) -- `name`, `generator`, `generatorScript`, `testcases`, `subgroups`, `validator`, `score`, `deps`
- **`TestcaseSubgroup`** -- `testcases` list, `generator` (GeneratorCall or CodeItem)
- **`Testcase`** -- `inputPath`, `outputPath` (for manual test cases)
- **`GeneratorCall`** -- `name`, `args` (references a generator program)
- **`CodeItem`** -- `path`, `language`, `compilationArgs` (reference to any code file)
- **`LimitsProfile`** -- Per-packager limit overrides with `modifiers` per language, `formula` support
- **`LimitModifiers`** -- `time`, `timeMultiplier`, `memory` per language

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
3. **`_produce_solution_items()`** -- Creates `Deferred[Evaluation]` items per (solution, testcase)
4. **`print_run_report()`** -- Drives deferred execution, displays live results

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
- **`FullRunReporter`** -- Compact verdict marks (checkmarks/crosses) per testcase
- **`LiveRunReporter`** -- Real-time `rich.live.Live` updates
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

## Code Compilation (`code.py`)

Bridge between box-level code items and the grading engine:
- `compile_item()` -- Resolves language, builds compilation command, calls `grading/steps.compile_item()`
- `run_item()` -- Resolves limits, calls `grading/steps.run_item()`
- Language detection from file extension or explicit configuration

## Global State (`global_package.py`)

Singleton factories (via `@functools.cache`) for shared resources:
- `get_global_file_cacher()` -- Shared `FileCacher` instance
- `get_global_sandbox()` -- Shared `StupidSandbox` instance
- `get_global_dependency_cache()` -- Shared `DependencyCache`
- Cache versioning via `CACHE_STEP_VERSION` -- incremented when cache format changes
- `clear_global_cache()` -- Nukes the cache directory (used by `rbx clear`)
