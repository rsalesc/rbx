# Statements guide — structure plan (scaffold-docs pass)

Second pass over the statements feature guide (PR #606). The first pass got the
*facts* right; this one gets the *shape* right, applying the `scaffold-docs`
workflow and matching the page architecture of the hand-written guides
(`verification/validators.md`, `testset/generators.md`, `running/index.md`,
`stress-testing.md`, `profiling/index.md`).

## Audiences

**Primary:** Problem setters preparing a problem or a contest with rbx.
They know C++ and LaTeX and have set problems before, on Polygon or by hand.
They have never seen rbx's statement model. They want a PDF out of the package
and they want the constraints in the statement to be the same constraints the
validator enforces.

**Secondary:**

- Contest directors assembling a book out of problems other people wrote — they
  care about the join, the chrome, the cover page and the infosheet.
- Setters migrating a package from Polygon — they care about which of their
  habits carry over and which do not.

## What changed from the first pass

1. **A motivational problem per page.** The hand-written guides open with a
   concrete frustration and then carry one running example the whole way down.
   `writing.md` now reuses the connected-graph problem from
   `verification/validators.md`, so the statement a reader writes here prints the
   constraints the validator they already wrote enforces.
2. **Extra features live in their own `##` sections**, at the bottom of the page,
   after the happy path — the shape of "Sharing a report" in `running/index.md`
   or "Fuzzing inputs" in `stress-testing.md`. Nothing optional is sprinkled into
   the main narrative any more.
3. **Casts.** The statements pages were the only feature guide with no terminal
   recording. `rbx st b` and `rbx contest st b` now get one each.
4. **Facts added from `main`** that the first pass predated: the `vars` shorthand,
   per-testgroup vars in a subtasks table, and `--partial`. The reserved-name
   list that ships with the shorthand was left out on purpose: it is an obscure
   load-time error, not something a setter needs while writing a statement.
5. **Prose pass** against `scaffold-docs/references/prose-style.md`: filler words
   cut, closing victory laps cut, em dashes rationed, hype removed. House voice
   (`docs/plans/docs-writing-style-guide.md`) wins wherever the two conflict.

## Page outlines

### `index.md` — Overview

Orientation page. Definition, the model, the commands, then the optional flags.

| Section | Kind |
| --- | --- |
| Opening: what a statement is, and the two things rbx buys you | intent |
| Building your first statement (cast) | happy path |
| What a statement is: `(language, variant)`, `type`, `file` | model |
| Where statements are declared: problem vs contest | model |
| The three kinds: statements, tutorials, documents | model |
| Formats at a glance | model |
| The build pipeline | model |
| Building only some languages | **extra** |
| Rendering against a timing profile | **extra** |
| Keeping two recipes for one language (`variant`) | **extra** |
| When a statement fails to build | **extra** |
| Where to go next | pointer |

### `writing.md` — Writing statements

| Section | Kind |
| --- | --- |
| Opening: why blocks instead of a document | intent |
| Motivational problem (the connected-graph problem) | example |
| Writing the statement (blocks: legend, input, output) | happy path |
| Blocks | model |
| Printing constraints from `vars` | happy path |
| Shorthand for vars | **extra** |
| Branching and looping in a statement | **extra** |
| Explaining a sample | **extra** |
| Shipping images and other resources | **extra** |
| Reusing a recipe across languages (`extends`) | **extra** |
| Writing in a format other than rbxTeX | **extra** |

### `context.md` — Template context

| Section | Kind |
| --- | --- |
| Opening: what is in scope while a statement renders | intent |
| Why the namespaces do not merge | design decision |
| `params` vs `vars` | design decision |
| The `problem` namespace | API, by intent |
| Pulling blocks into a template | API, by intent |
| Printing the samples | API, by intent |
| Filters | API, by intent |
| Building a subtasks table from testgroup vars | **extra** |
| Import handles (contest join only) | **extra** |
| Interactive samples | **extra** |
| Full field reference | pointer |

### `contest.md` — Contest statements

| Section | Kind |
| --- | --- |
| Opening: the book, and who owns the chrome | intent |
| The contest owns the templates | design decision |
| Writing the two templates | happy path |
| Joining the problems (cast) | happy path |
| Declaring a contest statement | model |
| Custom blocks | **extra** |
| Cover pages and infosheets (`documents`) | **extra** |
| Location and date | **extra** |
| Reusing a recipe with `extends` | **extra** |
| When a problem cannot be rendered (`--partial`) | **extra** |
| Learn through examples | pointer |

### `tutorials.md` — Tutorials

Stays short by design: what carries over, what differs, how to build.

## Casts

| Cast | Fixture | Shows |
| --- | --- | --- |
| `statement-build` | `statement-problem` (new) | `rbx st b` producing `en` and `pt` PDFs |
| `contest-statement-build` | `statement-contest` (new) | `rbx contest st b` joining two problems plus an infosheet |
