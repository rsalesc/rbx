# Contest statements

A **contest statement** is the joined task sheet: one document that pulls every
problem's statement into a single book, usually with a cover page and shared
chrome. It lives in `contest.rbx.yml`.

Here's the key idea: the contest
**owns the templates** that wrap each problem — both inside the book and when a
problem is built on its own. The problem brings only the content; the contest
decides how it looks.

In the sections below, we'll go through the two problem templates, how a contest
statement joins the problems that share its `(language, variant)`, the standalone
`documents` that never join, and how `extends` lets you reuse a build recipe across
languages.

## The contest owns the templates

A problem statement (in `problem.rbx.yml`) is only *content* — the
[blocks](writing.md#blocks) of what the problem says. It carries **no template** of
its own. The document structure — `\documentclass`, the preamble, how a `legend`
block turns into a section — lives on the **contest** statement, in two fields:

| Field | Produces | Used by |
| :--- | :--- | :--- |
| `standaloneProblemTemplate` | a **full document** for one problem | `rbx st b` |
| `contestProblemTemplate` | a **fragment** `\subimport`-ed into the book | `rbx contest st b` |

Why two? Because a problem gets built in two very different situations. When you
build a single problem on its own, it needs a complete document — `\documentclass`,
`\begin{document}`, the works. When that same problem is joined into the contest
book, though, the book *already* opened the document, so each problem must
contribute only its **body** — no second `\documentclass`. Same content, two
wrappers.

Writing that body twice would be asking for the two copies to drift apart. The
cleanest way to keep the templates in sync is to put the shared body in one file
and have both of them include it. Below, the two templates and the body they share:

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

The standalone template above opens a full document and `%- include`s the body; the
fragment includes the *same* body with no wrapper of its own. Change the body once,
and both builds follow.

### Custom blocks

A template is {{latex}} with {{Jinja2}} interpolation — `\VAR{...}` drops in a
value, `%- ...` runs logic. The way it places content is by reading
`problem.blocks.<name>`: each `%- block legend` you wrote in the statement shows up
as `\VAR{problem.blocks.legend}`, exactly as the shared body above does it.

Block names are free-form, so the same mechanic lets you
add a section the default chrome knows nothing about. Define the block in the
problem, then render it in the template. Notice we guard it with `%- if ... is
defined`, since not every problem will define every block:

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

The block above only shows up for problems that actually wrote a `hint`; everyone
else's document is untouched.

See [Writing statements](writing.md#blocks) for the conventional block names
(`legend`, `input`, `output`, `notes`, ...), and [Template context](context.md) for
the full set of handles in scope (`problem`, `samples`, `limits`, the join handles,
[filters](context.md#filters)).

## Declaring contest statements

A contest statement is a single entry under `statements:` in `contest.rbx.yml`.
Below, a fully wired one, field by field:

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

`variant`, `params`, and the two templates only mean something for the `rbx-*`
types — set them on a non-`rbx` contest statement and {{rbx}} will error out. For
the exhaustive field list, see the [contest schema](../reference/contest/schema.md).

## The (language, variant) join

Inside the contest `file`, you walk the `problems` list and `\subimport` each
problem's rendered fragment:

```latex title="statements/contest-en.rbx.tex"
%- for problem in problems
\subimport{\VAR{problem.import_dir}}{\VAR{problem.import_file}}
%- endfor
```

The loop above is the whole join. `problem.import_dir` / `problem.import_file` are
the `\subimport` handles {{rbx}} hands you for the fragment it built from each
problem using your `contestProblemTemplate`. They exist **only** here, in the join
context — see [Template context](context.md#import-handles-contest-join-only).

But which statement does each problem contribute? The join is by
`(language, variant)`. A contest statement pulls, from every problem, the problem
statement whose `(language, variant)` **matches its own** (and the matched problem
statement has to share the contest statement's `rbx-*` type). So `main-en`
(`en`/`default`) joins each problem's `en`/`default` statement — nothing more
magical than that.

That same key drives the **standalone** build too. For `rbx st b` to build a
problem on its own, exactly **one** contest statement must carry a
`standaloneProblemTemplate` for that problem's `(language, variant)`:

- **Exactly one** — that template is used. This is the normal case.
- **More than one** — a hard error: two contest statements both claim the same
  `(language, variant)`; disambiguate by removing one template.
- **Zero (or no contest at all)** — not an error: {{rbx}} falls back to the
  bundled default template and **warns**.

## Building

Each list has its own builder, and the two of them reach for the two templates
differently:

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

Sometimes a contest needs a page that isn't a problem at all — an infosheet, a
cover page, an instruction sheet. Those are `documents`: contest-only standalone
pages that **never join problems**. They live in their own list:

```yaml title="contest.rbx.yml"
documents:
  - name: infosheet-en
    language: en
    file: statements/infosheet-en.jinja.tex
    type: jinja-tex
```

Because a document never joins, its `type` has to be one that carries no blocks —
`jinja-tex`, `jinja-md`, `tex`, `md`, or `pdf`, and never the joining `rbx-*`
types.

It does still receive the `problems` list, but **metadata-only**: each entry
exposes `title`, `short_name`, `limits`, `profiles`, and `groups` — and **no**
`blocks`, `samples`, or import handles. That's exactly enough for a summary page,
like a per-problem limits table:

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

The table above walks the same `problems` list the contest book does, but reads
only metadata off each one. Documents are built by `rbx contest st b`, right
alongside the contest statements.

## Location and date

`location` and `date` are **per-language** fields on a contest statement — the
place and date exactly as they should read in that language. They surface in the
`contest.*` namespace (see [Template context](context.md)), so a cover page can
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

Notice the two entries above share a location but not a date string: `main-en`
reads "July 29, 2026", `main-pt` reads "29 de julho de 2026". Same event, each
language phrasing it its own way.

## Reusing recipes with extends

Across languages, two statements usually share almost everything except the source
file itself. Repeating the whole recipe on each one is exactly the kind of thing
that drifts out of sync — so `extends` lets one entry inherit another's **build
recipe** and only spell out what actually differs.

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

A problem statement (in `problem.rbx.yml`) is a little different — it extends by
**language** (`extends: en`) or by a `{language, variant}` pair:

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

Whichever side you're on, the merge is an **allowlist of the build recipe only** —
`type`, `file`, `params`, `assets`, and (contest statements only)
`standaloneProblemTemplate` / `contestProblemTemplate`. It **never** copies identity
(`name`, `language`, `variant`), and `params` deep-merges key by key rather than
replacing wholesale. Cycles and dangling `extends` references are errors.

## Learn through examples

Reading about templates only gets you so far — the fastest way in is a working one.
The [default preset](https://github.com/rsalesc/rbx/blob/main/rbx/resources/presets/default/contest/)
ships a complete, working contest: a joined task sheet, both problem templates
sharing one body file, an editorial, and an infosheet document. It's the best
starting point to copy and adapt, so grab it and start deleting the parts you don't
need.

From here, [Writing statements](writing.md) covers the blocks and {{rbxtex}} syntax
that fill these templates, [Template context](context.md) is the full reference for
every handle in scope, and [Tutorials](tutorials.md) does for editorials what this
page did for statements.
