# Writing statements

{{rbxtex}} (extension `.rbx.tex`) is the format we recommend for writing a
problem statement in {{rbx}}, and this page is a tour of it.

An {{rbxtex}} file is a set of named **blocks** of content, sprinkled with
{{Jinja2}} for variables and logic. It is a superset of {{latex}}: anything you
can write in LaTeX, you can write here. What it takes away is the document
around your text. No `\documentclass`, no packages, no section titles, no
`\begin{document}`. Those belong to a [template](contest.md), and the template
belongs to the contest.

That separation is worth the trouble for two reasons. You can restyle a whole
contest by changing one template, without opening a single problem. And a
problem written for one contest drops into the next one, with different chrome,
unchanged.

## Motivational problem

Let's write the statement for a problem we already know. In
[Validators](../verification/validators.md) we wrote a validator for a problem
that asks for a path between vertices 1 and `N` in a **connected** graph with
`N` vertices and `M` edges, where `N` is between 2 and 1000 and `M` is between
1 and `N * (N - 1) / 2`. The input looks like this:

```
3 2
1 2
2 3
```

That validator reads its bounds from `vars`:

```yaml title="problem.rbx.yml"
vars:
  N:
    min: 2
    max: 1000
```

By the end of this page, the statement will print those same bounds, and the
graph picture next to them, without repeating a single number.

## Writing the statement

Point a statement entry at a file, and write the blocks. `rbx-tex` is the
default `type`, so there is nothing else to configure:

=== "problem.rbx.yml"

    ```yaml
    statements:
      - language: "en"                       # (1)!
        file: "statements/statement.rbx.tex" # (2)!
    ```

    1.  The language code (ISO 639-1) this statement is written in.
    2.  The `.rbx.tex` source, relative to the package root. `type` defaults to
        `rbx-tex`, so it is omitted.

=== "statements/statement.rbx.tex"

    ```latex
    %- block legend
    You are given a connected undirected graph with $N$ vertices, numbered from
    $1$ to $N$, and $M$ edges. Find any path from vertex $1$ to vertex $N$.
    %- endblock

    %- block input
    The first line contains two integers $N$ and $M$.

    Each of the next $M$ lines contains two integers $u$ and $v$, indicating an
    undirected edge between $u$ and $v$.
    %- endblock

    %- block output
    Print the vertices of a path from $1$ to $N$, in order, separated by spaces.
    %- endblock
    ```

=== "Directory layout"

    ```text
    statements/
      statement.rbx.tex      # your blocks
      samples/
        000.in
        000.rbx.tex          # explanation for sample 0 (optional)
    ```

The statement above carves the problem into three blocks and nothing else. Build
it with `rbx st b` and you get a laid-out PDF: the title, the limits box, the
section headings and the samples all come from the template.

## Blocks

A block is a chunk of content between `%- block <name>` and `%- endblock`. Block
names are **free-form**. There is no fixed list, and `%- block whatever` is a
perfectly valid block; it is up to a template whether it gets rendered and where.

That said, the bundled default template, and every preset that inherits it,
renders this set of blocks by convention:

| Block | Renders as |
| :--- | :--- |
| `legend` | the main statement text |
| `input` | the input-format section |
| `output` | the output-format section |
| `interaction` | the interaction protocol (interactive problems) |
| `notes` | the notes section |
| `macros` | your `\newcommand`s, injected before the body |
| `preamble` | extra preamble injected into the document head |
| `explanation_<i>` | inline explanation for sample #i (0-indexed) |

Reusing these names keeps your statement portable across templates, and a few of
them get special treatment when packaging for {{polygon}}.

Want a section of your own? Write the block here, and wire it into the page from
the [template](contest.md#custom-blocks):

```latex title="statements/statement.rbx.tex"
%- block hint
Think about a breadth-first search.
%- endblock
```

## Printing constraints from vars

Here is where the statement stops being a text file. Any value from
`problem.rbx.yml` can be interpolated with `\VAR{...}`, and your problem's
`vars` live under `vars.*`:

=== "statements/statement.rbx.tex"

    ```latex
    %- block input
    The first line contains two integers $N$ and $M$
    ($\VAR{vars.N.min} \le N \le \VAR{vars.N.max}$).
    %- endblock
    ```

=== "problem.rbx.yml"

    ```yaml
    vars:
      N:
        min: 2
        max: 1000
    ```

The statement above reads `N.min` and `N.max` straight out of
`problem.rbx.yml`, which is where the validator we wrote reads them from too.
Change the bound in one place and the statement, the validator and the
generators all follow. This is the whole reason `vars` exists, and we cover it
in full in [Variables](../variables.md).

Large bounds read better in scientific notation, and the `sci` **filter** does
that for you:

```latex
$\VAR{vars.N.min} \le N \le \VAR{vars.N.max | sci}$   %# 1000000000 renders as 10^9
```

`sci` is one of a handful of LaTeX-aware filters {{rbx}} registers on top of the
standard {{Jinja2}} ones. [Template context](context.md#filters) lists them all.

!!! danger "Never type a bound twice"
    A hard-coded `10^9` in a statement is the single most common way a package
    goes out of sync. If a number appears in both the statement and the
    validator, it belongs in `vars`.

### Shorthand for vars

Writing `vars.` in front of every constraint gets old fast in a section that
mentions a dozen of them. So the keys of a `vars` block are **also** available
directly in the namespace that holds it. Both spellings always work:

| Long form | Shorthand |
|---|---|
| `\VAR{vars.N.max}` | `\VAR{N.max}` |
| `\VAR{problem.vars.N.max}` | `\VAR{problem.N.max}` |
| `\VAR{contest.vars.year}` | `\VAR{contest.year}` |
| `\VAR{g.vars.N.max}` (for a group `g`) | `\VAR{g.N.max}` |

So the constraints line above reads as:

```latex title="statements/statement.rbx.tex"
$\VAR{N.min} \le N \le \VAR{N.max}$
```

## Branching and looping in a statement

Everything in an {{rbxtex}} file is LaTeX-flavored {{Jinja2}}, so you get more
than interpolation. A line starting with `%-` is a Jinja statement, which is the
same thing as `\BLOCK{ ... }`:

```latex
%- if vars.multitest
Each test file contains several test cases.
%- else
There is a single test case per file.
%- endif
```

The snippet above prints one line or the other depending on `vars.multitest`, so
a single statement file covers both the single-case and the multi-case flavor of
your problem. Loops work the same way, and the
[template context](context.md) page is where the interesting things to loop over
live.

!!! tip
    `%#` starts a comment that is stripped before compilation. Plain `%` is a
    normal LaTeX comment and survives into the generated `.tex`, which is handy
    when you are debugging the output.

## Explaining a sample

Samples are loaded from your testset and printed by the template, so they show
up without you doing anything. To *explain* one, {{rbx}} looks in three places,
in descending priority. For the same sample, a higher source wins.

1. **An inline `explanation_<i>` block** in the statement file (`explanation_0`
   for the first sample). Because the statement is built per language, this text
   is language-specific.

2. **A sibling file next to the sample input** *(recommended)*. Swap the suffix:
   `000.in` becomes `000.rbx.tex`. It is a blocks file with one block **per
   language**, keyed by the language code:

    ```latex title="statements/samples/000.rbx.tex"
    %- block en
    The graph is a path already, so $1, 2, 3$ is a valid answer.
    %- endblock

    %- block pt
    O grafo já é um caminho, então $1, 2, 3$ é uma resposta válida.
    %- endblock
    ```

    Only the block matching the statement's language is rendered, and it
    receives the same variables as the rest of the statement.

3. **A language-agnostic `000.tex`**, which is the same text for every language.

We recommend the sibling file: the explanation sits next to the sample it
explains, and all the languages of one sample stay in one place.

!!! warning "One explanation file per sample"
    A sample may not have **both** `000.rbx.tex` and `000.tex`. That is a hard
    error, and you have to pick one.

Markdown statements use the same scheme with Markdown suffixes: `000.rbx.md` for
per-language blocks, or `000.md` for a language-agnostic one.

## Shipping images and other resources

The golden rule: put images, `.sty` files and PDFs **in the same directory as
your `.tex`**, and reference them by a plain relative path.

```latex title="statements/statement.rbx.tex"
\includegraphics{graph.png}   % graph.png sits next to statement.rbx.tex
```

The line above works because {{rbx}} mirrors the directory that holds your
`file`, the whole subtree, into the build. Anything sitting next to your `.tex`
is staged for you.

!!! tip
    Keep everything next to your `.tex` and you will never have to touch
    `\graphicspath` or `TEXINPUTS`.

The `assets` field is a different concern: it is about **packaging**, not the
local build. It lists extra globs, relative to the package root, to ship with
the statement when you export the package, notably to {{polygon}}. Use it for
resources that live **outside** the statement's directory, since those are not
picked up by the mirroring above:

```yaml title="problem.rbx.yml"
statements:
  - language: "en"
    file: "statements/statement.rbx.tex"
    assets:
      - "shared/logos/*.png"   # out-of-tree resources to ship on export
```

## Reusing a recipe across languages

Two statements in different languages usually share everything except the source
file. Repeating the rest on every entry is how they drift apart, so `extends`
lets one entry inherit another's **build recipe** and spell out only what
differs.

A problem statement extends another by **language**, or by a
`{language, variant}` pair:

```yaml title="problem.rbx.yml"
statements:
  - language: en
    file: statements/statement-en.rbx.tex
    params: { show_limits: true }
  - language: pt
    extends: en                      # (1)!
    file: statements/statement-pt.rbx.tex
    params: { show_limits: false }   # (2)!
```

1.  Inherits `type`, `assets` and `params` from the `en` statement. It does not
    inherit identity: `pt` keeps its own `language` and `variant`.
2.  `params` **deep-merges** key by key, so `pt` overrides `show_limits` and
    keeps every other key `en` defined.

The merge is an allowlist of the build recipe: `type`, `file`, `params` and
`assets`. Omit `file` on the child and it inherits the parent's, which is how a
single source renders under two different `params`. Cycles and dangling
references are errors.

Contest statements extend by `name` instead, and carry the two templates along.
See [Reusing a recipe with extends](contest.md#reusing-a-recipe-with-extends).

## Writing in a format other than rbxTeX

{{rbxtex}} is the default, and for the vast majority of problems it is all you
will touch. Still, `type` accepts a few alternatives. The one thing to keep in
mind is that only `rbx-tex` and `rbx-md` process blocks and can **join into a
contest statement**. The rest are standalone-only, meant for
[`documents`](contest.md#cover-pages-and-infosheets) or for drop-in files.

### Markdown (`rbx-md`)

The same block, variable and {{Jinja2}} machinery as {{rbxtex}}, except you write
the body in Markdown (`.rbx.md`). Reach for it when you are targeting HTML or
Markdown output and still want the block structure.

### Jinja (`jinja-tex` / `jinja-md`)

Full control of the whole document. You write the `\documentclass`, the
`\begin{document}` and everything else, with `\VAR{...}` and `%- ...` available
for interpolation and logic:

```latex
\documentclass{article}
\begin{document}
\title{\VAR{problem.title}}
\maketitle
%- for sample in problem.samples
  \subsection*{Sample \VAR{loop.index}}
%- endfor
\end{document}
```

The document above is self-contained: it declares its own `\documentclass` and
loops over `problem.samples` by hand. You get the interpolation and none of the
block structure, which is why it cannot join a contest. This is the type most
[`documents`](contest.md#cover-pages-and-infosheets) use.

### Plain LaTeX or Markdown (`tex` / `md`)

The file is treated as a **static** document: no blocks, no variables, no
templating. Reach for these when you already have a finished `.tex` or `.md` and
want {{rbx}} to compile it as-is.

### PDF (`pdf`)

A pre-built PDF. The build is a copy, with no templating, variable substitution
or asset processing. Handy for statements produced by an external tool, or
pulled out of an old archive:

```yaml title="problem.rbx.yml"
statements:
  - language: "en"
    file: "statements/statement.pdf"
    type: "pdf"
```

Now that the source side is covered, [Template context](context.md) is the
reference for every value your blocks and templates can reach.
