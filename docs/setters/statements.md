# Statements

Problem statements are one of the core components of competitive programming problems. The rbx statement system provides a powerful and flexible way to write, manage, and build problem statements in multiple formats and languages.

## Overview

The statement system in rbx supports:

- **Multiple formats**: rbxTeX, rbxMarkdown, LaTeX with Jinja2, and pure LaTeX
- **Multi-language support**: Create statements in different languages using ISO 639-1 language codes
- **Asset management**: Include images, style files, and other resources in your statements
- **Template inheritance**: Extend base statements to avoid duplication
- **Variable substitution**: Use variables in statements for dynamic content
- **Automatic conversion**: Convert between formats with implicit conversion steps
- **Sample integration**: Automatically include test samples in statements

## Statement Configuration

Statements are configured in the `problem.rbx.yml` file under the `statements` section:

```yaml
statements:
  - name: "statement-en"
    title: "Example Problem"
    path: "statement/statement.rbx.tex"
    type: "rbxTeX"
    language: "en"
    assets:
      - "statement/icpc.sty"
      - "statement/*.png"
    vars:
      time_limit: 2
      memory_limit: 256
```

### Statement Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | required | Unique identifier for the statement |
| `extends` | string | null | Name of another statement to inherit from |
| `language` | string | "en" | ISO 639-1 language code (lowercase) |
| `title` | string | "" | Problem title as it appears in the statement |
| `path` | path | required | Path to the statement source file |
| `type` | StatementType | "rbxTeX" | Type of the statement file |
| `steps` | ConversionStep[] | [] | Explicit conversion steps to apply |
| `configure` | ConversionStep[] | [] | Configuration for conversion steps |
| `assets` | string[] | [] | Files to include when building the statement |
| `vars` | dict | {} | Variables available in the statement |

## Statement Types

### rbxTeX (`rbx-tex`)

The default and most powerful format for writing statements. It combines LaTeX with a block-based structure for easy organization.

```latex
%- block description
Alice and Bob are playing a game...
%- endblock

%- block input
The first line contains an integer $n$ ($1 \leq n \leq 10^5$).
%- endblock

%- block output
Output a single integer — the answer to the problem.
%- endblock

%- block samples
%- endblock

%- block explanation_0
In the first example...
%- endblock
```

**Features:**
- Block-based structure for organizing content
- Automatic sample inclusion
- Support for sample explanations
- Full LaTeX capabilities
- Requires a template file (default: `template.rbx.tex`)

### rbxMarkdown (`rbx-md`)

Write statements in Markdown with automatic conversion to LaTeX.

```markdown
%- block description
Alice and Bob are playing a game...
%- endblock

%- block input
The first line contains an integer $n$ ($1 \leq n \leq 10^5$).
%- endblock
```

**Features:**
- Easier to write for simple statements
- Automatic conversion to LaTeX via Pandoc
- Same block structure as rbxTeX
- Good for problems without complex mathematical notation

### JinjaTeX (`jinja-tex`)

Pure LaTeX with Jinja2 templating for dynamic content.

```latex
\section{{{ problem.title }}}

Time limit: {{ vars.time_limit }} seconds

{% for sample in problem.samples %}
\begin{example}
\exmp{
{{ sample.inputPath.read_text() }}
}{
{{ sample.outputPath.read_text() }}
}
\end{example}
{% endfor %}
```

**Features:**
- Full control over LaTeX output
- Direct access to problem data and variables
- No block structure requirements
- Best for custom statement layouts

### Pure LaTeX (`tex`)

Standard LaTeX files without any templating.

**Features:**
- Complete control over document structure
- No processing or templating
- Useful for pre-existing LaTeX statements

## Building Statements

Use the `rbx statements build` command to build statements:

```bash
# Build all statements to PDF
rbx statements build

# Build specific statements
rbx statements build statement-en statement-pt

# Build for specific languages
rbx statements build --languages en pt

# Build without samples (faster for testing)
rbx statements build --no-samples

# Build to a specific format
rbx statements build --output tex

# Pass custom variables
rbx statements build --vars time_limit=3 memory_limit=512
```

### Command Options

- `names`: Names of specific statements to build
- `--languages`: Filter by language codes
- `--output`: Target format (PDF, TeX, etc.)
- `--samples/--no-samples`: Include or exclude test samples
- `--vars`: Override or add variables for the build

## Conversion Pipeline

The statement system uses a pipeline of converters to transform between formats:

1. **rbxMarkdown → rbxTeX**: Converts Markdown blocks to LaTeX
2. **rbxTeX → TeX**: Applies template and renders blocks
3. **JinjaTeX → TeX**: Processes Jinja2 templates
4. **TeX → PDF**: Compiles LaTeX to PDF using pdfLaTeX

### Implicit Conversions

If you don't specify conversion steps, rbx will automatically determine the necessary conversions based on input and output types.

### Explicit Steps

You can force specific conversion steps:

```yaml
statements:
  - name: custom-statement
    path: statement.md
    type: rbxMarkdown
    steps:
      - type: rbx-md-tex  # Force Markdown to rbxTeX conversion
      - type: rbx-tex     # Then rbxTeX to TeX
        template: custom-template.tex
      - type: tex2pdf     # Finally TeX to PDF
```

### Configuring Conversions

Configure conversion behavior without forcing steps:

```yaml
statements:
  - name: statement-en
    path: statement.rbx.tex
    configure:
      - type: rbx-tex
        template: mytemplate.tex  # Use custom template if rbx-tex conversion happens
```

## Assets and Resources

Include additional files (images, style files, etc.) with your statements:

```yaml
assets:
  - "imgs/diagram.png"          # Single file
  - "styles/*.sty"              # Glob pattern
  - "resources/**/*.pdf"        # Recursive glob
```

Assets are:
- Copied to the build directory preserving relative paths
- Available during LaTeX compilation
- Must be relative to the package directory

## Variables

Variables can be used in statements for dynamic content:

```yaml
statements:
  - name: statement-en
    vars:
      time_limit: 2
      memory_limit: 256
      constraints:
        n_max: 100000
```

Access variables in statements:
- **rbxTeX/rbxMarkdown**: `{{ vars.time_limit }}`
- **JinjaTeX**: `{{ vars.time_limit }}` or `{{ vars.constraints.n_max }}`

Variables are expanded from:
1. Environment variables (using `$ENV_VAR` syntax)
2. Package-level vars
3. Statement-level vars
4. Command-line vars (highest priority)

## Template Inheritance

Avoid duplication by extending base statements:

```yaml
statements:
  - name: base-statement
    path: base.rbx.tex
    vars:
      time_limit: 2
      memory_limit: 256

  - name: statement-en
    extends: base-statement
    language: en
    title: "Example Problem"

  - name: statement-pt
    extends: base-statement
    language: pt
    title: "Problema Exemplo"
```

Child statements inherit all properties from the parent and can override specific fields.

## Working with Samples

Samples (test cases marked as samples in `problem.rbx.yml`) are automatically available in statements:

```yaml
testcases:
  - inputPath: tests/01.in
    outputPath: tests/01.out
    group: samples
```

Access in templates:
- `problem.samples`: List of sample objects
- Each sample has `inputPath`, `outputPath`, and optional `interaction`
- Use `explanation_N` blocks in rbxTeX for sample explanations

## Interactive Problems

For interactive problems, use `.pio` files to show interaction examples:

```
# tests/01.pio
> 3          # Judge sends n=3
< QUERY 1 2  # Solution queries
> YES        # Judge responds
< QUERY 2 3
> NO
< ANSWER 1   # Solution gives answer
```

The statement system automatically parses and includes these interactions.

## Best Practices

1. **Use rbxTeX for standard problems**: It provides the best balance of features and ease of use
2. **Organize assets**: Keep images and styles in subdirectories
3. **Use variables**: Define constants like limits in vars instead of hardcoding
4. **Multi-language support**: Use the same `name` with different `language` codes
5. **Test without samples**: Use `--no-samples` for faster iteration during writing
6. **Version control templates**: Keep your LaTeX templates in the repository

## Example: Complete Statement Setup

```yaml
# problem.rbx.yml
name: "sum-of-two"
author: "Contest Team"

vars:
  time_limit: 1
  memory_limit: 256
  n_max: 1000000

statements:
  - name: statement-base
    path: statement/base.rbx.tex
    type: rbxTeX
    assets:
      - statement/icpc.sty
    vars:
      time_limit: $time_limit
      memory_limit: $memory_limit

  - name: statement-en
    extends: statement-base
    language: en
    title: "Sum of Two Numbers"
    
  - name: statement-pt
    extends: statement-base
    language: pt
    title: "Soma de Dois Números"

testcases:
  - inputPath: tests/sample1.in
    outputPath: tests/sample1.out
    group: samples
```

```latex
% statement/base.rbx.tex
%- block description
Given two integers, calculate their sum.
%- endblock

%- block input
The only line contains two integers $a$ and $b$ ($-{{ vars.n_max }} \leq a, b \leq {{ vars.n_max }}$).
%- endblock

%- block output
Output a single integer — the sum $a + b$.
%- endblock

%- block samples
%- endblock

%- block notes
Time limit: {{ vars.time_limit }} seconds

Memory limit: {{ vars.memory_limit }} MB
%- endblock
```

Build with: `rbx statements build`