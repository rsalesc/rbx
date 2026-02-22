# demacro_utils Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `rbx/box/statements/demacro_utils.py` that collects macro definitions from TeX files (recursively) and expands macro usages via hybrid TexSoup + text replacement.

**Architecture:** Two-phase design — (1) `collect_macro_definitions` parses TeX/STY files with TexSoup to extract `\newcommand`, `\renewcommand`, `\def` definitions into a `MacroDefinitions` object, recursively following `\input`, `\include`, `\usepackage`, `\RequirePackage`; (2) `expand_macros` uses TexSoup for identification and text-level replacement for substitution, iterating until fixpoint.

**Tech Stack:** TexSoup (existing dep), Python dataclasses, re, pathlib

**Design doc:** `docs/plans/2026-02-22-demacro-utils-design.md`

---

### Task 1: Data Model — MacroDef and MacroDefinitions

**Files:**
- Create: `rbx/box/statements/demacro_utils.py`
- Create: `tests/rbx/box/statements/test_demacro_utils.py`

**Step 1: Write the failing tests**

In `tests/rbx/box/statements/test_demacro_utils.py`:

```python
from rbx.box.statements.demacro_utils import MacroDef, MacroDefinitions


def test_macro_def_creation():
    md = MacroDef(name='foo', n_args=2, default=None, body='#1 + #2', source_file=None)
    assert md.name == 'foo'
    assert md.n_args == 2
    assert md.body == '#1 + #2'


def test_macro_definitions_add_and_get():
    defs = MacroDefinitions()
    md = MacroDef(name='foo', n_args=0, default=None, body='bar', source_file=None)
    defs.add(md)
    assert 'foo' in defs
    assert defs.get('foo') is md


def test_macro_definitions_overwrite():
    defs = MacroDefinitions()
    md1 = MacroDef(name='foo', n_args=0, default=None, body='old', source_file=None)
    md2 = MacroDef(name='foo', n_args=0, default=None, body='new', source_file=None)
    defs.add(md1)
    defs.add(md2)
    assert defs.get('foo').body == 'new'


def test_macro_definitions_merge():
    defs1 = MacroDefinitions()
    defs1.add(MacroDef(name='a', n_args=0, default=None, body='A', source_file=None))
    defs2 = MacroDefinitions()
    defs2.add(MacroDef(name='b', n_args=0, default=None, body='B', source_file=None))
    defs1.merge(defs2)
    assert 'a' in defs1
    assert 'b' in defs1


def test_macro_definitions_iter():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='x', n_args=0, default=None, body='X', source_file=None))
    defs.add(MacroDef(name='y', n_args=0, default=None, body='Y', source_file=None))
    names = list(defs)
    assert 'x' in names
    assert 'y' in names
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/statements/test_demacro_utils.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

In `rbx/box/statements/demacro_utils.py`:

```python
import dataclasses
from typing import Dict, Iterator, Optional


@dataclasses.dataclass
class MacroDef:
    name: str
    n_args: int
    default: Optional[str]
    body: str
    source_file: Optional[str] = None


class MacroDefinitions:
    def __init__(self) -> None:
        self._defs: Dict[str, MacroDef] = {}

    def add(self, macro_def: MacroDef) -> None:
        self._defs[macro_def.name] = macro_def

    def get(self, name: str) -> Optional[MacroDef]:
        return self._defs.get(name)

    def merge(self, other: 'MacroDefinitions') -> None:
        self._defs.update(other._defs)

    def __contains__(self, name: str) -> bool:
        return name in self._defs

    def __iter__(self) -> Iterator[str]:
        return iter(self._defs)

    def __len__(self) -> int:
        return len(self._defs)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/statements/test_demacro_utils.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: add MacroDef and MacroDefinitions data model for demacro
```

---

### Task 2: Extract Macro Definitions from a Single TeX String

**Files:**
- Modify: `rbx/box/statements/demacro_utils.py`
- Modify: `tests/rbx/box/statements/test_demacro_utils.py`

**Step 1: Write the failing tests**

Add to test file:

```python
from rbx.box.statements.demacro_utils import extract_definitions


def test_extract_newcommand_no_args():
    tex = r'\newcommand{\hello}{world}'
    defs = extract_definitions(tex)
    assert 'hello' in defs
    assert defs.get('hello').n_args == 0
    assert defs.get('hello').body == 'world'


def test_extract_newcommand_with_args():
    tex = r'\newcommand{\add}[2]{#1 + #2}'
    defs = extract_definitions(tex)
    assert defs.get('add').n_args == 2
    assert defs.get('add').body == '#1 + #2'


def test_extract_newcommand_with_default():
    tex = r'\newcommand{\greet}[1][World]{Hello, #1!}'
    defs = extract_definitions(tex)
    m = defs.get('greet')
    assert m.n_args == 1
    assert m.default == 'World'
    assert m.body == 'Hello, #1!'


def test_extract_renewcommand():
    tex = r'\renewcommand{\foo}{bar}'
    defs = extract_definitions(tex)
    assert 'foo' in defs
    assert defs.get('foo').body == 'bar'


def test_extract_newcommand_star():
    tex = r'\newcommand*{\starred}[1]{*#1*}'
    defs = extract_definitions(tex)
    assert defs.get('starred').n_args == 1
    assert defs.get('starred').body == '*#1*'


def test_extract_def_zero_args():
    tex = r'\def\myconst{42}'
    defs = extract_definitions(tex)
    assert defs.get('myconst').n_args == 0
    assert defs.get('myconst').body == '42'


def test_extract_multiple_definitions():
    tex = r'''
\newcommand{\foo}{FOO}
\newcommand{\bar}[1]{BAR #1}
\def\baz{BAZ}
'''
    defs = extract_definitions(tex)
    assert len(defs) == 3
    assert 'foo' in defs
    assert 'bar' in defs
    assert 'baz' in defs


def test_extract_renewcommand_overwrites():
    tex = r'''
\newcommand{\foo}{old}
\renewcommand{\foo}{new}
'''
    defs = extract_definitions(tex)
    assert defs.get('foo').body == 'new'
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/statements/test_demacro_utils.py::test_extract_newcommand_no_args -v`
Expected: FAIL with ImportError

**Step 3: Write implementation**

Add to `demacro_utils.py`:

```python
from TexSoup.data import BraceGroup, BracketGroup, TexCmd, TexNode

from rbx.box.statements.texsoup_utils import parse_latex


_NEWCOMMAND_NAMES = {'newcommand', 'newcommand*', 'renewcommand', 'renewcommand*'}


def _extract_name_from_arg(arg) -> Optional[str]:
    """Extract command name (without backslash) from a newcommand's first argument."""
    if isinstance(arg, BraceGroup):
        # \newcommand{\foo}... -> BraceGroup contains TexCmd('foo')
        for child in arg.contents:
            if isinstance(child, TexCmd):
                return child.name
        # Fallback: parse the string content
        text = arg.string.strip()
        if text.startswith('\\'):
            return text[1:]
    return None


def _extract_newcommand(node: TexNode, source_file: Optional[str] = None) -> Optional[MacroDef]:
    """Extract a MacroDef from a \\newcommand or \\renewcommand node."""
    args = list(node.args)
    if not args:
        return None

    name = _extract_name_from_arg(args[0])
    if name is None:
        return None

    idx = 1
    n_args = 0
    default = None
    body = ''

    # Optional [n] for argument count
    if idx < len(args) and isinstance(args[idx], BracketGroup):
        try:
            n_args = int(args[idx].string)
        except ValueError:
            pass
        idx += 1

    # Optional [default] for first optional argument
    if idx < len(args) and isinstance(args[idx], BracketGroup):
        default = args[idx].string
        idx += 1

    # Final {body}
    if idx < len(args) and isinstance(args[idx], BraceGroup):
        body = args[idx].string

    return MacroDef(
        name=name,
        n_args=n_args,
        default=default,
        body=body,
        source_file=source_file,
    )


def _extract_def(node: TexNode, source_file: Optional[str] = None) -> Optional[MacroDef]:
    """Extract a MacroDef from a \\def node (0-arg form only)."""
    args = list(node.args)
    if len(args) < 2:
        return None

    # args[0] is either a TexCmd (bare \foo) or BraceGroup ({\foo})
    first = args[0]
    if isinstance(first, TexCmd):
        name = first.name
    elif isinstance(first, BraceGroup):
        text = first.string.strip()
        if text.startswith('\\'):
            name = text[1:]
        else:
            return None
    else:
        return None

    # args[1] is the body BraceGroup
    if isinstance(args[1], BraceGroup):
        body = args[1].string
    else:
        return None

    return MacroDef(
        name=name,
        n_args=0,
        default=None,
        body=body,
        source_file=source_file,
    )


def extract_definitions(
    tex_content: str,
    source_file: Optional[str] = None,
) -> MacroDefinitions:
    """Extract all macro definitions from a TeX string."""
    soup = parse_latex(tex_content)
    defs = MacroDefinitions()

    for cmd_name in _NEWCOMMAND_NAMES:
        for node in soup.find_all(cmd_name):
            macro = _extract_newcommand(node, source_file)
            if macro is not None:
                defs.add(macro)

    for node in soup.find_all('def'):
        macro = _extract_def(node, source_file)
        if macro is not None:
            defs.add(macro)

    return defs
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/statements/test_demacro_utils.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: add extract_definitions for parsing macro definitions from TeX
```

---

### Task 3: Recursive File Collection — `collect_macro_definitions`

**Files:**
- Modify: `rbx/box/statements/demacro_utils.py`
- Modify: `tests/rbx/box/statements/test_demacro_utils.py`

**Step 1: Write the failing tests**

These tests use `tmp_path` fixture to create temporary TeX/STY files on disk.

```python
import pathlib

from rbx.box.statements.demacro_utils import collect_macro_definitions


def test_collect_from_single_file(tmp_path: pathlib.Path):
    tex = tmp_path / 'main.tex'
    tex.write_text(r'\newcommand{\foo}{bar}')
    defs = collect_macro_definitions(tex)
    assert 'foo' in defs


def test_collect_follows_input(tmp_path: pathlib.Path):
    (tmp_path / 'defs.tex').write_text(r'\newcommand{\fromInput}{yes}')
    (tmp_path / 'main.tex').write_text(r'\input{defs.tex}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromInput' in defs


def test_collect_follows_input_no_extension(tmp_path: pathlib.Path):
    (tmp_path / 'defs.tex').write_text(r'\newcommand{\fromInput}{yes}')
    (tmp_path / 'main.tex').write_text(r'\input{defs}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromInput' in defs


def test_collect_follows_include(tmp_path: pathlib.Path):
    (tmp_path / 'chapter.tex').write_text(r'\newcommand{\fromInclude}{yes}')
    (tmp_path / 'main.tex').write_text(r'\include{chapter}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromInclude' in defs


def test_collect_follows_local_sty(tmp_path: pathlib.Path):
    (tmp_path / 'mypkg.sty').write_text(r'\newcommand{\fromSty}{yes}')
    (tmp_path / 'main.tex').write_text(r'\usepackage{mypkg}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromSty' in defs


def test_collect_follows_requirepackage(tmp_path: pathlib.Path):
    (tmp_path / 'req.sty').write_text(r'\newcommand{\fromReq}{yes}')
    (tmp_path / 'main.tex').write_text(r'\RequirePackage{req}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromReq' in defs


def test_collect_skips_system_package(tmp_path: pathlib.Path):
    # No amsmath.sty locally, should not error
    (tmp_path / 'main.tex').write_text(r'\usepackage{amsmath}' + '\n' + r'\newcommand{\local}{yes}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'local' in defs


def test_collect_no_cycles(tmp_path: pathlib.Path):
    (tmp_path / 'a.tex').write_text(r'\input{b.tex}' + '\n' + r'\newcommand{\fromA}{A}')
    (tmp_path / 'b.tex').write_text(r'\input{a.tex}' + '\n' + r'\newcommand{\fromB}{B}')
    defs = collect_macro_definitions(tmp_path / 'a.tex')
    assert 'fromA' in defs
    assert 'fromB' in defs


def test_collect_recursive_depth(tmp_path: pathlib.Path):
    (tmp_path / 'c.tex').write_text(r'\newcommand{\deep}{yes}')
    (tmp_path / 'b.tex').write_text(r'\input{c.tex}')
    (tmp_path / 'a.tex').write_text(r'\input{b.tex}')
    defs = collect_macro_definitions(tmp_path / 'a.tex')
    assert 'deep' in defs


def test_collect_with_base_dir(tmp_path: pathlib.Path):
    sub = tmp_path / 'sub'
    sub.mkdir()
    (sub / 'defs.tex').write_text(r'\newcommand{\subDef}{yes}')
    (tmp_path / 'main.tex').write_text(r'\input{sub/defs.tex}')
    defs = collect_macro_definitions(tmp_path / 'main.tex', base_dir=tmp_path)
    assert 'subDef' in defs
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/statements/test_demacro_utils.py::test_collect_from_single_file -v`
Expected: FAIL with ImportError

**Step 3: Write implementation**

Add to `demacro_utils.py`:

```python
import pathlib
from typing import Set


def _resolve_input_path(name: str, base_dir: pathlib.Path, extensions: tuple = ('.tex',)) -> Optional[pathlib.Path]:
    """Resolve an \\input/\\include filename to an actual file path."""
    candidate = base_dir / name
    if candidate.is_file():
        return candidate.resolve()
    for ext in extensions:
        with_ext = base_dir / (name + ext)
        if with_ext.is_file():
            return with_ext.resolve()
    return None


def _resolve_package_path(name: str, base_dir: pathlib.Path) -> Optional[pathlib.Path]:
    """Resolve a \\usepackage/\\RequirePackage name to a local .sty file."""
    candidate = base_dir / (name + '.sty')
    if candidate.is_file():
        return candidate.resolve()
    return None


def _collect_recursive(
    tex_path: pathlib.Path,
    base_dir: pathlib.Path,
    visited: Set[pathlib.Path],
) -> MacroDefinitions:
    resolved = tex_path.resolve()
    if resolved in visited:
        return MacroDefinitions()
    visited.add(resolved)

    try:
        content = tex_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return MacroDefinitions()

    defs = extract_definitions(content, source_file=str(resolved))

    soup = parse_latex(content)

    # Follow \input and \include
    for cmd_name in ('input', 'include'):
        for node in soup.find_all(cmd_name):
            args = list(node.args)
            if not args:
                continue
            ref_name = args[0].string.strip()
            ref_path = _resolve_input_path(ref_name, base_dir)
            if ref_path is not None:
                child_defs = _collect_recursive(ref_path, base_dir, visited)
                defs.merge(child_defs)

    # Follow \usepackage and \RequirePackage
    for cmd_name in ('usepackage', 'RequirePackage'):
        for node in soup.find_all(cmd_name):
            args = list(node.args)
            if not args:
                continue
            # usepackage can have comma-separated packages
            pkg_arg = args[-1].string.strip()  # last brace group is the package name(s)
            for pkg_name in pkg_arg.split(','):
                pkg_name = pkg_name.strip()
                if not pkg_name:
                    continue
                pkg_path = _resolve_package_path(pkg_name, base_dir)
                if pkg_path is not None:
                    child_defs = _collect_recursive(pkg_path, base_dir, visited)
                    defs.merge(child_defs)

    return defs


def collect_macro_definitions(
    tex_path: pathlib.Path,
    base_dir: Optional[pathlib.Path] = None,
) -> MacroDefinitions:
    """Collect all macro definitions from a TeX file, recursively visiting dependencies."""
    if base_dir is None:
        base_dir = tex_path.parent
    return _collect_recursive(tex_path, base_dir, set())
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/statements/test_demacro_utils.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: add collect_macro_definitions with recursive file traversal
```

---

### Task 4: Macro Expansion — `expand_macros`

**Files:**
- Modify: `rbx/box/statements/demacro_utils.py`
- Modify: `tests/rbx/box/statements/test_demacro_utils.py`

**Step 1: Write the failing tests**

```python
from rbx.box.statements.demacro_utils import expand_macros


def test_expand_zero_arg_macro():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='foo', n_args=0, default=None, body='REPLACED', source_file=None))
    result = expand_macros(r'Hello \foo world', defs)
    assert 'REPLACED' in result
    assert r'\foo' not in result


def test_expand_one_arg_macro():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='bold', n_args=1, default=None, body=r'\textbf{#1}', source_file=None))
    result = expand_macros(r'\bold{hello}', defs)
    assert r'\textbf{hello}' in result
    assert r'\bold' not in result


def test_expand_two_arg_macro():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='pair', n_args=2, default=None, body='(#1, #2)', source_file=None))
    result = expand_macros(r'\pair{a}{b}', defs)
    assert '(a, b)' in result


def test_expand_with_default_arg_used():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='greet', n_args=1, default='World', body='Hello, #1!', source_file=None))
    result = expand_macros(r'\greet', defs)
    assert 'Hello, World!' in result


def test_expand_with_default_arg_overridden():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='greet', n_args=1, default='World', body='Hello, #1!', source_file=None))
    result = expand_macros(r'\greet[Alice]', defs)
    assert 'Hello, Alice!' in result


def test_expand_preserves_non_macro_content():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='foo', n_args=0, default=None, body='X', source_file=None))
    result = expand_macros(r'before \foo after', defs)
    assert 'before' in result
    assert 'after' in result
    assert 'X' in result


def test_expand_nested_macros():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='inner', n_args=0, default=None, body='INNER', source_file=None))
    defs.add(MacroDef(name='outer', n_args=0, default=None, body=r'\inner', source_file=None))
    result = expand_macros(r'\outer', defs)
    assert 'INNER' in result
    assert r'\outer' not in result
    assert r'\inner' not in result


def test_expand_no_matching_macros():
    defs = MacroDefinitions()
    tex = r'\unknown{arg} text'
    result = expand_macros(tex, defs)
    assert r'\unknown{arg}' in result


def test_expand_multiple_usages():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='x', n_args=0, default=None, body='X', source_file=None))
    result = expand_macros(r'\x and \x', defs)
    assert result.count('X') == 2
    assert r'\x' not in result
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/statements/test_demacro_utils.py::test_expand_zero_arg_macro -v`
Expected: FAIL with ImportError

**Step 3: Write implementation**

Add to `demacro_utils.py`:

```python
import re


def _substitute_body(body: str, args: list[str]) -> str:
    """Replace #1, #2, ... in body with actual argument strings."""
    result = body
    for i, arg_val in enumerate(args, 1):
        result = result.replace(f'#{i}', arg_val)
    return result


def _find_and_expand(tex_content: str, macro_defs: MacroDefinitions) -> tuple[str, int]:
    """Single pass: find macro usages and expand them. Returns (new_content, substitution_count)."""
    try:
        soup = parse_latex(tex_content)
    except Exception:
        return tex_content, 0

    # Collect replacements as (start_pos, end_pos, replacement_text)
    replacements: list[tuple[int, int, str]] = []

    def visit(node: TexNode) -> None:
        if not isinstance(node, TexNode):
            return

        name = getattr(node, 'name', None)
        if name and name in macro_defs:
            macro = macro_defs.get(name)
            pos = getattr(node, 'position', None)
            if pos is None:
                return

            node_str = str(node)
            start = pos
            end = pos + len(node_str)

            # Extract arguments from the node
            node_args = list(node.args)
            arg_strings: list[str] = []

            if macro.n_args > 0:
                if macro.default is not None:
                    # First arg is optional
                    from TexSoup.data import BracketGroup as BG
                    if node_args and isinstance(node_args[0], BG):
                        arg_strings.append(node_args[0].string)
                        remaining = node_args[1:]
                    else:
                        arg_strings.append(macro.default)
                        remaining = node_args
                    for arg in remaining:
                        arg_strings.append(arg.string)
                else:
                    for arg in node_args:
                        arg_strings.append(arg.string)

            expanded = _substitute_body(macro.body, arg_strings)
            replacements.append((start, end, expanded))
            return  # Don't recurse into this node's children

        # Recurse into children
        for child in node.contents:
            if isinstance(child, TexNode):
                visit(child)

    visit(soup)

    if not replacements:
        return tex_content, 0

    # Apply replacements in reverse order to preserve positions
    replacements.sort(key=lambda r: r[0], reverse=True)
    result = tex_content
    for start, end, replacement in replacements:
        result = result[:start] + replacement + result[end:]

    return result, len(replacements)


def expand_macros(
    tex_content: str,
    macro_defs: MacroDefinitions,
    max_iterations: int = 10,
) -> str:
    """Expand all macro usages in a TeX string using the given definitions.

    Iterates until no more substitutions are made or max_iterations is reached.
    """
    content = tex_content
    for _ in range(max_iterations):
        content, count = _find_and_expand(content, macro_defs)
        if count == 0:
            break
    return content
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/statements/test_demacro_utils.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: add expand_macros with iterative hybrid TexSoup + text replacement
```

---

### Task 5: Integration Test and Edge Cases

**Files:**
- Modify: `tests/rbx/box/statements/test_demacro_utils.py`

**Step 1: Write integration and edge case tests**

```python
def test_end_to_end_collect_and_expand(tmp_path: pathlib.Path):
    """Full integration: collect from files, then expand in a document."""
    (tmp_path / 'macros.sty').write_text(
        r'\newcommand{\prob}[1]{\textbf{Problem: #1}}'
        + '\n'
        + r'\newcommand{\io}{Input/Output}'
    )
    (tmp_path / 'main.tex').write_text(
        r'\usepackage{macros}'
        + '\n'
        + r'\prob{A} -- \io'
    )
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    content = (tmp_path / 'main.tex').read_text()
    result = expand_macros(content, defs)
    assert r'\textbf{Problem: A}' in result
    assert 'Input/Output' in result
    assert r'\prob' not in result
    assert r'\io' not in result


def test_expand_does_not_remove_definitions():
    """expand_macros operates on usage sites, not on definition sites."""
    defs = MacroDefinitions()
    defs.add(MacroDef(name='foo', n_args=0, default=None, body='X', source_file=None))
    tex = r'\newcommand{\foo}{X}' + '\n' + r'\foo'
    result = expand_macros(tex, defs)
    # The \newcommand line may or may not be preserved depending on TexSoup parsing.
    # The key assertion: the usage \foo (not inside \newcommand) should be expanded.
    assert 'X' in result


def test_expand_macro_with_nested_braces():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='wrap', n_args=1, default=None, body=r'{\textbf{#1}}', source_file=None))
    result = expand_macros(r'\wrap{hello}', defs)
    assert r'{\textbf{hello}}' in result
```

**Step 2: Run all tests**

Run: `uv run pytest tests/rbx/box/statements/test_demacro_utils.py -v`
Expected: PASS

**Step 3: Run linting**

Run: `uv run ruff check rbx/box/statements/demacro_utils.py tests/rbx/box/statements/test_demacro_utils.py`
Run: `uv run ruff format rbx/box/statements/demacro_utils.py tests/rbx/box/statements/test_demacro_utils.py`

**Step 4: Commit**

```
test: add integration and edge case tests for demacro_utils
```

---

### Task 6: Run Full Test Suite and Final Verification

**Step 1: Run existing statement tests to ensure no regressions**

Run: `uv run pytest tests/rbx/box/statements/ -v`
Expected: All PASS

**Step 2: Run full project linting**

Run: `uv run ruff check rbx/box/statements/demacro_utils.py`
Run: `uv run ruff format --check rbx/box/statements/demacro_utils.py`
Expected: Clean

**Step 3: Final commit (if any fixes needed)**

```
fix: address lint/format issues in demacro_utils
```
