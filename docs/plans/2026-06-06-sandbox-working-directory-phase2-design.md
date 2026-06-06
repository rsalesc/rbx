# Sandbox dir mirroring Phase 2: `executionFiles` + auto-expansion

**Issue:** [#524](https://github.com/rsalesc/rbx/issues/524) — follow-up to #522 / #523
(Phase 1). With implications baked in for
[#525](https://github.com/rsalesc/rbx/issues/525) (packaging flatten/rewrite).

**Phase 1 design:** `docs/plans/2026-06-05-sandbox-working-directory-design.md`

## Problem

Phase 1 made the sandbox working directory mirror the package layout: sources
compile at their package-relative path, `compilationFiles` land package-relative (the
under-code-folder restriction was lifted, enabling `#include "../lib.h"`), and the
builtin headers (testlib/jngen/tgen/rbx + `bits/stdc++.h`) live in a reserved
`__internal__/` dir exposed via `-I__internal__`, so a quoted `#include "testlib.h"`
resolves from any source location, flat or nested. Bringing extra files into the
mirror still requires **manual declaration**, and there is **no execution-time
equivalent** of `compilationFiles` at all.

Phase 2 adds:

1. **`executionFiles`** on every `CodeItem` — the runtime equivalent of
   `compilationFiles`. Declared files are mirrored into the sandbox at *execution*
   time. For a flat package this is a no-op; for a subdir source the file lands at
   its package-relative path.
2. **Default-on, recursive, quoted-only auto-expansion** of dependencies,
   per-language: C++ `#include "..."` → compilation files; Python relative / sibling
   imports → execution files. Follows transitively, cycle-safe. Manual fields remain
   as an additive escape hatch.

Per the issue owner, both must flow through a **common per-language interface** that
returns compilation and execution files, dispatched by the language being
compiled/run — and that *same* interface must serve #525, which needs to flatten
sources and rewrite cross-directory `#include "..."` for flat/inline judges (Polygon,
BOCA). #525 therefore dictates the shape of the interface: it needs not just the
*set* of dependency files but the per-file include **edges** (directive → resolved
target) so it can rewrite them.

## Findings that scope this work

- **The issue's Phase-1 limitation "builtins only in the source's directory" is
  already resolved.** Phase 1 was revised during implementation to place builtins in
  `__internal__/` with `-I__internal__` (see Phase 1 design § 3). A cross-directory
  header that itself does `#include "testlib.h"` resolves via that `-I` fallback. No
  further work needed here. (`maybe_get_bits_stdcpp_for_commands` finds system bits on
  Linux/GCC and clang-bundled bits on macOS, so `-I__internal__` is reliably present
  on C++ commands.)
- **The "deprecate auto-placed builtins" idea is out of scope.** It is a larger,
  riskier change (every package would have to declare testlib). Builtins stay
  auto-injected via `__internal__/`; auto-expansion naturally ignores them because
  they are not package files.

## Non-goals (this phase)

- Anything under `rbx/box/packaging/` (that is #525). We deliver the
  `DependencyGraph` + `rewrite()` primitive that #525 will consume; we do not wire any
  packager.
- Deprecating / removing the auto-injected builtin headers.
- Python source flattening / `rewrite()` for Python (the interface slot exists behind
  a capability flag; C++ is the only implementer for now).

## Architecture

A single per-language extension point (a *scanner* that knows one language's
include/import syntax) plus a generic, language-agnostic engine (transitive walk +
graph). Three consumers read from the one structure: compilation, execution, and
(future) packaging-rewrite.

### New package `rbx/box/dependencies/`

Mirrors the `linters/` package (registry + per-language modules, self-registering via
`__init__.py`).

```
dependencies/
  scanner.py    # DependencyKind, Reference, DependencyScanner ABC, registry
  graph.py      # DependencyGraph + expand(code)
  cpp.py        # CppScanner    (tree-sitter-cpp; kinds={COMPILATION}; can_rewrite=True)
  python.py     # PythonScanner (ast; kinds={EXECUTION}; can_rewrite=False)
  __init__.py   # imports cpp/python so they self-register
```

### Core types (`scanner.py`)

```python
class DependencyKind(enum.Enum):
    COMPILATION = 'compilation'
    EXECUTION = 'execution'


@dataclasses.dataclass(frozen=True)
class Reference:
    spelling: str                 # exactly as written, e.g. '../lib.h'  (drives rewrite)
    target: Optional[pathlib.Path]  # package-relative resolved file, or None
                                    # (system/builtin/unresolved → ignored)


class DependencyScanner(abc.ABC):
    kinds: ClassVar[Set[DependencyKind]]
    can_rewrite: ClassVar[bool] = False

    @abc.abstractmethod
    def handles(self, language: str) -> bool: ...

    @abc.abstractmethod
    def references(self, file: pathlib.Path) -> List[Reference]:
        """Direct dependency references of `file`, already resolved against the
        package root. Unresolvable / system / builtin references have target=None."""

    def rewrite(self, text: str, rename: Callable[[str], Optional[str]]) -> str:
        """Rewrite each include/import directive whose spelling `rename` maps to a
        new spelling. Pure text transform; only the path token changes. Default
        raises NotImplementedError; overridden by languages with can_rewrite=True."""
        raise NotImplementedError
```

Registry: `@register` decorator + `get_scanner(language) -> Optional[DependencyScanner]`
(returns `None` for unhandled languages — Java/Kotlin/etc.). Same shape as
`linters/registry.py`.

### The engine (`graph.py`)

```python
@dataclasses.dataclass
class DependencyGraph:
    root: pathlib.Path                                   # package-relative source
    nodes: Dict[pathlib.Path, List[Reference]]           # file -> its edges (incl. root)
    kinds: Set[DependencyKind]                            # from the scanner

    def files(self) -> List[pathlib.Path]:
        """All discovered dependency files (package-relative), EXCLUDING the root.
        Deterministic order."""


def expand(
    code: CodeItem, require_kind: Optional[DependencyKind] = None
) -> Optional[DependencyGraph]:
    """BFS from code.path using the language scanner. Cycle-safe (visited set);
    keeps only references that resolve to an existing file under the package root.
    Returns None when there is no scanner for the language, or the source lives
    outside the package root (remote/temporary files stay flat, as today).

    `require_kind` short-circuits *before* the walk when the language's scanner
    cannot contribute that kind: a C++ source skips scanning entirely on the
    execution path (`_prepare_run` runs once per solution x testcase, the hot path),
    and a Python source skips it on the compile path."""
```

`nodes` includes the **root** so that #525 can rewrite the root source's own
directives; `files()` excludes the root because the root is added to the artifacts
separately (as the compilable / executable).

### Resolution rules

Each scanner owns its resolution (single source of truth; never duplicated in
`rewrite`):

- **C++ (`CppScanner`, tree-sitter-cpp).** Walk `preproc_include` nodes; keep those
  with a `string_literal` child (quoted), skip `system_lib_string` (`<...>`). For each
  quoted include with spelling `s`: candidate = `file.parent / s`, normalized; if it
  is an existing file under the package root → `target` = its package-relative path,
  else `target = None`. So `#include "testlib.h"` (builtin, not a package file) →
  `None` → ignored (it resolves via `-I__internal__`); `#include "../lib.h"` → `lib.h`.
  `kinds = {COMPILATION}`. `can_rewrite = True`.
- **Python (`PythonScanner`, `ast`).** Parse and walk `Import` / `ImportFrom`. Use
  `node.level` for relative imports (`from . import x`, `from ..pkg import y`) and
  treat a bare `import sibling` / `from sibling import …` as a sibling only when
  `<dir>/sibling.py` or `<dir>/sibling/__init__.py` exists; otherwise (stdlib /
  third-party) `target = None`. For a deep dotted import (`import a.b.c`) it also
  emits the existing intermediate package markers (`a/__init__.py`,
  `a/b/__init__.py`) so the mirror preserves regular-package semantics.
  `kinds = {EXECUTION}`. `can_rewrite = False`. (A relative `from . import x` is
  *discovered* and mirrored but cannot execute in a directly-run `__main__` script;
  the runnable idiom for a mirrored script is the absolute `import x`.)

tree-sitter-cpp is already a dependency (`pyproject.toml`) and is used by
`linters/cpp/testlib.py`; the C++ scanner reuses that pattern. tree-sitter is
error-tolerant, so a malformed source yields a (partial) tree rather than throwing.

### The `rewrite` primitive (baked for #525, implemented for C++)

`rewrite(text, rename)` is *only* the textual transform — it does not resolve paths,
allocate names, or copy files. Keyed on **spelling**, not the resolved target, so
resolution stays solely in `references()`; because both use the same tree-sitter
traversal, every spelling the caller learned from the graph matches exactly.

How #525 will compose it (illustrative; not built this phase):

```python
graph = expand(code)
flat = allocate_flat_names([graph.root, *graph.files()])   # #527 collision scheme
for file, refs in graph.nodes.items():
    rename = {r.spelling: flat[r.target] for r in refs if r.target in flat}
    new_text = scanner.rewrite(file.read_text(), rename.get)
    ship(new_text, as_name=flat[file])
```

Worked example:

```
lib.h
gens/gen.cpp        #include "../lib.h"   #include "helpers/rng.h"
gens/helpers/rng.h  #include "../../lib.h"
```

`expand(gen)` → `files() == [lib.h, gens/helpers/rng.h]`; nodes carry the edges
`gen.cpp: {../lib.h→lib.h, helpers/rng.h→gens/helpers/rng.h}`,
`rng.h: {../../lib.h→lib.h}`. With flat names `{gen.cpp, lib.h, rng.h}` the rewrites
become `#include "lib.h"`, `#include "rng.h"` (in `gen.cpp`) and `#include "lib.h"`
(in `rng.h`). The graph already holds every `spelling→target` edge, so the caller
never re-parses; the primitive is sufficient.

C++ `rewrite` implementation: tree-sitter parse → for each quoted `preproc_include`
extract its spelling, call `rename`; collect `(byte_start, byte_end, replacement)` for
the path token; apply right-to-left to preserve offsets; return new text. Comment- and
raw-string-safe; `<...>` includes are never touched; unmapped quoted includes (rename
returns `None`) are left byte-for-byte.

## Consumers wired this phase

### Compilation (`code.compile_item`)

After the manual `compilationFiles` inputs are added, call `expand(code)`; if
`DependencyKind.COMPILATION in graph.kinds`, add `graph.files()` to the compile inputs
as a **union** with the manual set (dedup by dest path). Builtins, `__internal__/`,
`-I__internal__`, and precompiled-header logic are unchanged. (Python returns early
from `compile_item` — its `compilation_options.commands` is empty — so its deps are
not added here; they are added at run time.)

### Execution (`code._prepare_run`)

`_prepare_run` is the single chokepoint for run-time artifacts (used by `run_item` and
the communication path). Add **manual `executionFiles`** for all languages, **plus**
(if `DependencyKind.EXECUTION in graph.kinds`) `graph.files()` — union, dedup by dest.
This is the new execution-time mirroring.

### Execution: `PYTHONPATH` (discovered during implementation)

Mirroring the sibling module into the sandbox is **necessary but not sufficient** for
Python. The entry script is materialized as a **symlink into the content-addressed
cache** (the sandbox's perf optimization). Python ≥3.11 sets `sys.path[0]` to the
*realpath* of the script's directory, which resolves through the symlink to the cache
store — **not** the mirrored sandbox directory where the sibling module lives. So
`import sibling` fails with `ModuleNotFoundError` even though `sibling.py` sits right
next to the script in the sandbox. (This is a latent issue since Phase 1; #524 is the
first feature to actually exercise runtime sibling imports — Phase 1's nested-Python
guard had no imports, so it passed under the old flat layout too.)

**Fix:** for execution-mirrored languages, set `sandbox_params.set_env['PYTHONPATH']`
to the mirrored source's directory (package-relative; `.` for a flat package),
preserving any existing value. This restores the directory that `python3 dir/script.py`
would normally put on the path. It is gated on `DependencyKind.EXECUTION in
graph.kinds` (currently Python only) and reuses the graph already computed in
`_prepare_run`. `set_env` is part of the run cache key, so this is cache-correct (a
one-time invalidation for Python runs). We deliberately add **only** the source dir
(not the package root) to match normal Python semantics and avoid shadowing stdlib
with root-level modules.

### Schema (`schema.CodeItem`)

Add `executionFiles: Optional[List[str]] = Field(default=[], …)` mirroring
`compilationFiles` (paths relative to the package root; placed at the same
package-relative path inside the sandbox). Add `package.get_execution_files(code)`
mirroring `get_compilation_files` (exists-and-under-root checks; src == dest ==
package-relative path). Propagate `executionFiles` in `CodeItemWithDigest.create` and
`OutputFromItemWithDigest.create`.

## Override semantics

Auto-expansion is **additive**, not an off-switch: manual
`compilationFiles`/`executionFiles` are unioned with auto-discovered files (deduped).
The scanner only ever adds files that are both quoted-included *and* exist under the
package root, so it cannot introduce phantom dependencies; manual declaration stays
the escape hatch for files the scanner cannot see (macro-built include paths, runtime
data files). No `autoExpand` flag (YAGNI; can be added later if a real need appears).

## Caching impact

Auto-discovered compilation files become compile inputs → already part of the
dependency-cache key (inputs are content-hashed). Auto-discovered execution files
become run inputs → part of the run cache key. If a dependency's contents change (e.g.
it gains/loses an `#include`), the discovered set changes and the inputs change, so the
cache invalidates correctly. No cache-format change. Affected packages take a one-time
recompile/rerun.

## Testing

- **Unit — scanners & engine** (no toolchain needed):
  - C++: nested / transitive `#include "..."`; ignore `<...>`; ignore builtin
    (`testlib.h`, not a package file) → `target=None`; resolve `../lib.h`; cycle
    safety; refuse references outside the package root.
  - Python: `from .`, `from ..pkg`, sibling `import x` (resolves only if the sibling
    file exists); ignore stdlib/third-party; transitive; cycle safety.
  - `expand`: returns `None` for Java/Kotlin and for sources outside the package root;
    `files()` excludes root and is deterministic.
  - C++ `rewrite`: maps quoted includes via `rename`; leaves `<...>` and unmapped
    quoted includes untouched; ignores an `#include` inside a `/* … */` comment;
    preserves the rest byte-for-byte. Python `rewrite` raises `NotImplementedError`.
- **Integration — teeth-having** (real toolchain; new file alongside the Phase 1
  `code_compile_integration_test.py`):
  - Subdir C++ source whose `#include "../lib.h"` is **auto-discovered** (no manual
    `compilationFiles`) compiles and runs.
  - Subdir Python source importing a **sibling module** runs correctly end-to-end —
    the execution-mirroring test Phase 1 could only smoke-test.
  - Flat package regression (unchanged behaviour).

Pre-existing local C++/sandbox/docker failures on this machine are environmental
(see project memory); only new include/import-resolution failures are ours.

## Definition of done

- [ ] `rbx/box/dependencies/` with `scanner.py`, `graph.py`, `cpp.py`, `python.py`,
      registry, self-registration.
- [ ] `CodeItem.executionFiles` + `package.get_execution_files`; propagated in the
      `*WithDigest.create` factories.
- [ ] C++ compilation auto-expands `#include "..."` (transitive, quoted-only, additive).
- [ ] Execution mirrors manual + auto-discovered execution files via `_prepare_run`.
- [ ] C++ `rewrite` implemented (tree-sitter, span-based) and unit-tested; Python
      `rewrite` gated behind `can_rewrite=False`.
- [ ] Unit + integration tests pass (modulo pre-existing environmental failures).
- [ ] Lint clean; conventional commits throughout. No `packaging/` changes.

## Deferred to #525 (interface consumed, not built here)

Flatten + rename + rewrite for Polygon offline (checker/interactor), Polygon upload
(all sources), BOCA (checker/interactor), plus the interim guardrail that errors on a
non-flat mirrored layout when `can_rewrite` is False. #525 also coordinates with #526
(ship `compilationFiles` bytes) and #527 (flat-name collision scheme).
