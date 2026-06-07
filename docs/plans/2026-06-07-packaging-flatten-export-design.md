# Design: Flatten + ship sources for flat/inline judges (#525 + #526 + #527)

Follow-up to #522 / #523 / #524 (sandbox directory mirroring, Phases 1–2). Those
phases let setters organize sources into subdirectories and `#include "../lib.h"`
locally. The export packagers were never updated, so such a package can build +
verify green locally yet be silently broken once exported. This design closes that
gap for the three flat/inline targets — Polygon (offline + upload) and BOCA — and
folds in the shared collision-free naming scheme that #527 requires.

## Problem

Packaging re-exports source files to a target judge, which compiles them in its own
environment. Two targets have no notion of directories:

- **Polygon** is strictly flat — one flat file namespace.
  - Offline `problem.zip` (`polygon/packager.py:225-233`): checker/interactor copied
    into `files/` beside only `testlib.h`/`rbx.h`; `_get_files()` (`:159`) declares
    only those two headers.
  - API upload (`polygon/upload.py`): every source uploaded **by basename**; only
    `testlib/jngen/tgen/rbx` headers uploaded as RESOURCE.
- **BOCA** (`boca/packager.py:208-240`, `resources/packagers/boca/checker.sh`): the
  checker/interactor source is embedded **inline** via exactly three fixed heredocs
  (`testlib.h`, `rbx.h`, the source), compiled flat with no `-I` and nothing else
  beside it.

Consequences:
- Any exported C++ source using a directory-resolving quoted include
  (`#include "../lib.h"`, `#include "subdir/x.h"`) fails to compile on the target.
- Any source relying on a custom `compilationFiles` header fails — the header is
  never shipped (`grep -rn compilationFiles rbx/box/packaging/` finds only the
  Polygon *importer*).
- Two sources sharing a basename across directories (`gens/a/gen.cpp`,
  `gens/b/gen.cpp`) collide into one Polygon file; one silently overwrites the other
  and the freemarker test script's stem reference becomes ambiguous (#527).

All three become the **default** failure mode now that #524 ships default-on
auto-expansion of `#include "..."`.

## Decisions (locked with the owner)

1. **Full solution in one PR** — build the real flatten + include-rewrite (#525) and
   `compilationFiles` shipping (#526) together. The guardrail (originally proposed in
   #525 as a cheap interim) is demoted to the error path for genuinely unsupportable
   cases only.
2. **One shared naming scheme that also closes #527** — a single flat-naming utility
   applied across all uploaded Polygon sources, fully resolving #527 in the same
   effort.
3. **Path-based disambiguation with a `__` separator** — a file with a globally-unique
   basename keeps its bare basename (so flat packages stay byte-identical); colliding
   files become `str(path)` with `/` → `__` (`gens/a/gen.cpp` → `gens__a__gen.cpp`),
   with a deterministic counter fallback for residual collisions.

## What already exists (do not rebuild)

#524 shipped every hard primitive in `rbx/box/dependencies/`:

- `graph.expand(code, require_kind=DependencyKind.COMPILATION) -> Optional[DependencyGraph]`
  — transitively walks a source's quoted-include deps; returns `None` when no scanner
  applies / the source is outside the package root. `DependencyGraph.files()` lists
  every package-relative dependency (root excluded); `graph.nodes[path]` gives each
  visited file's direct `References`.
- `Reference(spelling, target)` — `spelling` is the include exactly as written
  (`../lib.h`); `target` is its resolved package-relative path, or `None` for
  system/builtin/unresolved includes (`<...>`, `testlib.h`, `rbx.h`).
- `CppScanner.rewrite(text, rename: spelling -> Optional[str]) -> str` — pure textual
  transform rewriting quoted `#include "..."` spellings; `can_rewrite = True` for C++,
  `False` for Python. Returns input unchanged when `rename` yields `None`.

This design is pure packaging-side orchestration + naming on top of those.

## Architecture: one shared `FlatNamespace`, three materializers

New module `rbx/box/packaging/flattening.py`.

### Data model

```python
@dataclasses.dataclass(frozen=True)
class FlatFile:
    flat_name: str               # name within the flat namespace
    source_path: pathlib.Path    # package-relative original
    content: bytes               # rewritten bytes for rewritable members; original otherwise
    is_root: bool                # a top-level source vs. a discovered/declared dep
    origin_code: Optional[CodeItem]

@dataclasses.dataclass
class FlatNamespace:
    files: List[FlatFile]
    name_of: Dict[pathlib.Path, str]      # package-relative path -> flat name
    def flat_name_for(self, code: CodeItem) -> str: ...
    def materialize(self, into_dir: pathlib.Path) -> None: ...   # writes every FlatFile
```

### Builder

```python
def build_flat_namespace(
    sources: Sequence[CodeItem],
    *,
    reserved: Mapping[pathlib.Path, str] = {},  # force a source to a fixed flat name
    enforce_stem_unique: bool = False,          # for sources consumed by stem (generators)
) -> FlatNamespace
```

1. **Collect members.** For each `code` in `sources`:
   - `graph = deps_graph.expand(code, require_kind=COMPILATION)`; members =
     `{graph.root} ∪ set(graph.files())`, recording `graph.nodes[f]` references per file.
   - Fold in manual `compilationFiles` (`package.get_compilation_files(code)`). Each is
     itself scanned the same way (re-expanded with the owning source's scanner) so its
     own transitive quoted includes are captured and rewritten too.
   - Union all members into one global set of package-relative paths. (Upload passes
     all sources in one call → cross-source collisions handled. Offline/BOCA pass only
     checker/interactor.)
2. **Assign flat names** over the union:
   - Seed `reserved`.
   - A globally-unique basename — and unique *stem* when `enforce_stem_unique` — that
     does not clash a reserved name → keep the bare basename. **This is what keeps
     flat packages byte-identical.**
   - Otherwise → `str(path)` with `/` → `__` and any char outside `[A-Za-z0-9._]`
     sanitized to `_`, preserving the extension (`gens/a/gen.cpp` → `gens__a__gen.cpp`).
   - **Residual-collision fallback:** after mangling, if any flat name (or stem, when
     enforced) still collides, append `__<n>` by sorted package-relative path.
     Deterministic and order-independent.
3. **Rewrite.** Each member reached through a rewritable (C++) root is rewritten once.
   Build `rename` from that file's own `References`: `spelling -> name_of[ref.target]`,
   skipping refs whose `target is None` (system/testlib/rbx left untouched).
   `content = CppScanner.rewrite(text, rename).encode()`. Non-rewritable members ship
   original bytes. Rewrite depends only on `(text, name_of restricted to the file's own
   refs)`, so a dep shared by two roots rewrites identically regardless of order.

## Per-target wiring

### Polygon offline (`polygon/packager.py`)
- `ns = build_flat_namespace([checker, interactor],
   reserved={checker.path: 'check.cpp', interactor.path: 'interactor.cpp'})`.
- `ns.materialize(into_path / 'files')` writes `check.cpp`, `interactor.cpp`, and every
  dep under its flat name. Root copy `into_path / 'check.cpp'` gets the rewritten bytes
  (Polygon UI `cpy`). `testlib.h`/`rbx.h` still written as builtins.
- Extend `_get_files()` to declare every dep file
  (`polygon_schema.File(path=f'files/{flat_name}', type=...)`, `h.g++` / `cpp.g++` by
  extension) alongside `testlib.h` / `rbx.h`.

### Polygon upload (`polygon/upload.py`)
- One `build_flat_namespace([...generators, ...validators, ...solutions, checker,
  interactor], enforce_stem_unique=True, reserved={checker→'checker', ...})` across
  every uploaded source — checker/validator/interactor keep their special stems.
- Upload each root under its flat name (rewritten content); upload each dep under its
  flat name as `FileType.RESOURCE`.
- Rewrite the freemarker test-generation script's generator references from
  `generator.path.stem` → flat stem. **This resolves #527**: same-basename generators
  in different dirs now get distinct names/stems and the script targets the right one.

### BOCA (`boca/packager.py`, `resources/packagers/boca/checker.sh`)
- Generalize the three fixed heredocs into a Python-generated `{{embedded_files}}`
  block — one `read -r -d '' VAR_i <<"EOF_i" ... EOF_i` + `printf ... > <flat_name>`
  per flat file (testlib.h, rbx.h, checker.cpp, + each dep) — plus
  `{{embedded_hash_inputs}}` listing all files so the md5 cache key covers them.
- Checker still compiles as `checker.cpp` with deps written beside it. Same
  generalization for the interactor template. MOJ inherits via the generalized
  `_get_checker()`.

## Error handling (the guardrail, demoted)

Because C++ is fully handled, the guardrail fires only when a member **needs**
rewriting (has a directory-resolving quoted include / lives non-flat) but its language
scanner has `can_rewrite = False` (e.g. a Python generator with a cross-package
relative import that resolves under root) or no scanner applies. Raise a clear,
actionable `RbxError` naming the file + target ("Polygon/BOCA export can't flatten
`<file>` … see #525"). Sources whose only unresolved refs are system/builtin
(`target is None`) are fine and ship by basename exactly as today.

## Testing

- **Unit** (`tests/rbx/box/packaging/test_flattening.py`): basename preserved when
  unique; `__` path-disambiguation on collision; stem-uniqueness enforcement; reserved
  names honored; residual counter fallback; deterministic ordering. Rewrite via
  `CppScanner`: a subdir checker `#include "../lib.h"` names `lib.h` and rewrites the
  include. Guardrail raises on a non-rewritable cross-dir source.
- **Integration (teeth-having)**: a subdir checker `#include "../lib.h"` →
  - Polygon offline package whose `files/check.cpp` actually compiles flat against the
    shipped `files/lib.h`;
  - BOCA rendered `checker.sh` runs and builds `checker.exe`;
  - a custom `compilationFiles` header (#526) ships and compiles in both;
  - Polygon upload dry-run ships rewritten files + deps and the freemarker script
    references the correct stems;
  - two same-basename generators in different dirs (#527) get deterministic distinct
    names and the script targets the right one.
- **Regression (#526)**: a flat package with no `compilationFiles` produces Polygon
  offline + BOCA output byte-identical to today (golden compare).

> The real-`g++` compile integration tests are environmentally broken on the author's
> machine (local C++ / sandbox compile tests fail pre-existingly) but pass in CI. Mark
> them with the appropriate markers (`docker` / `slow`) and verify the non-compile
> logic locally.

## Out of scope

- `<...>` system includes and the builtin testlib/jngen/tgen/rbx headers — they resolve
  on the target already (`Reference.target is None`).
- Non-C++ include/import rewriting (Python `can_rewrite = False`) — handled by the
  guardrail (error), not by flattening.
- MOJ/PKG beyond what MOJ inherits from BOCA; PKG ships sources differently and is not
  a flat-compile target.
