# Contest statements

A **contest statement** is the joined task sheet: one document that pulls every
problem's statement into one book, usually behind a cover page and shared
chrome. It lives in `contest.rbx.yml`.

The templates that wrap each problem **belong to the contest**, both inside the
book and when a problem is built on its own. The problem provides the content,
and the contest decides how it looks. So you can restyle eight problems by editing
one file, and a problem written for last year's regional can go into this year's
book unchanged.

In the sections below we'll go through the two problem templates, how a contest
statement joins the problems that share its `(language, variant)`, and then the
extras: custom blocks, cover pages, `extends`, and what happens when a problem
refuses to build.

## The contest owns the templates

A problem statement is only *content*: the [blocks](writing.md#blocks) of what
the problem says. It has **no template** of its own. The document structure
lives on the contest statement, in two fields:

| Field | Produces | Used by |
| :--- | :--- | :--- |
| `standaloneProblemTemplate` | a **full document** for one problem | `rbx st b` |
| `contestProblemTemplate` | a **fragment** `\subimport`-ed into the book | `rbx contest st b` |

Why two? Because a problem gets built in two different situations. Built on its
own, it needs a complete document: `\documentclass`, `\begin{document}`, the
works. Joined into the contest book, the book has already opened the document,
so each problem must contribute only its **body**, with no second
`\documentclass`. Same content, two wrappers.

## Writing the two templates

Writing that body twice is asking for the two copies to drift apart. Put the
shared body in one file and have both templates include it:

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

The standalone template above opens a full document and includes the body; the
fragment includes the same body with no wrapper of its own. Change the body once
and both builds follow.

A template is {{latex}} with {{Jinja2}} interpolation, and the way it places
content is by reading `problem.blocks.<name>`. Everything else in scope, the
samples, the limits, the filters, is listed in
[Template context](context.md).

## The (language, variant) join

Inside the contest `file`, you walk the `problems` list and `\subimport` each
problem's rendered fragment:

```latex title="statements/contest-en.rbx.tex"
%- for problem in problems
\subimport{\VAR{problem.import_dir}}{\VAR{problem.import_file}}
%- endfor
```

The loop above is the whole join. `problem.import_dir` and
`problem.import_file` are the handles {{rbx}} gives you for the fragment it
built from each problem using your `contestProblemTemplate`. They exist only
here, in the join context.

But which statement does each problem contribute? The join is by `(language,
variant)`. A contest statement pulls, from every problem, the problem statement
whose `(language, variant)` **matches its own**, and the matched statement has to
share the contest statement's `rbx-*` type. So a contest statement declared as
`en`/`default` joins each problem's `en`/`default` statement, and that is the
whole rule.

The standalone build uses the same key. `rbx st b` looks for the contest
statements that declare a `standaloneProblemTemplate` for the problem's
`(language, variant)`:

- **Exactly one**: that template is used. This is the normal case.
- **More than one**: a hard error, because two contest statements both claim the
  same `(language, variant)`. Disambiguate by removing one of the templates.
- **Zero, or no contest at all**: not an error. {{rbx}} falls back to the bundled
  default template and **warns**.

!!! warning "Unselected dispatcher"
    The zero-match fallback has one exception. If the contest here is an
    unselected multi-contest dispatcher, `rbx st b` errors instead of falling
    back. Pass `-C <id>`, or set `RBX_CONTEST=<id>`, to pick a contest.

## Building the book

`rbx contest st b` renders each problem with the `contestProblemTemplate`, joins
them through the contest `file`, and writes
`build/<statement-name>[-<profile>].pdf`, keyed by the contest statement's
**`name`** rather than its language. It builds the contest
[`documents`](#cover-pages-and-infosheets) in the same run.

When you select a contest variant with `-C <id>`, the book nests under
`build/variants/<id>/` instead, so building one variant never overwrites
another's. The default contest keeps the bare `build/` path. The heading over
the build summary names the variant it built.

<!--termynal-->
```bash
# Build the contest book (joins problems) and its documents.
$ rbx contest statements build     # alias: rbx contest st b

# Build only some contest statements, by name.
$ rbx contest st b main-en main-pt

# Restrict to languages, or render against a timing profile.
$ rbx contest st b --languages en
$ rbx contest st b -p icpc
```

{{ asciinema("contest-statement-build") }}

To build one problem instead, run `rbx st b` from inside the problem
directory. It picks up the same contest's `standaloneProblemTemplate` and writes
`build/statement-<lang>[-<variant>][-<profile>].pdf`.

!!! warning "Problem artifacts are not variant-scoped yet"
    A problem's own `build/` directory is shared across every contest variant. A
    statement built there uses the selected contest's chrome and the problem's
    letter in that contest, but is always written to the same path, so
    switching variants overwrites it. Rebuild after switching. Tracked as
    [#753](https://github.com/rsalesc/rbx/issues/753).

## Declaring a contest statement

A contest statement is one entry under `statements:` in `contest.rbx.yml`. Below
is a fully wired one, field by field:

```yaml title="contest.rbx.yml"
statements:
  - name: main-en                                        # (1)!
    language: en                                         # (2)!
    variant: default                                     # (3)!
    file: statements/contest-en.rbx.tex                  # (4)!
    type: rbx-tex                                        # (5)!
    standaloneProblemTemplate: statements/problem-standalone.rbx.tex # (6)!
    contestProblemTemplate: statements/problem-in-contest.rbx.tex    # (7)!
    params:                                              # (8)!
      show_limits: true
```

1.  **`name`** is **required** and **unique within the contest**. It identifies
    the entry, since positional arguments to `rbx contest st b` are names, and
    it keys the output PDF. Problem statements have no `name`; contest ones must.
2.  **`language`** is an ISO 639-1 code, and half of the join key.
3.  **`variant`** is an optional discriminator that defaults to `default`. It is
    the other half of the join key.
4.  **`file`** is the joined document itself, the contest book that iterates over
    the problems.
5.  **`type`** defaults to `rbx-tex`. Only the `rbx-*` types can join problems,
    so a contest statement is almost always `rbx-tex` or `rbx-md`.
6.  **`standaloneProblemTemplate`** is the full-document template for `rbx st b`.
7.  **`contestProblemTemplate`** is the fragment template for the join.
8.  **`params`** are knobs exposed to the templates as `params.*`, kept separate
    from problem and contest `vars`. See [Template context](context.md).

`variant`, `params` and the two templates only mean something for the `rbx-*`
types. Set them on a non-`rbx` contest statement and {{rbx}} errors out. For the
exhaustive field list, see the [contest
schema](../reference/contest/schema.md).

## Custom blocks

Block names are free-form, so you can add a section the default chrome doesn't
have. Define the block in the problem, then render it in the
template. Guard it with `%- if ... is defined`, since not every problem defines
every block:

=== "statement.rbx.tex"

    ```latex
    %- block hint
    Think about a breadth-first search.
    %- endblock
    ```

=== "_problem-body.rbx.tex"

    ```latex
    %- if problem.blocks.hint is defined
    \section*{Hint}
    \VAR{problem.blocks.hint}
    %- endif
    ```

The block above shows up only for problems that wrote a `hint`, and everyone
else's document is untouched.

## Cover pages and infosheets

Sometimes a contest needs a page that is not a problem at all: an infosheet, a
cover page, an instruction sheet. Those are `documents`, contest-only standalone
pages that **never join problems**, and they live in their own list:

```yaml title="contest.rbx.yml"
documents:
  - name: infosheet-en
    language: en
    file: statements/infosheet-en.jinja.tex
    type: jinja-tex
```

Because a document never joins, its `type` has to be one without blocks:
`jinja-tex`, `jinja-md`, `tex`, `md` or `pdf`, and never the joining `rbx-*`
types.

It does still receive the `problems` list, but **metadata-only**. Each entry
exposes `title`, `short_name`, `limits`, `profiles` and `groups`, and no
`blocks`, `samples` or import handles. That is enough for a summary page, such
as a per-problem limits table:

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

The table above walks the same `problems` list the contest book does, and reads
only metadata off each one. Documents are built by `rbx contest st b`, alongside
the contest statements.

## Printing the date and location

A contest's date and venue are contest `vars`:

```yaml title="contest.rbx.yml"
vars:
  date: "2026-07-29"
  location: "Porto, Portugal"
```

The contest `file` reads them as `\VAR{vars.date}` and `\VAR{vars.location}`,
and a problem template as `\VAR{contest.date}` and `\VAR{contest.location}`.

Contest `vars` are the same for every language. To print the date differently
per language, put it in each contest statement's `params` and read
`\VAR{params.date}` in the contest `file`. Problem templates don't see a
contest statement's `params`:

```yaml title="contest.rbx.yml"
statements:
  - name: main-en
    language: en
    file: statements/contest-en.rbx.tex
    params:
      date: "July 29, 2026"
  - name: main-pt
    language: pt
    file: statements/contest-pt.rbx.tex
    params:
      date: "29 de julho de 2026"
```

## Reusing a recipe with extends

Across languages, two contest statements share almost everything except the
source file and, often, a few `params`. `extends` lets one entry inherit another's **build
recipe** and spell out only what differs.

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
    not inherit identity, so `main-pt` keeps its own `name`, `language` and
    `variant`.
2.  Overrides the joined document, and inherits everything else.

The merge is an **allowlist of the build recipe only**: `type`, `file`,
`params`, `assets`, and for contest statements the two templates. It never
copies identity, and `params` deep-merges key by key rather than replacing
wholesale. Cycles and dangling references are errors.

Problem statements extend by language instead. See [Reusing a recipe across
languages](writing.md#reusing-a-recipe-across-languages).

## When a problem cannot be rendered

Contest statements are built independently of each other, so a broken English
book never blocks the Portuguese one. Within one book the rule is the opposite,
and deliberately strict. If any problem can't be rendered (for example, it has
no statement in that language, its samples failed to build, or its template is
broken), then **that statement fails**. {{rbx}} won't quietly hand you a
problemset PDF with a problem missing from it.

The `-p` flag is the exception. With `-p`, {{rbx}} skips each problem that
doesn't define the profile and prints a warning. Check for that warning before
you ship.

When you *do* want the incomplete document, for example to proofread a book
while one problem is still being written, pass `--partial`:

```bash
# Build the contest book without the problems that fail, instead of failing.
rbx contest statements build --partial
```

`--partial` leaves out each failing problem and names it. If the only failures
were problems that wouldn't render, the command exits `0`. If a problem's
samples failed to build, it's left out too, but the command still exits
non-zero.

!!! warning
    A partial book leaves out the problems that failed, and the others keep their
    letters, so the sequence has gaps and isn't a preview of the final one. Don't
    ship it.

## Learning from the default preset

We recommend learning templates from a working one. The [default
preset](https://github.com/rsalesc/rbx/blob/main/rbx/resources/presets/default/contest/)
ships a complete contest: a joined task sheet, both problem templates sharing
one body file, an editorial and an infosheet document. Copy it and start
deleting the parts you don't need.

From here, [Tutorials](tutorials.md) does for editorials what this page did for
statements.
