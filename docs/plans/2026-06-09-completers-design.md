# Dynamic shell completers design

- **Issue:** [#575 — Add a few interesting autocompleters](https://github.com/rsalesc/rbx/issues/575)
- **Date:** 2026-06-09
- **Status:** Design approved; implementation pending
- **Builds on:** [fast-completion design](2026-06-09-fast-completion-design.md) (#333 / #573)

## Problem

The fast-completion engine (#573) ships a static spec plus a lazy completer
registry, but only `--language` is wired to a dynamic completer; `checker` and
`problem` are registered but mostly unused. Issue #575 asks for a batch of
high-value dynamic completers across `rbx run`/`irun`/`stress`/`on` and several
cross-cutting flags.

## Constraints (from the existing completion architecture)

These shape every decision below; see
[`rbx/box/completion/CLAUDE.md`](../../rbx/box/completion/CLAUDE.md).

1. **Completers must stay light.** `firewall_test.py` asserts the completion
   path imports none of `rbx.box.cli`, `rbx.box.solutions`, `rbx.box.packaging`,
   `textual`, `mechanize`, `bs4`, `git`, … So a completer may **not** import
   `schema`, `environment`, `remote`, or `contest.*`. Enum-derived value sets
   (outcomes, verification levels, `@`-prefixes) are therefore **hardcoded small
   tables** in `completers.py`, each guarded by a *consistency test* that imports
   the real enum and asserts the table is complete and valid.
2. **Differential parity.** `differential_test.py` holds the fast engine
   byte-equal to real Typer on `(value, type)` pairs across a spec-derived
   corpus. It compares value+type only — **not** `help` — but the fast engine
   *does* surface `help` to users (zsh/fish). Rich descriptions are therefore
   free for plain completers.
3. **Typer callbacks can only emit plain, prefix-filtered items.** Verified in
   `typer.core.compat_autocompletion` (typer 0.21.1): an `autocompletion=`
   callback may return only `str` or `(value, help)` tuples; Typer always builds
   a **plain** `CompletionItem` and prefix-filters by the incomplete. It can
   never emit a `file`/`dir` directive. So a "dynamic candidates + file
   completion" union needs explicit engine/spec/test support — Typer can never
   reproduce it, and the parity test must carve out a documented exemption.
4. **Corpus probes value positions only with `incomplete=''`.** So completers
   need not prefix-filter to pass parity (the shell filters at runtime); this
   matches the existing `language`/`checker`/`problem` completers, which return
   full lists.

## Completers

All read package YAML via the cheap `peek.peek()` (no pydantic) and stay light.

| key | source | candidates (help) |
|---|---|---|
| `solutions` | `problem.rbx.yml` → `solutions[]` | each `path` (help = `outcome`) + `@main`, `@boca/` |
| `outcome` | hardcoded table | `ac`, `wa`, `tle`, `rte`, `mle`, `ole`, `ac/tle`, `tle/rte`, `incorrect`, `any`, … (help = full name) |
| `verification_level` | hardcoded table | `0`–`4` (help = `NONE`/`VALIDATE`/`FAST_SOLUTIONS`/`ALL_SOLUTIONS`/`FULL`) |
| `profile` | glob `.limits/*.yml` | profile basenames |
| `testgroup` | `problem.rbx.yml` → `testcases[].name` | group names |
| `contest_variant` | glob `contest.*.rbx.yml` (+ canonical), up-tree | variant ids |
| `problem` (extend) | `contest.rbx.yml` → `problems[]` | `short_name` **+ `aliases`** |

`stress --finder` and `stress --reference` reuse the `solutions` completer (the
finder grammar is a superset; we complete its solution-expression part).

### Hardcoded tables + consistency tests

`outcome` and `verification_level` cannot import their source enums
(`ExpectedOutcome` in `schema.py`, `VerificationLevel` in `environment.py`) on
the light path. Each is a literal table in `completers.py`. A consistency test
(allowed to import the heavy app) asserts:

- every `outcome` value parses to a valid `ExpectedOutcome`, and every
  `ExpectedOutcome` member is represented by exactly one offered token;
- the `verification_level` tokens are exactly the `VerificationLevel` int values
  with matching names.

This keeps the runtime light while failing loudly if the enums drift.

## File-union mechanism

The chosen approach (over dynamic-only) lets `rbx run`/`irun` solution
positionals and `stress --finder`/`--reference` complete **registered solutions
+ `@`-prefixes + ordinary files** as a single union.

- `annotations._adapt(key, *, file=False)` — when `file=True`, tags the closure
  with `_completer_file='file'`. The Typer-oracle path still returns plain
  values (no directive), as it must.
- `generate._value_spec` reads that tag → spec value becomes
  `{'kind': 'completer', 'completer': key, 'file': 'file'}`.
- `engine._value_items` appends the `FILE` directive after the completer's items
  when `value.get('file')` is set.
- **Variadic arguments.** `solutions` is an `Optional[List[str]]` argument
  (Click `nargs == -1`); real Typer re-offers it on every positional
  (`rbx run a b<tab>`). The static spec gains `variadic: bool` on argument
  params (from `nargs == -1`); the engine clamps the positional index to the
  last argument when it is variadic, so each position re-offers
  solutions + files.
- **Differential exemption.** `differential_test.py` detects a file-union value
  position, strips `file`/`dir` directives from the engine output, asserts the
  remainder equals the Typer oracle, and asserts the directive *is* appended — a
  documented, tested divergence, mirroring the existing command-name divergence.

## Wiring

Then regenerate and commit: `mise run gen-completion-spec` → commit `_spec.py`
(`drift_test.py` enforces it).

| param | sites | adapter |
|---|---|---|
| `solutions` arg | `run`, `irun` | `_adapt('solutions', file=True)` |
| `--outcome` | `run`, `irun` | `_adapt('outcome')` |
| `--testcase/-t` | `irun` | `_adapt('testgroup')` |
| `--fuzz-on` | `stress` | `_adapt('testgroup')` |
| `--finder`, `--reference` | `stress` | `_adapt('solutions', file=True)` |
| `--verification-level` | shared `VerificationParam` (9 sites) | `_adapt('verification_level')` |
| `--profile` | 4 sites | `_adapt('profile')` |
| `-C/--contest` | `cli.py` + `contest/main.py` callbacks | `_adapt('contest_variant')` |
| `on` first arg | `cli.py` + `contest/main.py` | wrap bare `str` → `Argument(autocompletion=_adapt('problem'))` |

The existing `problem` completer is extended to also offer `aliases` (valid
problem references everywhere per the contest schema), which benefits `rbx on`
and every other site already wired to it.

## Tests (TDD)

- `completers_test.py`: tmp package/contest fixtures → assert each completer's
  items (values + help where relevant).
- consistency tests: hardcoded `outcome`/`verification_level` tables ≡ real
  `ExpectedOutcome`/`VerificationLevel`.
- wiring test: parametrized over (command-path, param, expected key) — every
  issue param resolves to its completer in the generated spec.
- engine tests: `file` flag appends `FILE`; variadic positional re-offers the
  completer on repeated positions.
- differential exemption for file-union positions (above).
- extend `firewall_test.py` to probe `rbx run <tab>`, `rbx run --outcome <tab>`,
  `rbx irun -t <tab>`, etc. — proving the new completers import nothing heavy.
- `drift_test.py` passes after regeneration.

## Out of scope (YAGNI)

- `@boca/<run>` cannot enumerate run numbers — we offer only the `@boca/` prefix
  and `@main`.
- No cross-variant problem merging for `rbx on` — canonical `contest.rbx.yml`
  only, matching the existing `complete_problem`.
