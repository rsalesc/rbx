# Packaging Module (`rbx/box/packaging/`)

Exports problem packages to various competitive programming judge system formats.

## Architecture

### Base Abstractions (`packager.py`)

- **`BasePackager`** (ABC) -- Problem-level packager. Subclasses implement `name()` and `package(build_path, into_path, built_statements)`.
- **`BaseContestPackager`** (ABC) -- Contest-level packager. Receives `BuiltProblemPackage` list.
- **`ContestZipper`** -- Generic contest packager that zips all problem packages together.

### Orchestration: `run_packager()`

The main entry point in `packager.py`. Pipeline:
1. Generate header (`header.generate_header()`)
2. Apply packager-specific limits profile (`limits_info.use_profile(packager_name)`)
3. **Full build + verify** (`builder.verify()`) -- generates tests, validates, runs solutions
4. Build statements (produce PDFs via `execute_build_on_statements()`)
5. Call `packager.package()` to produce the final zip

**Packaging always requires a full build first.** The packagers only read pre-built artifacts.

### Contest Orchestration (`contest_main.py`)

`run_contest_packager()` iterates over each problem in the contest, calls `run_packager()` per problem, then calls the contest packager.

## Source Flattening (`flattening.py`)

Polygon (offline + upload) and BOCA/MOJ are **flat** judges: they compile each source in a single flat file namespace. A source organized under the Phase-1 mirrored layout (`#522`/`#523`/`#524`) -- living in a subdirectory, using `#include "../lib.h"`, or relying on custom `compilationFiles` -- builds locally but breaks on these targets unless its compilation closure is shipped flat with includes rewritten. `flattening.py` is the shared machine that does this (issues #525/#526/#527).

- **`assign_flat_names(paths, *, reserved={}, enforce_stem_unique=False)`** -- pure, package-independent naming. A globally-unique basename (and stem, when `enforce_stem_unique`) keeps its **bare basename**, so flat packages stay byte-identical to pre-flattening output. Collisions get a `__`-joined sanitized path rendering (`gens/a/gen.cpp` -> `gens__a__gen.cpp`), with a deterministic `__<n>` counter for residual clashes. `reserved` pins specific sources to fixed names (e.g. the checker -> `check.cpp`); reserved values must be mutually distinct. This single scheme closes #527 (same-basename generators/solutions colliding across directories).
- **`build_flat_namespace(sources, *, reserved, enforce_stem_unique)`** -> `FlatNamespace`. For each source `CodeItem` it collects the transitive quoted-`#include` closure (via `rbx.box.dependencies.graph.expand`, the #524 scanner) plus manual `compilationFiles`, assigns flat names, and rewrites C++ quoted includes to those names (`CppScanner.rewrite`). System/builtin headers (`<...>`, `testlib.h`, `rbx.h`, jngen/tgen) resolve to `target=None` and are left untouched. Out-of-package roots (e.g. the builtin checker) are read from their real path.
- **`FlatNamespace`** -- `.files` (each `FlatFile` has `.flat_name` + rewritten `.content` bytes), `.root_files()`/`.dep_files()`, `.flat_name_for(code)`, `.content_for(code)`, `.materialize(into_dir)`.

**Consumers:** Polygon offline (`polygon/packager.py:_flatten_sources` -> `files/` + `_get_files` declares deps), Polygon upload (`polygon/upload.py:_build_upload_namespace` -> one namespace over checker/interactor/validator/solutions/generators, deps shipped as RESOURCE, freemarker references flat **stems**), BOCA (`boca/packager.py:_embed_block` -> N heredocs in `checker.sh`/`interactor_compile.sh`), MOJ (`moj/packager.py` -> rewritten source + deps into `scripts/`).

**Guardrail:** a non-rewritable source (e.g. a Python generator, `can_rewrite=False`) with a *cross-directory* resolving dependency cannot be flattened, so `build_flat_namespace` errors with an actionable message rather than shipping a broken package. Same-directory and system/builtin deps are fine.

**Known limitations:** (1) plain *absolute* Python imports (`from common.helper import x`) resolve as siblings of the importing file in the scanner, so a cross-package absolute import is neither shipped nor guard-flagged -- only parent-relative (`from ..common import`) cross-dir imports trip the guard; the feature is C++-centric. (2) A user-authored file literally named `testlib.h`/`rbx.h` next to a source is a pathological name clash with the injected builtin headers and is not specially guarded.

## Format Implementations

### Polygon (`polygon/`)

**`PolygonPackager`** -- Produces `problem.zip` containing:
- `problem.xml` (serialized from `pydantic-xml` models in `xml_schema.py`)
- `files/` -- `testlib.h`, `rbx.h`, `check.cpp`, `interactor.cpp`, plus any flattened dependency headers (see [Source Flattening](#source-flattening-flatteningpy))
- `tests/` -- testcases named `001`, `001.a`, etc.

**`PolygonContestPackager`** -- Produces `contest.zip` with `contest.xml`, `contest.dat`, and per-problem directories.

**API Upload (`upload.py`):**
- `upload_problem()` orchestrates: find/create problem, upload files, solutions, testcases, statements, commit
- Uses `ThreadPoolExecutor(4)` for parallel solution uploads
- Maps solutions to Polygon tags: MA (main accepted), OK, WA, TL, ML, RE, RJ
- Statement upload: renders Jinja blocks to Polygon's structured format, uploads resources (images, TikZ PDFs)
- API client in `polygon_api.py` with SHA-512 signed requests, env vars `POLYGON_API_KEY`/`POLYGON_API_SECRET`
- `--upload-tests-raw` escape hatch: uploads built test inputs as raw files (1 MiB cap each), skips generator uploads, and clears the freemarker script. Use when Polygon-side generator compilation is failing.

**`xml_schema.py`** -- pydantic-xml models: `Problem`, `Contest`, `Testset`, `Checker`, `Interactor`, `Name`, `Statement`, `File`, `Test`.

### BOCA (`boca/`)

**`BocaPackager`** -- Most structurally complex. Produces zip with per-language shell scripts:
- `limits/{lang}` -- time limit script. Emits an EXACT fractional time budget (no rounding). When the optional `minRunningTime` is set, it runs the solution `ceil(minRunningTime / timeLimit)` times (capped at 10) so the accumulated budget reaches the floor while the effective per-run TL stays exact.
- `compile/{lang}` -- embeds checker source, testlib.h, rbx.h (and any flattened dependency headers, see [Source Flattening](#source-flattening-flatteningpy)) inline in shell scripts via N heredocs
- `compare/{lang}`, `run/{lang}`, `tests/{lang}` -- per-language scripts from templates
- `description/problem.info` + PDF statement
- `input/`, `output/` -- test I/O, `solutions/` -- all solutions

Supports interactive problems with special `run` scripts.

**`extension.py`** -- `BocaExtension` model with language mapping, flags, `minRunningTime`, `preferContestLetter`, `usePypy`. (`maximumTimeError` is deprecated/ignored -- see issue #494.)

### MOJ (`moj/`)

**`MojPackager`** (extends `BocaPackager`) -- Overrides BOCA methods for MOJ format:
- `scripts/` directory with checker, testlib, per-language scripts
- `sols/{good,wrong,slow}/` -- solutions categorized by outcome
- `docs/enunciado.pdf` -- statement
- Optional `--for-boca` mode that uses BOCA-style layout

### PKG (`pkg/`)

**`PkgPackager`** -- Simplest format:
- `statement.pdf`, `tests/{001.in, 001.ans, ...}`, `solutions/` (accepted only)

**`PkgContestPackager`** -- Contest-level: `statement.pdf` + per-problem directories.

### Importer (`importer.py`, `polygon/importer.py`)

Reverse operation: `PolygonImporter` imports from Polygon packages into rbx format:
- Parses `problem.xml`, copies tests, statements, checker, interactor, headers
- Writes `problem.rbx.yml` with constructed package metadata

## CLI Commands (`main.py`)

| Command | Packager | Extra Options |
|---------|----------|---------------|
| `rbx package polygon` | `PolygonPackager` | `--upload`, `--language`, `--upload-as-english`, `--upload-only`, `--upload-skip`, `--upload-tests-raw` |
| `rbx package boca` | `BocaPackager` | `--upload`, `--language` |
| `rbx package moj` | `MojPackager` | `--for-boca` |
| `rbx package pkg` | `PkgPackager` | (none) |

All are guarded by `@package.within_problem`.

## Key Detail: Limits Profiles

Different judge systems have different time/memory limits. The `LimitsProfile` system (defined in `schema.py`) allows per-packager limit overrides. `limits_info.use_profile(name)` applies the correct profile during build and packaging.
