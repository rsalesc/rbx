# VS Code: distinguishing contest variants in the problem selector

Refs #745.

## Problem

The extension is a pure reader. It never spawns rbx and never learns which
contest variant `-C`/`RBX_CONTEST` selected, so `contestIndex.ts` reads the
canonical `contest.rbx.yml` *and* every sibling `contest.<id>.rbx.yml` and
merges them first-wins in filename order. That union is the right default --
a reader cannot know what the user will type in the terminal -- and it stays.

What the union costs today is that the variants become indistinguishable once
merged:

- every variant collapses into one `<optgroup>` keyed by the contest root, so
  nothing says whether a letter came from `div1` or `div2`;
- `order` is counted per contest file, so div1's first problem and div2's first
  problem both claim `0` and the sort falls through to label and root, which
  interleaves the two variants' letters (`A`, `A`, `B`, `B`).

A user running a two-division contest sees one jumbled list of letters with no
way to tell the divisions apart.

## Design

Group by *contest file* rather than by contest root, and name the variant in
the group heading.

### Carry the variant id through the index

`rbx/contest.ts` gains `contestVariantId(name)`, the inverse of the existing
`isContestVariantFile`: the id for `contest.<id>.rbx.yml`, `undefined` for the
canonical name. `ProblemIdentity` gains an optional `variantId`.

`indexContests` already walks `contestFiles()` and knows each filename, so it
stamps the id onto the identities that file produced. First-wins is untouched:
a package named by both the canonical file and `div2` keeps the canonical
identity, and therefore lands in the canonical group.

### Group by (root, variant)

`problems.ts` splits today's single `group` field -- which is both sort key and
heading -- into the two things it was doing at once:

- key: `contestRoot` plus `variantId ?? ''`;
- heading: `basename(contestRoot)`, with ` (<id>)` appended for a variant.

Canonical-first ordering falls out of the empty string sorting before any valid
id, and the ids then sort in exactly the filename order `contestFiles()` merged
in, so heading order and merge order cannot drift apart. Disjoint variants land
as two contiguous blocks; overlapping ones read as "the canonical's problems,
then what only `div2` adds", which is what first-wins actually produced.

Grouping unconditionally, rather than only when the variants happen to be
disjoint, keeps the dropdown's structure from reshuffling wholesale the moment
someone adds one shared problem.

### `order` stops colliding

Each group is now exactly one contest file, so two problems can no longer claim
the same `order` within a group. The `label`/`root` tie-breaks stay as
belt-and-braces, but their comment -- which describes the merged-variants case
outright -- no longer applies and is rewritten.

## Deliberately unchanged

- **The union itself.** Every variant's problems stay visible whichever one is
  selected.
- **"One group is no grouping".** A dispatcher holding a single
  `contest.div1.rbx.yml` yields one group and renders headingless: there is no
  second variant to distinguish it from, and the heading would be chrome for
  nothing.
- **`renderSelector`'s one-pass open/close**, which keys on the heading string
  and so merges two same-named contest directories. That approximation predates
  this change -- `compareGroups` documents it -- and is neither worsened nor
  fixed here.
- **Run artifacts.** The extension watches `<pkg>/.rbx/runs` and
  `<pkg>/build/testset.yml`, both variant-invariant, and stay so under the split
  planned in #753. Nothing outside the selector is variant-aware.
