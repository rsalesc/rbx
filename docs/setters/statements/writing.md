# Writing statements

{{rbxtex}} (extension `.rbx.tex`) is the recommended way to write a problem
statement in {{rbx}}. This page is a tour of the format, from blocks to samples
to assets, and finishes with the other formats {{rbx}} also understands.

## rbxTeX — what & why

An {{rbxtex}} file is a set of named **blocks** of content, sprinkled with
{{Jinja2}} for variables and logic. It is a superset of {{latex}}: anything you
can write in LaTeX, you can write here.

```latex title="statement/statement.rbx.tex"
%- block legend
Given two integers $A$ and $B$, determine the value of $A + B$.
%- endblock

%- block input
The input is a single line with two integers $A$ and $B$
($\VAR{vars.N.min} \le A, B \le \VAR{vars.N.max | sci}$).
%- endblock

%- block output
The output must contain only one integer, the sum of $A$ and $B$.
%- endblock
```

The blocks hold *what the problem says*; a separate [template](templates.md)
decides *how it looks*. That separation is the whole point:

- **Swap the look** by changing the template — the content never moves.
- **Full LaTeX power** is still there; {{rbxtex}} is just a thin wrapper.
- **Samples and variables** are injected for you, so the content stays clean.

You rarely need to configure anything — `rbx-tex` is the default `type`, so
pointing `file` at your `.rbx.tex` is enough.

=== "problem.rbx.yml"

    ```yaml title="problem.rbx.yml"
    statements:
      - language: "en"                        # (1)!
        file: "statement/statement.rbx.tex"   # (2)!
        params:                               # (3)!
          show_limits: true
    ```

    1.  The language code (ISO 639-1) this statement is written in.
    2.  The `.rbx.tex` source, relative to the package root. `type` defaults to
        `rbx-tex`, so it can be omitted.
    3.  Free-form values passed to the template as `params.*` (here the default
        template uses `show_limits` to toggle the limits box).

=== "Directory layout"

    ```text
    statement/
      statement.rbx.tex      # your blocks
      samples/
        000.in
        000.rbx.tex          # explanation for sample 0 (optional)
    ```

See the [package schema](../reference/package/schema.md) for every field a
statement entry accepts.

## Blocks

A block is a chunk of content between `%- block <name>` and `%- endblock`:

```latex title="statement/statement.rbx.tex"
%- block legend
Given an array of $\VAR{vars.n}$ integers, find the largest sum of a
contiguous subarray.
%- endblock
```

Block names are **free-form**: any `%- block foo` becomes `problem.blocks.foo`,
which the template reads with `\VAR{problem.blocks.foo}`. There is no fixed list
— custom blocks are perfectly fine. See [context.md](context.md) for everything
exposed as `problem.blocks.<name>` and the rest of the template scope.

The bundled default template (and every preset that inherits it) renders this
set of blocks by convention:

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

To add your own section, define a block and render it in your
[template](templates.md):

```latex title="statement/statement.rbx.tex"
%- block hint
Try to use dynamic programming.
%- endblock
```

!!! note "There is no `editorial` block"
    An editorial is a **separate statement file** — a *tutorial* — that puts its
    solution text in a `legend` block, not an `editorial` block inside the
    problem statement. See [Tutorials & editorials](tutorials.md).

## Variables & logic

Interpolate any value from `problem.rbx.yml` (and the built-in context) with
`\VAR{...}`. Your problem-level `vars` live under `vars.*`:

=== "statement.rbx.tex"

    ```latex title="statement/statement.rbx.tex"
    %- block input
    The first line contains an integer $N$
    ($\VAR{vars.N.min} \le N \le \VAR{vars.N.max | sci}$).
    %- endblock
    ```

=== "problem.rbx.yml"

    ```yaml title="problem.rbx.yml"
    vars:
      N:
        min: 1
        max: 1000000000
    ```

The `sci` **filter** renders `1000000000` as `10^9` — one of several LaTeX-aware
filters available in statements.

Everything is LaTeX-flavored {{Jinja2}}, so you also get:

- `%#` — a line comment that is stripped before compilation (unlike `%`, which
  is a normal LaTeX comment that survives).
- `%- ... ` line statements for **loops and conditionals** — the same thing as
  `\BLOCK{ ... }`:

```latex
%- if vars.multitest
Each test file contains several test cases.
%- else
There is a single test case per file.
%- endif
```

For the complete list of what is in scope (`problem`, `vars`, `samples`,
`limits`, filters, …) see [context.md](context.md).

## Samples & explanations

Samples are loaded automatically from your testset and handed to the template as
`problem.samples`; the default template already prints them. To explain a
specific sample, {{rbx}} looks in three places, in **descending priority** (a
higher source wins for the same sample):

1. **An inline `explanation_<i>` block** in the statement file (`explanation_0`
   for the first sample). Because the statement is built per language, this text
   is language-specific.
2. **A sibling file next to the sample input** *(recommended)* — swap the
   suffix: `000.in` → `000.rbx.tex`. It is a blocks file with one block **per
   language**, keyed by the language code:

    ```latex title="statement/samples/000.rbx.tex"
    %- block en
    In the first sample, $A = 3$ and $B = 7$, so the answer is $A + B = 10$.
    %- endblock

    %- block pt
    No primeiro exemplo, $A = 3$ e $B = 7$, logo a resposta é $A + B = 10$.
    %- endblock
    ```

    Only the block matching the statement's language is rendered; it receives
    the same variables as the rest of the statement.
3. **A language-agnostic `000.tex`** — the same text for every language.

!!! warning "One explanation file per sample"
    A sample may not have **both** `000.rbx.tex` and `000.tex` — that is a hard
    error. Pick one.

Markdown statements use the same scheme with Markdown suffixes: `000.rbx.md`
(per-language blocks) or `000.md` (language-agnostic).

## Assets & resources

**The golden rule:** put images, `.sty` files, and PDFs **in the same directory
as your `.tex`**, and reference them by a plain relative path.

```latex title="statement/statement.rbx.tex"
\includegraphics{figure.png}   % figure.png sits next to statement.rbx.tex
```

During a local build (`rbx st b`), {{rbx}} mirrors the directory that holds your
`file` — the whole subtree — so anything sitting next to your `.tex` is staged
automatically. You never need `\graphicspath` or `TEXINPUTS`.

The `assets` field is a **packaging** concern, not a local-build one: it lists
extra globs (relative to the package root) to ship with the statement when you
**export**, notably to {{polygon}}. Use it to declare resources that live
**outside** the statement's directory, since those aren't picked up by the
directory mirroring above.

```yaml title="problem.rbx.yml"
statements:
  - language: "en"
    file: "statement/statement.rbx.tex"
    assets:
      - "shared/logos/*.png"   # out-of-tree resources to ship on export
```

## Other formats

{{rbxtex}} is the default, but `type` accepts a few alternatives (case- and
hyphen-insensitive). Only `rbx-tex` and `rbx-md` process blocks and can **join
into a contest statement** — see [Contest statements](contest.md). The rest are
standalone-only, meant for `documents` or drop-in files.

### Markdown (`rbx-md`)

The same block / variable / {{Jinja2}} machinery as {{rbxtex}}, but you write the
body in Markdown (`.rbx.md`) instead of LaTeX. Ideal for HTML or Markdown output
targets while keeping the block structure.

### Jinja (`jinja-tex` / `jinja-md`)

Full control of the whole document — you write the `\documentclass`,
`\begin{document}`, and everything else, with `\VAR{...}` and `%- ...` available
for interpolation and logic. There are **no blocks**, so these files cannot join
a contest; use them for standalone documents.

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

### Plain LaTeX / Markdown (`tex` / `md`)

The file is treated as a **static** document: no blocks, no variables, no
templating. Reach for these when you already have a finished `.tex` or `.md` and
just want {{rbx}} to compile it as-is.

### PDF (`pdf`)

A pre-built PDF. The build is essentially a copy — no templating, variable
substitution, or asset processing is done. Handy for statements produced by an
external tool or pulled from an old archive.

```yaml title="problem.rbx.yml"
statements:
  - language: "en"
    file: "statement/statement.pdf"
    type: "pdf"
```
