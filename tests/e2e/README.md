# E2E Tests

A YAML-driven end-to-end test framework for the `rbx` CLI. Each subdirectory
of `tests/e2e/testdata/` is a self-contained `rbx` package (`problem.rbx.yml`,
`sols/`, `gens/`, ...) plus an `e2e.rbx.yml` describing one or more scenarios
to run against it. Pytest auto-collects every scenario as a test, tags them
with the `e2e` marker, and runs each one in an isolated tmpdir copy of the
package so source files are never mutated.

For design rationale and migration history, see
[`docs/plans/2026-05-03-e2e-testing-strategy-design.md`](../../docs/plans/2026-05-03-e2e-testing-strategy-design.md).

## Running

```bash
# All e2e scenarios.
mise run test-e2e

# A single package.
uv run pytest tests/e2e/testdata/<package>/ -v

# A single scenario.
uv run pytest 'tests/e2e/testdata/<pkg>/e2e.rbx.yml::<scenario>' -v
```

`mise run test` runs everything *except* e2e (it filters with
`-m 'not (e2e or slow or docker)'`). The default `pytest` invocation, with
no marker filter, will pick up e2e tests like any other test.

## Adding a new package

1. Create `tests/e2e/testdata/<name>/` and lay it out exactly like a real
   `rbx` problem package: at minimum a `problem.rbx.yml`, plus whatever
   `sols/`, `gens/`, `checker/`, `validator/`, etc. the scenario needs.
2. Verify the package builds standalone:
   ```bash
   cd tests/e2e/testdata/<name>
   uv run rbx build
   ```
   Then remove the generated artefacts. `tests/e2e/testdata/.gitignore`
   already covers `*/.box/`, `*/build/`, `*/rbx.h`, and friends, so a
   `git status` after building should be clean.
3. Author `tests/e2e/testdata/<name>/e2e.rbx.yml` with at least one
   scenario (see [Schema reference](#schema-reference) and
   [Examples](#examples)).
4. Run it:
   ```bash
   uv run pytest tests/e2e/testdata/<name>/ -v
   ```

The runner copies the package to a fresh tmpdir per scenario, sets cwd
there, and invokes `rbx` via `typer.testing.CliRunner` (so don't include
the `rbx` prefix in `cmd`). On scenario failure the source tree is
untouched.

## Schema reference

All fields below come from the Pydantic models in
[`tests/e2e/spec.py`](spec.py). Unknown fields raise at parse time
(`extra='forbid'`).

### `scenarios`

Top-level list. Names must be unique within a file.

```yaml
scenarios:
  - name: smoke           # required, used as the pytest test id
    description: ...      # optional, free-form
    markers: [slow]       # optional, see Marker passthrough
    steps: [...]          # one or more Step entries
```

### `Step`

```yaml
- cmd: build              # required, parsed via shlex.split, no `rbx` prefix
  expect_exit: 0          # optional, defaults to 0
  expect:                 # optional, all sub-fields below are optional
    ...
```

### `Expect`

#### `stdout_contains` / `stderr_contains`

String or list of strings. Each must appear as a literal substring.

```yaml
expect:
  stdout_contains: "Build succeeded"
  stderr_contains:
    - "warning: foo"
    - "warning: bar"
```

#### `stdout_matches`

Single regex, evaluated with Python `re.search`.

```yaml
expect:
  stdout_matches: "build/tests/main/\\d+-gen-\\d+\\.in"
```

#### `files_exist` / `files_absent`

List of glob patterns relative to the package root. Magic chars: `*`,
`?`, and matched `[...]` char-classes. A literal `[` must be escaped as
`[[]`. A pattern with no magic chars is a literal path test.

```yaml
expect:
  files_exist:
    - "build/tests/main/*.in"
    - "build/manifest.yml"
  files_absent:
    - "build/.scratch"
```

#### `file_contains`

Map of `path -> matcher`. The matcher is a literal substring unless it
is wrapped in slashes and longer than two characters, in which case the
inside is treated as a regex (Python `re.search`). Beware: a literal
substring that itself starts and ends with `/` (e.g. `/usr/bin/`) is
ambiguous and will be parsed as a regex. Pad the value if you need a
literal slash-bounded substring.

```yaml
expect:
  file_contains:
    build/manifest.yml: "checker: checker.cpp"
    build/log.txt: "/error\\s+code=\\d+/"
```

#### `zip_contains` / `zip_not_contains`

```yaml
expect:
  zip_contains:
    path: build/*.zip       # glob to locate the zip in the package root
    entries:
      - description/problem.info
      - "input/*"
      - "limits/*"
```

`entries` are `fnmatch` patterns matched against the zip's namelist.
Note that `fnmatch` does **not** treat `/` specially: `*` matches across
slashes, so `input/*` matches `input/foo/bar` too. `zip_not_contains`
uses the same shape and asserts none of the patterns match. A missing
zip in either matcher is an error, not a silent pass.

#### `solutions`

Per-solution verdict map. Reads `.box/runs/skeleton.yml` and the
sibling `.eval` files, so the scenario must run `rbx run` (or
equivalent) before the assertion fires.

Verdicts use the `ExpectedOutcome` aliases — `ac`, `wa`, `tle`,
`incorrect`, `ac+tle`, etc.

The shorthand `solutions[path]: <verdict>` is sugar for
`{"*": <verdict>}`. The map form supports a `*` baseline plus
group-name overrides plus per-test overrides keyed `<group>/<test_idx>`:

```yaml
expect:
  solutions:
    sols/main.cpp: ac                  # shorthand, `*: ac`
    sols/wa.cpp:
      "*": wa                          # baseline for unmentioned groups
      samples: wa                      # group-level override
      main/0: wa                       # per-test override (group/index)
    sols/tle.cpp: tle
```

Coverage is sparse: groups (and tests) you don't mention — and aren't
covered by `*` — are not asserted. A group that has a per-test override
does **not** also receive an implicit group-level `*` assertion.

#### `tests`

Assertions about `build/tests/` after `rbx build`. Counts come from
`*.in` files; `*.out`/`*.eval` siblings are ignored. Group names are the
immediate subdirs of `build/tests/`.

```yaml
expect:
  tests:
    count: 6                # total *.in
    groups:
      samples: 2
      main: 4
    exist:
      - main/1-gen-000.in
```

`all_valid` is reserved and currently raises `AssertionError` when set
to `true`: `rbx build` does not persist a per-testcase validation report
on disk. Track [#418](https://github.com/rsalesc/robox.io/issues/418).

### `markers`

Per-scenario list of pytest markers, applied on top of the implicit
`e2e` marker. Whitelist: `slow`, `docker`. Anything else raises at
parse time.

```yaml
scenarios:
  - name: heavy
    markers: [slow]
    steps: [...]
```

## Examples

Simplest possible — copied from
[`simple-ac/e2e.rbx.yml`](testdata/simple-ac/e2e.rbx.yml):

```yaml
scenarios:
  - name: smoke
    steps:
      - cmd: build
        expect:
          files_exist:
            - "build/tests/main/*.in"
          tests:
            count: 3
            groups:
              main: 3
            exist:
              - main/1-gen-000.in
              - main/1-gen-001.in
              - main/1-gen-002.in
```

Full verdict-matrix syntax — from
[`mixed-solutions/e2e.rbx.yml`](testdata/mixed-solutions/e2e.rbx.yml):

```yaml
scenarios:
  - name: verdict-matrix
    steps:
      - cmd: run
        expect:
          solutions:
            sols/main.cpp: ac
            sols/wa.cpp:
              "*": wa
              samples: wa
              main/0: wa
            sols/tle.cpp: tle
```

Packaging assertion — from
[`pkg-boca/e2e.rbx.yml`](testdata/pkg-boca/e2e.rbx.yml):

```yaml
scenarios:
  - name: package-boca
    steps:
      - cmd: build
      - cmd: time -s inherit -p boca
      - cmd: pkg boca
        expect:
          files_exist:
            - "build/*.zip"
          zip_contains:
            path: build/*.zip
            entries:
              - description/problem.info
              - "input/*"
              - "output/*"
              - "limits/*"
```

## Debugging a failing scenario

The pytest output wraps every failure with the package + scenario + step
prefix and the full captured stdout/stderr:

```
[<package>::<scenario>] step '<cmd>': <inner-message>
stdout:
  ...
stderr:
  ...
```

For `solutions:` failures, the matcher names the (solution, group/test,
expected, actual) cell that disagreed:

```
sols/wa.cpp::main/0: expected wa, got AC (3)
```

The runner copies the package to a tmpdir per scenario; the source tree
is never modified. To keep the tmpdirs around for inspection, point
pytest at a stable `--basetemp`:

```bash
uv run pytest tests/e2e/testdata/<pkg>/ -v --basetemp=/tmp/e2e-debug
```

Each scenario then lives under
`/tmp/e2e-debug/.../rbx-e2e-<...>/` and its `.box/`, `build/`, etc. can
be inspected directly.

## Marker passthrough

Per-scenario `markers:` entries layer on top of the implicit `e2e`
marker:

```yaml
scenarios:
  - name: long-build
    markers: [slow]
    steps: [...]
  - name: needs-daemon
    markers: [docker]
    steps: [...]
```

Filter the usual way:

```bash
uv run pytest tests/e2e/ -m 'e2e and not slow'
uv run pytest tests/e2e/ -m 'docker'
```

The marker whitelist is `{slow, docker}`. Adding a new entry to the
whitelist requires editing `_ALLOWED_MARKERS` in
[`spec.py`](spec.py) and registering the marker in `pyproject.toml`.

## Out of scope

The following are intentionally not yet supported. See the
[design doc](../../docs/plans/2026-05-03-e2e-testing-strategy-design.md)
for rationale and the GitHub issues for tracking:

- `rbx stress` matchers — deferred.
- `expect.tests.all_valid` — no on-disk validation report yet
  ([#418](https://github.com/rsalesc/robox.io/issues/418)).
- Subgroup verdict matchers — only top-level groups today
  ([#418](https://github.com/rsalesc/robox.io/issues/418)).
- Multi-language statement assertions
  ([#419](https://github.com/rsalesc/robox.io/issues/419)).
- Contest-level packages (`contest.rbx.yml`).

When one of these unblocks, extend `Expect` in
[`spec.py`](spec.py) and add a corresponding `check_*` in
[`assertions.py`](assertions.py).
