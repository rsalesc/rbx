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

## Format Implementations

### Polygon (`polygon/`)

**`PolygonPackager`** -- Produces `problem.zip` containing:
- `problem.xml` (serialized from `pydantic-xml` models in `xml_schema.py`)
- `files/` -- `testlib.h`, `rbx.h`, `check.cpp`, `interactor.cpp`
- `tests/` -- testcases named `001`, `001.a`, etc.

**`PolygonContestPackager`** -- Produces `contest.zip` with `contest.xml`, `contest.dat`, and per-problem directories.

**API Upload (`upload.py`):**
- `upload_problem()` orchestrates: find/create problem, upload files, solutions, testcases, statements, commit
- Uses `ThreadPoolExecutor(4)` for parallel solution uploads
- Maps solutions to Polygon tags: MA (main accepted), OK, WA, TL, ML, RE, RJ
- Statement upload: renders Jinja blocks to Polygon's structured format, uploads resources (images, TikZ PDFs)
- API client in `polygon_api.py` with SHA-512 signed requests, env vars `POLYGON_API_KEY`/`POLYGON_API_SECRET`

**`xml_schema.py`** -- pydantic-xml models: `Problem`, `Contest`, `Testset`, `Checker`, `Interactor`, `Name`, `Statement`, `File`, `Test`.

### BOCA (`boca/`)

**`BocaPackager`** -- Most structurally complex. Produces zip with per-language shell scripts:
- `limits/{lang}` -- time limit script (uses clever rounding with multiple runs to minimize error)
- `compile/{lang}` -- embeds checker source, testlib.h, rbx.h inline in shell scripts
- `compare/{lang}`, `run/{lang}`, `tests/{lang}` -- per-language scripts from templates
- `description/problem.info` + PDF statement
- `input/`, `output/` -- test I/O, `solutions/` -- all solutions

Supports interactive problems with special `run` scripts.

**`extension.py`** -- `BocaExtension` model with language mapping, flags, `maximumTimeError`, `preferContestLetter`, `usePypy`.

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
| `rbx package polygon` | `PolygonPackager` | `--upload`, `--language`, `--upload-as-english`, `--upload-only`, `--upload-skip` |
| `rbx package boca` | `BocaPackager` | `--upload`, `--language` |
| `rbx package moj` | `MojPackager` | `--for-boca` |
| `rbx package pkg` | `PkgPackager` | (none) |

All are guarded by `@package.within_problem`.

## Key Detail: Limits Profiles

Different judge systems have different time/memory limits. The `LimitsProfile` system (defined in `schema.py`) allows per-packager limit overrides. `limits_info.use_profile(name)` applies the correct profile during build and packaging.
