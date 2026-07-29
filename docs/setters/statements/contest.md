# Contest statements

A **contest statement** is the joined task sheet: one document that pulls every
problem's statement into a single book, usually with a cover page and shared
chrome. It lives in `contest.rbx.yml`, and — this is the key idea — it **owns the
templates** that wrap each problem, both inside the book and when a problem is
built on its own.

This page covers the two problem templates, how a contest statement joins the
problems that share its `(language, variant)`, standalone `documents`, and how
`extends` reuses a build recipe across languages.

## The contest owns the templates

A problem statement (in `problem.rbx.yml`) is only *content* — the
[blocks](writing.md#blocks) of what the problem says. It carries **no template**.
The document structure — `\documentclass`, the preamble, how a `legend` block
turns into a section — lives on the **contest** statement, in two fields:

| Field | Produces | Used by |
| :--- | :--- | :--- |
| `standaloneProblemTemplate` | a **full document** for one problem | `rbx st b` |
| `contestProblemTemplate` | a **fragment** `\subimport`-ed into the book | `rbx contest st b` |

Why two? When you build a single problem, it needs a complete document —
`\documentclass`, `\begin{document}`, the works. When the same problem is joined
into the contest book, the book *already* opens the document, so each problem must
contribute only its **body** — no second `\documentclass`. Same content, two
wrappers.

The cleanest way to keep them in sync is to put the shared body in one file and
have both templates include it:

=== "problem-standalone.rbx.tex (full document)"

    ```latex
    \documentclass[a4paper,11pt]{article}
    \usepackage{icpc}
    \usepackage{import}

    \begin{document}
    %- include "_problem-body.rbx.tex"   %# the shared body
    \end{document}
    ```

=== "problem-in-contest.rbx.tex (fragment)"

    ```latex
    %% No \documentclass, no \begin{document}: the book provides those.
    %- include "_problem-body.rbx.tex"   %# the same shared body
    ```

=== "_problem-body.rbx.tex (shared)"

    ```latex
    \section*{\VAR{problem.short_name}. \VAR{problem.title}}

    \VAR{problem.blocks.legend}

    %- if problem.blocks.input is defined
    \subsection*{Input}
    \VAR{problem.blocks.input}
    %- endif
    ```

### Custom blocks

A template is {{latex}} with {{Jinja2}} interpolation (`\VAR{...}` for values,
`%- ...` for logic). It **places content by reading `problem.blocks.<name>`** —
each `%- block legend` in the statement becomes `\VAR{problem.blocks.legend}`, as
the shared body above shows. Block names are free-form, so the same mechanic adds
a section the default chrome doesn't know about: define the block in the problem,
then render it — guarded, since not every problem defines it — in the template.

=== "statement.rbx.tex"

    ```latex
    %- block hint
    Try to use dynamic programming.
    %- endblock
    ```

=== "_problem-body.rbx.tex"

    ```latex
    %- if problem.blocks.hint is defined
    \section*{Hint}
    \VAR{problem.blocks.hint}
    %- endif
    ```

See [Writing statements](writing.md#blocks) for the conventional block names
(`legend`, `input`, `output`, `notes`, ...); [Template context](context.md) lists
the full set of handles in scope (`problem`, `samples`, `limits`, the join
handles, [filters](context.md#filters)).

## Declaring contest statements

A contest statement is a single entry under `statements:` in `contest.rbx.yml`:

```yaml title="contest.rbx.yml"
statements:
  - name: main-en                                        # (1)!
    language: en                                         # (2)!
    variant: default                                     # (3)!
    file: statements/contest-en.rbx.tex                  # (4)!
    type: rbx-tex                                         # (5)!
    standaloneProblemTemplate: statements/problem-standalone.rbx.tex # (6)!
    contestProblemTemplate: statements/problem-in-contest.rbx.tex    # (7)!
    params:                                              # (8)!
      show_limits: true
```

1.  **`name`** — **required** and **unique within the contest**. It identifies
    the entry (positional args to `rbx contest st b` are names) and keys the
    output PDF. Problem statements have no `name`; contest ones must.
2.  **`language`** — ISO 639-1 code. Half of the join key.
3.  **`variant`** — optional discriminator, defaults to `default`. The other half
    of the join key; lets you keep, say, a `short` variant alongside the full one.
4.  **`file`** — the **joined document** itself: the contest book that iterates
    over the problems (see the join loop below).
5.  **`type`** — defaults to `rbx-tex`. Only the `rbx-*` types can join problems,
    so a contest statement is almost always `rbx-tex` (or `rbx-md`).
6.  **`standaloneProblemTemplate`** — full-document template for `rbx st b`.
7.  **`contestProblemTemplate`** — fragment template for the join.
8.  **`params`** — free-form knobs exposed to the templates as `params.*` (kept
    separate from problem/contest `vars` — see [Template context](context.md)).

`variant`, `params`, and the two templates are meaningful only for the `rbx-*`
types; setting them on a non-`rbx` contest statement is an error. For the
exhaustive field list, see the [contest schema](../reference/contest/schema.md).

## The (language, variant) join

Inside the contest `file`, you iterate the `problems` list and `\subimport` each
problem's rendered fragment:

```latex title="statements/contest-en.rbx.tex"
%- for problem in problems
\subimport{\VAR{problem.import_dir}}{\VAR{problem.import_file}}
%- endfor
```

`problem.import_dir` / `problem.import_file` are the `\subimport` handles for the
fragment {{rbx}} built from each problem using your `contestProblemTemplate`. They
exist **only** in this join context — see
[Template context](context.md#import-handles-contest-join-only).

The join is by `(language, variant)`. A contest statement pulls, from every
problem, the problem statement whose `(language, variant)` **matches its own** (the
matched problem statement must also share the contest statement's `rbx-*` type). So
`main-en` (`en`/`default`) joins each problem's `en`/`default` statement.

The same key drives the **standalone** build. For `rbx st b` to build a problem on
its own, exactly **one** contest statement must carry a `standaloneProblemTemplate`
for that problem's `(language, variant)`:

- **Exactly one** — that template is used. This is the normal case.
- **More than one** — a hard error: two contest statements both claim the same
  `(language, variant)`; disambiguate by removing one template.
- **Zero (or no contest at all)** — not an error: {{rbx}} falls back to the
  bundled default template and **warns**.

## Building

Each list has its own builder; contest and problem builds use the two templates
differently.

<!--termynal-->
```bash
# Build the contest book (joins problems) + its documents
$ rbx contest statements build     # alias: rbx contest st b

# Build ONE problem standalone, using the contest's standaloneProblemTemplate
$ rbx st b

# Build only some contest statements, by name
$ rbx contest st b main-en main-pt

# Restrict to languages (repeatable) or render against a timing profile
$ rbx contest st b --languages en --languages pt
$ rbx contest st b -p icpc
```

- **`rbx contest st b`** renders each problem with the `contestProblemTemplate`,
  joins them through the contest `file`, and produces
  `build/<statement-name>[-<profile>].pdf` — keyed by the contest statement's
  **`name`**, not its language. It also builds the contest
  [`documents`](#documents); the [tutorials](tutorials.md) builder does not.
- **`rbx st b`** builds a single problem in place with the matching
  `standaloneProblemTemplate`, producing
  `build/statement-<lang>[-<variant>][-<profile>].pdf`.

!!! warning "Unselected dispatcher"
    The zero-match fallback above has one exception: if the contest here is an
    **unselected multi-contest dispatcher**, `rbx st b` errors instead of falling
    back — pass `-C <id>` (or set `RBX_CONTEST=<id>`) to pick a contest.

## Documents

`documents` are contest-only standalone pages that **never join problems** —
infosheets, cover pages, instruction sheets. They live in their own list:

```yaml title="contest.rbx.yml"
documents:
  - name: infosheet-en
    language: en
    file: statements/infosheet-en.jinja.tex
    type: jinja-tex
```

Because a document never joins, its `type` must be one that carries no blocks —
`jinja-tex`, `jinja-md`, `tex`, `md`, or `pdf` (never the joining `rbx-*` types).

A document still receives the `problems` list, but **metadata-only**: each entry
exposes `title`, `short_name`, `limits`, `profiles`, and `groups` — **no**
`blocks`, `samples`, or import handles. That is enough for a summary page such as
a per-problem limits table:

```latex title="statements/infosheet-en.jinja.tex"
\begin{tabular}{c|cc}
{\sf Problem} & {\sf Time (ms)} & {\sf Memory (MB)} \\
\hline
%- for problem in problems
\VAR{problem.short_name}
& \VAR{problem.limits.timeLimit}
& \VAR{problem.limits.memoryLimit} \\
%- endfor
\end{tabular}
```

Documents are built by `rbx contest st b`, alongside the contest statements.

## Location and date

`location` and `date` are **per-language** fields on a contest statement — the
place and date as they should read in that language. They surface in the
`contest.*` namespace (see [Template context](context.md)), so your cover page can
print them:

```yaml title="contest.rbx.yml"
statements:
  - name: main-en
    language: en
    file: statements/contest-en.rbx.tex
    location: "Porto, Portugal"
    date: "July 29, 2026"
  - name: main-pt
    language: pt
    file: statements/contest-pt.rbx.tex
    location: "Porto, Portugal"
    date: "29 de julho de 2026"
```

## Reusing recipes with extends

Multiple languages usually share almost everything but the source file. `extends`
lets one entry inherit another's **build recipe** so you don't repeat it.

A contest statement extends another **by `name`**:

```yaml title="contest.rbx.yml"
statements:
  - name: main-en
    language: en
    file: statements/contest-en.rbx.tex
    standaloneProblemTemplate: statements/problem-standalone.rbx.tex
    contestProblemTemplate: statements/problem-in-contest.rbx.tex
  - name: main-pt
    language: pt
    extends: main-en                      # (1)!
    file: statements/contest-pt.rbx.tex   # (2)!
```

1.  Inherits the recipe from `main-en`: `type` and **both templates**. It does
    **not** inherit `main-en`'s identity — `main-pt` keeps its own `name`,
    `language`, and `variant`.
2.  Override just the joined document; everything else is inherited.

A problem statement (in `problem.rbx.yml`) extends by **language** (`extends: en`)
or by a `{language, variant}` pair:

```yaml title="problem.rbx.yml"
statements:
  - language: en
    file: statements/statement.rbx.tex
    params: { show_limits: true }
  - language: pt
    extends: en                      # (1)!
    params: { show_limits: false }   # (2)!
```

1.  Inherits `file`, `type`, `assets`, and `params` from the `en` statement.
2.  `params` **deep-merges** key by key: `pt` overrides `show_limits`, and any
    other keys defined on `en` are kept.

The merge is an **allowlist of the build recipe only** — `type`, `file`,
`params`, `assets`, and (contest statements only) `standaloneProblemTemplate` /
`contestProblemTemplate`. It **never** copies identity (`name`, `language`,
`variant`), and `params` deep-merges rather than replacing. Cycles and dangling
`extends` references are errors.

## Learn through examples

The [default preset](https://github.com/rsalesc/rbx/blob/main/rbx/resources/presets/default/contest/)
ships a complete, working contest: a joined task sheet, both problem templates
sharing one body file, an editorial, and an infosheet document. It is the best
starting point to copy and adapt.
