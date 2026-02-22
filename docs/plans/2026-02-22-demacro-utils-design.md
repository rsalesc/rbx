# Design: demacro_utils.py - TeX Macro Expansion via TexSoup

## Overview

A new module `rbx/box/statements/demacro_utils.py` that provides two main capabilities:

1. **Collect macro definitions** from a TeX file (recursively visiting local `.sty` and `\input`/`\include` files)
2. **Expand macro usages** in a TeX file, replacing references with their fully substituted bodies

## Data Model

```python
@dataclasses.dataclass
class MacroDef:
    name: str               # command name without backslash, e.g. 'foo'
    n_args: int             # number of arguments (0 for \def)
    default: Optional[str]  # default value for optional first arg (from \newcommand{\foo}[1][default]{...})
    body: str               # replacement body with #1, #2, ... placeholders
    source_file: Optional[str]  # path where it was defined
```

`MacroDefinitions` is a wrapper around `dict[str, MacroDef]` providing:
- `add(macro_def)` -- adds/overwrites a definition (supports `\renewcommand` semantics)
- `get(name)` -- looks up by command name
- `merge(other)` -- merges another `MacroDefinitions` into this one
- `__contains__`, `__iter__` -- standard dict-like protocol

## Function 1: `collect_macro_definitions`

```python
def collect_macro_definitions(
    tex_path: pathlib.Path,
    base_dir: Optional[pathlib.Path] = None,
) -> MacroDefinitions:
```

### Behavior

- Parses the file at `tex_path` with TexSoup
- Extracts definitions from: `\newcommand`, `\newcommand*`, `\renewcommand`, `\renewcommand*`, `\def` (0-arg only)
- Recursively follows:
  - `\input{file}` -- resolves relative to `base_dir`, appends `.tex` if no extension
  - `\include{file}` -- same resolution as `\input`
  - `\usepackage{pkg}` / `\RequirePackage{pkg}` -- resolves to `pkg.sty` in `base_dir`; silently skips if file doesn't exist (system package)
- Tracks visited files (by resolved absolute path) to avoid cycles
- `base_dir` defaults to `tex_path.parent` if not provided

### Extraction Logic

For `\newcommand{\foo}[2]{#1 and #2}`:
- `args[0]`: BraceGroup containing command name -> extract name
- Next BracketGroup (if present): argument count
- Next BracketGroup (if present): optional arg default
- Final BraceGroup: replacement body

For `\def\foo{body}`:
- `args[0]`: TexCmd -> extract name
- `args[1]`: BraceGroup -> body
- Always 0 arguments (parameterized `\def` not supported due to TexSoup limitation)

## Function 2: `expand_macros`

```python
def expand_macros(
    tex_content: str,
    macro_defs: MacroDefinitions,
    max_iterations: int = 10,
) -> str:
```

### Approach: Hybrid TexSoup + Text Replacement

1. Parse `tex_content` with TexSoup
2. Walk the AST to find nodes whose names match a defined macro
3. For each match, extract arguments from the node's `args` list
4. Build expanded text: substitute `#1`, `#2`, ... in the body with actual argument strings
5. Handle optional first argument: if macro has a default and usage doesn't provide optional arg, use default
6. Collect all (position, length, replacement) tuples
7. Apply replacements in reverse order (right-to-left) to preserve positions
8. Re-parse and repeat until no substitutions made or `max_iterations` reached

### Why Hybrid (Not Pure AST)

TexSoup's tree manipulation (`replace_with`, `insert`) is fragile and produces incorrect output for complex replacements. The existing `texsoup_utils.py` already has workarounds for this. By using TexSoup only for parsing/identification and doing replacement at the text level, we get reliability without sacrificing structural understanding.

## Scope Limitations

- **`\def` limited to 0-argument form**: TexSoup misparsed `\def\foo#1{body}` (parameter tokens between name and body). Only `\def\foo{body}` is supported.
- **No `\newenvironment` / `\renewenvironment`**: Commands only. Environments can be added later.
- **No `\let`, `\gdef`, `\edef`, `\xdef`**: These TeX primitives are not reliably parsed by TexSoup.
- **Expansion order**: Not guaranteed to match TeX's exact expansion order for deeply nested macros, but iterative fixpoint handles common cases.

## File Location

`rbx/box/statements/demacro_utils.py` -- alongside `texsoup_utils.py` in the statements module.

## Dependencies

- `TexSoup` (already a project dependency)
- `pathlib`, `dataclasses`, `re` (stdlib)
- `texsoup_utils.parse_latex` (internal)
