# Design: explicit `assets` field for Polygon statement resources (#595)

Date: 2026-06-11
Issue: #595 (supersedes/closes audit findings #5 and #6 from
`docs/plans/2026-06-10-polygon-statement-upload-audit.md`). Sibling of #590.

## Problem

The Polygon statement-upload path (`rbx package polygon -u`) decides *which files
to ship as statement resources* by recursively globbing **only the directory that
contains the statement `file`** — `_statement_asset_files` in
`rbx/box/packaging/polygon/upload.py`. That implicit rule is simultaneously:

- **too broad** — it ships `*.in` / `*.out` / `*.rbx.tex` (sample I/O and
  explanation *sources*) as Polygon statement resources (audit finding #5, noise);
- **too narrow** — any asset referenced from *outside* the statement directory is
  never uploaded, leaving a dangling `\includegraphics` on Polygon.

### The concrete bug

A sample explanation that lives outside the statement folder and references an
image in its own directory:

```
statement/statement.rbx.tex      # statement file -> implicit asset scope = statement/
tests/samples/000.in             # manual sample, outside statement/
tests/samples/000.tex            # explanation: \includegraphics{diagram.png}
tests/samples/diagram.png
```

- **PDF channel — correct.** `sample_staging.stage_samples` overlays the
  explanation's *own* directory into `.samples/<idx>/`, so the template's
  `\subimport` makes `\includegraphics{diagram.png}` resolve base-relative.
- **Polygon channel — broken.** `tests/samples/diagram.png` is not under
  `statement/`, so `_statement_asset_files` never collects it, there is no remap
  entry, and the uploaded `notes` reference a resource that does not exist.

The #589 fix for finding #4 (separate-file explanations now reach `notes`) made
this visible: the explanation text now uploads, carrying a `\includegraphics`
whose target was left behind.

## Key enabling fact (verified)

For the standalone build that the Polygon upload reads, `render_problem_tex` is
called with `problem_root = overlay_root` and `root_prefix=''`
(`build_statements.py:319-333`). `stage_samples` overlays each sample's
explanation-source directory into `.samples/<idx>/`
(`sample_staging.py:130-140`). Therefore the external `diagram.png` already lands
in the overlay at `build/statements/st/<lang>-<variant>/.samples/<idx>/diagram.png`
— exactly the directory `build_statements.get_statement_dir(statement)` returns to
the upload path.

**Consequence:** the fix lives entirely in the upload path. The build already
stages everything needed; no new build artifact or manifest is required.

## Decisions

1. **Architecture: upload-side resolution + rewriting** (not a build-side
   manifest). Faithful to v2's "the upload reads the overlay"; smallest blast
   radius.
2. **`extends` semantics: child replaces parent** for `assets` (same as
   `file`/`type`). Runtime image/PDF defaults concatenate on top regardless.
3. **Preset stays minimal — no demo image.** This is an explicit deviation from
   the issue's AC4 ("default preset uploads a real in-statement image"). The
   user's standing preference is a lean, ready-to-increment preset; demo assets
   that every new problem must delete do not belong there. The in-statement-image
   worked example is demonstrated by an **e2e testing package** instead.

## Out of scope

- Sample-explanation **TikZ** externalization — tracked by #590 (finding #2).
  This issue is about *images/PDFs that already exist on disk*.
- Staging arbitrary out-of-tree `assets` into the overlay so the *PDF* can
  reference them. `assets` here governs the Polygon resource upload set; PDF
  availability still requires staging, which already holds for the statement and
  sample subtrees the defaults cover.

## Design

### 1. Schema + inheritance

- Add to `BaseStatement` (`rbx/box/statements/schema.py`):

  ```python
  assets: List[str] = Field(
      default_factory=list,
      description='Globs (relative to the package root) selecting files to ship '
      'as statement resources (e.g. images/PDFs). Inherited via `extends`. At '
      'build time the default image/PDF globs over the statement subtree and each '
      'sample subtree are concatenated to this list.',
  )
  ```

- Globs resolve against the **package root** with `Path.glob` (so `**` works),
  match files only, dedup, deterministic sort. A small pure helper
  (`_resolve_asset_globs(root, globs) -> List[Path]`) makes this unit-testable.
- Add `'assets'` to `_PROBLEM_ALLOWLIST` and `_CONTEST_ALLOWLIST`
  (`rbx/box/statements/expander.py:34`). The existing `_merge` inherits any
  allowlisted field the child did not set explicitly → child replaces parent.

### 2. Asset resolution model (three scopes), in `upload.py`

Replace `_statement_asset_files`'s `rglob('*')` with scope-aware collection:

- **Statement-scope** — image/PDF (`*.png`, `*.jpg`, `*.jpeg`, `*.pdf`,
  recursive) under `statement.file.parent`, **∪** `assets` glob matches that fall
  under the statement dir (lets users ship `.svg`/`.eps`/etc. beyond the
  defaults). Referenced **statement-dir-relative**; flat name `a/b -> a__b.ext`.
  Used in `legend`/`input`/`output`/the `notes` block. Drops
  `*.in`/`*.out`/`*.rbx.tex` (**fixes finding #5**).
- **Sample-scope** — image/PDF (recursive) under each overlay `.samples/<idx>/`
  (folder `{idx:03d}` ↔ explanation index `idx`). Uploaded under a per-sample
  namespace `sample_<idx>__<rel>.ext`; rewrites **only that sample's
  explanation**. This is what fixes the bug: the explanation's sibling image is
  now in the upload set. Bounded duplication when several samples share one
  source dir (each namespaces its own copy); only referenced ones matter for
  integrity.
- **Out-of-tree `assets`** — glob matches outside both subtrees: upload by a
  flattened name (`assets/logo.png -> assets__logo.png`), **no auto-rewrite**
  (referenced by the uploaded flat name only), per the issue's scope note.

### 3. Upload rewrite (fixes finding #6)

- **Uniform remap:** record a remap entry for **every** uploaded asset, including
  root-level ones (today a root-level `pic.png` gets no entry and only resolves by
  stem coincidence).
- **Parser-based rewrite:** replace the naive per-key `str.replace`
  (`_replace_resources`) with a TexSoup pass over `\includegraphics` arguments
  (TexSoup is already a dependency; see `polygon_utils`/`texsoup_utils`). Match a
  ref both with and without extension, eliminating the `imgs__fig.png.png`
  double-extension bug. **Channel-anchored:** statement-scope remap for
  `legend`/`input`/`output`/the `notes` block; per-sample remap applied to each
  explanation *before* they are merged into `notes`.

### 4. e2e + unit tests

- New pdflatex fixture `tests/e2e/testdata/polygon-explanation-external-assets/`:
  manual samples, their explanations, and the explanation images all **outside**
  the statement directory; plus an in-statement image declared via `assets` to
  cover the AC4 worked example (moved here from the preset). Assert (a) the
  explanation image is uploaded and the `notes` `\includegraphics` resolves
  (`resources_referenced_consistent`), and (b) `*.in`/`*.out`/`*.rbx.tex` are not
  among the uploaded resources. Because the fix lands in this PR, this scenario is
  a **passing** assertion (not xfail).
- Unit tests: `assets` glob resolution (dedup/sort/`**`, files-only); expander
  inheritance through `extends` (child replaces parent); the TexSoup rewrite
  (with-extension/double-extension, root-level, sub-dir); scope classification.

## Acceptance mapping

- Referential integrity, incl. external sample images — §2 sample-scope + §3.
- Resources restricted to `assets` + defaults; no `.in`/`.out`/`.rbx.tex` — §2
  statement-scope (supersedes finding #5).
- `assets` honored through `extends` — §1 expander allowlist.
- Worked in-statement-image example via `assets` — §4 e2e package (deviation:
  not the preset, per decision 3).
