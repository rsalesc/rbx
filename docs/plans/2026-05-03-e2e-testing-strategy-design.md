# E2E Testing Strategy — Design

## Problem

`rbx` has no broad, declarative e2e coverage. The existing e2e tests live in
`tests/rbx/box/cli/problem_test.py` (CLI smoke tests against the default preset
and an interactive problem) and `tests/rbx/box/packaging/e2e/test_boca_e2e.py`
(docker-orchestrated BOCA upload). They are written as ad-hoc Python and only
assert exit codes; adding a new e2e case means writing a new Python test by
hand.

We want a way to drop a barebones problem package into a directory tree, write
a small YAML file next to it describing what `rbx` should do with it and what
the expected outcomes are, and have pytest automatically pick it up.

## Goals

- Adding a new e2e test = create a directory + write `e2e.rbx.yml`.
- Expressive enough to assert verdict matrices for `rbx run`, generated tests
  for `rbx build`, statement artifacts for `rbx st b`, and packaging artifacts
  for `rbx pkg <format>`.
- Always opt-in (gated by `@pytest.mark.e2e`); never runs on `mise run test`.
- Hermetic tmpdir isolation per scenario via `shutil.copytree` plus
  session-scoped autouse fixtures (mirrored from `tests/rbx/box/conftest.py`)
  that redirect the global app/cache/setter-config paths.

## Non-goals (v1)

- `rbx stress` assertions — deferred. Needs a `--report` JSON flag added to
  `stress`; design captured at the bottom under "Future work."
- Migrating the docker-based BOCA upload test (`test_boca_e2e.py`). The DSL is
  not a good fit for orchestrating an external service; it stays Python.
- Multi-problem contest packages.

## Layout

A new tree, separate from the existing CLI/packaging e2e tests:

```
tests/e2e/
  __init__.py
  conftest.py            # collection hook + Pydantic schema
  e2e_runner.py          # pytest Item + assertion classes
  testdata/
    simple-ac/
      e2e.rbx.yml
      problem.rbx.yml
      sols/main.cpp
      gens/gen.cpp
      ...
    mixed-solutions/
      e2e.rbx.yml
      ...
    bad-validator/
      e2e.rbx.yml
      ...
```

Pytest collects every `e2e.rbx.yml` automatically; the directory tree itself is
the test suite. Each `e2e.rbx.yml` describes one or more **scenarios**; pytest
reports one node per scenario as `tests/e2e/testdata/<pkg>/e2e.rbx.yml::<scenario>`.

## Execution model

- Each scenario gets a fresh tmpdir copy of its package directory via
  `shutil.copytree` (with an ignore list that drops `.box`, `build`,
  `.limits`, `__pycache__`, `*.pyc`, `rbx.h`, `.local.rbx`, `.cache`,
  `.testdata`). The scenario's CLI invocations run with that tmpdir as
  cwd. Scenarios are independent.
- We deliberately bypass `rbx.box.testing.testing_package.TestingPackage`
  because its `initialize_preset` step writes a
  `.local.rbx/preset.rbx.yml` without a `min_version` field, which the
  `rbx` CLI then rejects on load (see
  `rbx/box/testing/testing_preset.py:14-27`). The runner instead chdirs
  into the copied package and lets `rbx` resolve `problem.rbx.yml` via
  its normal lookup path.
- Global isolation (the user's real `~/.local/share/rbx/`,
  `setter_config.yml`, `pdflatex` binary) is provided by autouse
  session-scoped fixtures in `tests/e2e/conftest.py` that mirror the
  ones already present in `tests/rbx/box/conftest.py`. They are
  re-declared (not inherited) because `tests/e2e/` is a sibling of
  `tests/rbx/`, not a descendant.
- Steps within a scenario share the tmpdir and run in order. The first failing
  step fails the scenario; subsequent steps are skipped.
- All scenarios are marked `@pytest.mark.e2e` so they are excluded from
  `mise run test` and run only via the existing `mise run test-e2e`.
- Commands are invoked with Typer's `CliRunner` against `rbx.box.cli.app`, the
  same approach the current CLI tests use. Command strings are split with
  `shlex.split`.

## Schema

Top-level `e2e.rbx.yml`:

```yaml
scenarios:
  - name: <string, required, unique within file>
    description: <string, optional>
    steps: [<step>]
```

Step:

```yaml
cmd: <string, required>           # e.g. "build", "run", "pkg boca", "st b -l en"
expect_exit: <int, default 0>
expect:                           # all keys optional
  stdout_contains: <string | list[string]>
  stderr_contains: <string | list[string]>
  stdout_matches: <regex>
  files_exist: <list[glob]>       # paths relative to package root (tmpdir)
  files_absent: <list[glob]>
  file_contains:
    <path>: <substring or /regex/>
  zip_contains:
    path: <glob to zip artifact>
    entries: <list[glob within zip]>
  zip_not_contains:
    path: <glob>
    entries: <list[glob]>
  # Command-specific structured matchers (only valid for that cmd):
  solutions: ...                  # only with cmd: run
  tests: ...                      # only with cmd: build
```

The schema is a Pydantic model with `extra="forbid"` so typos surface at
collection time, not run time.

`expect_exit` defaults to `0`. Negative tests opt in by setting it. When
`expect_exit != 0`, structured assertions (`solutions:`, `tests:`) may produce
no data; it is the user's responsibility to write only assertions that make
sense for the expected exit state.

### Structured matcher: `solutions:` (cmd: `run`)

Source of truth: `skeleton.yml` produced by `rbx run`, which already contains
per-(solution, group) outcomes and per-(solution, test) verdicts.

Per solution path, the value is either a bare verdict or a map:

```yaml
solutions:
  # Bare: shorthand for {"*": ac}
  sols/main.cpp: ac

  # Map: '*' baseline + group/test overrides
  sols/wa.cpp:
    "*": wa                         # every group's outcome is WA
    samples: ac                     # group 'samples' outcome is AC (overrides *)
    main_tests/edge_case: ac        # specific test verdict is AC
```

**Verdict vocabulary:** values are parsed as `ExpectedOutcome`
(`rbx/box/schema.py`), reusing the same matching grammar (and aliases:
`ac`/`wa`/`tle`/`incorrect`/`any`/`ac+tle`/etc.) that `problem.rbx.yml`'s
`outcome:` field already accepts. Each `ExpectedOutcome` exposes
`match(outcome: Outcome) -> bool`, which the runner uses for assertions.

**Resolution (per user-written entry):**

1. If the key contains `/` it is interpreted as a **test path**; assert that
   test's verdict matches the `ExpectedOutcome`.
2. Else if the key matches a **group name** in the package; assert that
   group's overall outcome matches.
3. Else if the key is `*`; assert every group's overall outcome matches
   (groups separately overridden by name take precedence).

**Sparse coverage is valid.** Untouched groups and tests are simply not
asserted. The user opts into whatever subset they care about.

**Group vs. test verdicts** (important distinction):
- `<group>: wa` asserts the **group's aggregated outcome** (the same notion
  rbx already computes from `skeleton.yml` and uses for reporting and for
  `expectedOutcomes` in `problem.rbx.yml`). It does **not** assert "every
  test in the group is WA."
- `<group>/<test>: wa` asserts the specific test's verdict.

### Structured matcher: `tests:` (cmd: `build`)

Source: enumerate generated test files in `build/tests/` after the build
completes, plus the validation report (if a structured one is not currently
persisted, the implementation will add one — same pattern as the
`--report`-flag escape hatch we're considering for `stress`).

```yaml
tests:
  count: <int>                    # optional total count
  groups:                         # optional per-group counts
    samples: 3
    main_tests: 9
  all_valid: <bool, default true> # all generated tests passed validation
  exist: [<path>, ...]            # specific paths under build/tests/ that must exist
```

Anything more granular (asserting test file content) is expressed via the
generic `file_contains:` matcher; no need to special-case it here.

## Concrete examples

### Vanilla AC pipeline

```yaml
# tests/e2e/testdata/simple-ac/e2e.rbx.yml
scenarios:
  - name: full-pipeline
    steps:
      - cmd: build
        expect:
          tests:
            count: 5
            all_valid: true

      - cmd: run
        expect:
          solutions:
            sols/main.cpp: ac

      - cmd: st b
        expect:
          files_exist: [build/statements/statement.pdf]

      - cmd: pkg boca
        expect:
          files_exist: ["build/boca/*.zip"]
          zip_contains:
            path: build/boca/*.zip
            entries: [description.xml, "limits/*"]
```

### Mixed verdicts, sparse assertions

```yaml
# tests/e2e/testdata/mixed-solutions/e2e.rbx.yml
scenarios:
  - name: verdict-matrix
    steps:
      - cmd: run
        expect:
          solutions:
            sols/main.cpp: ac
            sols/wa_on_big.cpp:
              "*": ac
              main_tests: wa
              main_tests/edge_case: ac
            sols/tle.cpp:
              "*": tle
              samples: ac
            sols/sometimes_wa.cpp:
              samples/0: ac
              main_tests/tricky: wa
```

### Negative test (broken validator)

```yaml
# tests/e2e/testdata/bad-validator/e2e.rbx.yml
scenarios:
  - name: build-should-fail
    steps:
      - cmd: build
        expect_exit: 1
        expect:
          stderr_contains: "validator"
```

### Multiple scenarios per package

```yaml
# tests/e2e/testdata/full-coverage/e2e.rbx.yml
scenarios:
  - name: build-and-run
    steps:
      - cmd: build
      - cmd: run
        expect:
          solutions:
            sols/main.cpp: ac

  - name: package-boca
    steps:
      - cmd: build
      - cmd: pkg boca
        expect:
          files_exist: ["build/boca/*.zip"]

  - name: package-polygon
    steps:
      - cmd: build
      - cmd: pkg polygon
        expect:
          files_exist: ["build/polygon/*.zip"]
```

Each scenario starts from a fresh tmpdir copy, so `build` is repeated in
scenarios 2 and 3.

## Implementation sketch

### Collection hook

```python
# tests/e2e/conftest.py
def pytest_collect_file(parent, file_path):
    if file_path.name == "e2e.rbx.yml":
        return E2EYamlFile.from_parent(parent, path=file_path)
```

`E2EYamlFile.collect()` parses the YAML through a Pydantic `E2ESpec` model
and yields one `E2EScenarioItem` per scenario. Schema errors fail at
collection (clear pytest error) rather than runtime.

### Scenario item

```python
class E2EScenarioItem(pytest.Item):
    def runtest(self):
        source_dir = self.path.parent
        with tempfile.TemporaryDirectory(prefix='rbx-e2e-') as tmp_root:
            pkg_dir = pathlib.Path(shutil.copytree(
                source_dir, tmp_root, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS),
            ))
            for step in self.scenario.steps:
                run_step(self.path, self.scenario.name, step, pkg_dir)

# `run_step` is a free function so it can be unit-tested without going
# through pytest collection.
def run_step(scenario_path, scenario_name, step, cwd):
    result = CliRunner().invoke(rbx_app, shlex.split(step.cmd))
    assert result.exit_code == step.expect_exit, ...
    for assertion in step.assertions:
        assertion.check(cwd, result)
```

### Assertion classes

Each assertion is a small Pydantic submodel with a `check(pkg, result)`
method. One class per matcher: `StdoutContains`, `StderrContains`,
`StdoutMatches`, `FilesExist`, `FilesAbsent`, `FileContains`, `ZipContains`,
`ZipNotContains`, `SolutionsMatcher`, `TestsMatcher`.

All assertion failures embed: package name, scenario name, step `cmd`,
expected vs. found.

### Marker

`pytest_collection_modifyitems` adds `pytest.mark.e2e` to every collected
`E2EScenarioItem` so `mise run test` keeps ignoring them. No new mise task is
required — `mise run test-e2e` already runs everything tagged `e2e`.

## Migration of existing e2e tests

**Migrate to the new tree:**

- `tests/rbx/box/cli/problem_test.py::test_default_preset_problem` →
  one package + scenario invoking `run`, `unit`, `st b`, `pkg boca`,
  `pkg polygon`. Strengthen the assertions beyond exit code where the
  structured matchers can express something.
- `tests/rbx/box/cli/problem_test.py::test_interactive_problem` →
  same structure for an interactive problem package.
- `tests/rbx/box/packaging/e2e/testdata/simple-problem/` → moves under
  `tests/e2e/testdata/`.

**Leave in Python:**

- `tests/rbx/box/packaging/e2e/test_boca_e2e.py` — docker-compose
  orchestration and HTTP uploads to a real BOCA service; not a fit for the
  YAML DSL. Keep its existing markers.

## Future work

- **`rbx stress` support.** Add a `--report <path>` flag to `rbx stress` that
  emits structured JSON (counterexamples found, seeds, finder verdicts).
  Then add a `stress:` matcher with assertions like
  `found_counterexample: true|false`, `count_at_least: <int>`. Determinism
  via pinned `--seed` in `cmd:`.
- **Multi-language statement assertions.** Trivial extension once the v1
  `files_exist` matcher exists.
- **Contest packages (`contest.rbx.yml`).** Same DSL with a top-level
  contest scenario; deferred until needed.

## Risks

- **Schema drift.** Adding new `expect:` keys is cheap, but renaming or
  changing the resolution algorithm later breaks existing YAML. Mitigation:
  `extra="forbid"` plus this design doc as the schema's source of truth.
- **`skeleton.yml` format dependency.** If `rbx run` ever changes that
  file's shape, every e2e test breaks at once. Mitigation: a single
  `SolutionsMatcher` reads it, isolating the parsing concern.
- **`build` validation report not yet structured.** If `rbx build` does not
  already persist a validation report, the `tests.all_valid` matcher needs
  one added during implementation. The implementation plan should confirm
  this on day one.

## Verdict source (Task 0 spike findings)

This section documents how the `SolutionsMatcher` (Task 7) reads
per-(solution, group, testcase) verdicts off disk. Confirmed by reading
`rbx/box/tasks.py`, `rbx/box/solutions.py`, and `rbx/box/ui/utils/run_ui.py`,
and by running `uv run rbx run` against
`tests/rbx/box/packaging/e2e/testdata/simple-problem` (copied to a tmpdir).

### Directory layout

After `rbx run`, the runs directory at `package.get_problem_runs_dir()` —
which resolves to `<problem-root>/.box/runs/` (see
`rbx/box/package.py:172`) — has this shape:

```
.box/runs/
  skeleton.yml                  # the plan (SolutionReportSkeleton)
  0/                            # solution index 0 (== solutions[0] in skeleton)
    samples/
      000.eval                  # YAML-serialized Evaluation
      000.log                   # same content (TestcaseLog dump)
      000.out / 000.err         # captured stdout / stderr (binary)
    main/
      000.eval
      000.log
      000.out / 000.err
      001.eval
      001.log
      001.out / 001.err
  1/                            # solution index 1
    samples/000.eval ...
    main/000.eval ...
    main/001.eval ...
```

For the `simple-problem` package (2 solutions × 3 testcases across 2 groups)
the spike produced exactly the files above.

### File format and Pydantic model

Each `<idx:03d>.eval` is YAML serialized via `utils.model_to_yaml(eval)` from
`rbx/box/tasks.py:174`. The model is `rbx.grading.steps.Evaluation`:

```python
class Evaluation(BaseModel):
    result: CheckerResult            # outcome (Outcome enum), message,
                                     # no_tle_outcome, sanitizer_warnings
    testcase: TestcaseIO             # index, input, output (paths)
    log: TestcaseLog                 # exitcode, exitstatus, time, wall_time,
                                     # memory, metadata, stdout/stderr/log/eval
                                     # absolute paths
```

`Outcome` values on disk are the lowercased enum serializations declared at
`rbx/grading/steps.py:37-47`:

```python
class Outcome(Enum):
    ACCEPTED = 'accepted'
    WRONG_ANSWER = 'wrong-answer'
    MEMORY_LIMIT_EXCEEDED = 'memory-limit-exceeded'
    TIME_LIMIT_EXCEEDED = 'time-limit-exceeded'
    IDLENESS_LIMIT_EXCEEDED = 'idleness-limit-exceeded'
    RUNTIME_ERROR = 'runtime-error'
    OUTPUT_LIMIT_EXCEEDED = 'output-limit-exceeded'
    JUDGE_FAILED = 'judge-failed'
    INTERNAL_ERROR = 'internal-error'
    COMPILATION_ERROR = 'compilation-error'
```

These ten string aliases are the exact tokens the matcher's verdict-comparison
code (Task 7) will compare against. Each YAML file is preceded by a
`# yaml-language-server` comment line, which is fine for
`utils.model_from_yaml`.

The sibling `<idx>.log` file is intentionally identical to `<idx>.eval` —
both come from the same `model_to_yaml(eval)` call (lines 173-174). The
matcher reads `.eval` (canonical for run_ui too, see below).

### Lookup procedure (solution_path, group, index) → file

The skeleton at `.box/runs/skeleton.yml` is a `SolutionReportSkeleton` whose
`solutions: List[SolutionSkeleton]` carries the per-solution `runs_dir`
(absolute path, e.g. `<root>/.box/runs/0`). `SolutionSkeleton` exposes:

```python
def get_entry_prefix(self, entry: TestcaseEntry) -> Path:
    return self.runs_dir / entry.group / f'{entry.index:03d}'
```

so the eval path is `skeleton.yml`-driven, not constructed from raw input.
The TUI helper `rbx/box/ui/utils/run_ui.py:34-39` (already production code)
is the exact pattern the matcher should reuse:

```python
def get_solution_eval(solution, entry):
    path = solution.get_entry_prefix(entry).with_suffix('.eval')
    if not path.is_file():
        return None
    return utils.model_from_yaml(Evaluation, path.read_text())
```

The matcher's lookup, given a YAML row addressing `solutions/foo.cpp` on
group `main` index `1`:

1. Load `.box/runs/skeleton.yml` once per scenario into
   `SolutionReportSkeleton` via `utils.model_from_yaml`. When walking
   `.box/runs/` for skeletons, ignore the `.box/runs/.irun/` subtree —
   that is the interactive-debug scratch space (`rbx irun`) and is not
   part of the matcher's input.
2. Find the `SolutionSkeleton` whose `path` equals `solutions/foo.cpp`
   (skeleton stores it as a relative `pathlib.Path`, identical to the
   `Solution.path` declared in `problem.rbx.yml`). Do **not** construct
   `runs_dir` yourself: always read it back from
   `SolutionReportSkeleton.solutions[i].runs_dir`. The field is absolute
   (see `SolutionSkeleton.runs_dir_href` at `rbx/box/solutions.py:112-114`,
   which calls `relative_to(package.find_problem())` on it), so matching
   solutions by `path` equality across different CWDs would otherwise bite.
3. Build a `TestcaseEntry(group="main", index=1)` and resolve the eval
   filename via the testcase's `inputPath.stem` (looked up from the
   matching `GenerationTestcaseEntry` in `skeleton.entries`). On packages
   with subgroups the on-disk filename is e.g. `1-gen-000.eval`, **not**
   `f'{idx:03d}.eval'`. The `SolutionSkeleton.get_entry_prefix` helper at
   `rbx/box/solutions.py:109-110` returns the latter form and is therefore
   only correct for packages without subgroups; the matcher recovers the
   real stem from `entry.metadata.copied_to.inputPath.stem`. (Production
   code in `rbx/box/ui/utils/run_ui.py` has the same blind spot — fixing
   it is out of scope for Task 7 and is filed as a follow-up.)
4. Parse with `utils.model_from_yaml(Evaluation, …)` and read
   `eval.result.outcome` (an `Outcome` enum value).

For "all testcases in a group" assertions, iterate the testcase indices
exposed by `skeleton.find_group_skeleton(group).testcases` (length gives
the index range; per-index files are `000`, `001`, …). Note
`find_group_skeleton` only resolves top-level groups; subgroups
(`TestcaseGroup.subgroups`) are out of scope for v1 and could later be
addressed via `<group>/<subgroup>` syntax in the DSL.

### Soft-TLE preservation

Soft-TLE conversion happens in `rbx/box/checkers.py:_convert_tle` BEFORE the
`Evaluation` is serialized. When CPU time exceeds the configured `timeLimit`
but the checker would otherwise have returned AC/WA/RTE, the function sets
`result.outcome = Outcome.TIME_LIMIT_EXCEEDED` and stores the original
verdict in `result.no_tle_outcome` (line 203-204). Both fields land in the
on-disk YAML. The matcher therefore sees:

- `result.outcome` — the user-facing verdict (already TLE-promoted).
- `result.no_tle_outcome` — the un-promoted verdict, available if a future
  e2e DSL ever needs to assert "would have been WA without the TL."

Caveat observed during the spike: the slow solution in `simple-problem`
sleeps via wall-clock, so its CPU time stays at ~8 ms while wall_time hits
~3 s. With sandbox `wallTimeLimit = 2 × timeLimit = 4 s`, neither the CPU
soft-TLE check (`run_log.time * 1000 >= timelimit`) nor the wall-time kill
fires, so its `.eval` records `outcome: accepted` despite the run report
rendering `>2000 ms ⧖`. That rendering is a presentation-layer concern in
`solutions.get_capped_evals_formatted_time` (and a sibling `is_slow()`
short-circuit in the score column). It is **not** persisted, and the
canonical verdict for the matcher is the on-disk `Outcome` enum — which
matches what `ExpectedOutcome.match()` already operates on inside
`run_solutions`. This means our DSL will agree with `ExpectedOutcome` and
may diverge from the cosmetic "⧖" display in pathological CPU-vs-wall
cases. That is acceptable; document it in the matcher's docstring (Task 7).

### Persistence status: yes, no work needed

`Evaluation` IS persisted today, on every `rbx run` (and every `rbx irun`,
which uses `.box/runs/.irun/<i>/...` instead — same file shape, see
`solutions.py:801-819`). No `--report` flag, no new code path required.
The matcher's only dependency on production code is reading two existing
formats: `SolutionReportSkeleton` from `skeleton.yml` and `Evaluation` from
`<runs_dir>/<group>/<idx:03d>.eval`. Both already have stable Pydantic
schemas (with `# yaml-language-server: $schema=…` headers exported to
`https://rsalesc.github.io/rbx/schemas/`), so drift is detectable.

The "TBD: implement during Task 7" branch from the original task brief
(adding a `--report` flag or new persistence path) is therefore **not
needed** and Task 7 collapses to: load skeleton, walk YAML expectations,
read each `.eval`, compare `result.outcome` against the expected
`Outcome` (or `ExpectedOutcome`-style alias). One implementation
follow-up worth recording: the matcher should accept solution paths
exactly as written in `problem.rbx.yml` (e.g. `solutions/main.cpp`), and
should fail loudly with a clear message when:

- the targeted `.eval` is missing — almost always means the scenario
  forgot to actually run `rbx run` before the matcher fired;
- a group named in the e2e YAML is not present in the skeleton —
  `skeleton.find_group_skeleton(...)` returns `Optional[GroupSkeleton]`,
  so the matcher must check for `None` and surface a clear "unknown
  group `X`" error rather than letting an `AttributeError` bubble up.
