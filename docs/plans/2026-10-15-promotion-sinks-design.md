# Promotion sinks: one promote for every source and destination

Status: approved (brainstorm 2026-10-15), implementing.

## Problem

"Promotion" grew up in three places with three shapes:

| Surface | Source | Destinations | Mode |
|---|---|---|---|
| `rbx testcases promote`, testplan lens | a testplan statement | manual (glob) groups only | move |
| `rbx stress` prompt, `add-finding`, stress view | a stress finding | `.txt` script groups (append at EOF) or manual groups | copy |
| `rbx irun` | an ad-hoc input | none | -- |

The destinations are the poorest part. A script group can only be appended to
at the end of the file, so a script shared by several groups (a problem-level
`generatorScript`, or `@testgroup` blocks) gets an untagged line every group
picks up. There is no way to turn a generator call into a `@copy`, to put a
test inside a `@testgroup`, to address a subgroup, or to move a test between
groups.

## Model: source x sink x form x mode

**Sources** -- what is being promoted. Each has a *recipe* (a generator call
that makes it), *bytes* (an input file), or both, and possibly an *answer*.

| Selector | Source | Recipe | Bytes | Answer | Removable (move) |
|---|---|---|---|---|---|
| `script:line` | a testplan statement | call statements | always (generated) | `@copy` sibling `.ans` | rbx-format `.txt` scripts |
| `group/index` | a built test | when from a call | always | glob / `@copy` / inline `.ans` | script statements and glob files |
| `finding:K` | a stress finding | its seeded call | its input | -- | never (always a copy) |
| `file:IN[:ANS]` | a file on disk | -- | `IN` | `ANS` | never (always a copy) |

Tests from inline `testcases:` lists, `generators:` lists, dynamic scripts and
`box`-format scripts can be copied but not moved: removing them is not
supported, so promoting them without `--keep-source` is refused, naming the flag.

**Sinks** -- where a test can be inserted. They are **derived** from the
package; nothing is declared. Focus is on testplans and existing globs:

- **glob** -- a group or subgroup whose `testcaseGlob` contains a `*` and ends in
  `.in`. Takes bytes: the file is written by filling the glob's last `*`.
- **plan** -- a group or subgroup whose effective `generatorScript` (its own, or
  the problem-level default it inherits) is a static rbx-format `.txt` file.
  Takes a recipe line or a `@copy` line. Its **scope** is `None` (top level)
  when the script backs only this one group key, and the key itself
  (`@testgroup key { ... }`) when several keys share the script, since an
  untagged line would reach all of them.

Sinks are addressed by the group key (`samples`, `main`, `main/large`). A key
backed by both a glob and a script (illegal today: `check_oneof`) cannot occur.
`samples` is not a sink kind but a role: whatever backs the `samples` group.

**Form** -- `recipe` or `copy`. `@input` is never a promotion form.

- A glob sink always takes bytes.
- A plan sink defaults to `recipe` when the source has one, else `copy`.
  `--as recipe|copy` overrides; `recipe` on a bytes-only source is an error.

**Mode** -- move by default; `--keep-source` copies. Moving removes the source
statement (and the comment lines directly above it), or a glob test's `.in` and
`.ans`. A moved `@copy` also deletes the file it copied, unless another test
of the package still reads it.

## Placement

- **Same plan, routed to the target key** (the source statement is in the
  sink's script and `_group_matches` routes it to the sink's key): the
  statement is **replaced in place**, keeping the comments above it. This is
  "freeze": `gen 5` becomes `@copy tests/main/007.in`, and no index moves. When
  the source already has the requested form there, nothing changes.
- **Anywhere else**: at the **end of the target scope** -- end of file for a
  top-level scope, or just before the closing `}` of the last `@testgroup`
  block whose full path is the key. If no such block exists, a new
  `@testgroup key { ... }` is appended to the file.

Lines inside a block are indented like the block's existing statements (two
spaces when it has none).

## `@copy` paths: inferred, overridable

A `@copy` needs a file on disk, and nothing declares where. rbx **suggests**
one and the setter can **override** it:

1. **Infer from siblings.** Take the `@copy` statements routed to the same key
   in the same script (same scope). Pick the directory most of them share and
   generalize their names around the varying part, dropping digits from the
   common prefix and suffix: `edge-001.in`, `edge-002.in` -> `tests/edge/edge-*.in`.
2. **Fallback convention**: `tests/<key>/*.in`.
3. **Fill** the pattern's `*` with the next stem after the highest numeric stem
   among the siblings and the files on disk, zero-padded to their width (at
   least 3): `edge-003`. With no numeric stems, the lowest free `000`, `001`...
4. **Override**: `--name STEM` fills the suggested pattern; `--path P` replaces
   it (a path with a `*` is a pattern, filled as above; one without is used
   verbatim). Either must end in `.in`, stay inside the package, and not land on
   an existing file or under another group's glob (which would silently add the
   test to that group too).

Glob sinks keep today's rule (`--name`, else the lowest free counter).

Answers travel with bytes: when the source has an answer and the form is
`copy`, it is written as the `.ans` sibling of the new file, which glob and
`@copy` tests both already read. rbx never generates an answer when
promoting; the main solution does at build time.

## One plan, applied by rbx or by the editor

Every promotion is computed as a **plan**: an ordered list of file changes.

```json
{
  "sink": {"name": "main", "kind": "plan", "path": "tests/plan.txt", "scope": null},
  "changes": [
    {"path": "/abs/tests/plan.txt", "action": "modify", "before": "...", "after": "..."},
    {"path": "/abs/tests/main/007.in", "action": "create", "from": "/abs/.rbx/.../003.in"},
    {"path": "/abs/tests/old/001.in", "action": "delete"}
  ],
  "promoted": [{"source": "tests/plan.txt:3", "test": "main/2", "form": "copy", "to": "tests/main/007.in"}],
  "skipped": []
}
```

`create` names the file to copy bytes from rather than inlining them (inputs
can be megabytes); for a generated source that is the generated input in the
build folder, which the dry run produces. Creating a group edits
`problem.rbx.yml` (or the `!include` fragment owning `testcases`) and appears
as a `modify` of that file, computed by a new `EditSession.pending()` that
renders without writing.

`rbx testcases promote ... --dry-run --json` prints the plan. Without
`--dry-run`, rbx applies it: checks first (creates must not exist, deletes
must, modifies must still read `before`), then creates, then modifies, then
deletes, so a failure never loses the only copy of a test.

## CLI

```
rbx testcases promote [SOURCE...] [--to SINK | --new-manual NAME --glob G | --new-script PATH]
                      [--as recipe|copy] [--name STEM | --path P] [--keep-source]
                      [--dry-run] [--list-sinks] [--json]
```

- `SOURCE`: `script:line`, `group/index`, `finding:K`, `file:IN[:ANS]`.
  Omitted: interactive selection, as today.
- `--list-sinks [SOURCE...] --json`: one row per sink -- `{name, kind, path,
  scope, forms, form, suggested}` -- where `forms`/`form` are what the given
  sources can be written as there and the default, and `suggested` is the
  pattern a `copy` would fill. Rows are ordered for a picker: the sink the
  sources already live in, then `samples`, then the rest in package order.
- `--group/-G` stays as an alias of `--to`, and `--list-groups` keeps printing
  the old manual-only rows (hidden), so an older extension keeps working.
- `add-finding` keeps its flags and JSON; it becomes a thin wrapper over the
  same core with `finding:K` sources and `--keep-source` semantics, and keeps
  its dedup (a call or input the group already has is skipped).
- The `rbx stress` end-of-run prompt uses the same sink list and core.
- Interactive mode: checkbox of tests, a sink picker (with "new manual group" /
  "new script group"), a form choice when both apply, and the batch filename
  editor around the suggested pattern.

## VS Code

One host class, `Promoter`, replaces the two flows (`StressPromoter`'s and the
testplan lens's). Every entry point builds a source selector and calls
`promoter.promote(root, sources, label)`:

| Entry point | Source |
|---|---|
| testplan lens / context menu "Promote…" (now also on `@copy` and `@input`) | `script:line` |
| Stress view finding "Promote" | `finding:K` (+ `--session`) |
| Run / Tests view testcase row "Promote This Test…" | `group/index`, or `file:` for an ad-hoc `irun` row |
| Editor / explorer "Promote This File as a Test…" on a file | `file:` |

The flow:

1. `promote SOURCE --list-sinks --json` (headless, read-only) -> QuickPick:
   sinks with their kind and path, the source's own scope marked "in place",
   then "New manual group..." and "New script group...".
2. When the sink takes both forms, a QuickPick for recipe vs `@copy`, the
   default first.
3. For a copy, an input box pre-filled with the suggested path (`--path`),
   validated by the same rules client-side for quick feedback.
4. `promote ... --dry-run --json` (headless: computes, writes nothing the user
   owns) -> a **proposal bundle**: each modified text file opens as an editable
   diff (the user may still reword a line), titled with the whole bundle's
   summary (`+1 file, -1 file`).
5. **Accept** (from any diff of the bundle, or a modal when the bundle has no
   text diff) applies everything as one `WorkspaceEdit`: creates with the
   source's bytes, the (possibly edited) modifications, deletes -- one undo.
   Deletions are confirmed in a modal first. Every change is checked against
   the dry run's view of the disk; anything stale refuses with "promote again".

Writes no longer need a terminal, so promotion also works with dispatch off.

## Testing

- Python unit tests for sink enumeration, scope insertion (top level, existing
  block, nested block, new block), in-place replacement, `@copy` inference,
  plan computation for each source kind and both modes, the apply order and
  its staleness checks, and the CLI's `--list-sinks` / `--dry-run` / JSON.
- The existing `promote` / `add-finding` / stress-prompt tests keep passing,
  updated only where the output shape deliberately changed.
- The `testplan-promote` e2e scenario gains a freeze-in-place and a
  move-to-`@testgroup` step.
- Vitest for the pure TS half: parsing sinks and plans, argv, path checks,
  picker rows.
