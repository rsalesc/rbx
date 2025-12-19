# Templates

The power of **rbxTeX** comes from its template system. The content you write in blocks (description, input, output) is injected into a base LaTeX template to produce the final document.

## Default template

By default, {{rbx}} uses a built-in template that provides a standard competitive programming layout. However, you can (and often should) provide your own `template.rbx.tex` or modify the existing template to match your contest's branding or specific requirements.

To use the default template as is, you can simply create a problem from the default preset, and fill in the blocks
in your main statement file.

You can find the default template [here](https://github.com/rsalesc/rbx/blob/main/rbx/resources/presets/default/shared/problem_template.rbx.tex) to use as inspiration to create your own.

## Customizing templates

To use a custom template, simply create a file named `template.rbx.tex` in the same directory as your statement file, and refer to it in your statement configuration.

```yaml title="problem.rbx.yml"
statements:
  - name: statement
    path: statement/statement.rbx.tex
    configure:
      - type: rbx-tex
        template: "statement/template.rbx.tex"
```

### Template structure

A template is a LaTeX file that defines the document structure and placeholders for content blocks. It uses [Jinja2](https://jinja.palletsprojects.com/) syntax for logic and variables.

#### {{rbx}}-provided variables

The following variables are available in the template context:

- `problem`: An object containing problem metadata.
    - `problem.title`: The problem title.
    - `problem.short_name`: The problem short name (e.g., `A`, `B`, etc.).
    - `problem.blocks`: A dictionary of content blocks (e.g., `problem.blocks.legend`, `problem.blocks.input`, etc.).
    - `problem.samples`: A list of sample objects.
    - `problem.vars`: Variables defined in `problem.rbx.yml`.
    - `problem.limits`: Time and memory limits.

The `sample` object contains the following attributes:

- `sample.inputPath`: The input path, relative to the statement build directory (a `pathlib.Path` object, so `read_text()` can be called)
- `sample.outputPath`: The output path, relative to the statement build directory, similar to the input path

The `limits` object contains the following attributes/methods:

- `limits.timeLimit`: The time limit in milliseconds
- `limits.memoryLimit`: The memory limit in megabytes
- `limits.outputLimit`: The output limit in megabytes
- `limits.timelimit_for_language(lang)`: The time limit in milliseconds for a specific language.
- `limits.memorylimit_for_language(lang)`: The memory limit in megabytes for a specific language.

### Creating custom blocks

While the default template uses standard blocks (`description`, `input`, etc.), you can define **custom blocks** in your {{rbxtex}} files and render them in your template.

For example, if you want a "Hint" section:

1.  **In your statement**:
    ```latex title="statement.rbx.tex"
    %- block hint
    Try to use dynamic programming.
    %- endblock
    ```

2.  **In your template**:
    ```latex title="template.rbx.tex"
    % ...
    %- if problem.blocks.hint
    \section*{Hint}
    \VAR{problem.blocks.hint}
    %- endif
    % ...
    ```

This gives you unlimited flexibility to structure your problem statements.

### Example Template

Here is a simplified example of a custom template:

```latex title="template.rbx.tex"
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


## Learn more through examples

Look at our [default preset](https://github.com/rsalesc/rbx/blob/main/rbx/resources/presets/default/) to see how it works and modify it to your liking.