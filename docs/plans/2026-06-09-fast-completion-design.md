# Fast shell completion design

- **Issue:** [#333 — `<tab>` autocomplete is slow in linux](https://github.com/rsalesc/rbx/issues/333)
- **Date:** 2026-06-09
- **Status:** Design approved; implementation pending

## Problem

Shell completion takes ~1s on Linux (~741ms measured locally). Every `<tab>`
runs the `rbx` binary, and `main.py:app()` → `run_app_cli()` →
`import rbx.box.cli`, which eagerly imports the **entire application surface**
before Typer computes a single completion.

### Measured baseline

Cold subprocess imports, best-of-3, on the dev machine:

| What | Cost |
|---|---|
| `python -c pass` (interpreter) | 16ms |
| `import typer` | 39ms |
| `import rbx.box.main` (entry, lazy) | 165ms |
| `import rbx.box.cli` (**full CLI — the completion path today**) | **741ms** |

Where the 741ms goes (`-X importtime`, by cumulative cost):

| Cluster | Cost | Drags in |
|---|---|---|
| `compile` / `code` | ~295ms | grading steps, sandbox, schema |
| `download` / `remote` | ~294 / 177ms | `mechanize`, `bs4`, `lxml`, `html5lib`, `dateparser`, BOCA scraper (96ms) |
| `ui.*` → `textual.app` | ~61ms | the whole TUI framework |
| `presets`, `contest`, `statements`, `package`, `tooling` | ~100ms each | pydantic schema trees, jinja |
| `git` (GitPython), `iso639`, `questionary`/`prompt_toolkit` | ~120ms | misc |

Completion needs **none** of this — only the command tree structure plus, for
the one parameter under the cursor, a small dynamic completer
(language / problem / checker). Two things force full price: `cli.py` imports
everything at module load, and `add_typer(...)` forces eager import of every
sub-command module.

### How completion is triggered (verified)

Click 8.3.1 / Typer 0.21.1. The installed shell script sets
`_RBX_COMPLETE=complete_<shell>` plus `_TYPER_COMPLETE_ARGS`, then
`ShellComplete.complete()` does three things:

1. `get_completion_args()` — parse input from env (cheap).
2. `get_completions(args, incomplete)` — **the resolution; this is the ~741ms.**
3. `format_completion()` per item — cheap, per-shell output protocol.

Click's completion descends the tree via `Group.get_command(name)` with
`resilient_parsing=True` and, per the Click source, "doesn't trigger input
prompts or callbacks." **The command function never runs during completion —
only the tree is walked.**

## Goals

1. Make completion fast (target: `rbx <tab>` ≈ 40–60ms vs 741ms).
2. Provide clean, well-built hooks for adding new autocomplete features.
3. Guarantee the fix can't silently regress (benchmarks + an import firewall in CI).

## Approach (decided)

A **precomputed static completion engine**, generated from Typer:

- Typer stays the single source of truth for execution.
- A generator introspects the live Click tree and serializes a **static spec**,
  committed to the repo and shipped inside the wheel. A CI drift test regenerates
  and diffs it.
- At `<tab>` time we intercept **before any heavy import** and run our own
  resolver over the static spec.
- We **reinvent only the resolution** (the slow part). We reuse Click's
  per-shell **output formatters** and env-parsing, so bash/zsh/fish/pwsh output
  stays correct for free.
- We **never** fall back to the live Typer completion at runtime. When we have no
  completion for a position (path argument, uncovered case, or engine error) we
  emit a `file`/`dir` directive that hands control to the **shell's own default
  completion**. There is no slow path, ever.

### Why this is fast

The whole tree is precomputed, so resolution imports nothing. The only possible
heavy import is the single dynamic completer under the cursor, loaded lazily.
`rbx <tab>` never imports `rbx.box.cli` at all.

### Why this is correct

Typer remains the source of truth (spec generated from it, drift-gated). Click
produces the actual shell output. A **differential test** asserts our engine's
completions equal real Typer's across a large corpus of command lines. Because
the spec ships inside the same wheel as the binary, it can never be stale at
runtime — staleness is a dev-only concern the drift test catches.

## Architecture

```
shell <tab>
  └─ rbx binary  →  main.py:app()
        │
        ├─ is _RBX_COMPLETE set?  ──no──→ normal pre-flight + run_app_cli()  (unchanged)
        │
        yes
        ↓   (skip symlink check, asyncio handlers, nest_asyncio entirely)
   completion/entry.py
        ├─ parse _RBX_COMPLETE → instruction, shell
        ├─ instruction == "source"? ──→ render script from template (no app import)
        ↓   instruction == "complete"
   FastComplete(get_completion_class(shell))     # reuse Click's bash/zsh/fish/pwsh class
        ├─ get_completion_args()        ← reused from Click (reads _TYPER_COMPLETE_ARGS)
        ├─ get_completions(args, inc)   ← OURS: static-spec resolver  (only reinvented part)
        │       ├─ walk SPEC tree along args  (no imports — whole tree precomputed)
        │       ├─ decide cursor target: subcommand names / option names / choices / dynamic
        │       └─ dynamic? lazy-import ONE completer via registry (+ cheap package peek)
        ├─ format_completion() per item ← reused from Click (correct per-shell output)
        └─ on path arg / uncovered / exception → CompletionItem(type="file") → shell default
```

New package `rbx/box/completion/`:

| Component | Responsibility |
|---|---|
| `entry.py` | Fast-path detection + dispatch + shell-default fallback. The only thing `main.py` calls. |
| `spec.py` + committed `_spec.py` | The precomputed tree: commands, aliases, help, params, types/choices, completer keys. |
| `engine.py` | `FastComplete` + the static resolver (`get_completions` override). |
| `registry.py` + `completers.py` | Extensibility hooks: `@register_completer`, `CompletionContext`, lazy dynamic completers, cheap package peek + caching. |
| `generate.py` | Introspects the real Typer app → serializes the spec. Run by a `mise` task; drift-tested. |

## The static spec

**Format:** a committed Python module `_spec.py` holding one literal —
`SPEC = {...}` — loaded by `import` (compiled to `.pyc`, near-zero parse cost,
no file-IO). Kept minimal:

```python
Command = {
  'name': 'package',
  'aliases': ['pkg'],            # from AliasGroup comma-splitting
  'help': 'Build problem packages (sub-command).',
  'panel': 'Deploying',          # rich_help_panel, for grouped name completion
  'is_group': True,
  'children': { 'build': Command, ... },   # groups only — names+help inline, no import
  'params': [ Param, ... ],      # leaf commands
}
Param = {
  'kind': 'option' | 'argument',
  'names': ['--language', '--lang', '-l'],   # [] for positional args
  'takes_value': True,
  'multiple': False,
  'help': 'Language to use.',
  'value': {
     'kind': 'choice' | 'completer' | 'path' | 'none',
     'choices': ['cpp', 'py', ...],          # for enums/Literal (static, inline)
     'completer': 'language',                # registry key → lazy import
     'path': 'file' | 'dir' | None,
  },
}
```

### Generation (`generate.py`, dev/CI only)

Imports the real Typer `app`, converts to its Click command, walks recursively:

- Names/aliases from `AliasGroup` splitting; help/panel from the Click objects.
- Enum/`Literal` option types → `choices` inlined.
- A param with `autocompletion=<fn>` → look the function up in the registry's
  reverse map (by identity) to record its stable `completer` key. **If an
  `autocompletion` function isn't registered, generation fails loudly** — this
  forces every completer through the hook interface.
- Path-typed params (`click.Path`/`click.File`) → `path: 'file'|'dir'`.

### Drift gate (pytest)

Regenerate in-memory, assert equality with committed `_spec.py`. Fails CI if a
command changes without running `mise run gen-completion-spec`.

## The resolver (only reinvented logic)

`resolve(SPEC, args, incomplete) -> list[CompletionItem]`, mirroring Click's
semantics over the static tree.

**Walk** `args` from root: a `-`token consumes an option (skips its value token,
or splits `--opt=val`), recording preceding values like `--problem` for context.
A bare token descends into a matching child (resolving aliases like
`pkg`→`package`) or fills the next positional. After the walk we know the current
`node`, the unfilled positional index, and preceding option values.

**Decide the target from `incomplete`:**

| Situation | Emit |
|---|---|
| `incomplete` starts with `-` | option names of `node` (filtered), `plain` + help |
| value position of a `choice` param | filtered `choices`, `plain` |
| value position of a `completer` param | lazy-import registry completer → its items |
| value position of a `path` param, OR no rule, OR exception | `CompletionItem(type='file'/'dir')` → shell default |
| group, command position | child names (filtered), `plain` + help/panel |

**Engine wiring** keeps Click for everything except this one method:

```python
base = get_completion_class(shell)            # Click's Bash/Zsh/Fish/Pwsh
class _Fast(base):
    def get_completions(self, args, incomplete):
        return resolve(SPEC, args, incomplete)   # ← ours; the rest is Click's
comp = _Fast(click.Command('rbx'), {}, 'rbx', '_RBX_COMPLETE')  # dummy cli, never walked
print(comp.complete())                          # reuses get_completion_args + format_completion
```

We do **not** hand-enumerate every Click edge case (`--`, `--opt=`, short
clusters, aliases, empty incomplete). The stance: mirror Click's behavior and
let the **differential corpus** be the correctness oracle.

### Shell-default fallback mechanism (verified)

Click's installed scripts already key off `CompletionItem.type`:

- **Bash:** `type=file` → `compopt -o default` (native filename completion);
  `type=dir` → `compopt -o dirnames`.
- **Zsh:** `type=file` → `_path_files -f`; `type=dir` → `_path_files -/`.
- **Fish:** same `type` channel; fish file-completes by default.

So "tell the shell to use its own completion" = emit
`CompletionItem(value="", type="file")`. One constraint: in bash the `file`
branch does `COMPREPLY=()` (a reset), so we can't reliably mix our own `plain`
items with a file-default in the same response — it's either/or per position
(choices/subcommands → `plain`; path/unknown → `file`).

The `source` instruction (install-time script generation) is just a template
render needing `prog_name` only — no tree walk — so it also avoids importing the
app.

## The completer hooks (extensibility)

One module, one decorator:

```python
# rbx/box/completion/registry.py
@dataclass
class CompletionContext:
    args: list[str]                 # full token path
    command: tuple[str, ...]        # e.g. ('run',)
    option_values: dict[str, str]   # preceding values, e.g. {'--problem': 'A'}
    package_root: Path | None       # cheap upward walk for problem.rbx.yml (no pydantic load)

Completer = Callable[[CompletionContext, str], list[CompletionItem]]

_REGISTRY: dict[str, str] = {}      # key -> dotted path
def register_completer(key): ...    # decorator; also builds reverse map fn->key for generation
def load_completer(key) -> Completer:   # importlib, lazy — imports ONLY that completer's module
```

Rules that keep it fast and clean:

- Completers live in `completion/completers.py` (or per-domain modules) that must
  **not** import the heavy app. Package-aware ones use a **cheap YAML peek**
  (`yaml.safe_load` of `problem.rbx.yml`, no pydantic), `mtime`-cached. So
  "complete solution paths" reads one small file, not the whole schema.
- Optional on-disk **result cache** keyed by `(key, package mtime)` for stable
  listings, making repeat tabs instant.
- **Adding a new completer = 3 lines:** write the function,
  `@register_completer('solutions')`, set the param's `autocompletion` to the
  lazy loader. Regenerate spec. The "unregistered completer → hard error"
  generation rule guarantees nothing slips the net.

**Migration:** the existing 3 completers (`language`, `problem` [re-enabled],
`checker`) become the first registry citizens, and `annotations.py` references
them by key instead of importing `config` eagerly — which also slims the
non-completion path.

## Benchmark & correctness harness

Built first, run at every phase.

1. **Differential correctness test — the oracle.** Auto-generate a corpus of
   partial command lines by walking the spec (every group → child names; every
   leaf → option names, each value position, aliases, `--opt=`, `--`, prefix
   filters) plus hand-added edge cases. For each, run both `resolve(SPEC, …)`
   and the real Typer completion (build the real app once in-process, reuse for
   all lines) and assert identical items (value + type + help).
2. **Import-firewall test — the hard speed gate (CI).** Run a real completion in
   a subprocess with the env protocol, then assert `sys.modules` contains none of
   a denylist: `textual, mechanize, bs4, lxml, git, agents, prompt_toolkit,
   questionary, rbx.box.cli, rbx.box.solutions, rbx.box.packaging, …`.
   Deterministic, machine-independent. If anyone reintroduces a heavy import on
   the completion path, CI goes red.
3. **Latency benchmark — dev-facing.** `scripts/bench_completion.py`
   (+ `mise run bench-completion`): cold subprocess timing, best-of-N, table per
   scenario (`rbx <tab>`, `rbx run <tab>`, `rbx package <tab>`, `rbx --lang
   <tab>`, …) with the 741ms baseline alongside. A soft pytest ceiling (~150ms,
   marked `slow`) is informational; the firewall is the real gate.
4. **Drift test** — regenerated spec == committed `_spec.py`.
5. **Robustness tests** — engine raises → `file` directive, exit 0, clean stderr;
   unknown shell; `source` renders without importing the app; malformed args
   don't crash.

## Phased rollout

| Phase | Deliverable | Gate |
|---|---|---|
| **0 — Harness first** | Bench script + import-firewall + differential scaffold against *current* behavior; capture 741ms baseline + golden Typer completions | Baseline table recorded |
| **1 — Registry** | `registry.py` + `completers.py`; migrate the 3 completers (re-enable `problem`), cheap YAML peek; no runtime change yet | Differential still green |
| **2 — Generator** | `generate.py`, `mise` task, committed `_spec.py`, drift test | Drift test green |
| **3 — Engine** | `engine.py` (resolver + `FastComplete`) + `entry.py`; `main.py` routes `_RBX_COMPLETE` to fast path | Differential 100% green; firewall green; latency ~741ms→~50ms |
| **4 — Hardening + docs** | Corpus edge cases, fallback directives, "how to add a completer" doc, wire all into CI/`mise` | Full suite green |

Each phase ends with the benchmark table + green differential test.

## Risks & mitigations

- **Resolver vs Click divergence** → differential corpus is the oracle; large and
  spec-derived.
- **Spec drift** → committed spec shipped in the wheel (no runtime staleness);
  drift test in CI.
- **Heavy import creeps back onto the path** → import-firewall test.
- **Import-time side effects** (linters self-register, pydantic model builds) no
  longer triggered eagerly → relevant subtree triggers them when it actually
  loads; covered by the existing global-state isolation fixture and the test
  suite.
- **`source` instruction** must not import the app → rendered from template;
  asserted by the firewall test.

## Out of scope

- Rewriting how commands are declared (Typer stays the source of truth).
- A general lazy-loading refactor of the whole CLI (a separate, larger effort;
  this design only touches the completion path and the small completer
  extraction).
- Pushing below ~40–60ms (would require slimming `config`/interpreter startup;
  revisit only if the benchmark says it's needed).
