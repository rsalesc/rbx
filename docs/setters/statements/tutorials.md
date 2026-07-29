# Tutorials

A tutorial is an editorial — the write-up that explains how to *solve* a problem,
not how to read it. In {{rbx}}, a tutorial is **just a statement**.
Same source model, same schema, same build engine as a [statement](index.md) — so
this page can stay short. Let's just walk through the handful of places where
tutorials differ; everything else on the other three pages applies unchanged.

## What tutorials are

You write a tutorial exactly like you write a statement: an {{rbxtex}} file (or any
other [format](index.md#formats-at-a-glance)), the same fields, the same build
pipeline. Only two things change — it lives in a separate `tutorials` list, and it
builds to a `tutorial-<lang>…` PDF instead of a `statement-<lang>…` one.

!!! note "No editorial block"
    There is **no `editorial` block**. A tutorial is a normal statement file that
    happens to describe the solution, so the write-up just goes in a plain
    `legend` block — like any statement body.

Concretely, the legend of a simple two-integer editorial reads:

```latex title="statements/editorial-en.rbx.tex"
%- block legend
We read the two integers $A$ and $B$ and output their sum $A + B$. The intended
solution is a direct $O(1)$ computation.
%- endblock
```

## Declaring

`tutorials` is a list parallel to `statements`, and you'll find it on **both**
`problem.rbx.yml` and `contest.rbx.yml` with the exact same fields (see
[Writing statements](writing.md) and [Contest statements](contest.md)). If you've
declared a statement before, you already know how to declare a tutorial.

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

Both templates are **optional** and behave exactly as they do for a contest
statement — a full document for the standalone build, a fragment for the join.
Leave the standalone template out and {{rbx}} falls back to the bundled default
editorial. See [Contest statements](contest.md) for the full mechanics.

## Building

Tutorials get their own builders, mirroring the statement commands with the very
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

The built PDFs land in `build/`, with a `tutorial-` prefix where a statement would
carry `statement-`:

- **Standalone** — `build/tutorial-<lang>[-<variant>][-<profile>].pdf`.
- **Contest** — `build/<tutorial-name>[-<profile>].pdf`, keyed by the contest
  tutorial's `name`.

## What carries over and what differs

Everything on the other three pages carries over to tutorials **unchanged**:

- [Writing statements](writing.md) — blocks, variables, samples, and assets.
- [Template context](context.md) — the `params` / `vars` / `contest` / `problem`
  namespaces and per-sample handles.
- [Contest statements](contest.md) — the two contest-owned templates, the
  `(language, variant)` join, and `extends`.

There's really just **one** difference worth remembering:

!!! warning "`documents` are statements-only"
    `documents` is a statements-only section. `rbx contest tut b` builds the
    tutorials and nothing else — it does **not** build
    [`documents`](contest.md#documents). Only `rbx contest st b` does.
