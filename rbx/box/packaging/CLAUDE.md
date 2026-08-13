# Packaging Module (`rbx/box/packaging/`)

Exports problem packages to various competitive programming judge system formats.

## Architecture

### Base Abstractions (`packager.py`)

- **`BasePackager`** (ABC) -- Problem-level packager. Subclasses implement `name()` and `package(build_path, into_path, built_statements)`.
- **`BaseContestPackager`** (ABC) -- Contest-level packager. Receives `BuiltProblemPackage` list.
- **`ContestZipper`** -- Generic contest packager that zips all problem packages together.

### Statement Export Bundle (`rbx/box/statements/export.py`)

A packager that ships a **PDF** statement needs none of this. A packager that consumes statement *blocks* (Polygon today, any block-consuming judge tomorrow) goes through `export.py`, which was extracted from `polygon/upload.py` -- the only consumer -- precisely because no other packager could reach it. Design: `docs/plans/2026-08-13-statement-export-bundle-design.md`.

- **Opt in via `BasePackager.statement_export_params()`.** Returning the externalize+demacro `ConversionStep`s is the declaration "I read blocks"; `run_packager` then builds every statement with them, and *that build* is what writes the `blocks.sub.yml` / `macros.json` / `artifacts/tikz_figures/*.pdf` the bundle reads out of the v2 standalone overlay root (`build/statements/st/<lang>-<variant>/` = `build_statements.get_statement_dir`). Without it the artifacts do not exist.
- **`build_statement_bundle(statement, *, layout, normalize=True)`** -> `StatementBundle` (`.blocks`, `.explanations`, `.assets`, `.remaps`, `.materialize(root)`). Five stages: read+macro-expand+filter the blocks (`get_processed_statement_blocks`; `normalize` converts to the Polygon TeX subset -- the conservative dialect, hence the default, not a Polygon special case), `resolve_assets`, ask the layout where things go, `derive_remap`, rewrite. An uploader reads `assets[i].content`/`.size` (`.size` stats rather than reads, so a size cap is not a multi-MB read) and never materializes; a tarball packager calls `.materialize(root)` and never touches `.content`. Deliberately mirrors `flattening.FlatNamespace`.
- **A scope is a reference base.** `AssetScope` (STATEMENT / TIKZ / SAMPLE / EXTERNAL) names the *directory an asset's `\includegraphics` reference resolves against* -- the statement `file`'s dir, the overlay root, `<overlay>/.samples/<idx>/`, the package root. `ResolvedAsset` carries `scope`/`source`/`rel`/`ref_key` and **no name**: that is what lets one asset list serve an uploader and a tarball writer. `rel`/`ref_key` are NOT unique across the list; only `source` is.
- **Flat naming and single-root are orthogonal** -- conflating them is why the old code was unreusable. `FlatLayout` (Polygon) collapses separators because Polygon has no directories, and uses one root because Polygon has one statement definition; two independent facts. `SubtreeLayout` keeps directories under per-scope roots *and* lets documents live in roots of their own -- the shape a tarball judge such as MOJ needs (`docs/enunciado.md` plus a separate sample-notes dir). **The MOJ packager is its production consumer**; #583 (offline `problem.zip`) is the next candidate. Its per-sample roots -- `asset_roots[AssetScope.SAMPLE]` and `document_dirs['sample_explanation']` -- must both be configured; `build_statement_bundle` derives a remap per explanation index, so a layout missing the `sample_explanation` document dir raises `StatementExportError` on any statement that has explanations at all, images or not. The `{index}` placeholder is **required** in the asset root (many files land there, and a constant root would collapse every sample's entries onto one path) but only **permitted** in the document dir, which is not a destination but the base a remap is computed against -- MOJ gives both slots a constant `docs`, because `gen-problem-json.sh` renders every note with `--resource-path=<pkg>/docs`.
- **The remap is derived, never configured.** `derive_remap(assets, layout, slot)` computes `relpath(place_asset(asset), document_dir(slot))` per `DocumentSlot` (`body()` / `sample(idx)`, since a reference's meaning depends on where the citing text sits) and drops entries equal to the authored reference. So an identity-preserving layout yields an **empty** remap and no block is touched -- that is what makes rewriting optional without a flag. Identity is a property of the *binding* (`asset_roots[scope] == document_dirs[slot.kind]`), which `keep_extension=False` merely permits. The bundle deliberately writes **assets only, never documents**, so `layout.document_dir(slot)` is the other half of that contract: a consumer rendering text of its own reads `remaps[slot]` for the rewrites and `document_dir(slot)` for the directory that text must be written into, since the remap is only correct relative to it.
- **Two complementary guards**, both `StatementExportError` (a `ValueError` subclass, so a CLI boundary can turn exactly these setter mistakes into a clean message without swallowing pydantic/YAML `ValueError`s): *reference ambiguity* (several assets reduce to one extensionless key -- resolved by sample-shadowing then graphicx extension precedence, so `fig.pdf` beats `fig.png` exactly as the local build did, raising only when genuinely undecidable) and *destination collision* (two different sources placed on one path). Neither subsumes the other: `d.png`/`d.pdf` share a key but not a destination; two same-named files from different scopes share a destination while precedence has nothing to disagree about.

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

## Source Amalgamation (`dependencies/amalgamation.py`)

See the **Sibling tool** paragraph at the end of [Source Flattening](#source-flattening-flatteningpy).

## Source Flattening (`flattening.py`)

Polygon (offline + upload) and BOCA are **flat** judges: they compile each source in a single flat file namespace. A source organized under the Phase-1 mirrored layout (`#522`/`#523`/`#524`) -- living in a subdirectory, using `#include "../lib.h"`, or relying on custom `compilationFiles` -- builds locally but breaks on these targets unless its compilation closure is shipped flat with includes rewritten. `flattening.py` is the shared machine that does this (issues #525/#526/#527).

- **`assign_flat_names(paths, *, reserved={}, enforce_stem_unique=False)`** -- pure, package-independent naming. A globally-unique basename (and stem, when `enforce_stem_unique`) keeps its **bare basename**, so flat packages stay byte-identical to pre-flattening output. Collisions get a `__`-joined sanitized path rendering (`gens/a/gen.cpp` -> `gens__a__gen.cpp`), with a deterministic `__<n>` counter for residual clashes. `reserved` pins specific sources to fixed names (e.g. the checker -> `check.cpp`); reserved values must be mutually distinct. This single scheme closes #527 (same-basename generators/solutions colliding across directories).
- **`build_flat_namespace(sources, *, reserved, enforce_stem_unique)`** -> `FlatNamespace`. For each source `CodeItem` it collects the transitive quoted-`#include` closure (via `rbx.box.dependencies.graph.expand`, the #524 scanner) plus manual `compilationFiles`, assigns flat names, and rewrites C++ quoted includes to those names (`CppScanner.rewrite`). System/builtin headers (`<...>`, `testlib.h`, `rbx.h`, jngen/tgen) resolve to `target=None` and are left untouched. Out-of-package roots (e.g. the builtin checker) are read from their real path.
- **`FlatNamespace`** -- `.files` (each `FlatFile` has `.flat_name` + rewritten `.content` bytes), `.root_files()`/`.dep_files()`, `.flat_name_for(code)`, `.content_for(code)`, `.materialize(into_dir)`.

**Consumers:** Polygon offline (`polygon/packager.py:_flatten_sources` -> `files/` + `_get_files` declares deps), Polygon upload (`polygon/upload.py:_build_upload_namespace` -> one namespace over checker/interactor/validator/solutions/generators, deps shipped as RESOURCE, freemarker references flat **stems**), BOCA (`boca/packager.py:_embed_block` -> N heredocs in `checker.sh`/`interactor_compile.sh`). MOJ does not use flattening -- it amalgamates instead, see the sibling tool below.

**Guardrails:** `build_flat_namespace` errors with an actionable message rather than shipping a broken package in two cases: (1) a non-rewritable source (e.g. a Python generator, `can_rewrite=False`) with a *cross-directory* resolving dependency cannot be flattened; (2) a *rewritable* source (or dep) has a quoted include that escapes the package root (`#include "../../shared/lib.h"`) -- it resolves locally against the file's real location (so the package builds green) but its target is outside the package, so it is never shipped and the `..` spelling cannot survive flattening. Only `..`-bearing unresolved spellings trip case (2): bare builtins (`testlib.h`/`rbx.h`/`jngen.h`/`tgen.h`) and quoted system headers resolve on the judge, and a forward-only subpath either resolves in-package or fails locally too. Same-directory and system/builtin deps are fine.

**Sibling tool -- `rbx/box/dependencies/amalgamation.py`:** flattening ships a closure as N files in one flat namespace with includes *rewritten*. Some targets instead need **one file**: MOJ's checker bridge compiles `scripts/checker.cpp` with only `testlib.h` bound into the jail, and MOJ compiles a submission from a single source. `amalgamate(root, *, extra_roots, keep, scanner)` -> `AmalgamationResult` (`.content`, `.inlined`, `.kept`) *inlines* the closure instead, each file contributing once (keyed on resolved realpath, so diamonds collapse and cycles terminate), dropping `#pragma once` and leaving `<system>` includes alone. It is built on a new `DependencyScanner.reference_spans` splice capability (`can_splice`), which reports the byte span of a whole directive -- `rewrite` only renames the quoted path. Unlike flattening, resolution is *not* confined to the package root: `extra_roots` is how a caller makes builtin headers (`testlib.h`, `rbx.h`) inlinable without the library knowing what they are. An unresolvable quoted include raises `AmalgamationError` unless `keep` whitelists the spelling. It is package-agnostic and reusable by any other flat/single-unit target.

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
- Statement upload (statements v2, S12 #568): `upload.py:_build_bundle` calls `export.build_statement_bundle(statement, layout=export.FlatLayout())` — see [Statement Export Bundle](#statement-export-bundle-rbxboxstatementsexportpy) — and uploads `bundle.assets` by `str(bundled.dest)` (Polygon's flat resource name, `sample_<idx>__` for sample-scope assets), keeping the 1 MiB per-resource cap. `PolygonPackager.statement_export_params` is what forces the externalize+demacro build the bundle reads. The blocks arrive **already rewritten**, so `upload.py` owns no asset, naming or `\includegraphics` logic at all: `_collect_assets`/`_rewrite_includegraphics` (#595, audit #5/#6 — TexSoup parsing rather than substring replace, fixing root-level/double-extension references and dropping `*.in`/`*.out`/`*.rbx.tex` noise) are gone from here, living in `export.py`/`texsoup_utils.rewrite_includegraphics`. `upload.py`'s only remaining job at this seam is catching `export.StatementExportError` at the CLI boundary. Offline `problem.zip`/`contest.zip` statement embedding is a follow-up (#583)
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

**`extension.py`** -- env-level `BocaExtension` (`flags`, `minRunningTime`, `preferContestLetter`, `usePypy`) and per-language `BocaLanguageExtension` (`languages` list + required `template`). Both `model_config = extra='forbid'`. rbx v1 (#471) removed the legacy singular `bocaLanguage`, the env-level `languages` allowlist, the implicit `template` fallback, and `maximumTimeError` (#494). Removed fields are kept as fields flagged `Annotated[..., Removed()]` + `Field(deprecated='<migration hint>')`: the shared `RejectsRemovedFields` base (in `rbx/utils.py`) reads the flag and raises that hint at env load, so the explanation lives on the field. `template` is required whenever `languages` is set (`model_validator`), and `resolved_languages`/`primary_language`/`resolved_template` read only the plural fields.

### MOJ (`moj/`)

**`MojPackager`** (`rbx package moj`) -- extends `BasePackager` directly, targeting MOJ as [`cd-moj/mojtools`](https://github.com/cd-moj/mojtools) actually consumes it. It replaced a legacy `BocaPackager` subclass that emitted a shape MOJ no longer accepts -- an authored `tl`, a bundled checker bridge, `docs/enunciado.pdf`, and `001`-style test names with no samples. See [`moj/CLAUDE.md`](moj/CLAUDE.md) for the full picture; the load-bearing parts:

- **Calibration-only time limits.** MOJ *measures* the TL from `sols/good`; no `tl` is emitted, and `conf` carries `MEMLIMITMB` (peak RSS, replacing the legacy `ULIMITS[-v]`), `ULIMITS[-f]` and `TLMOD[calibrafactor]`.
- **Stub vs copy.** `scripts/compare.sh` is a byte-copy of mojtools' canonical stub (the bridge stays upstream -- a bundled copy once replicated a bwrap bug into 198 packages); only the in-jail `scripts/<lang>/{compile,run}.sh` are real copies.
- **Single-file checker.** The bridge binds only `checker.cpp` + `testlib.h` into the compile jail, so the checker (and every C/C++ solution) is amalgamated -- see [Source Amalgamation](#source-amalgamation-dependenciesamalgamationpy). Packaging refuses rather than shipping something that judge-errors on every test.
- **Naming/scoring.** `sample001…` plus `t<NN>_<group>_<NNN>`, so samples sort first in MOJ's lexicographic judging loop; `tests/score` for POINTS only.
- **`.moj-meta.json`.** Only the *content* fields the server accepts from a tar: `display_title` (always) and `languages` (the languages with an accepted solution, since MOJ can only calibrate those). The *access* fields (`public`/`public_at`/`owner`) are never written -- they are ignored from a tar anyway, and `public` is fail-closed server-side.
- **Markdown statements.** `task_types()` is `[BATCH]`; `statement_types()` is `[rbxTeX]` and `statement_export_params()` forces externalize+demacro, so the packager consumes [the export bundle](#statement-export-bundle-rbxboxstatementsexportpy) and converts each block TeX -> Markdown with pandoc -- which is the target dialect, since MOJ renders statements by running pandoc over them. `docs/enunciado.md` carries no title (MOJ injects the `<h1>` from `display_title`), the mandatory `## Entrada`/`## Saída`, and neither an examples section nor a fence (both trip `validate-problem.sh`). Sample explanations become `docs/notes/<sample>.md`, paired to the test **by name**. `--language` selects the statement, and `display_title` resolves from the same one. A package with no statement keeps the `DUMMY_STATEMENT` fallback. **`SubtreeLayout`'s first production consumer**; PDF figures are rasterized with poppler, so packaging refuses without it.
- `MojLanguageExtension` (key `moj`) mirrors `BocaLanguageExtension`: `languages` + required `template` + optional `flags`.

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
| `rbx package moj` | `MojPackager` | `--language` |
| `rbx package pkg` | `PkgPackager` | (none) |

All are guarded by `@package.within_problem`.

## Key Detail: Limits Profiles

Different judge systems have different time/memory limits. The `LimitsProfile` system (defined in `schema.py`) allows per-packager limit overrides. `limits_info.use_profile(name)` applies the correct profile during build and packaging.
