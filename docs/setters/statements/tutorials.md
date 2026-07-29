# Tutorials

A **tutorial** is an editorial — the write-up that explains how to *solve* a
problem. In {{rbx}} a tutorial is **just a statement**: the same source model,
schema, and build engine as a [statement](index.md), so this page is thin. It
only says *where tutorials differ*; everything on the other three pages applies
unchanged.

## What tutorials are

A tutorial is authored exactly like a statement — an {{rbxtex}} file (or any
other [format](index.md#formats-at-a-glance)) — but it is declared in a separate
`tutorials` list and built to a `tutorial-<lang>…` PDF instead of a
`statement-<lang>…` one. The engine reads the same fields and runs the same
pipeline; only the list it reads and the output prefix change.

The solution text goes in a plain `legend` block, like any statement body. There
is **no `editorial` block** — a tutorial is a normal statement file that happens
to describe the solution:

```latex title="statement/editorial.rbx.tex"
%- block legend
We read the two integers $A$ and $B$ and output their sum $A + B$. The intended
solution is a direct $O(1)$ computation.
%- endblock
```

## Declaring

`tutorials` is a list parallel to `statements`, present on **both**
`problem.rbx.yml` and `contest.rbx.yml`, using the identical fields (see
[Writing statements](writing.md) and [Contest statements](contest.md)).

A **problem** tutorial is keyed only by `(language, variant)` — no `name`, just
like a problem statement:

```yaml title="problem.rbx.yml"
tutorials:
  - language: en
    file: statements/editorial-en.rbx.tex
```

A **contest** tutorial **requires** a `name` and, like a contest statement,
carries the two problem templates
([`standaloneProblemTemplate` / `contestProblemTemplate`](contest.md#the-contest-owns-the-templates)):

```yaml title="contest.rbx.yml"
tutorials:
  - name: editorial-en
    language: en
    file: statements/editorial-sheet.rbx.tex
    standaloneProblemTemplate: statements/editorial-standalone.rbx.tex
    contestProblemTemplate: statements/editorial-fragment.rbx.tex
```

Both are **optional** and behave exactly as they do for a contest statement — a
full document for the standalone build, a fragment for the join; when the
standalone template is absent, {{rbx}} falls back to the bundled default
editorial. See [Contest statements](contest.md) for the full mechanics.

## Building

Tutorials have their own builders, mirroring the statement commands with the
same flags:

<!--termynal-->
```bash
# Build problem tutorials (one PDF per language)
$ rbx tutorials build          # alias: rbx tut b

# Build the joined editorial book
$ rbx contest tutorials build  # alias: rbx contest tut b

# Same flags as the statement commands
$ rbx tut b --languages en --languages pt
$ rbx tut b -p icpc
```

Built PDFs land in `build/`, with a `tutorial-` prefix in place of `statement-`:

- **Standalone** — `build/tutorial-<lang>[-<variant>][-<profile>].pdf`.
- **Contest** — `build/<tutorial-name>[-<profile>].pdf`, keyed by the contest
  tutorial's `name`.

## What carries over and what differs

Everything on the other three pages applies to tutorials **unchanged**:

- [Writing statements](writing.md) — blocks, variables, samples, and assets.
- [Template context](context.md) — the `params` / `vars` / `contest` / `problem`
  namespaces and per-sample handles.
- [Contest statements](contest.md) — the two contest-owned templates, the
  `(language, variant)` join, and `extends`.

The **one** difference: `documents` are a **statements-only** section.
`rbx contest tut b` builds only the tutorials — it does **not** build
[`documents`](contest.md#documents); only `rbx contest st b` does.
