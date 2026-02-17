# Statements Module (`rbx/box/statements/`)

Builds problem statements from LaTeX/Jinja templates into PDF, HTML, or Markdown.

## Pipeline Overview

```
problem.rbx.yml (statements config)
  |
  v
schema.py: Statement models define source path, type, conversion steps, vars
  |
  v
expander.py: expand_statements() resolves wildcards and preset inheritance
  |
  v
build_statements.py: execute_build_on_statements() orchestrates the build
  |
  +-- For each statement × language × output type:
  |     1. Copy statement source to build directory
  |     2. Apply conversion steps in sequence
  |     3. Produce final output (PDF, HTML, Markdown)
  |
  v
Output files in build directory
```

## Schema (`schema.py`)

### Core Types

- **`StatementType`** -- Enum: `PDF`, `HTML`, `MARKDOWN`
- **`StatementLanguage`** -- ISO 639-1 language code + display name
- **`Statement`** -- Pydantic model: `name`, `path` (source file), `type` (PDF/HTML/MD), `language`, `title`, `vars`, `steps`, `configure`
- **`ConversionStep`** -- Discriminated union (via `type` field):
  - `rbxToTeX` -- Convert rbxTeX format to standard LaTeX (the main custom format)
  - `TexToPDF` -- Compile LaTeX to PDF via `pdflatex`
  - `TexToHTML` -- Convert LaTeX to HTML via `pandoc`
  - `TexToMarkdown` -- Convert LaTeX to Markdown via `pandoc`
  - `HtmlToPDF` -- Convert HTML to PDF (via browser/wkhtmltopdf)
  - `MarkdownToHTML` -- Convert Markdown to HTML via `pandoc`
  - `MarkdownToPDF` -- Convert Markdown to PDF via `pandoc`
- **`Joiner`** -- Joins multiple problem statements for contest output

### rbxTeX Format

The main custom format. An rbxTeX file is a LaTeX file with Jinja2 template syntax:
- `\VAR{variable}` -- Variable substitution (from `vars` in problem.rbx.yml)
- `%- for`, `%- if`, `%- block` -- Jinja control flow using `%` line prefix
- Sample I/O auto-insertion from built test cases
- `\subimport` for composing multi-file statements

### Conversion Steps

Steps are applied in sequence. Default flow for rbxTeX:
1. `rbxToTeX` -- Jinja rendering with variable substitution, sample I/O injection
2. `TexToPDF` -- pdflatex compilation (with optional TikZ externalization)

Each step has a `configure` list for step-specific parameters (e.g., `externalize: true` for TikZ extraction in Polygon upload).

## Build Pipeline (`build_statements.py`)

**`execute_build_on_statements()`** -- Main entry point, called from `packager.py` and `cli.py`.

For each statement:
1. Resolves the statement source path
2. Creates a build directory
3. Applies conversion steps sequentially via `builders.py`
4. Returns `BuiltStatement` objects with paths to output files

## Builders (`builders.py`)

Each conversion step has a corresponding builder function:

- **`_build_rbx_to_tex()`** -- The most complex builder:
  1. Copies source and included files to build dir
  2. Sets up Jinja environment via `latex_jinja.py` (`jinja2.Environment` with `\VAR{}` syntax, `%-` blocks, `\BLOCK{}`)
  3. Injects variables: problem vars, samples, language strings
  4. Renders the template
  5. Processes `\subimport` directives for multi-file statements

- **`_build_tex_to_pdf()`** -- Calls `latex.py` to run `pdflatex` (with retry for cross-references)
- **`_build_tex_to_html()`** / **`_build_tex_to_md()`** -- Uses `pypandoc` for conversion
- **`_build_html_to_pdf()`** -- HTML to PDF conversion
- **`_build_md_to_html()`** / **`_build_md_to_pdf()`** -- Markdown conversions via `pypandoc`

## LaTeX Integration

### `latex.py`
- `compile_latex()` -- Runs `pdflatex` with configurable options
- Handles build retries for cross-references
- Error extraction from LaTeX log files

### `latex_jinja.py`
- Custom Jinja2 environment configured for LaTeX:
  - Variable syntax: `\VAR{...}` instead of `{{ ... }}`
  - Block syntax: `\BLOCK{...}` instead of `{% ... %}`
  - Comment syntax: `\#{...}`
  - Line statement prefix: `%-`
  - Line comment prefix: `%#`
- `get_latex_jinja_env()` factory function

## Expander (`expander.py`)

`expand_statements()` processes the raw statement list from `problem.rbx.yml`:
- Resolves wildcard paths to actual files
- Applies preset-defined default statements
- Handles statement overrides from contest config

## Joiners (`joiners.py`)

Joins multiple problem statements into a single contest document:
- Produces combined PDFs for contest printing
- Handles table of contents, page numbering

## Statement Templates (`rbx/resources/templates/`)

Bundled LaTeX templates:
- `statements/` -- Default problem statement templates (ICPC style with `icpc.sty`)
- `contest/` -- Contest-level templates (cover pages, info sheets with limits tables)
- Templates use Jinja syntax: `\VAR{problem.title}`, `\VAR{problem.limits.timelimit_for_language('cpp')}`

## Polygon Integration (`polygon_utils.py`)

Helpers for extracting statement sections (legend, input, output, notes) for Polygon API upload. Parses LaTeX to extract named blocks.

## Context Variables Available in Templates

- `vars` -- User-defined variables from `problem.rbx.yml`
- `lang` -- Current language code
- `problem` -- Problem metadata (title, limits, etc.)
- `problems` -- (Contest only) List of all problems
- `contest` -- (Contest only) Contest metadata
- `samples` -- Auto-generated sample I/O from built test cases
