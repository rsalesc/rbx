# Inline var hints for statically named groups

Extends the inline statement var hints of
[2026-08-28](2026-08-28-vscode-statement-var-hints-design.md), whose "Not in v1"
list named group scope and predicted the shape this takes: "a group flag serves
group scope, and the scanner's rejected-prefix list is where the others would be
admitted." Both halves held. What that list did not anticipate is which prefix
had to be admitted, and why the admission has to be narrow.

## G1. Only a statically named group

Three new spellings get a badge, and all three resolve to exactly one value:

```
\VAR{problem.groups.sub2.vars.AB.max}        = 1000
\VAR{problem.groups.sub2.AB.max}             = 1000   (GroupView shorthand, #630)
\VAR{problem.groups['sub-2'].vars.AB.max}    = 1000
```

A **loop-bound** reference -- `\VAR{g.vars.AB.max}` inside `\BLOCK{for g in
groups}` -- is still not badged, and that is the standing limit rather than an
oversight. One source position renders a different value per iteration, so a
single badge would have to lie, name a group, or list several; D1 rejected all
three, and nothing here changes that argument.

It is worth being plain about the consequence: the loop is the *common* spelling.
The bundled fixture
(`rbx/testdata/contests/statements_v2_group_vars/statements/problem-standalone.rbx.tex`)
writes its subtasks table as `\subtask{\VAR{g.name}}{\VAR{g.vars.AB.min}}...` and
names a group statically on exactly one line. So this change lights up the "By
name:" reference, not the table. The table needs a surface an inlay hint does not
have -- a hover with a group-by-group table is the obvious candidate -- and that
is a separate piece of work, not a wider regex.

## G2. `problem.groups`, and nothing else under `problem`

The scanner's `FOREIGN_SCOPE` rejects the whole `problem.` prefix. The spelling
that has to be admitted is *inside* it, which is not what the earlier design
assumed: it listed `groups` among the foreign scopes, as though `\VAR{groups.x}`
were reachable. It is not. `context.problem_jinja_kwargs` lifts only `vars` to
the top level; `groups` lives solely inside `problem.namespace()`. The `groups.`
entry in that list has always been dead for a problem statement, and is kept only
for the reason the comment there already gives.

So `FOREIGN_SCOPE` stops being a blanket reject and becomes a three-way
classifier: group, foreign, root -- tried in that order, so
`problem.groups.sub1.N.max` is claimed before the `problem.` rejection can see
it, and every *other* `problem.` spelling still falls through to that rejection.
`problem.title` and `problem.params.x` are answered by a resolved statement,
which `rbx vars` deliberately never loads, so widening past `problem.groups`
would badge nothing and cost a spawn per keystroke to learn it.

**Both spellings of the group name.** `fields.NameField` permits
`^[a-zA-Z0-9][a-zA-Z0-9\-_]*$`, so `sub-1` and `1st` are legal group names that
Jinja can only reach as `problem.groups['sub-1']`. Supporting only the dotted
form would quietly unbadge every package that names its groups that way, with
nothing on screen to say why. `JinjaGroupsGetter` serves both, so both are real
spellings of the same reference.

**The shorthand needs no model-field check.** `problem.groups.sub1.name`
resolves to the `TestcaseGroup` field, not to a var, and `GroupView` gives model
fields precedence. The scanner does not have to know that:
`RESERVED_STATEMENT_VAR_NAMES` (`rbx/box/fields.py`) already lists every one of
those fields, so no var can be called `name`/`score`/`validator`, the payload
lookup misses, and no badge is drawn. The existing invariant does the work.

## G3. The payload gains groups behind an opt-in flag

`rbx vars --json --groups` nests what `--json` used to print flat:

```json
{"vars": {"AB.max": "200"},
 "groups": {"sub1": {"AB.max": "10"}, "sub2": {"AB.max": "200"}}}
```

Values stay display *strings* for D3's reason -- `JSON.parse` yields IEEE
doubles, and a bound of `` py`10**18 + 7` `` would badge wrong -- and the
non-finite guard now covers every group's set as well as the root one.

Each group's set is **resolved**, not its raw override block: package vars with
that group's overrides applied, straight from
`package.get_expanded_vars_for_group`. That is the same distinction
`statements.context.GroupView` documents, and for the same reason -- a group that
overrides nothing would otherwise answer nothing at all, which is precisely the
silent degradation per-group vars exist to remove.

**Opt-in, not always-on.** An rbx older than this change exits non-zero on the
unknown option, which is what lets the extension notice and fall back to plain
`--json` and root-only badges. Folding a `groups` key into the flat map instead
would have been silently wrong in the other direction: an old rbx would answer
the flat map, and the extension would read the absence as "this package declares
no groups".

## G4. `--render` takes the group on the line

A filtered group reference has to render, for the same reason a filtered root one
does (2026-08-29): the pipeline is what decides what the statement shows. So each
line of `--render` stdin may name its group ahead of a tab:

```
AB.max | sci            <- root
sub1\tAB.max | sci      <- group sub1
```

A line with no tab is a root expression, so the pre-group protocol is a strict
subset of this one. Keys come back **verbatim**, group prefix and all, so the
caller looks its answer up under the line it sent and the extension's render
cache keys per group for free -- `pendingRenders` needed no new concept.

A tab because a group name cannot hold one (`NameField` allows only word
characters and dashes) and neither can any expression a scanner extracts, so the
split needs no quoting.

**An unknown group is dropped, not resolved.** `Package.expanded_vars_for_group`
falls back to the *package* vars for a name it does not know -- right for a sample
or a unit test, and exactly wrong here: a statement still naming a renamed group
would badge the package value under the old name, confidently. `--render` checks
the name against the declared groups first and reports the miss on stderr, like
any other drop.

## G5. Failure is still an absent badge

Every new failure mode joins D5's list: an rbx too old for `--groups`, a group
renamed or deleted, a name absent from that group's set, a malformed group in the
payload. None of them can draw a wrong number, which is the property the whole
feature rests on.

One new cost: a package whose manifest cannot be read pays *two* spawns per load
instead of one, because a non-zero exit is ambiguous between "old rbx" and "bad
package" and the retry resolves it. Sniffing the error message instead would mean
parsing a Rich panel whose wrapping depends on the terminal width rbx thinks it
has. The retry is paid once and then cached like any other answer, until the
`problem.rbx.yml` watcher drops the entry.

## G6. Testing

Python, over `rbx/testdata/contests/statements_v2_group_vars/A` -- the one
package in the tree with per-group vars, and already shaped for this: two groups
each override one leaf of a nested block and must keep its sibling, and a third
overrides nothing. It covers the nested payload, the inherited leaves, the
non-finite guard reaching a group, the group-column render, filters over it, the
`vars.`-prefixed spelling, and the unknown group.

TypeScript, in `statementVars.test.ts`: the dotted form, the shorthand, both
bracket forms, an inherited name, a filtered reference's wire key, an unknown
group, a name absent from the group, a model field, and -- still rejected -- `g.`,
`p.groups.`, `problem.title` and `problem.groups` itself.
`varsPayload.test.ts` covers the nested shape, an empty `groups`, the refusal of
a flat payload, and the refusal of a malformed group.
