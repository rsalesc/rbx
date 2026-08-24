# Scaffolding a contest

<!-- SCAFFOLD PASS A -- structure, learning bullets and verified commands only.
     Prose comes in Pass C. Every command, flag, field name and behaviour below
     was read out of rbx/box/contest/main.py, rbx/box/contest/schema.py and
     rbx/resources/presets/default at scaffold time. -->

<!-- INTRO
     - Step 1 of the "Delivering a contest" track; addressed to the chief setter.
     - Where First steps built one problem, this builds the folder that holds
       every problem and the statement chrome they share.
     - By the end: a contest package with three problems in it, verified with
       `rbx contest summary`.
     - Prereq note: link back to First steps for `rbx create`; assume rbx and a
       C++ toolchain are already working.
-->

## Creating the contest package

<!-- TEACHES
     - `rbx contest create` takes a path and scaffolds a new folder there;
       `rbx contest init` scaffolds into the current directory instead.
     - Which to use: `create` when starting fresh, `init` when the folder
       already exists (a freshly cloned empty repo, a directory you made by
       hand). `create` on an existing directory prompts before writing into it.
     - Both take `--preset/-p`; `create` also takes `--variant/-v` and `--local`.
       Omitted preset means the active preset, then the default one.
     - Point at the Presets guide rather than explaining presets here.
-->

```bash
rbx contest create --path contests/summer-cup
```

<!-- CAST: contest creation + adding problems + summary. One recording,
     spec at casts/contest-scaffold.yml, embedded here with
     {{ asciinema("contest-scaffold") }}. Not recorded yet. -->

## Reading the contest folder

<!-- TEACHES
     - What the default preset ships at the contest level:
       contest.rbx.yml, .gitignore, statements/ (problem-sheet, problem,
       problem-fragment, editorial-*, icpc.sty, info.jinja.tex, logo.png).
     - The one idea to land: the contest owns the statement chrome. Problems
       carry only their own text -- that moved up here in statements v2.
     - Problems do not exist yet; they will be sibling folders under this root.
-->

<!-- OPEN QUESTION (needs your call)
     `preset_tree()` in main.py walks the *problem* preset only
     (PRESET_PROBLEM_DIR). Hand-transcribing a contest tree here reintroduces
     exactly the drift the 2026-08-24 audit removed. Options:
       a) parameterise the macro over the preset subdir and add
          docs/_data/contest-preset-tree.yml annotations;
       b) show no tree, and describe statements/ in prose only.
     Pass A assumes (a). -->

## Reading `contest.rbx.yml`

<!-- TEACHES
     - `name` is the only required field.
     - `titles` is per-language; `vars` are contest-wide and reach statements.
     - `statements` / `tutorials` / `documents` exist and are step 3's subject --
       name them, do not explain them here.
     - `problems` is the list this walkthrough grows.
     - Link the Contest reference for the full field list.
-->

```yaml
name: "summer-cup"
titles:
  en: "Summer Cup 2026"
```

## Adding problems

<!-- TEACHES
     - `rbx contest add` prompts for two things and creates the problem for you:
       `--path` (relative to the contest root; its basename becomes the
       problem's `name`) and `--short_name` (the contest letter).
     - It runs the same problem scaffold as `rbx create`, so `--preset` and
       `--variant/-v` apply here too.
     - It then writes a `{short_name, path}` entry into contest.rbx.yml,
       inserted so the list stays ordered by short name.
     - `short_name` is constrained: ^[A-Z]+[0-9]*$, 1-4 chars. So A, B1, AA are
       legal; a1 and "apple" are not -- names like that are `aliases`.
     - Adding a letter (or alias) that already exists is rejected.
-->

```bash
rbx contest add --path problems/chocolate --short_name A
rbx contest add --path problems/gardens --short_name B
```

<!-- CHECK BEFORE PASS C: whether `add` writes only short_name+path, or also
     leaves room for color/aliases. Read: it writes exactly those two keys. -->

## Bringing in a problem you already have

<!-- TEACHES
     - There is no import command. Doing this is two manual steps:
       1. move the problem directory under the contest root;
       2. add its entry to `problems` in contest.rbx.yml by hand.
     - `path` is optional: omit it and rbx looks for ./{short_name}/.
     - Say plainly that this is manual today, and link the affordance issue.
-->

```yaml
problems:
  - short_name: "A"
    path: "problems/chocolate"
  - short_name: "B"
    path: "problems/gardens"
  - short_name: "C"
    path: "problems/sum-of-n"   # moved in from the First steps walkthrough
```

<!-- OPEN QUESTION (needs your call)
     Issue #440 anticipates this: "if first-class import doesn't exist as a
     single command today, file a separate affordance issue and link it here."
     It does not exist. Want me to file `rbx contest import <dir> --short_name`
     and link it from this section? -->

## Renaming and removing problems

<!-- TEACHES
     - Letters are just the `short_name` values in contest.rbx.yml. Reordering
       or relettering is editing that file; there is no reorder command, and
       nothing renames the folder for you.
     - Keeping list order and letters in sync matters: `A..C` ranges and the
       summary table both read the file's order.
     - `rbx contest remove <letter-or-path>` drops the entry AND deletes the
       problem directory from disk, with no confirmation prompt.
     - The argument matches by path, short_name or alias.
-->

```bash
rbx contest remove B
```

<!-- Pass C: this warrants a `!!! warning`, not a parenthetical. Deleting a
     colleague's problem folder is unrecoverable outside git. -->

## Verifying the contest

<!-- TEACHES
     - `rbx contest summary` (alias `sum`) prints one row per problem: letter,
       name, TL, ML, test counts, flags, solutions bucketed by expected outcome.
     - Read it as the answer to "is every problem wired up correctly?" -- a
       problem that fails to summarize prints an error row and the rest continue.
     - Mention `rbx contest each` / `rbx contest on` only as the next tool the
       reader will meet; selector syntax lives in the Contest reference.
-->

```bash
rbx contest summary
```

<!-- SAMPLE OUTPUT: paste a real table here once the cast is recorded. -->

## Continue the track

<!-- Cards, matching the pattern at the foot of first-steps.md:
     - next: Profiling time limits (step 2) -- issue #439, not written yet.
       Until it lands, point at Packaging a problem (step 4).
     - sideways: contest.rbx.yml reference.
     - back: First steps, for readers who arrived without a problem. -->
