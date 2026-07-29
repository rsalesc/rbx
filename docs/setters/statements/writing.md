# Writing statements

{{rbxtex}} (extension `.rbx.tex`) is our recommended way of writing a problem
statement in {{rbx}}, and this page is a tour of it — from blocks, to samples, to
assets. We'll finish with the other formats {{rbx}} understands too, but be
warned: unless you have a specific reason to reach for one of them, {{rbxtex}} is
what you want.

## Why rbxTeX

An {{rbxtex}} file is just a set of named **blocks** of content, sprinkled with
{{Jinja2}} for variables and logic. It's a superset of {{latex}} — anything you
can write in LaTeX, you can write here:

```latex title="statements/statement.rbx.tex"
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

The file above carves the statement into three blocks — `legend`, `input` and
`output` — and nothing else. Notice what's *not* there: no `\documentclass`, no
fonts, no section titles. Those blocks only hold *what the problem says*; a
separate [template](contest.md#the-contest-owns-the-templates) decides *how it
looks*. That separation is the whole point:

- **Swap the look** by changing the template — the content never moves.
- **Full LaTeX power** is still there; {{rbxtex}} is just a thin wrapper around it.
- **Samples and variables** are injected for you, so your content stays clean.

And you rarely have to configure anything. `rbx-tex` is the default `type`, so
just pointing `file` at your `.rbx.tex` is enough:

=== "problem.rbx.yml"

    ```yaml
    statements:
      - language: "en"                        # (1)!
        file: "statements/statement.rbx.tex"   # (2)!
    ```

    1.  The language code (ISO 639-1) this statement is written in.
    2.  The `.rbx.tex` source, relative to the package root. `type` defaults to
        `rbx-tex`, so it can be omitted.

=== "Directory layout"

    ```text
    statements/
      statement.rbx.tex      # your blocks
      samples/
        000.in
        000.rbx.tex          # explanation for sample 0 (optional)
    ```

See the [package schema](../reference/package/schema.md) for every field a
statement entry accepts.

## Blocks

A block is just a chunk of content between `%- block <name>` and `%- endblock`:

```latex title="statements/statement.rbx.tex"
%- block legend
Given an array of $\VAR{vars.n}$ integers, find the largest sum of a
contiguous subarray.
%- endblock
```

The block above is named `legend` — and that's all a block is: a **named chunk of
your statement's content**. Block names are **free-form** — any `%- block foo`
works, there is no fixed list, so custom blocks are perfectly fine. How a template
later turns these blocks into a rendered page is a story for
[context.md](context.md); we'll get to how they're rendered there.

That said, the bundled default template (and every preset that inherits it)
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
them even get special treatment when packaging for {{polygon}}.

Want a section of your own? Define the block right here; wiring it into the page
comes later, from the [template](contest.md#custom-blocks):

```latex title="statements/statement.rbx.tex"
%- block hint
Try to use dynamic programming.
%- endblock
```

!!! note "There is no `editorial` block"
    An editorial is a **separate statement file** — a *tutorial* — that puts its
    solution text in a `legend` block, not an `editorial` block inside the
    problem statement. See [Tutorials and editorials](tutorials.md).

## Variables and logic

You can interpolate any value from `problem.rbx.yml` (and the built-in context)
into your statement with `\VAR{...}`. Your problem-level `vars` live under
`vars.*`:

=== "statement.rbx.tex"

    ```latex
    %- block input
    The first line contains an integer $N$
    ($\VAR{vars.N.min} \le N \le \VAR{vars.N.max | sci}$).
    %- endblock
    ```

=== "problem.rbx.yml"

    ```yaml
    vars:
      N:
        min: 1
        max: 1000000000
    ```

The snippet above reads `N.min` and `N.max` straight out of `problem.rbx.yml`, so
the bounds printed in the statement and the bounds your validator checks come from
the exact same place — change one, and both follow. That's the whole point of
`vars`: they're your problem's own values, referenced with `\VAR{vars.…}`, a
single source of truth.

The `sci` **filter** renders `1000000000` as `10^9` — one of several LaTeX-aware
filters available in statements.

Everything is LaTeX-flavored {{Jinja2}}, so you get a bit more than plain
interpolation:

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

The block above prints one line or the other depending on `vars.multitest`, so a
single statement file can cover both the single-case and multi-case flavors of
your problem.

For the complete list of what is in scope (`problem`, `vars`, `samples`,
`limits`, [filters](context.md#filters), …) see [context.md](context.md).

## Sample explanations

Samples are loaded automatically from your testset, and the default template
already prints them — you don't have to lift a finger for the samples themselves
to show up. To *explain* a specific sample, though, {{rbx}} looks in three
places, in **descending priority** (for the same sample, a higher source wins):

1. **An inline `explanation_<i>` block** in the statement file (`explanation_0`
   for the first sample). Because the statement is built per language, this text
   is language-specific.
2. **A sibling file next to the sample input** *(recommended)* — swap the
   suffix: `000.in` → `000.rbx.tex`. It is a blocks file with one block **per
   language**, keyed by the language code:

    ```latex title="statements/samples/000.rbx.tex"
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

## Assets and resources

**The golden rule:** put images, `.sty` files and PDFs **in the same directory
as your `.tex`**, and reference them by a plain relative path:

```latex title="statements/statement.rbx.tex"
\includegraphics{figure.png}   % figure.png sits next to statement.rbx.tex
```

The line above references `figure.png` by name, and it just works because that
file sits right next to `statement.rbx.tex`. During a local build (`rbx st b`),
{{rbx}} mirrors the directory that holds your `file` — the whole subtree — so
anything sitting next to your `.tex` is staged for you, automagically.

!!! tip
    Keep everything next to your `.tex` and you'll never have to touch
    `\graphicspath` or `TEXINPUTS` — {{rbx}} sorts out the paths for you.

The `assets` field, on the other hand, is a **packaging** concern, not a
local-build one: it lists extra globs (relative to the package root) to ship with
the statement when you **export**, notably to {{polygon}}. Use it to declare
resources that live **outside** the statement's directory, since those aren't
picked up by the directory mirroring above:

```yaml title="problem.rbx.yml"
statements:
  - language: "en"
    file: "statements/statement.rbx.tex"
    assets:
      - "shared/logos/*.png"   # out-of-tree resources to ship on export
```

## Other formats

{{rbxtex}} is the default, and for the vast majority of problems it's all you'll
ever touch. Still, `type` accepts a few alternatives — the [Formats at a
glance](index.md#formats-at-a-glance) table in the Overview lists them all. The
one thing to keep in mind: only `rbx-tex` and `rbx-md` process blocks and can
**join into a contest statement** (see [Contest statements](contest.md)). The
rest are standalone-only, meant for [`documents`](index.md#the-three-kinds) or
drop-in files.

### Markdown (`rbx-md`)

The same block / variable / {{Jinja2}} machinery as {{rbxtex}}, except you write
the body in Markdown (`.rbx.md`) instead of LaTeX. Reach for it when you're
targeting HTML or Markdown output and still want the block structure.

### Jinja (`jinja-tex` / `jinja-md`)

Full control of the whole document — you write the `\documentclass`,
`\begin{document}`, and everything else, with `\VAR{...}` and `%- ...` available
for interpolation and logic. There are **no blocks** here, so these files can't
join a contest; use them for standalone documents:

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

The document above is a complete, self-contained LaTeX file — it declares its own
`\documentclass` and loops over `problem.samples` by hand. You get all the
interpolation, but none of the block structure, which is exactly why it can't
join a contest.

### Plain LaTeX / Markdown (`tex` / `md`)

The file is treated as a **static** document: no blocks, no variables, no
templating. Reach for these when you already have a finished `.tex` or `.md` and
just want {{rbx}} to compile it as-is.

### PDF (`pdf`)

A pre-built PDF. The build is essentially a copy — no templating, variable
substitution, or asset processing happens at all. Handy for statements produced
by an external tool, or pulled out of an old archive:

```yaml title="problem.rbx.yml"
statements:
  - language: "en"
    file: "statements/statement.pdf"
    type: "pdf"
```

And that's every format {{rbx}} understands. When you're ready to see what your
blocks actually have in scope, and how templates turn them into a polished PDF,
head over to [Template context](context.md) and [Contest statements](contest.md).
