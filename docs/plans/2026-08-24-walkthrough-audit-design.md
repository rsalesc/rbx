---
# This page quotes macro calls and `{{...}}` placeholders as examples.
# Without this they would be expanded -- `{{ preset_tree() }}` below would
# inline the whole preset tree into the design doc.
render_macros: false
---

# Walkthrough audit: fixing the drift, and making the tree reproducible

The four Walkthrough pages had drifted from the code they describe. This document
records what was wrong, what changed, and -- for the one piece that had drifted
silently for several releases -- how it is now kept honest by construction.

## What was wrong

The audit covered `first-steps.md`, `custom-checker-walkthrough.md`,
`stress-testing-walkthrough.md` and `packaging-walkthrough.md`.

### The preset directory tree

`first-steps.md` printed an annotated tree of the default preset that named a
`documents/` folder holding `statement.rbx.tex`, `icpc.sty`, `template.rbx.tex`
and `samples/`. The preset ships none of that layout. It ships:

```
problem.rbx.yml, rbx.h, validator.cpp, wcmp.cpp, .gitignore
sols/main.cpp
statement/{statement.rbx.tex, editorial.rbx.tex, samples/{000.in,000.rbx.tex,001.in}}
tests/{gen.cpp, testplan.txt}
```

`documents/` became `statement/` when statements v2 moved the statement chrome
up to the contest, so `icpc.sty` and `template.rbx.tex` are not in a problem at
all any more -- they live in `contest/statements/`.

This drift was already known. `casts/create-problem.yml` carried a comment
explaining that the recording deliberately omits an `ls` of the folder it just
created, because "the tree says `documents/` while the preset ships
`statement/`, so showing both would put the contradiction on screen", and
`casts/README.md` repeated it under Known gaps. The contradiction was documented
rather than fixed, and the recording was shaped around it.

The same stale path reached three more places: the `testcaseGlob` in the
`problem.rbx.yml` sample (`documents/samples/*.in`), the prose naming the
statement file, and two tab labels.

### The `corner.txt` section

`stress-testing-walkthrough.md` ended by telling the reader to run `rbx build`
and collect the counterexample as a permanent test. That could not work. When
`rbx stress` offers to save a finding into a new script, `cli.py` created the
file at the path the user typed (`tests/corner.txt`) but wrote only its basename
into `problem.rbx.yml`:

```python
'generatorScript': {'path': new_script_path.name}
```

`GeneratorScript.path` is a `CodeItem` path, resolved from the package root, so
the next build looked for `corner.txt` at the root and failed with
`Generator script not found`. The page's annotation (2) explained the mismatch
away by inventing a rule -- "the `path` is relative to the testplan root" --
that rbx does not implement.

This too was known: `casts/README.md` recorded that
`stress-walkthrough.cast` stops at the save confirmation rather than going on to
`rbx build`, and named it "an rbx bug, not a recording one".

### Everything else

Smaller, but wrong: two C++ snippets in `first-steps.md` that do not compile or
do not work (`cin`/`cout` with no `using namespace std;`, and a generator that
computes `n` and then never prints it), a YAML block tab-labelled
`=== "validator.cpp"`, a malformed `ls build` output block, two next-steps cards
pointing at feature-guide pages instead of the walkthrough that continues the
track, an understated `rbx on` selector syntax, and a UI menu label missing its
`(in development)` suffix.

## The findings, in full

| # | Where | What was wrong |
| :-- | :-- | :-- |
| 1 | `first-steps.md` tree | Showed `documents/` with `icpc.sty` and `template.rbx.tex`; the preset ships `statement/` and the chrome lives in the contest. Omitted `rbx.h`, `.gitignore` and `statement/editorial.rbx.tex`. |
| 2 | `first-steps.md` | `testcaseGlob: 'documents/samples/*.in'` |
| 3 | `first-steps.md` | `documents/statement.rbx.tex` named as the statement file, in prose and in two tab labels |
| 4 | `first-steps.md` | `\VAR{N.max}` rather than `\VAR{vars.N.max}`. Bare names still resolve, but the preset and every other page carry the namespace. |
| 5 | `first-steps.md` | A YAML block tab-labelled `=== "validator.cpp"`, and a `vars` replacement that silently dropped the preset's `author` |
| 6 | `first-steps.md` | Two solutions using `cin`/`cout` with no `using namespace std;`, and a generator that computed `n` then printed a blank line instead of it. Also `problem.rbx.yaml`, and a validator ignoring the `MIN_N` it had just read. |
| 7 | `first-steps.md` | `ls build` shown printing a tree, mis-indented under a phantom root |
| 8 | `first-steps.md` | Next-steps cards pointed at the feature guides, not the walkthroughs that continue the track |
| 9 | `stress-testing-walkthrough.md` | `testcaseGlob: 'documents/samples/*.in'` |
| 10 | `stress-testing-walkthrough.md` | Told the reader to run `rbx build`, which could not work, and explained the mismatch with a "testplan root" rule rbx does not implement |
| 11 | `stress-testing-walkthrough.md` | "two extra options" -- the picker offers three, plus the manual groups |
| 12 | `custom-checker-walkthrough.md` | The "Continue the track" card pointed at the stress-testing *reference* |
| 13 | `packaging-walkthrough.md` | `rbx on` described as taking letters only; it takes names, aliases, folders, globs and `!` exclusions |
| 14 | `packaging-walkthrough.md` | TUI entry quoted without its `(in development)` suffix |
| 15 | `casts/create-problem.yml` | Answered two `rbx create` prompts; the preset's `interactive` variant added a third, so a re-record hung. Found only by re-recording. |

Two more outside the Walkthrough, same root cause as 1--3: `presets/index.md`
(a `tracking` block that did not match the preset it claimed to document, and a
symlink example built on `documents/`) and `verification/validators.md`.

The three pages that were *not* the tree held up well -- flags, schema field
names, strategy names, verification levels and the BOCA profile requirement all
still matched. Which is the argument for the macro: those facts are one command
away from being checked, and a hand-copied directory listing is not.

## Why the tree drifted and the rest mostly did not

The other three pages held up well: flags, schema field names, strategy names
and verification levels all still matched. The tree was different in kind. Every
other fact on those pages is checkable by running one command and reading the
output. The tree is a *picture of a directory*, hand-transcribed once and never
re-derived, and nothing in the build or the test suite reads it. It could only
be checked by a person who happened to look at both the page and the preset in
the same sitting.

So the fix is not to correct the tree. It is to stop transcribing it.

## The design

### A macro that walks the preset

`main.py` gains a `preset_tree()` macro. It walks
`rbx/resources/presets/default/problem/`, restricted to files tracked by git --
the preset directory accumulates local `.box/` and `build/` artifacts that a
naive walk would render into the page -- and emits the fenced box-drawing tree.

The repo already had the pattern. `default_timing_formula()` serves the
estimation formula out of `rbx.box.environment` so the profiling page cannot
restate it wrongly, and `tests/casts/test_macro.py` asserts the page calls the
macro instead of spelling the formula out. `preset_tree()` is the same move
applied to a directory listing.

### Annotations keyed by path, not by position

The tree is not a neutral listing. Each entry carries a numbered annotation with
real teaching prose, and the page deliberately shows some files without
annotating them. A macro that only emitted the tree would leave the numbered
list below it hand-maintained and *positional*: a preset that gained a file near
the top would shift every annotation down by one, and nothing would fail.

So the macro emits the tree **and** the numbered list, and the prose is keyed by
path in `docs/_data/preset-tree.yml`:

```yaml
'problem.rbx.yml': |
  The {{YAML}} configuration file for this problem.
```

Numbering is derived from walk order. A path with no entry renders as a plain
tree line with no annotation marker, which is how the sample files are shown
today. A path in the YAML that no longer exists in the preset raises, rather
than silently annotating nothing.

Keeping the prose in YAML rather than in `main.py` is deliberate. Path-keyed
annotations are what make the numbering safe, but the documentation voice
belongs with the documentation; a block scalar holds the nested admonitions and
code fences the annotations use, and the file reads as prose.

### Resolving `{{...}}` inside annotation prose

mkdocs-macros renders a page once. Macro output is not re-scanned, so a
`{{testlib}}` or `{{tags.accepted}}` inside annotation prose would reach the
reader as literal text. The macro resolves these itself against `env.variables`,
supporting the dotted lookups (`tags.accepted`) the existing annotations use.

### The drift guard

`tests/casts/test_macro.py` asserts (the same file that guards
`default_timing_formula`, which is where macro tests already live):

1. `first-steps.md` contains `{{ preset_tree() }}` and no hand-written *annotated*
   tree line, so the page cannot quietly regrow a transcribed copy. The check
   keys on the `# (n)!` marker rather than the box-drawing character, because
   the page legitimately draws another tree -- the `build` layout -- that has no
   preset in it;
2. every annotation key in the YAML exists in the tracked preset, which is what
   a stale `documents/` would trip;
3. every tracked preset file appears in the rendered tree, which is what a
   preset that gains a file would trip.

Together these mean the tree can only be wrong if the preset and the test change
in the same commit.

### Fixing the bug instead of documenting it

`cli.py` now writes the script's package-root-relative path, so the file it
creates and the path it records agree and `rbx build` finds the script. The
walkthrough's claim becomes true as written, its invented "testplan root" rule
is replaced by what actually happens, and the `casts/README.md` known-gap entry
goes away.

With both contradictions gone, `casts/create-problem.yml` can finally do what
its own comment asked for: `ls` the problem it just created, so the recording
and the tree below it show the same thing.

Re-recording surfaced a third piece of drift, invisible until something tried to
run the flow again. The default preset has since gained an `interactive` problem
variant, so `rbx create` now asks **`Which problem template do you want to use?`**
after cloning. The spec answered two prompts and the recording hung on the third
until the budget ran out. It answers three now, and its `timeout` covers the whole
network round trip, since the budget is per instruction and the clone, the prompt
and the library materialization all sit inside one of them.

The recording also shows the three materialized libraries (`testlib.h`, `jngen.h`,
`tgen.h`) that the tree does not, because they are fetched rather than shipped.
Rather than filter the `ls`, the page says so in a line under the tree -- the
recording should show what the folder really contains.

## Scope note

Two stale `documents/` references outside the Walkthrough --
`docs/setters/presets/index.md` and `docs/setters/verification/validators.md` --
share the root cause and are corrected here too. They are not covered by the
drift guard, which reads only the first-steps tree.
