# Tutorials

A tutorial is the editorial of a problem, the write-up that explains how to
*solve* it. In {{rbx}}, a tutorial is **a statement**: it uses the same source
model, schema and build engine. Let's walk through the few places where
tutorials differ. Everything else in [Writing statements](writing.md),
[Template context](context.md) and [Contest statements](contest.md) applies
unchanged.

## Writing a tutorial

You write a tutorial the way you write a statement: an {{rbxtex}} file, or any
other [format](index.md#formats-at-a-glance), with the same fields and the same
build pipeline. Only two things change: it lives in a separate `tutorials`
list, and it builds to a `tutorial-<lang>…` PDF instead of a `statement-<lang>…`
one.

The write-up itself goes in a plain `legend` block, like any statement body:

```latex title="statements/editorial-en.rbx.tex"
%- block legend
Run a breadth-first search from vertex $1$, keeping the parent of every vertex
we reach, and walk the parents back from $N$. The graph is connected, so vertex
$N$ is always reachable, and the whole thing is $O(N + M)$.
%- endblock
```

## Declaring a tutorial

`tutorials` is a list parallel to `statements`, and you will find it on **both**
`problem.rbx.yml` and `contest.rbx.yml` with the same fields.

A **problem** tutorial is keyed only by `(language, variant)`, with no `name`,
like a problem statement:

```yaml title="problem.rbx.yml"
tutorials:
  - language: en
    file: statements/editorial-en.rbx.tex
```

A **contest** tutorial **requires** a `name` and, like a contest statement,
declares the two problem templates:

```yaml title="contest.rbx.yml"
tutorials:
  - name: editorial-en
    language: en
    file: statements/editorial-sheet.rbx.tex
    standaloneProblemTemplate: statements/editorial-standalone.rbx.tex
    contestProblemTemplate: statements/editorial-fragment.rbx.tex
```

Both templates are optional and behave as they do for a contest statement: a
full document for the standalone build, a fragment for the join. Leave the
standalone template out and {{rbx}} falls back to the bundled default editorial.
See [Contest statements](contest.md#the-contest-owns-the-templates) for the full
mechanics.

## Building tutorials

Tutorials get their own builders, mirroring the statement commands with the same
flags:

<!--termynal-->
```bash
# Build problem tutorials (one PDF per language).
$ rbx tutorials build          # alias: rbx tut b

# Build the joined editorial book.
$ rbx contest tutorials build  # alias: rbx contest tut b

# The same flags as the statement commands.
$ rbx tut b --languages en --languages pt
$ rbx tut b -p icpc
```

{{rbx}} writes the PDFs to `build/`, with a `tutorial-` prefix where a statement
would have `statement-`:

- **Standalone**: `build/tutorial-<lang>[-<variant>][-<profile>].pdf`.
- **Contest**: `build/<tutorial-name>[-<profile>].pdf`, keyed by the contest
  tutorial's `name`.

## What carries over, and what differs

Everything on these pages carries over to tutorials unchanged:

- [Writing statements](writing.md) for blocks, variables, samples and images.
- [Template context](context.md) for the namespaces and the per-sample handles.
- [Contest statements](contest.md) for the two contest-owned templates, the
  join and `extends`.

One more thing differs at the contest level:

!!! warning "`documents` are statements-only"
    `rbx contest tut b` builds the tutorials and nothing else. It does **not**
    build [`documents`](contest.md#cover-pages-and-infosheets). Only
    `rbx contest st b` does.
