# Add tgen as a default include for `rbx`

Issue: [#409](https://github.com/rsalesc/rbx/issues/409)

## Goal

Promote [tgen](https://github.com/brunomaletta/tgen) to a first-class header
in `rbx`, with the same availability as `jngen`:

- `rbx download tgen` fetches the latest `tgen.h` and writes it into the package.
- `tgen.h` is auto-included in every C++ compilation (alongside `testlib.h`,
  `jngen.h`, `rbx.h`).
- `tgen.h` is uploaded to Polygon as a resource file when packaging.
- Docs mention `tgen` alongside `jngen`.

Two side asks from the issue:

1. **Always-latest downloads.** Today `rbx download jngen` / `rbx download
   testlib` only fetch from GitHub when the app-dir cache is missing — once
   cached, the command silently no-ops. Treat this as a bug: `rbx download …`
   should always re-fetch the latest version. The compile-time auto-include
   still uses the cached copy (refreshed whenever the user runs download).
2. **`--into PATH` flag** on `rbx download <header>` that places the file at a
   path **relative to the package root**, so setters can keep a vendored copy
   of `tgen.h` (or jngen/testlib) updated in-place.

## Source URL

`tgen` exposes its single-header build at
`https://raw.githubusercontent.com/brunomaletta/tgen/main/single_include/tgen.h`.
Default branch is `main` (verified via GitHub API).

## Changes

### 1. `rbx/config.py` — always-refresh downloads

Split each header into two layers:

- `get_<header>() -> pathlib.Path` — return the cached path, downloading only
  if missing. Used by compile auto-include and Polygon upload.
- `download_<header>() -> pathlib.Path` — always re-fetch, overwrite the cache,
  return the path. Used by the `rbx download` CLI.

Add the parallel trio for tgen (`_download_tgen`, `get_tgen`, `download_tgen`)
pointing at the URL above. Apply the same `download_*` always-refresh
treatment to `testlib` and `jngen`. `bits/stdc++.h` is left as-is (not
user-facing via `rbx download`).

### 2. `rbx/grading/steps.py` — compilation artifact

- Add `tgen_grading_input()` mirroring `jngen_grading_input()`.
- Extend the `'testlib' in file or 'jngen' in file or 'stresslib' in file`
  warning-ignore branch (line ~648) to also include `'tgen'`.

### 3. `rbx/box/download.py` — auto-include + CLI

- Add `maybe_add_tgen(code, artifacts)` mirroring `maybe_add_jngen`.
- New Typer command `tgen` that calls `download_tgen()` (always refresh).
- Update `testlib` and `jngen` commands to call their `download_*` siblings so
  every invocation refreshes.
- Add a shared `--into PATH` option to `testlib`, `jngen`, `tgen`:
  - When omitted: preserve current behavior (write `<name>.h` to cwd).
  - When given: resolve `PATH` relative to the package root
    (`package.get_problem_package_dir() / path`), `mkdir(parents=True,
    exist_ok=True)` on the parent, then copy.
  - A small `_resolve_into(name, into)` helper keeps the three commands
    symmetric.
- Help text documents that `--into` is anchored to the package root.

### 4. `rbx/box/code.py` — wire and precompile

- After `download.maybe_add_jngen(code, artifacts)` (line ~620), call
  `download.maybe_add_tgen(code, artifacts)`.
- Add `'tgen.h'` to the precompilation allowlist at line ~660 alongside
  `stdc++.h`, `jngen.h`, `testlib.h`.

### 5. `rbx/box/packaging/polygon/upload.py` — Polygon resource upload

- Add `_update_tgen(problem)` mirroring `_update_jngen` (uses
  `download.get_tgen()`).
- Call it in the upload pipeline next to `_update_jngen(problem)` (line ~305).

### 6. `rbx/box/packaging/polygon/test.py` — fixture

Add `<file path="files/tgen.h" type="h.g++"/>` to the expected resource list
parallel to jngen.

### 7. Docs

- `docs/setters/testset/generators.md`: after the Jngen section (~line 122),
  add a parallel "Tgen" section linking to
  https://github.com/brunomaletta/tgen and noting that `tgen.h` is
  auto-included in C++ compilation.
- `docs/setters/cheatsheet.md` (line 34): add a row
  `Download tgen to the current folder … rbx download tgen`.
- `docs/setters/reference/cli.md` (line 545 area): add a `### tgen` section
  mirroring `### jngen`; document the new `--into PATH` option on
  `testlib`/`jngen`/`tgen`.
- `rbx/box/schema.py:288`/`:293`: update the comment "Testlib and jngen are
  already included by default." → add tgen.

### 8. Tests

In `tests/rbx/box/code_compile_test.py`:

- Mirror the existing jngen assertion: a compilation artifact list contains
  `tgen.h`.
- Verify the precompile path treats `tgen.h` like the other allowlisted
  headers.

New `tests/rbx/box/download_test.py` (or extend an existing one):

- `rbx download tgen` writes `tgen.h` to cwd and re-fetches on every call
  (patch `requests.get`, assert it is called both times).
- `rbx download tgen --into libs/tgen.h` writes to
  `<package-root>/libs/tgen.h` (creating parents), regardless of cwd inside
  the package.
- `rbx download jngen` now re-fetches on every call (regression for the
  cache-forever bug).

## Out of scope (YAGNI)

- No `--refresh` / TTL flag — `rbx download` is the explicit refresh path.
- No `env.rbx.yml` opt-out for the tgen auto-include — symmetric with jngen;
  easy to add later if a user reports a conflict.
- `bits/stdc++.h` keeps its current cache-once behavior; not user-facing.
- `rbx download checker` and `rbx download remote` are not touched by
  `--into` (checker takes a filename argument; remote already has `-o`).

## Risks

- **Network on every download invocation.** Users who run `rbx download
  jngen` offline will now error instead of silently succeeding. Mitigation:
  the existing `predownloaded=True` fallback inside `get_*` already covers
  the offline-compile case; the CLI command surfaces a clear error if the
  fetch fails. Acceptable.
- **tgen API drift.** Always-latest means a `tgen` upstream change could
  break a package between two builds (one downloaded, one not). Mitigation:
  the auto-include uses the cached copy, so builds are stable until the
  setter explicitly re-runs `rbx download tgen`.
