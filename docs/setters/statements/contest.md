# Contest statements

In addition to problem-level statements, {{rbx}} supports creating **contest statements**. A contest statement is typically a single document (usually PDF) that aggregates all the problem statements in a contest, often with a cover page, customized header/footer, and problem numbering.

## Configuration

Contest statements are defined in the `contest.rbx.yml` file, and are usually JinjaTeX statements
since there's no need to define blocks (but can be {{rbxtex}} as well if you prefer).

```yaml title="contest.rbx.yml"
name: "my-contest"
problems:
  - short_name: A
    path: problems/A
  - short_name: B
    path: problems/B

statements:
  - name: contest-en
    title: "My Contest"
    language: en
    path: statement/contest.rbx.tex
    type: jinja-tex
    # Contest-statement specific knobs.
    match: statement-en # (1)!
    joiner: {type: "tex2pdf"} # (2)!
    override:
      configure: # (3)!
        - type: "rbx-tex" # Convert rbxTeX to TeX
          template: "statement/contest_template.rbx.tex"
      vars: # (4)!
        showLimits: true
    vars: # (5)!
      editorial: false
```

1.  **match**: Point to the `name` of the problem statements that should be built
    and joined into this contest statement.
2.  **joiner**: Usually `tex2pdf`, meaning each problem-level statement will be
    built into a TeX file (as opposed to the default PDF) and then, after that,
    joined into a single PDF file. This configuration is **crucial** for contest-level
    statements.
3.  **override.configure**: Overrides the `rbx-tex` template to use when building each
    problem statement. Useful because the problem template when building for contests
    has to be slightly different (no `\document` directive and such).
4.  **override.vars**: Variables to pass to the problem statement context.
5.  **vars**: Variables to pass to the contest statement context.

## Building contest statements

The build process for contest statements is slightly different. Instead of compiling each problem statement to PDF individually and merging them, {{rbx}} usually compiles the contest template which *includes* the content of each problem.

### The contest template

The contest template receives a few special variables.

The `contest` variable contains the following attributes:

- `contest.title`: The title of the contest.

The `lang` variable contains the language of the contest (ISO 639-1 code).

The `languages` and `keyed_languages` variables contains the programming languages available
for contestants, based on the languages configured in the preset. `languages` is a list, and
`keyed_languages` is a dictionary with the language ID as the key. These are really useful
when you want to render an info sheet.

The `vars` variable receive all variables defined in the contest statement configuration.

The `problems` variable is a list of problems in the contest. You can read more about
what is available in each problem [here](templates.md#rbx-provided-variables). Additionally,
it will have a `problem.path` field pointing to the built TeX file of the problem statement, which
you can use in your contest template to include it.

```latex title="contest.tex"
\documentclass{article}
\usepackage{icpcformat} % Your custom package

\title{\VAR{contest.title}}

\begin{document}
\maketitle

% Render contest header, front-page, etc.

% Iterate over problems
%- for problem in problems
    \clearpage
    \subimport{\VAR{problem.path | parent}/}{\VAR{problem.path | stem}}
%- endfor

\end{document}
```

## Variable overrides

You can override problem-level settings within the contest statement configuration. This is useful if you want to change the visual appearance of problems specifically for the contest book (e.g., adding the "Editorial" block or changing time limit rendering).

```yaml title="contest.rbx.yml"
statements:
  - name: contest-editorial
    # Other options...
    override:
      vars:
        # Sets a custom variable that identifies this as the
        # editorial. This can be used in the problem template to
        # render an additional "Editorial" block after the statements.
        editorial: true
```

## Matching

When building a contest statement, {{rbx}} tries to find the corresponding problem statement for each problem. By default, it matches based on **language**.

- If the contest statement is `en`, it looks for an `en` statement in each problem definition.
- You can customize this matching behavior if needed using the `match` field in `contest.rbx.yml`.

### Example: Matching by Name

If you have multiple statements per language (e.g., `statement-en` and `statement-en-simplified`) and want to pick a specific one for the contest:

=== "contest.rbx.yml"

    ```yaml
    statements:
      - name: contest-en
        language: en
        path: contest.rbx.tex
        match: statement-en-simplified # (1)!
    ```

    1.  This tells {{rbx}} to look for a statement named `statement-en-simplified` in each problem, instead of just picking the first English statement.

=== "problem.rbx.yml"

    ```yaml
    statements:
      - name: statement-en
        language: en
        path: statement-en.rbx.tex
        type: rbx-tex

      - name: statement-en-simplified
        language: en
        path: statement-en-simplified.rbx.tex
        type: rbx-tex
    ```

## Learn through examples

Look at our [default preset](https://github.com/rsalesc/rbx/blob/main/rbx/resources/presets/default/) to see how it works and modify it to your liking.