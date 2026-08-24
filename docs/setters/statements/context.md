# Template context

Every value a statement prints, and every value the [template](contest.md) that
wraps it reaches for, comes from one of a handful of **namespaces** exposed to
`\VAR{...}` and to the `%- ...` {{Jinja2}} statements. This page is the
reference for what lives in each one, and for why they stay separate.

## Why the namespaces don't merge

Here is the pain this design spares you. Older versions of {{rbx}} collapsed
everything into one merged `vars`: your problem's data, the template's knobs,
the contest's metadata. That is convenient right up until two of those sources
want the same key. One of them silently wins, and you are left debugging a
statement that prints the wrong number with no way to tell which source produced
it.

So they no longer merge. `params`, `vars` and `contest` are **three distinct
namespaces**, each source keeps its own name, and nothing is copied between
them. Reaching a value means knowing which namespace it belongs to:

```latex
\VAR{params.show_limits}   %# the statement's own param
\VAR{vars.author}          %# a problem/package var
\VAR{contest.title}        %# contest metadata
\VAR{contest.vars.year}    %# a contest var, dotted and separate
```

The exact set of top-level names depends on **what is being rendered**:

| Namespace | Contents | Available in |
| :--- | :--- | :--- |
| `params` | this render's own statement `params` | all renders |
| `vars` | the problem/package `vars` (problem render) or the contest `vars` (contest join) | all renders |
| `contest` | `contest.title`, `contest.vars.*`, and when set `contest.location` / `contest.date` | all renders |
| `problem` | `title`, `limits`, `profiles`, `groups`, `samples`, `vars`, `params`, `blocks`, and when set `short_name`, `import_dir`, `import_file` | problem renders |
| `problems` | a list of the above, full in a contest join and metadata-only in a document | contest join; documents |
| `lang`, `languages`, `keyed_languages` | environment languages | all renders |

!!! note "`problem` vs `problems`"
    A **problem render** (`rbx st b`, and each problem inside a contest join)
    exposes the singular `problem`, and there is **no `problems`**. The
    **contest joining document** exposes the list `problems`, and there is **no
    singular `problem`**. [Documents](contest.md#cover-pages-and-infosheets) also
    get `problems`, but metadata-only: per-problem `title`, `short_name`,
    `limits`, `profiles` and `groups`, with no `blocks`, `samples` or import
    handles.

## `params` vs `vars`

They answer two different questions, which is why they sit in two different
namespaces.

- **`vars`** is *your problem's own data*: constraints, an author name, a flag
  your statement text keys off. It comes from `vars` in `problem.rbx.yml`, or
  from the contest's `vars` in a contest join.
- **`params`** are *knobs for the presentation*, such as whether to draw the
  limits box. They come from the `params` of the statement entry being rendered.

Let's put them side by side. The author name is data; the "show limits" toggle
is a presentation knob:

=== "statement.rbx.tex"

    ```latex
    %- if params.show_limits
    Time limit: \VAR{problem.limits.timeLimit} ms.
    %- endif

    Problem by \VAR{vars.author}.
    ```

=== "problem.rbx.yml"

    ```yaml
    vars:
      author: "Jane Doe"      # your problem's data -> vars.*
    statements:
      - language: en
        file: statements/statement.rbx.tex
        params:
          show_limits: true   # a presentation knob -> params.*
    ```

Notice that `author` and `show_limits` sit in the *same* `problem.rbx.yml`, and
the template reaches them as `vars.author` and `params.show_limits`, never as
one flattened blob.

`contest` is a separate, dotted namespace, and it is never folded into the
top-level `vars`. A contest variable is `\VAR{contest.vars.year}`; the contest
title is `\VAR{contest.title}`. Top-level `vars` still means the *problem's*
vars in a problem render, so in a single render these two point at
different values:

```latex
\VAR{vars.author}        %# the problem's var
\VAR{contest.vars.year}  %# a contest var, never merged into vars
```

## The `problem` namespace

In a problem render, `problem` is the problem you are building. Its most-used
fields:

```latex
\VAR{problem.title}                  %# the problem title
\VAR{problem.limits.timeLimit} ms    %# time limit (ms)
\VAR{problem.limits.memoryLimit} MB  %# memory limit (MB)
```

`problem.short_name` (the letter, `A`) is **conditional**. It may be unset, so
guard it:

```latex
%- if problem.short_name is defined
\textbf{\VAR{problem.short_name}.} \VAR{problem.title}
%- endif
```

`problem.vars` and `problem.params` hold that problem's own vars and params, the
same data as the top-level `vars` and `params` in a standalone render. They
matter mostly when iterating `problems` in a [contest join](contest.md), where
each member exposes its own `problem.vars.*`.

## Pulling blocks into a template

`problem.blocks` is a dict of block-name to rendered {{latex}}. This is how a
template places the statement's content: each `%- block legend` in the source
becomes `problem.blocks.legend`. So a template drops the legend in, and the
input section only when it exists, like this:

```latex
\VAR{problem.blocks.legend}

%- if problem.blocks.input is defined
\section*{Input}
\VAR{problem.blocks.input}
%- endif
```

Block names are free-form. See [Writing statements](writing.md#blocks) for the
conventional set.

## Printing the samples

Samples are handed to the template as `problem.samples`, a list you iterate.
Each item is a **sample handle**:

| Field | Meaning |
| :--- | :--- |
| `sample.index` | 0-based position (int) |
| `sample.input` | root-relative path to the input file |
| `sample.output` | root-relative path to the output file |
| `sample.has_output` | whether an output file exists (bool) |
| `sample.dir` | import-base directory for the explanation |
| `sample.explanation_file` | explanation file to `\subimport`, when present |
| `sample.interaction` | interaction protocol for interactive problems |

`sample.input` and `sample.output` are **path strings meant for verbatim
printing**, so feed them straight to `\VerbatimInput`. The explanation is a
separate file you `\subimport` from `sample.dir`, and you should guard it, since
not every sample has one:

```latex
%- for sample in problem.samples
\VerbatimInput{\VAR{sample.input}}
%- if sample.has_output
\VerbatimInput{\VAR{sample.output}}
%- endif
%- if sample.explanation_file is defined
\subimport{\VAR{sample.dir}}{\VAR{sample.explanation_file}}
%- endif
%- endfor
```

!!! note "Why two path anchorings"
    `sample.input` and `sample.output` are **root-relative**, because
    `\VerbatimInput` ignores the `\subimport` base. `sample.dir` and
    `sample.explanation_file` are **import-base-relative**, for `\subimport`.
    You don't have to think about it; use each handle as shown above.

## Filters

Any `\VAR{...}` value can be piped through a **filter** with `|`, as in
{{Jinja2}}. On top of the standard {{Jinja2}} filters, {{rbx}} registers a few
LaTeX-aware ones you will reach for constantly:

- **`sci`** renders a round integer in scientific notation:
  `\VAR{vars.N.max | sci}` prints `1000000000` as `10^9`.
- **`rsci`** is `sci` with the remainder kept: `\VAR{vars.MOD | rsci}` prints
  `1000000007` as `10^9 + 7`.
- **`escape`** LaTeX-escapes a string (`_`, `%`, `&`, ...):
  `\VAR{vars.author | escape}`.
- **`parent`** takes a path's parent directory: `\VAR{sample.input | parent}`.
- **`stem`** takes a path's filename without its extension:
  `\VAR{sample.input | stem}`.

The standard {{Jinja2}} filters (`upper`, `join`, `default`, ...) work too.

## Building a subtasks table from testgroup vars

A scored problem usually wants a table of its subtasks, and the constraints in
that table are the ones the validator enforces for each group. {{rbx}} exposes
them: the variables of each testgroup, after applying its [per-testgroup
overrides](../verification/validators.md#varying-constraints-per-test-group), are
available as `problem.groups.<name>.vars.<key>`.

So the whole table is a loop:

=== "template.rbx.tex"

    ```latex
    \begin{tabular}{lcc}
    {\sf Subtask} & {\sf Score} & {\sf Constraints} \\
    \hline
    %- for g in problem.groups
    \VAR{g.name} & \VAR{g.score} & $N \le \VAR{g.vars.N.max}$ \\
    %- endfor
    \end{tabular}
    ```

=== "problem.rbx.yml"

    ```yaml
    vars:
      N:
        min: 1
        max: 1000
    testcases:
      - name: "small"
        score: 30
        vars:
          N:
            max: 50 # (1)!
      - name: "large"
        score: 70 # (2)!
    ```

    1.  Overrides `N.max` for this group only.
    2.  No override, so the package-level values apply.

The loop above prints `50` for `small` and `1000` for `large`. These are the
**resolved** values, so a testgroup that overrides nothing still renders the
package-level number, and you never have to restate a constraint you did not
change. The [shorthand](writing.md#shorthand-for-vars) works here too:
`\VAR{g.N.max}`.

## Import handles

`problem.import_dir` and `problem.import_file` are the `\subimport` handle for a
problem being pulled into a contest book. They exist **only** in a contest-join
fragment, and are absent in a standalone `rbx st b` render, so guard them:

```latex
%- if problem.import_dir is defined
\subimport{\VAR{problem.import_dir}}{\VAR{problem.import_file}}
%- endif
```

See [Contest statements](contest.md#the-language-variant-join) for the full join
pattern.

## Interactive samples

For an [interactive problem](../grading/interactors.md), a sample is a
conversation rather than an input and an output file. Iterate
`sample.interaction.chunks` instead of printing plain I/O, and each chunk carries
`.path`, `.pipe` and `.data`:

```latex
%- for sample in problem.samples
%- if sample.interaction is not none
%- for chunk in sample.interaction.chunks
\interactionchunk{\VAR{chunk.path}}{\VAR{chunk.pipe}}
%- endfor
%- endif
%- endfor
```

## Full field reference

The tables above cover what you reach for day to day. For the exhaustive field
list, every attribute on `limits`, `profiles`, `groups` and the statement entry
itself, consult the auto-generated schemas rather than a restatement of them
here:

- [Package schema](../reference/package/schema.md) for problems, statements,
  `vars`, `params`, samples and limits.
- [Contest schema](../reference/contest/schema.md) for contest statements,
  documents and the contest `vars`.

And once you know what is in the context, [Contest statements](contest.md) is the
page that puts it to work.
