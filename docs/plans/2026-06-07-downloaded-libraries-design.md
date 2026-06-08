# Rethink how downloaded libraries are handled

Design doc for [#392](https://github.com/rsalesc/rbx/issues/392).

Date: 2026-06-07

## Problem

Third-party libraries (`testlib.h`, `jngen.h`, `tgen.h`) and the system header
`bits/stdc++.h` are currently **hardcoded** in `rbx/config.py`, each pointing at
a fixed GitHub raw URL at the branch **HEAD** (`master`/`main`). Consequences:

- **No version pinning.** A setter's view of `testlib.h` silently drifts as
  upstream changes. The issue's first concern — "a consistent view" — is unmet.
- **Closed set.** Adding a library means editing `config.py`; presets/setters
  cannot declare libraries they need.
- **Tool-global, not preset-scoped.** A preset/contest cannot say "this package
  uses testlib version X."

Today the files lazy-download to `~/.rbx/`, fall back to bundled `predownloaded/`
copies on network failure, and at compile are injected into the reserved
`__internal__/` sandbox dir via `-I__internal__`
(`rbx/box/download.py`, `rbx/box/code.py:674-709`). The default preset also ships
a committed `testlib.h` in its `problem/` template.

## Goal

Make third-party libraries **preset-declared, versioned, fetched, cached, and
materialized into the package** — reproducible across a team via committed files,
with a clean compile story built on the existing `compilationFiles`
auto-expansion.

## Decisions (settled during brainstorming)

| # | Decision |
|---|----------|
| 1 | Libraries are **always cached** (fetch-dedup by version) **and always materialized** into the package. |
| 2 | Configuration lives **only in `preset.rbx.yml`**, in a new `libraries:` block with `problem`/`contest` lists (mirrors the existing `tracking` shape). |
| 3 | **No lockfile.** The committed materialized files are the pin. The version spec is consulted only by `rbx presets sync`. `latest` drifts on sync; pin a tag/commit to freeze. |
| 4 | **Clean cut.** `rbx.h` + `bits/stdc++.h` stay tool built-ins; `testlib`/`jngen`/`tgen` are removed from `config.py` and exist only as preset-declared libraries. Requires migration. |
| 5 | Default compile behavior: a materialized library is compiled-in **only when a source `#include`s it** (the quoted-include auto-expansion handles C++). `always_include: true` additionally injects it into `__internal__/`. |
| 6 | `source` reuses the **preset URI grammar** (`get_preset_fetch_info`) plus separate `path` + `version`; raw download URLs are detected as a URL source. |
| 7 | **No offline fallback.** First fetch requires network; afterwards the cache + committed files cover everything. The `predownloaded/` fallback for these libs is removed. |
| 8 | Materialized libraries are **committed** (copy at `dest`; symlink content under `.local.rbx/libs`, the symlink committed). No `.gitignore` changes. |

## Schema

New block in `preset.rbx.yml` (Pydantic models in `rbx/box/presets/schema.py`):

```yaml
libraries:
  problem:                          # mirrors `tracking`: problem + contest lists
    - name: testlib                 # logical name; cache key + `rbx download <name>`
      source: MikeMirzayanov/testlib  # preset URI grammar (see below)
      path: testlib.h               # file OR dir within the source repo
                                    #   (omit for a raw-URL source)
      version: latest               # commit prefix | tag/release/branch | "latest"
      dest: tests/testlib.h         # where it is materialized in the package
      symlink: false                # copy from cache (false) | symlink via .local.rbx/libs (true)
      always_include: false         # also inject into __internal__/ for global availability
      include_as: null              # optional; how it's #included when always_include
                                    #   (default = basename of `path`/`dest`; e.g. bits/stdc++.h)
  contest:
    - ...
```

Proposed models:

```python
class Library(BaseModel):
    name: str = NameField()
    source: str                       # parsed by get_preset_fetch_info (+ raw-URL/git extractors)
    path: Optional[pathlib.Path] = None
    version: str = 'latest'           # commit prefix | tag/release/branch | 'latest'
    dest: pathlib.Path
    symlink: bool = False
    always_include: bool = False
    include_as: Optional[pathlib.Path] = None

class Libraries(BaseModel):
    problem: List[Library] = []
    contest: List[Library] = []

# Preset gains:
#   libraries: Libraries = Field(default_factory=Libraries)
```

### `source` grammar

Reuse and extend `rbx/box/presets/fetch.py::get_preset_fetch_info`:

- `owner/repo`, `@gh/owner/repo`, `https://github.com/owner/repo` → GitHub repo.
  Single-file fetch uses the raw URL
  `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>` (no clone);
  directory fetch clones + checks out `version`, copies the `path` subtree.
- arbitrary git URL (e.g. `https://gitlab.com/u/r.git`) → clone + checkout `version` + take `path`. **(new extractor)**
- raw download URL (non-GitHub `https://…/file.h`) → direct download; `path`/`version` N/A. **(new extractor)**
- local path → copy from disk (testing / vendoring).

### Version resolution

- commit prefix / tag / branch → used as the git ref directly.
- `latest` → repo default-branch HEAD (or, for a raw URL, just fetch current).

## Fetch → cache → materialize

```
                 source + path + version
                          |
                          v
      ~/.rbx/libs/<source-hash>/<resolved-ref>/<path>     (global cache, fetch once)
                          |
            +-------------+--------------+
            | symlink:false              | symlink:true
            v                            v
   copy cache -> <pkg>/<dest>    copy cache -> <pkg>/.local.rbx/libs/<name>/<path>
   (committed real file)         then  <pkg>/<dest> -> relative symlink into it
                                 (content + symlink both committed)
```

- **Cache** keyed by `(source, resolved-ref, path)`; reused across every
  problem/contest. `latest` resolves the remote SHA each time (cheap
  `ls-remote`); identical content hits the cache. Caching is independent of the
  "no lock" decision — the cache is a performance layer, not a pin.
- A directory `path` mirrors its whole tree under `dest`.
- First fetch requires network (decision #7).

## Compile integration (`rbx/box/code.py`)

- **Remove** `download.maybe_add_testlib/jngen/tgen` calls (`code.py:674-676`).
  Keep `maybe_add_rbx_header` and the `bits/stdc++.h` injection — the two
  built-ins.
- **Default**: a materialized library at `dest` is pulled into compilation by the
  existing quoted-`#include` auto-expansion
  (`deps_graph.expand(code, COMPILATION)`, `code.py:666`) when a source
  references it. Preset authors place a lib where their sources include it from
  (e.g. `testlib.h` beside `gen.cpp` in `tests/`).
- **`always_include: true`**: additionally inject the materialized file into
  `__internal__/<include_as>` and ensure `-I__internal__` is present. Defaults to
  the `path`/`dest` basename; `include_as` covers nested names like
  `bits/stdc++.h`. Participates in the existing `.gch` precompile
  (`code.py:711+`), like the other static `__internal__` headers.

## `rbx presets sync`

Extend `rbx/box/presets/__init__.py::sync` to also process `libraries`:

- For each declared library: re-resolve `version`, fetch into cache if absent,
  re-materialize (copy/symlink).
- Libraries are tool-managed: sync **always** overwrites the materialized file
  with the freshly-fetched content. Per decision #3 the committed files are the
  pin (no lockfile), so a local hand-edit to a managed library is intentionally
  not preserved — vendor a custom copy under a different path/source to diverge.
- `--force`/`--symlinks` continue to apply to the preset's own tracked assets.

## `rbx download` (`rbx/box/download.py`)

- `rbx download <name>` resolves `<name>` against the active preset's declared
  libraries and fetches+materializes per its config; `--into` overrides `dest`.
  Since the default preset declares them, `rbx download testlib|jngen|tgen` keep
  working — now via name lookup, not hardcoded URLs.
- `rbx download` with no name refetches all declared libraries.
- Keep `rbx download checker <name>` and `rbx download remote` as-is (separate
  mechanisms: testlib checkers / remote code).

## Migration (cost of the clean cut)

- **Default preset** (`rbx/resources/presets/default/`): drop the committed
  `testlib.h` from `problem/`; add a `libraries` block to `preset.rbx.yml`
  declaring `testlib` with `dest` matching where `gen.cpp`/`validator.cpp`
  include it. `wcmp.cpp` stays a normal preset checker asset (out of scope).
- **Existing user packages**: `rbx presets sync` materializes the
  newly-declared libs. A source whose `#include "testlib.h"` no longer resolves
  produces a clear error pointing to `rbx download testlib`.
- **`rbx/config.py`**: remove `_download_testlib/_download_jngen/_download_tgen`,
  `get_testlib/get_jngen/get_tgen`, and the `download_*` variants, plus the
  `predownloaded/` fallback for these libs (decision #7). `bits/stdc++.h` and the
  testlib **checker** download path are unaffected.

## Testing

- **Unit**: extended `get_preset_fetch_info` parsing (raw URL, arbitrary git);
  version resolution; cache keying; copy-vs-symlink materialization;
  `always_include` → `__internal__` injection + `include_as` defaulting.
- **Integration**: a fixture preset declaring a library from a **local-path
  source** (deterministic, offline) → `rbx problem create` → assert the file is
  materialized at `dest` and the package compiles. One `always_include` library
  included from a source in a different directory.
- **e2e** (`tests/e2e/`): a fixture exercising `rbx download <name>` and a
  `rbx presets sync` version bump (local source so it stays offline/deterministic).

## Risks / open questions

- **Behavior change for "include testlib anywhere".** Today testlib is injected
  into `__internal__` for every compile, so any source can `#include "testlib.h"`
  regardless of location. After the clean cut, default behavior requires the
  include to resolve to the materialized `dest`. The default preset should set
  `always_include: true` on `testlib` (and document it) to preserve the
  ergonomics setters expect.
- **Symlink portability.** Symlink mode relies on the platform supporting
  symlinks (already a startup requirement) and on `.local.rbx` being committed
  (confirmed: not gitignored).
- **Directory fetch from GitHub** needs a clone (no raw-URL shortcut); acceptable
  given it is the less common case.
