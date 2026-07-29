# Template context

A statement — and the [template](templates.md) that wraps it — reaches everything
through a handful of **namespaces** exposed to `\VAR{...}` and the `%- ...` /
`\BLOCK{...}` {{Jinja2}} statements. This page is the reference for what lives in
each one, and why they stay separate.

## Namespaces don't merge

`params`, `vars`, and `contest` are **three distinct namespaces**. Older versions
of {{rbx}} collapsed everything into one merged `vars`; now each source keeps its
own name and nothing is copied between them. Reaching a value means knowing which
namespace it belongs to:

```latex
\VAR{params.show_limits}   %# the statement's own param
\VAR{vars.author}          %# a problem/package var
\VAR{contest.title}        %# contest metadata
\VAR{contest.vars.year}    %# a contest var (dotted, separate)
```

The exact set of top-level names depends on **what is being rendered**:

| Namespace | Contents | Available in |
| :--- | :--- | :--- |
| `params` | this render's own statement `params` | all renders |
| `vars` | the problem/package `vars` (problem render) or contest `vars` (contest render) | all renders |
| `contest` | `contest.title`, `contest.vars.*`, and (when set) `contest.location` / `contest.date` | all renders |
| `problem` | `title`, `limits`, `profiles`, `groups`, `samples`, `vars`, `params`, `blocks`, and (when set) `short_name`, `import_dir`, `import_file` | problem renders |
| `problems` | a list of the above (full in a contest join; metadata-only in a document) | contest join; documents |
| `lang`, `languages`, `keyed_languages` | environment languages | all renders |

!!! note "`problem` vs `problems`"
    A **problem render** (`rbx st b`, and each problem inside a contest join)
    exposes the singular `problem` — there is **no `problems`**. The **contest
    joining document** exposes the list `problems` — there is **no singular
    `problem`**. [Documents](contest.md) also get `problems`, but metadata-only
    (per-problem `title` / `short_name` / `limits` / `profiles` / `groups`; no
    `blocks`, `samples`, or import handles).

## `params` vs `vars`

They answer two different questions, so they live in two different namespaces:

- **`vars`** is *your problem's own data* — constraints, an author name, a flag
  your statement text keys off. It comes from `vars` in `problem.rbx.yml` (or the
  contest's `vars` in a contest render).
- **`params`** are *knobs for the template/presentation* — e.g. whether to draw
  the limits box. They come from the `params` of the statement entry being
  rendered.

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
      author: "Jane Doe"      # your problem's data → vars.*
    statements:
      - language: en
        file: statement/statement.rbx.tex
        params:
          show_limits: true   # a template knob → params.*
    ```

`contest` is a **separate, dotted** namespace — it is never folded into the
top-level `vars`. A contest variable is `\VAR{contest.vars.year}`, and the
contest title is `\VAR{contest.title}`; top-level `vars` still means the
*problem's* vars in a problem render.

```latex
\VAR{vars.author}        %# the problem's var
\VAR{contest.vars.year}  %# a contest var — dotted, never merged into vars
```

## The `problem` namespace

In a problem render, `problem` is the one problem being built. Its most-used
fields:

```latex
\VAR{problem.title}                  %# the problem title
\VAR{problem.limits.timeLimit} ms    %# time limit (ms)
\VAR{problem.limits.memoryLimit} MiB %# memory limit (MiB)
```

`problem.short_name` (the letter, e.g. `A`) is **conditional** — it may be unset,
so guard it:

```latex
%- if problem.short_name is defined
\textbf{\VAR{problem.short_name}.} \VAR{problem.title}
%- endif
```

`problem.vars` and `problem.params` hold that problem's own vars/params — the same
data as top-level `vars`/`params` in a standalone render. They matter mostly when
iterating `problems` in a [contest join](contest.md), where each member exposes
its own `problem.vars.*`.

### Pulling blocks into a template

`problem.blocks` is a dict of **block-name → rendered {{latex}}**. This is how a
template places the statement's content: each `%- block legend` in the source
becomes `problem.blocks.legend`.

```latex
\VAR{problem.blocks.legend}

%- if problem.blocks.input is defined
\section*{Input}
\VAR{problem.blocks.input}
%- endif
```

Block names are free-form. See [Writing statements](writing.md#blocks) for the
conventional set (`legend`, `input`, `output`, `notes`, ...).

### Import handles (contest join only)

`problem.import_dir` and `problem.import_file` are the `\subimport` handle for a
problem being pulled into a contest book. They exist **only** in a contest-join
fragment — they are **absent** in a standalone `rbx st b` render, so guard them:

```latex
%- if problem.import_dir is defined
\subimport{\VAR{problem.import_dir}}{\VAR{problem.import_file}}
%- endif
```

See [Contest statements](contest.md) for the full join pattern.

## Per-sample handles

Samples are handed to the template as `problem.samples` — a list you iterate. Each
item is a **sample handle** with these fields:

| Field | Meaning |
| :--- | :--- |
| `sample.index` | 0-based position (int) |
| `sample.input` | root-relative path to the input file |
| `sample.output` | root-relative path to the output file |
| `sample.has_output` | whether an output file exists (bool) |
| `sample.dir` | import-base directory for the explanation |
| `sample.explanation_file` | explanation file to `\subimport` (when present) |
| `sample.interaction` | interaction protocol (interactive problems), carrying `.chunks` |

`sample.input` / `sample.output` are **path strings meant for verbatim printing** —
feed them straight to `\VerbatimInput`. The explanation is a separate file you
`\subimport` from `sample.dir`; guard it, since not every sample has one:

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
    `sample.input` / `sample.output` are **root-relative** (`\VerbatimInput`
    ignores the `\subimport` base), while `sample.dir` / `sample.explanation_file`
    are **import-base-relative** for `\subimport`. You don't have to think about
    it — just use each handle as shown.

For an **interactive** problem, iterate `sample.interaction.chunks` instead of
printing plain I/O; each chunk carries `.path`, `.pipe`, and `.data`:

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

The tables above cover what you reach for day to day. For the **exhaustive** field
list — every attribute on `limits`, `profiles`, `groups`, and the statement entry
itself — consult the auto-generated schemas instead of restating them here:

- [Package schema](../reference/package/schema.md) — problems, statements, `vars`,
  `params`, samples, and limits.
- [Contest schema](../reference/contest/schema.md) — contest statements, documents,
  and the contest `vars`.
