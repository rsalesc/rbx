# YAML `!include` fragments for shared configuration

**Issue:** [#822](https://github.com/rsalesc/rbx/issues/822) — Figure out a way for a
variant to inherit the same statement configuration as the main contest.

Supersedes the "YAML inheritance / `extends:` between variants" follow-up deferred in
[the multi-contest design](2026-05-06-multi-contest-design.md).

## Problem

A contest directory with variants duplicates nearly all of its configuration. In a real
package (`subreg-2026`), `contest.warmup.rbx.yml` differs from `contest.rbx.yml` in five
fields, yet of the two files' ~145 lines each, **~110 are byte-identical**:

| Field | Variant vs. canonical |
|---|---|
| `name` | differs (it is the identity) |
| `titles` | identical |
| `statements` (9 entries) | identical |
| `documents` (6 entries) | identical |
| `tutorials` (3 entries) | dropped by the variant |
| `vars` | 3 of ~6 leaf keys differ |
| `problems` | own list |

The duplication is not merely verbose, it silently rots. That package has already drifted:
`vars.short_titles.es` reads "Programação" in the variant where the canonical reads
"Programación". Nothing detects it; it ships in a PDF.

The duplication is also *manufactured*: `rbx contest add_variant` scaffolds a full copy of
the preset's contest file. The tool creates the problem it then cannot help you manage.

## Approach

Composition over inheritance: a `!include` YAML tag that splices another file's document
into a node. Shared configuration moves into fragment files that several contests point at.

```yaml
# contest.warmup.rbx.yml
name: warmup
titles: !include shared/titles.yml
statements: !include shared/statements.yml
documents: !include shared/documents.yml
vars:
  <<: !include shared/vars.yml
  warmup: true
problems:
- short_name: A
  path: warmup/reuniao
```

The variant drops the tutorials by simply not including them. There is no removal verb and
no merge contract to specify, which is the point: `!include` adds one mechanism to the
grammar rather than a per-field inheritance policy across seven fields.

### Alternatives considered

**File-level `extends:` between contest files.** A variant names a parent and rbx
deep-merges. Terser at the call site and keeps schema-driven editor validation intact, but
it requires a per-field merge contract (which lists merge by key, which dicts deep-merge,
what is never inherited), plus a removal verb for entries the parent defines and the child
does not want. It also only helps things in an inheritance relationship — two sibling
contest *directories* cannot share anything. Rejected in favour of the smaller, more
general mechanism; see "Future work" for layering it on later.

**Implicit inheritance from the canonical.** Every `contest.<id>.rbx.yml` silently extends
`contest.rbx.yml`. Zero syntax, but a variant file stops reading as what it is, and it does
nothing in dispatcher mode where the canonical is empty by construction.

**Drift detection only.** A check that flags divergent statement recipes across variants.
Catches the "Programación" bug but leaves 110 duplicated lines to hand-edit. Worth having
independently; not a substitute.

## Semantics

### Forms

Whole-node replacement, valid anywhere a value is expected:

```yaml
statements: !include shared/statements.yml
```

Composed with YAML's merge key, for mappings:

```yaml
vars:
  <<: !include shared/vars.yml
  warmup: true
```

`<<` is **shallow** — the second form replaces sibling keys wholesale rather than merging
into them. A variant that wants to override `vars.short_titles.pt` while keeping `en` must
either restate `en` or push the merge a level down:

```yaml
vars:
  <<: !include shared/vars.yml
  short_titles:
    <<: !include shared/short-titles.yml
    pt: Maratona SBC de Programação
```

Fragment granularity is therefore the knob users tune. This is a real ergonomic cost and
the docs must say so plainly.

Splicing several fragments into one list (`statements: [!include a.yml, !include b.yml]`)
is **not** supported in v1; it would yield a list of lists. Revisit with an `!include_seq`
tag if asked for.

### Path resolution

Relative to the **including file**, so a fragment directory is movable as a unit and a
fragment may itself include a sibling without knowing who loaded it.

Absolute paths are rejected. Paths that escape the package root are allowed but produce a
warning, because a package that reads outside itself does not survive being copied or
packaged; sharing across a monorepo of contests is nonetheless a legitimate use.

An include stack detects cycles and reports the full chain.

### Scope

The tag is implemented in the loader, so it works uniformly in `contest.rbx.yml`,
`contest.<id>.rbx.yml`, `problem.rbx.yml`, `env.rbx.yml` and `preset.rbx.yml`. Fragment
files have no schema of their own; they are whatever node they are spliced into.

## Architecture

Three consumers today read these YAML files, and all three must understand the tag. They
share one component: an **include-graph walker**.

```
                      ┌──────────────────────┐
                      │ include-graph walker │
                      └──────────┬───────────┘
             ┌───────────────────┼───────────────────┐
             ▼                   ▼                   ▼
      pydantic loader        writers           yaml_validation
      (yaml.safe_load)      (ruyaml RT)        (loc → file:line)
```

### 1. Loader

`rbx/utils.py:419` `model_from_yaml` is the single choke point (7 call sites) and today
does `model(**yaml.safe_load(s))`. It takes a *string*, so it has no base directory to
resolve includes against.

- Add `model_from_yaml_path(model, path)` alongside it; keep the string form for callers
  that genuinely have no file (it rejects `!include` with a clear error).
- Return the **transitive set of files read** so callers can invalidate on any of them.

**`!include` must be a node-tree rewrite, not a constructor.** The obvious implementation —
`SafeLoader.add_constructor('!include', ...)` — cannot support the merge-key form.
PyYAML's `flatten_mapping` resolves `<<` at the *node* level, before any constructor runs,
and rejects a value node that is not already a mapping:

```
yaml.constructor.ConstructorError: while constructing a mapping
expected a mapping or list of mappings for merging, but found scalar
```

So the loader instead composes the document to a node tree, walks it replacing every
`!include` `ScalarNode` with the composed root node of the fragment (recursively, carrying
each fragment's own directory and the include stack), and only then constructs. Verified
against the pinned PyYAML: with the rewrite in place,

```yaml
vars: {<<: !include frag.yml, b: 99, c: 3}   # frag.yml = {a: 1, b: 2}
top: !include frag.yml
items: !include list.yml                      # list.yml = [x, y]
```

loads as `{'vars': {'a': 1, 'b': 99, 'c': 3}, 'top': {'a': 1, 'b': 2}, 'items': ['x', 'y']}`.

The rewrite has a second payoff: substituted nodes keep the fragment's own `start_mark`,
which is most of what consumer 3 needs.

### 2. Writers

`save_contest` (`contest_package.py:320`) and `save_package` (`package.py:127`) write
`model_to_yaml(package)` — a full re-serialization from the pydantic model, in which the
include no longer exists. Left alone, `rbx contest add` would silently inline every
fragment and destroy the sharing.

The fix does **not** require threading provenance through the pydantic load. ruyaml's
round-trip mode preserves an unknown tag as a `TaggedScalar`, so a writer can walk the
ruyaml tree itself: to edit `problems`, follow the key, observe that its value is
`!include shared/problems.yml`, open that file with ruyaml and recurse. The edit lands in
the file that owns the node, with comments preserved, by the same mechanism
`promotion.py` and `creation.py` already use.

Verified: ruyaml loads `statements: !include shared/statements.yml` as a `TaggedScalar`
carrying `Tag('!include')` and the path as its value, and dumps it back byte-identically
with surrounding comments intact.

ruyaml needs one patch, though — it has its own `flatten_mapping` and rejects
`<<: !include` for exactly the same reason PyYAML does. A `RoundTripConstructor` subclass
that lifts merge-key `!include` pairs out of the node before calling `super()` and
reinserts them afterwards round-trips the merge form byte-identically too (verified). The
round-trip tree is only ever navigated and edited, never read semantically, so the
placeholder value ruyaml gives that pair does not matter.

Because a fragment may be shared, the writer reports the blast radius. It builds the
reverse map by globbing `contest*.rbx.yml` in the contest root and expanding each one's
include closure (cheap — the closures are already computed by the loader):

```
$ rbx -C warmup contest add O problems/foo
added O to shared/problems.yml (included by contest.rbx.yml, contest.warmup.rbx.yml)
warning: this affects 2 contests.
```

When a fragment is reached by more than one contest, the command prompts for confirmation
unless `--yes` is passed.

### 3. Validation and error positions

`rbx/box/yaml_validation.py` maps a pydantic `loc` tuple onto ruyaml `CommentedMap`/
`CommentedSeq` source positions to render a caret diagnostic. A `loc` that lands inside a
fragment must resolve to `shared/statements.yml:12`, not to a wrong line in the parent.
The same walker handles this: descend the `loc`, and when the walk crosses an `!include`
node, switch to the fragment's ruyaml tree and continue. Getting this wrong makes every
schema error in shared config point at the wrong file, which is the paper cut that would
make people abandon the feature.

### 4. Cache invalidation

Whatever hashes `contest.rbx.yml` for build invalidation must hash the transitive include
closure, or editing `shared/statements.yml` rebuilds nothing. The loader's returned file
set feeds this directly.

## Editor support

This is the known cost of the tag spelling. `yaml-language-server` does not understand
`!include`: it flags the tag as an error and does not validate fragment files at all, so
the `# yaml-language-server: $schema=` completion currently covering those ~110 lines is
lost on anything moved into a fragment.

Two softeners, both optional follow-ups rather than blockers:

- Publish per-node sub-schemas (`ContestStatements.json`, `ContestVars.json`, …) so a
  fragment can carry its own `$schema` header and be validated on its own terms.
- `rbx contest check` validates the fully-expanded model regardless, so the CLI remains a
  correct backstop for whatever the editor cannot see.

## Migration

- `rbx contest add_variant` scaffolds the thin form — `name`, `problems`, and includes
  pointing at the canonical's fragments — instead of a full copy of the preset file.
- New `rbx contest extract <field> <path>` lifts a node out of a contest file into a
  fragment and replaces it with an `!include`, preserving comments via ruyaml. Migrating
  `subreg-2026` is then four invocations plus deleting the variant's duplicated blocks.
- Nothing existing breaks: no current package uses the tag, and files without it take an
  unchanged code path.

## Testing

- Loader unit tests: whole-node include of a mapping and of a sequence, merge-key include,
  merge-key include nested one level down, nested include (fragment includes a fragment,
  resolved relative to *its* directory), cycle detection, absolute-path rejection,
  escape-root warning, missing-fragment error message.
- A regression test pinning the merge-key form specifically — it is the case that breaks if
  anyone reimplements `!include` as a plain constructor.
- `model_from_yaml` (string form) rejects `!include` with a message naming the path form.
- Writer tests: `rbx contest add` against a plain `problems`, against an included
  `problems` (lands in the fragment, comments preserved), and against a fragment shared by
  two contests (warns, prompts, `--yes` proceeds).
- Validation tests: a schema error inside a fragment reports the fragment's path and line.
- Cache test: touching a fragment invalidates the contest build.
- E2E fixture mirroring `subreg-2026`: canonical plus one variant sharing `statements`,
  `documents` and `vars` fragments; assert both contests build statements and that the
  variant's `vars` override applies while the shared keys do not drift.

## Future work

- `extends:` between contest files, layered on top. It composes cleanly: `!include` shares
  nodes, `extends:` shares whole models. If added, a child clears an inherited section with
  an explicit empty value (`tutorials: []`), distinguished from an omitted field via
  pydantic's `model_fields_set`.
- Drift detection in `rbx contest check`: warn when two variants declare statements with
  the same `name` but different recipes, catching duplication that predates any migration.
- `!include_seq` for splicing multiple fragments into one list.
