# Completion Module (`rbx/box/completion/`)

Fast static shell-completion engine for the `rbx` CLI.

## Why this exists (#333)

Pressing `<tab>` used to take ~545ms: the entry point imported the whole CLI
(`rbx.box.cli` → grading, sandbox, schema, `textual`, `mechanize`/`bs4`,
GitPython, …) before Typer computed a single completion. Completion needs none
of that — only the command-tree structure plus one small dynamic completer for
the param under the cursor. This module serves completions from a precomputed
static spec **before** any heavy import, dropping `<tab>` to ~86ms (~9x).

## Architecture

Typer stays the single source of truth for execution. A generator introspects
the live Click command tree and serializes a static spec (committed to
`_spec.py`, shipped in the wheel, drift-gated). At `<tab>` time the engine
resolves completions against that spec without importing the app, reusing
Click's per-shell output formatters so bash/zsh/fish output stays byte-correct.
There is no slow path: when a position has no rule (path arg, uncovered case, or
any error) the engine emits a `file`/`dir` directive that hands control to the
shell's own default completion.

Data flow:

```
shell <tab>
  └─ rbx binary → main.py:app()
        └─ entry.handle_completion()         # reads _RBX_COMPLETE; returns False if not completing
              └─ engine.complete_to_string(shell, _spec.SPEC)
                    └─ engine.resolve(SPEC, args, incomplete)   # walks the static tree, no heavy import
                          └─ dynamic? registry.load_completer(key)(ctx, incomplete)   # lazy-import ONE completer
              └─ Click ShellComplete.format_completion()        # correct per-shell output
                    └─ shell
```

Spec generation (dev/CI only, imports the heavy app on purpose):
`generate.build_spec()` walks the Click tree → `serialize.write_spec()` renders
`_spec.py`. `mise run gen-completion-spec` regenerates it; `drift_test.py` fails
CI if the committed module is stale.

## Files

- `entry.py` — `handle_completion()`: the only thing `main.py` calls before the
  CLI. Reads `_RBX_COMPLETE` (`<instruction>_<shell>`), serves `complete`/`source`
  from the static spec, returns True. Returns False when not completing. Never
  raises; on any error writes `'file,\n'` (shell-default fallback).
- `engine.py` — `resolve(spec, args, incomplete)` (pure static resolver; swallows
  exceptions → `file` directive), `complete_to_string`, `source_to_string`. Binds
  Click's **native** ShellComplete classes by name.
- `registry.py` — `register_completer` / `register_completer_path` / `register_all`
  / `load_completer` / `key_for_function`, and the `CompletionContext` dataclass.
- `completers.py` — the dynamic completers (`language`, `checker`, `problem`,
  `solutions`, `outcome`, `verification_level`, `profile`, `testgroup`,
  `contest_variant`). Must stay light: heavy imports are local to each function.
- `peek.py` — `peek(path)`: cheap, tolerant, mtime-cached `yaml.safe_load` of
  package YAML (no pydantic, no full load).
- `context.py` — `find_package_root()`: cheap upward walk for
  `problem.rbx.yml`/`contest.rbx.yml`.
- `generate.py` — introspects the live Typer/Click tree → static spec dict.
- `serialize.py` — renders `_spec.py` (`SPEC` + `COMPLETERS`); `__main__` rewrites it.
- `_spec.py` — GENERATED, committed. `SPEC` (the tree) + `COMPLETERS` (key →
  dotted import path).

## How to add a new completer (the hook)

1. Write a light function in `completers.py`. Do heavy imports locally; use
   `peek.peek()` for package YAML:

   ```python
   @register_completer('solutions')
   def complete_solutions(ctx: CompletionContext, incomplete: str) -> list[CompletionItem]:
       if ctx.package_root is None:
           return []
       data = peek.peek(ctx.package_root / 'problem.rbx.yml')
       return [CompletionItem(s['path']) for s in data.get('solutions', [])]
   ```

2. The `@register_completer('solutions')` decorator records the key and a
   reverse `fn → key` map for the generator.

3. Attach it to a Typer param via the registry adapter in `rbx/annotations.py`:
   `autocompletion=rbx.annotations._adapt('solutions')` (or reuse one of the
   `Annotated` types there, e.g. `Language`, `Problem`, `Checker`).

4. Regenerate and commit: `mise run gen-completion-spec` then commit `_spec.py`.
   `drift_test.py` enforces this. Generation **fails loudly** if a param has an
   `autocompletion` callback that maps to no registry key, so nothing slips the net.

## Guarantees (tests)

- `differential_test.py` — the engine's completions equal real Typer's across a
  spec-derived corpus (499 cases). Typer is the correctness oracle.
- `firewall_test.py` — subprocess probe asserts the completion path imports none
  of a heavy denylist (`textual`, `mechanize`, `bs4`, `git`, `rbx.box.cli`, …).
- `drift_test.py` — regenerated spec == committed `_spec.py`.
- `robustness_test.py` — every failure mode (unknown shell, malformed args,
  forced engine failure) returns truthfully and degrades to the `file` directive;
  never crashes the shell.
- Benchmark: `mise run bench-completion` (cold-subprocess timing, baseline
  alongside; informational, not a hard gate).

## Gotchas

- The engine reuses Click's **native** ShellComplete classes (bound by name),
  **not** Typer's enhanced classes. The real CLI dispatches completion before
  `completion_init()` runs, so it emits Click-native output; calling
  `completion_init()` would change the output format and break byte-parity. (It
  also avoids global-registry pollution when tests import the heavy app.)
- Command names are stored **raw**, comma-joined (`'package, pkg'`); the engine
  splits on `', '` both for descent AND for completion. **Alias dedup:** both
  subcommand-name completion (`_command_name_items`) and option-name completion
  emit ONE candidate per command/option, via `_first_match` — the first name (in
  declaration order) that matches the incomplete. A broad prefix (`''`, `-`,
  `--`) yields the canonical full name (`package`, `--verification-level`); a
  prefix typed toward a specific alias or `--no-` form completes that exact
  spelling (`pkg`, `-v`, `--no-check`). This keeps `rbx <tab>` / `rbx run -<tab>`
  from listing every alias on its own line — important because zsh alias
  *grouping* (`_describe`) renders badly under some user configs (fzf TAB
  wrapper, oh-my-zsh `matcher-list`), so dedup is done at the application level
  instead of relying on the shell. This is a deliberate divergence from Typer
  (which offers every alias / the raw joined string); `differential_test.py`
  asserts each offered name is a REAL Typer name and that we show exactly one per
  command/option, keeping strict Typer-parity only for VALUES.
- Children are kept in **registration order** (not sorted): for ambiguous aliases
  (`t` registered by both `time, t` and `testcases, tc, t`), Click's `AliasGroup`
  resolves to the first match, so the engine must descend in the same order.
- Hidden commands (e.g. `diff`, `serve`) and the synthetic `--help` flag are
  handled in `generate.py`: hidden commands are skipped; Click's auto `--help`
  (not in `cmd.params`) is added explicitly; boolean `secondary_opts` (`--no-*`)
  are included.
- Wired completers (issue #575): `language` (`--language`), `solutions`
  (`run`/`irun` positional, `stress --finder`/`--reference`), `outcome`
  (`run`/`irun --outcome`), `testgroup` (`irun --testcase`, `stress --fuzz-on`),
  `verification_level` (the shared `VerificationParam`, i.e. every `-v`),
  `profile` (global `--profile`, `time --profile`, statement builds),
  `contest_variant` (`-C/--contest`), `problem` (`on` positional). `checker` is
  registered but not currently attached to a live CLI param, so it is absent from
  the committed `COMPLETERS` until something wires it. Wire more via the recipe.
- **File-union** lets a value position offer dynamic candidates AND hand off to
  the shell's default file completion. Tag the callback with
  `annotations._adapt(key, file=True)`; the generator records a `'file'` key on
  the value spec, the engine appends a `FILE` directive after the dynamic items
  (`_value_items`), and a **variadic** last argument (`nargs == -1`, recorded as
  `'variadic': True`) keeps re-offering its completer past its position
  (`resolve`). `differential_test.py` can't compare these against Typer (its
  callback contract can't emit a file directive), so `_cursor_value` **exempts**
  file-union positions: it asserts the dynamic part matches Typer exactly AND that
  exactly one shell directive is appended.
- `outcome` and `verification_level` are **hardcoded tables** in `completers.py`
  (`_OUTCOME_TABLE`, `_VERIFICATION_TABLE`) to keep the completer light (no enum
  import). `enum_consistency_test.py` (allowed to import the heavy app) pins each
  table to its source enum (`ExpectedOutcome` / `VerificationLevel`) — exactly one
  token per member — so a new enum member fails CI until the table is updated.
