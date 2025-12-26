# LaTeX statements

For advanced use cases, you can write statements directly in {{latex}}. {{rbx}} supports two flavors of {{latex}} statements: **JinjaTeX** and **Pure LaTeX**.

!!! tip "Recommendation"
    For most use cases, we recommend using {{rbxtex}} instead of raw {{latex}}. It provides a higher-level abstraction and handles document structure automatically, and the difference between them is minimal.


## JinjaTeX

**JinjaTeX** (extension: `.jinja.tex` or `.tex` with valid configuration) is a format that combines standard {{latex}} with the {{Jinja2}} templating engine.

Unlike {{rbxtex}}, which abstracts away the document structure using blocks, JinjaTeX gives you full control over the entire {{latex}} document. You are responsible for writing the `\documentclass`, `\begin{document}`, etc, plus any other {{latex}} and {{Jinja2}} code you need.

### When to use

Using JinjaLaTeX, you can inject variables and logic into your {{latex}} documents, making it easier to generate dynamic content, but if starting your statement from
scratch, we recommend using {{rbxtex}} instead.

### Syntax

You can use `\VAR{...}` to inject variables if using JinjaLaTeX. You can read
other supported syntax in {{Jinja2}} documentation.

You can also read the set of automatically available variables in the {{rbxtex}}
documentation.

```latex
\documentclass{article}

\begin{document}
\title{\VAR{problem.title}}
\maketitle

\section{Input}
...

\section{Samples}
% Iterate over samples manually
%- for sample in problem.samples
  \subsection*{Sample \VAR{loop.index}}
  \begin{verbatim}
  \VAR{sample.inputPath.read_text()}
  \end{verbatim}
%- endfor
\end{document}
```

## Pure {{latex}}

**Pure {{latex}}** (extension: `.tex`) treats the file as a static {{latex}} document. No templating or variable substitution is performed.

### When to use

- You have an existing {{latex}} statement and just want {{rbx}} to compile it to PDF.
- You don't need any dynamic features or variable injection.
- You want to ensure the file is valid standard {{latex}} that can be compiled by any TeX distribution without preprocessing.

In all other cases, we recommend using {{rbxtex}}.

