# Statements v2 — Design

Tracking issue: [#556 — Design statements v2](https://github.com/rsalesc/rbx/issues/556)
Status: **approved design**, ready to break into implementation issues.
Date: 2026-06-09

## 1. Motivation

The current statement engine accreted a lot of surface complexity: statement
inheritance (`extends`), param overriding (`override` / `inheritOverride` /
`configure` / `steps`), and three different asset sources (contest, problem,
sample explanations) that each resolve relative to different working
directories. The result is a "cwd mess" that is hard to reason about and hard to
keep correct (e.g. samples are injected by absolute path to dodge relative-import
problems, which then forces the Polygon packager into special-casing).

v2 simplifies the **configuration surface** (YAML) and the **path-resolution
model**, while keeping the builders themselves largely intact. This is a
**breaking change** shipped with v1. There is **no migration path** — the old
schema simply stops working (the change is intentionally undocumented as a
migration).

## 2. Decisions (resolved during brainstorming)

1. **Contest is required.** A problem statement cannot be built unless it is part
   of a contest. Initially this is a *hard error* outside a contest. A
   default-template fallback (so contest-less problems build) is a **deferred
   follow-up**, not part of the first cut.
2. **`params` ≠ `vars`.** `params` is the statement's *own* parameters (today's
   `Statement.vars`), renamed to stop it from being merged into the same object
   as problem `vars` and contest `vars`. In v2 these are **separate namespaces**
   in the template context — all injected, none merged.
3. **Match disambiguation is explicit, not silent.** For a standalone problem
   build, the candidate contest statements are those with the same
   `(language, variant)` *that carry a `standaloneProblemTemplate`*. Exactly one
   must exist; **0 or >1 is a hard config error** the user fixes (no `--using`
   flag, no first-wins).
4. **Path resolution: full overlay, everything relative.** The temp build tree
   mirrors the contest package as an overlay plus each problem in an isolated
   folder; samples are mirrored in too. Everything is referenced by **relative**
   paths so the generated TeX is **portable/self-contained**. The only injected
   LaTeX construct is `\subimport` in the joining template; **no user TeX is
   parsed or rewritten.**
5. **Three sections, one shared schema.** `statements` and `tutorials` are
   mechanically identical (join on problems; full type set). `documents` reuses
   the same model minus joining, restricted to jinja/static types.
6. **Build toggles leave the schema.** `externalize` and `demacro` are removed
   from the user-facing schema; the Polygon packager turns them on at export
   time.
7. **`extends` stays, but limited.** It inherits only build-recipe fields, never
   identity/targeting fields (see §5).
8. **No migration script.** Hard flip to the new behavior.

## 3. Schema

### 3.1 Problem (`problem.rbx.yml`)

Two sections, `statements` and `tutorials`, sharing one model. Note what is
**gone**: `assets`, `steps`, `configure`, `template`, `inheritFromContest`;
`vars` is renamed to `params`.

```yaml
statements:
  - language: en
    variant: default          # optional; (language, variant) UNIQUE within the problem
    file: statements/statement-en.rbx.tex
    type: rbxtex              # rbxtex (default) | rbxmd | tex | md | pdf
    params:
      show_limits: true       # the statement's OWN params — own namespace

tutorials:
  - language: en
    file: statements/tutorial-en.rbx.tex
    type: rbxtex
    params: {}
```

- **Asset-scope rule:** every file under the *directory containing `file`* (here
  `statements/`) is implicitly available during the build. Imports outside that
  directory are unsupported by construction (this bounds the overlay — §6).
- `variant` defaults to a sentinel (`default`). `(language, variant)` is the join
  key and must be unique within the problem.

### 3.2 Contest (`contest.rbx.yml`)

Same two sections plus `documents`. The contest now owns the templates.

```yaml
statements:
  - name: main-en             # UNIQUE within contest
    language: en
    variant: default          # pairs with problem (language, variant); NOT unique
    file: statements/contest-en.rbx.tex          # the joined contest document
    type: rbxtex
    standaloneProblemTemplate: statements/problem-standalone.rbx.tex
    contestProblemTemplate:    statements/problem-in-contest.rbx.tex
    params: { ... }

documents:                    # infosheets etc. — NEVER join on problems
  - name: infosheet-en
    language: en
    file: statements/infosheet-en.jinja.tex
    type: jinjatex            # jinjatex | jinjamd | tex | md | pdf  (no rbx* — nothing to join)
    params: { ... }
```

- `variant`, `params`, `standaloneProblemTemplate`, `contestProblemTemplate` are
  meaningful **only for `rbxtex`/`rbxmd`** (the joinable types). For `tex`/`md`/
  `pdf` they are inert/forbidden.
- `documents` is the shared model with joining removed and types restricted to
  jinja/static. "Documents can't join" is a **schema** constraint, not a runtime
  surprise.

### 3.3 Validation rules

- Problem: `(language, variant)` unique.
- Contest: `name` unique; `(language, variant)` may repeat.
- Template/`variant`/`params` fields only allowed for `rbx*` types.
- `documents` restricted to `jinjatex | jinjamd | tex | md | pdf`.

## 4. Template-context namespaces

Today everything collapses into one merged `vars`. v2 keeps them **separate**:

| Name | Contents | Available in |
|---|---|---|
| `params` | *this statement's* own params | all renders |
| `vars` | the **problem/package** vars | problem renders |
| `contest` | `title`, `location`, `date`, `contest.vars` | always (contest required) |
| `problem` | `title`, `short_name`, `limits`, `groups`, `samples` | problem renders |
| `problems` | list of the above | contest join only |
| `lang`, `languages`, `keyed_languages` | environment languages | all renders |

A template reads `\VAR{params.show_limits}` (statement), `\VAR{vars.author}`
(problem), `\VAR{contest.title}` — three distinct, non-colliding sources. This is
the concrete fix for the "huge mess" #556 calls out, and it also removes the
old precedence footgun where a contest could silently override a problem's
statement var.

New per-iteration handles exposed to templates:

- `problem.import_dir` / `problem.import_file` — the `\subimport` handle for a
  problem in the contest join.
- `sample.dir` — the `\subimport` base for a sample explanation.
- `sample.input` / `sample.output` — **root-relative** paths for verbatim I/O
  display (see §6.4).
- `sample.explanation_file` — present when the sample has an explanation.

## 5. `extends`

`extends` shares the *build recipe* across languages/variants; it **never**
shares identity/targeting fields.

- **Inherited** (child overrides parent; `params` deep-merges key-by-key):
  `type`, `file`, `params`, and — contest-only —
  `standaloneProblemTemplate`, `contestProblemTemplate`.
- **Never inherited** (always explicit on the child): `name`, `language`,
  `variant`.
- **Reference syntax:**
  - Problem statements (no `name`): a **string** for language-only
    (`extends: en`) or a **dict** when a variant is needed
    (`extends: { language: en, variant: short }`).
  - Contest statements: by `name` (`extends: main-en`).
- Resolved by a slimmed-down expander: the same topological sort over `extends`
  chains, but an **allowlist merge** instead of a full pydantic deep-merge.
  Cycles and dangling references are errors.

Motivating examples:

```yaml
# contest.rbx.yml — reuse the two template paths across languages
statements:
  - name: main-en
    language: en
    file: statements/contest-en.rbx.tex
    type: rbxtex
    standaloneProblemTemplate: statements/problem-standalone.rbx.tex
    contestProblemTemplate:    statements/problem-in-contest.rbx.tex
  - name: main-pt
    language: pt
    extends: main-en           # inherits type + both templates
    file: statements/contest-pt.rbx.tex   # overrides just the joined-doc file
```

```yaml
# problem.rbx.yml — pt reuses an en source that switches content via blocks
statements:
  - language: en
    file: statements/statement.rbx.tex
    type: rbxtex
    params: { show_limits: true }
  - language: pt
    extends: en                # inherits file + type + params
    params: { show_limits: false }   # override one key; rest merged from en
```

## 6. Temp-dir overlay & path resolution

The unifying rule applied **recursively at three levels**, each scoped by
`\subimport`:

```
contest root  ⊃  per-problem folder  ⊃  per-sample folder
```

Stated once: *the directory containing a `.tex` file is its asset scope; that
subtree is overlaid into the file's folder and `\subimport`ed.* Statement files,
the contest `file`, and sample explanations all obey it.

### 6.1 Standalone — `rbx st b`

One problem, borrowing the contest's `standaloneProblemTemplate`. A single
**merged overlay**: contest chrome + the problem's statement-dir subtree +
per-sample folders, all in one root. The rendered *full* document compiles in
place, so every path is a plain relative.

```
build/st/<lang>-<variant>/                 # overlay root = problem asset root
├── statement.tex                          # rendered standaloneProblemTemplate (blocks inlined)
├── statement.pdf                          # final → copied to build/statement-<lang>.pdf
├── icpc.sty   logo.png                    # contest chrome (from contest statement-file dir)
├── imgs/fig.png                           # problem assets (mirror of problem's statements/ subtree)
├── included.tex                           # a partial the statement \inputs
└── .samples/
    ├── 000/                               # sample 0 root (own \subimport base)
    │   ├── in   out                       # generated I/O, mirrored (relative now)
    │   ├── explanation.tex
    │   └── sample0-diagram.png            # overlaid from the explanation's source-dir subtree
    └── 001/
        ├── in   out
        └── explanation.tex
```

- Problem assets resolve as plain relatives (the doc sits at this root); contest
  chrome (`icpc.sty`) lands here too so `\usepackage{icpc}` just works.
- **Collision risk** (a problem file vs a chrome file with the same name) is the
  only downside of merging; we **detect and error** on it. Merging is safe here
  because there is exactly one problem and one contest — no cross-problem
  collisions are possible.

### 6.2 Contest join — `rbx contest st b`

Contest chrome overlaid at the **root**; each problem isolated under
`.problems/<SHORT>/`, scoped by `\subimport` so two problems can both ship
`imgs/fig.png` with zero collision.

```
build/contest-st/<name>/                   # overlay root = contest asset root
├── contest.tex                            # rendered contest `file` (joining document)
├── contest.pdf                            # final contest statement
├── icpc.sty   logo.png                    # contest chrome
└── .problems/
    ├── A/statements/                      # problem A root (\subimport base)
    │   ├── statement.tex                  # A rendered via contestProblemTemplate (a FRAGMENT)
    │   ├── imgs/fig.png
    │   └── .samples/000/{in,out,explanation.tex,...}
    └── B/statements/                      # problem B root, fully isolated from A
        ├── statement.tex
        ├── diagram.png                    # even if named like A's, never collides
        └── .samples/000/{in,out}
```

The contest `file` template joins via `\subimport`, iterating `problems`:

```latex
%- for problem in problems
    \subimport{\VAR{problem.import_dir}}{\VAR{problem.import_file}}
%- endfor
```

Inside `.problems/A/statements/statement.tex`, every relative path rebases to
`.problems/A/statements/` because `\subimport` sets the import base. **The same
problem-root-relative references work unchanged in standalone mode** (§6.1) —
that symmetry is what lets one rendering of the problem content be valid in both
contexts.

### 6.3 Sample folders (recursive)

Each sample gets its **own folder**, a mini-overlay of its explanation's
source-directory subtree, `\subimport`ed by the problem template:

```latex
%- for sample in problem.samples
    \example{\VAR{sample.input}}{\VAR{sample.output}}        %% root-relative I/O — see §6.4
    %- if sample.explanation_file is defined
        \subimport{\VAR{sample.dir}}{explanation}            %% rebases into the sample folder
    %- endif
%- endfor
```

- **Whole-directory overlay (intended):** because we never parse TeX to find
  imports, the explanation's *entire* containing directory is overlaid into each
  sample folder. If samples are flat in a shared `documents/samples/`, that dir
  is duplicated into each `000/`, `001/`. This duplication is accepted on purpose
  — it makes each sample folder **hermetic**. No source-layout convention is
  imposed.
- Interactive-sample chunks mirror under the sample folder too, referenced
  relatively.

### 6.4 The verbatim nuance (spike first)

The `import` package only rebases `\input` / `\include` / `\includegraphics` /
`\subimport`. It does **not** rebase verbatim file-readers like `\VerbatimInput`,
which is what `\example` uses to print sample I/O. Since `pdflatex` runs from the
overlay **root** in both modes, the portable fix is to feed I/O paths as
**root-relative** (`sample.input` = `.problems/A/statements/.samples/000/in`)
while the *explanation* goes through `\subimport` (base-relative). Both are
relative → TeX stays portable; they are simply anchored differently (root for
verbatim I/O, import-base for LaTeX content). This must be validated by a spike
before the builder contract is locked.

> **✅ Validated (S1, #557).** The spike at
> `docs/plans/spikes/2026-06-09-statements-v2-path-resolution/` compiles the full
> contest→problem→sample overlay end-to-end on the first `pdflatex` pass, zero
> warnings. Confirmed: nested `\subimport` (3 levels), `import.sty` auto-rebases
> `\includegraphics` to the import base at every depth (**no `\graphicspath` /
> `TEXINPUTS` needed**), same-named assets across problems don't collide, and
> `\VerbatimInput` requires **root-relative** I/O paths (proven by a negative
> control). No design change required — see the spike README for details.

### 6.5 Properties bought

- **Portable, self-contained TeX** — no absolute/temp paths leak in; `tar` the
  overlay and it compiles anywhere. Polygon export stops needing its
  absolute-path special-case.
- **Collision-proof joins** — `\subimport` scoping means problems never fight
  over an asset name.
- **No TeX parsing/rewriting** — only `\subimport` in the contest template +
  mirroring files on disk.
- **Two clearly-typed templates:** `standaloneProblemTemplate` → a *full*
  document; `contestProblemTemplate` → a *fragment* meant to be `\subimport`ed.

## 7. Pipeline, builders, CLI

### 7.1 Reused / new / deleted

**Reused** (the issue's "builders stay similar"): rbxTeX block-extraction +
template render, `tex→pdf` via pdflatex with rerun loop, pandoc for md, the
LaTeX Jinja env, TikZ externalization, demacro.

**New:**
- **Overlay stager** — mirrors statement-dir subtree + contest chrome +
  recursive per-sample folders; collision detection. Replaces today's
  per-builder `prepare_assets` flatten.
- **Contest-aware resolver** — standalone candidate resolution (error on 0/>1);
  join matcher; "contest required" error. Replaces `statement_overriding.py` +
  `inheritFromContest`.
- **Two render modes** sharing the block-extraction core: *full doc*
  (`standaloneProblemTemplate`, compiled in place) vs *fragment*
  (`contestProblemTemplate`, `\subimport`ed).
- **Namespaced context** + new template handles (§4).
- **pdflatex runs from the overlay root** in both modes.

**Deleted / replaced:**
- `Statement`: `assets`, `steps`, `configure`, `template`, `inheritFromContest`;
  `vars`→`params`.
- `ContestStatement`: `override`, `inheritOverride`, `match` (→ `variant`),
  `joiner` (→ implicit from type).
- The whole `statement_overriding.py` module.
- `expander.py` full deep-merge → slimmed allowlist merge.
- Per-builder flat asset dirs and absolute sample-path injection.

`extends` is **kept** (slimmed, §5).

### 7.2 CLI surface

- `rbx st b [names]` — standalone problem statements →
  `build/statement-<lang>[-<variant>].pdf`.
- `rbx contest st b` — joinable contest statements → contest PDF; plus
  `documents` emitted without joining.
- `tutorials` / `documents` — parallel commands reusing the same engine. Exact
  spelling is cosmetic and can be settled during implementation.

## 8. Out of scope / deferred

- **Default-template fallback** so contest-less problems build (initially it
  errors).
- CLI command spelling for tutorials/documents.

## 9. Work breakdown (implementation issues)

Suggested phases and dependencies. Each item is intended to be a single,
reviewable PR.

**Phase 0 — de-risk**
- **S1 (spike): LaTeX path-resolution proof.** Hand-build a minimal overlay
  (contest → 2 problems → samples with figures) and confirm nested `\subimport`
  + root-relative `\VerbatimInput` for I/O + chrome resolution all compile. Locks
  §6.4. *No product code.*

**Phase 1 — schema**
- **S2: v2 schema models.** New problem + contest models (statements / tutorials
  / documents; `params`, `variant`, templates; shared model). Delete old fields
  and `statement_overriding.py`. Validation rules (§3.3). *Depends on S1 only for
  field shape confidence.*
- **S3: `extends` v2 + slim expander.** Allowlist merge; reference resolution
  (string/dict for problem, name for contest); topo sort; cycle/dangling errors.
  *Depends on S2.*

**Phase 2 — engine core**
- **S4: overlay stager.** Mirror statement-dir subtree → problem root; overlay
  contest chrome; collision detection for the standalone merge. *Depends on S2.*
- **S5: namespaced context + template handles.** `params` / `vars` /
  `contest.vars` split; `problem.import_dir` / `import_file`; wire into builders.
  *Depends on S2.*
- **S6: recursive sample staging.** Per-sample folders, whole-dir explanation
  overlay, root-relative I/O, `\subimport` explanations, interactive chunks.
  *Depends on S4.*
- **S7: resolver + matching.** Standalone candidate resolution (0/>1 errors);
  join matcher; contest-required error. *Depends on S2.*

**Phase 3 — builders & build modes**
- **S8: builders rework + two render modes.** Adapt rbxTeX / tex2pdf / jinja / md
  builders to operate on the overlay; full-doc vs fragment; pdflatex from root.
  *Depends on S4, S5.*
- **S9: standalone build (`rbx st b`) end-to-end.** Wire resolver → stager →
  builder for the merged-overlay standalone path. *Depends on S6, S7, S8.*
- **S10: contest join (`rbx contest st b`) via `\subimport`.** Assemble the
  recursive overlay and join via `\subimport`; emit `documents` without joining.
  *Depends on S6, S7, S8.*

**Phase 4 — surrounding work**
- **S11: preset templates + bundled defaults.** Rewrite problem / contest / sample
  templates for v2 (subimport, namespaces, sample folders). *Depends on S8–S10.*
- **S12: Polygon packager update.** Consume the now-portable TeX; remove the
  absolute-path special-case; flip `externalize` / `demacro` at export. *Depends
  on S10.*
- **S13: tests + e2e port.** Update unit tests and e2e fixtures to v2. *Depends on
  S9, S10.*
- **S14: docs update.** Document the new statement model on the docs site.
  *Depends on S9, S10.*

**Deferred**
- **S15: contest-less default-template fallback.** Bundled default template so
  `rbx st b` works outside a contest. Separate, later.
