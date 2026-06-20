# rbxTeX statements

{{rbxtex}} (extension: `.rbx.tex`) is the recommended format for writing problem statements in {{rbx}}. It is a superset of LaTeX that adds a structured, block-based approach to writing statements, making them easier to organize and maintain.

## Why rbxTeX?

Standard LaTeX files can be cluttered with boilerplate code (document headers, packages, macros). {{rbxtex}} helps
separating the content of the problem (description, input, output) from the layout (the LaTeX template) with the
use of the templating engine {{Jinja2}}.

Key features:

- **Block-based**: Organize content into logical sections (`legend`, `input`, etc.).
- **Variable interpolation**: Use `\VAR{...}` to inject dynamic values like time limits and other user-defined variables.
- **Sample generation**: Samples are automatically fetched and made accessible as a {{Jinja2}} variable.
- **Leverage full LaTeX power**: You can still use any LaTeX capability, {{rbxtex}} is just a wrapper around LaTeX.

## Definition

{{rbxtex}} statements usually consist of two files: the main file (usually named `statement.rbx.tex`) and the template file (usually named `template.rbx.tex`).

The main file contains the blocks that define the content of the problem statement. Think of
it as usually containing a few sections, such as the `legend`, the `input`, the `output`, the
`notes`, etc.

The template file contains the layout of the problem statement, and through the use of {{Jinja2}}, it can access the content of the blocks defined in the main file and render
them in the appropriate place.

In a problem, a {{rbxtex}} statement can be defined as:

```yaml title="problem.rbx.yml"
statements:
  - name: statement
    path: statement/statement.rbx.tex # The main file
    configure:
      - type: rbx-tex
        template: "statement/template.rbx.tex" # The template file
```

For contest-level statements, please read the [Contest Statement](../contest.md) section.

## Syntax

{{rbxtex}} introduces a few special commands on top of LaTeX.

### Blocks

Blocks are the core of {{rbxtex}} statement organization that are usually placed in the
main file. In {{rbxtex}}, instead of mixing your content with layout commands (like `\section` or `\begin{itemize}`), you define **semantic blocks** of content. The template then decides *where* and *how* to render these blocks.

This separation of concerns allows you to:

-   **Change the look** of your statement just by swapping the template, without touching the content.
-   **Reuse content** easily (e.g., using the same block for both the full statement and a simplified statement).

```latex title="statement.rbx.tex"
%- block input
The input consists of a single integer $N$.
%- endblock

%- block output
The output consists of a single integer $N$.
%- endblock
```

You don't always need to define custom blocks, {{rbx}} works out-of-the-box with a few
pre-defined blocks that adhere to the nomenclature and sectioning used by {{polygon}}.
See the [default blocks](#default-blocks) section for more information.

### Variables

You can inject variables from `problem.rbx.yml` using the `\VAR{<variable-name>}` syntax, or
`\VAR{vars.<variable-name>}` syntax when there's a conflict between built-in variables and your custom
variables.

=== "statement.rbx.tex"

    ```latex title="statement.rbx.tex"
    %- block input
    The input consists of a single integer $N$
    ($\VAR{N.min} \le N \le \VAR{N.max}$).
    %- endblock
    ```

=== "problem.rbx.yml"

    ```yaml title="problem.rbx.yml"
    vars:
      N:
        min: 1
        max: 100
    ```

### Comments

You can use standard LaTeX comments `% ...`, but rbxTeX also supports block comments that are stripped before processing:

```latex
%# This is a comment that won't appear in the final LaTeX output
```

### Other Jinja2 features

Take a look at {{Jinja2}} website to see how other features work, such as conditionals, loops,
etc. These are very powerful for templating.

## Default blocks

The default template supports the following blocks:

| Block Name      | Description                                                          |
| :-------------- | :------------------------------------------------------------------- |
| `legend`        | The main problem description (the story and the task).               |
| `input`         | Description of the input format.                                     |
| `output`        | Description of the output format.                                    |
| `interaction`   | (Interactive problems only) Description of the interaction protocol. |
| `notes`         | Any additional notes, hints, or explanations.                        |
| `editorial`     | (Optional) Solution tutorial/editorial.                              |
| `explanation_N` | Explanation for the N-th sample (0-indexed).                         |

These can be specified in the main file, and will be rendered in the default templates supported by {{rbx}}.
It is a good practice to reuse these commonly defined blocks in your own templates as well, since they're
semantically meaningful, and have a special treatment for {{polygon}} packages.

## Sample explanations

There are three ways to attach an explanation to a sample, listed here in
descending priority (a higher-priority source overrides the ones below it for
the same sample):

1. **An `explanation_N` block in the statement file** — language-specific (the
   statement file is already built per language), as described in the table
   above.

2. **A `<sample>.rbx.tex` file next to the sample input** *(recommended)* — a
   per-sample file living alongside the `.in` file (e.g. `000.rbx.tex` next to
   `000.in`). It holds one block per language, keyed by the language code:

    ```latex
    %- block en
    In the first sample, the answer is $A + B = 10$.
    %- endblock

    %- block pt
    No primeiro exemplo, a resposta é $A + B = 10$.
    %- endblock
    ```

    Only the block matching the statement's language is rendered; any content
    outside a block is ignored. The file receives the same Jinja variables as
    the rest of the statement. For Markdown statements, use `<sample>.rbx.md`
    instead.

3. **A `<sample>.tex` file next to the sample input** — a per-sample file that
   is *language-agnostic*: the same text is used for every language. (For
   Markdown statements, `<sample>.md`.)

!!! warning
    A single sample may not have **both** a `<sample>.rbx.tex` and a
    `<sample>.tex` file — that is an error. Choose one. If a `<sample>.rbx.tex`
    file has no block for the statement's language, no explanation is shown for
    that sample in that language (and {{rbx}} warns you).

!!! note "Sample-explanation figures on {{polygon}}"
    If a sample explanation contains a figure (TikZ or an image) and you want it
    to show up when uploading to {{polygon}} (`rbx package polygon -u`), your
    statement template must `\subimport` that explanation — the figure is only
    uploaded when the template actually renders it. The bundled default (and
    fallback) preset already subimports every explanation, so it works out of the
    box. If you use a **custom** template that omits the explanation subimport,
    the figure won't be uploaded and the explanation will show a broken image on
    Polygon.

## Example

Here is a barebones example of a problem statement written in rbxTeX.

=== "Main (statement.rbx.tex)"

    ```latex
    %- block description
    Alice and Bob are playing a game with a sequence of integers.
    The game consists of $K$ turns. In each turn, a player can...
    
    Calculate the final score of the winner.
    %- endblock
    
    %- block input
    The first line contains two integers $N$ and $K$ ($\VAR{N.min} \le N, K \le \VAR{N.max}$) — the length of the sequence and the number of turns.
    
    The second line contains $N$ integers $A_1, A_2, \dots, A_N$ ($|A_i| \le \VAR{A.max}$).
    %- endblock
    
    %- block output
    Output a single integer — the final score of the winner.
    %- endblock
    
    %- block notes
    In the first sample, Alice chooses to...
    %- endblock
    
    %# We can explain specific samples using explanation blocks instead of notes if preferred.
    %- block explanation_0
    This explanation corresponds to the first sample case.
    %- endblock
    ```

=== "Template (template.rbx.tex)"

    ```latex
    \documentclass{article}
    \begin{document}

    \section*{\VAR{problem.short_name}. \VAR{problem.title}}
    
    \VAR{problem.blocks.description}
    
    \subsection*{Input}
    \VAR{problem.blocks.input}
    
    \subsection*{Output}
    \VAR{problem.blocks.output}
    
    \subsection*{Samples}
    %- for sample in problem.samples
    \subsection*{Sample \VAR{loop.index}}
    \begin{itemize}
        \item \textbf{Input:} \texttt{\VAR{sample.inputPath.read_text()}}
        \item \textbf{Output:} \texttt{\VAR{sample.outputPath.read_text()}}
    \end{itemize}
    %- endfor

    %- if problem.blocks.notes is defined
    \subsection*{Note}
    \VAR{problem.blocks.notes}
    %- endif
    
    \end{document}
    ```

## Learn more about templating

Learn more about creating your own template in our [templating guide](../templates.md).