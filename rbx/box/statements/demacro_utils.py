r"""Static macro collection and expansion, for the statement export path.

Two halves. **Collection** reads the ``\newcommand``/``\renewcommand``/``\def``
definitions out of a TeX file and everything it ``\input``s or loads as a local
package, without running TeX. **Expansion** replaces a macro's uses in a block
by its body, with its arguments substituted.

Collection is a static read, so it cannot know which of several definitions TeX
actually ran: a ``\def`` nested inside another macro's body only happens if that
macro is called, and a package can pick a table by option (#1007). The compile
that writes ``macros.json`` therefore asks TeX for the definitions in effect
(:mod:`rbx.box.statements.macro_meaning`), and uses this module to know which
names to ask about. To tell those cases apart, :class:`MacroDefinitions` keeps,
beside the definition it settled on, whether that one was nested in another
macro's body and which *other* definitions of the name it saw.
"""

import dataclasses
import json
import pathlib
import re
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from TexSoup.data import TexNode

from rbx.box.statements import tex_scan
from rbx.box.statements.texsoup_utils import (
    escape_for_texsoup,
    parse_latex,
)


@dataclasses.dataclass
class MacroDef:
    name: str
    n_args: int
    default: Optional[str]
    body: str
    source_file: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MacroDef':
        return cls(**data)

    def same_definition(self, other: 'MacroDef') -> bool:
        """Whether both say the same thing, wherever they were written."""
        return (self.n_args, self.default, self.body) == (
            other.n_args,
            other.default,
            other.body,
        )


@dataclasses.dataclass(frozen=True)
class _Scope:
    """Where a definition was written: its file, and the macro whose body it
    sits in (``None`` at top level)."""

    source_file: Optional[str]
    nested_in: Optional[str]


class MacroDefinitions:
    def __init__(self) -> None:
        self._defs: Dict[str, MacroDef] = {}
        self._scopes: Dict[str, _Scope] = {}
        # Every distinct definition of a name seen in a scope other than the
        # winner's, in the order seen. See `conflicts`.
        self._conflicts: Dict[str, List[MacroDef]] = {}

    def add(self, macro_def: MacroDef, *, nested_in: Optional[str] = None) -> None:
        """Record ``macro_def``, replacing any earlier definition of its name.

        A later definition in the same scope is a plain redefinition and leaves
        no trace. One from another scope -- nested in another macro's body, or in
        another file -- may never have run, so the one it replaces is kept as a
        conflict (see :meth:`conflicts`)."""
        name = macro_def.name
        scope = _Scope(macro_def.source_file, nested_in)
        previous = self._defs.get(name)
        if previous is not None and not previous.same_definition(macro_def):
            if self._scopes.get(name) != scope:
                self._record_conflict(name, previous)
        self._defs[name] = macro_def
        self._scopes[name] = scope

    def _record_conflict(self, name: str, macro_def: MacroDef) -> None:
        seen = self._conflicts.setdefault(name, [])
        if not any(macro_def.same_definition(other) for other in seen):
            seen.append(macro_def)

    def get(self, name: str) -> Optional[MacroDef]:
        return self._defs.get(name)

    def nested_in(self, name: str) -> Optional[str]:
        """The macro whose body the winning definition of ``name`` sits in, or
        ``None`` when it is at the top level of its file."""
        scope = self._scopes.get(name)
        return scope.nested_in if scope is not None else None

    def conflicts(self, name: str) -> List[MacroDef]:
        """The other definitions of ``name`` seen in other scopes, each saying
        something different from the winner. Empty when the static answer is
        unambiguous."""
        winner = self._defs.get(name)
        return [
            other
            for other in self._conflicts.get(name, [])
            if winner is None or not other.same_definition(winner)
        ]

    def merge(self, other: 'MacroDefinitions') -> None:
        for name in other:
            macro = other.get(name)
            if macro is None:
                continue
            for conflict in other.conflicts(name):
                self._record_conflict(name, conflict)
            self.add(macro, nested_in=other.nested_in(name))

    def __contains__(self, name: str) -> bool:
        return name in self._defs

    def __iter__(self) -> Iterator[str]:
        return iter(self._defs)

    def __len__(self) -> int:
        return len(self._defs)

    def filter(self, to_filter_out: Iterable[str]) -> 'MacroDefinitions':
        to_filter_out = set(to_filter_out)
        return self.select(lambda name: name not in to_filter_out)

    def select(self, keep: Callable[[str], bool]) -> 'MacroDefinitions':
        """The definitions whose name ``keep`` accepts, with their scope and
        conflicts."""
        new_defs = MacroDefinitions()
        for name, macro in self._defs.items():
            if keep(name):
                for conflict in self.conflicts(name):
                    new_defs._record_conflict(name, conflict)
                new_defs.add(macro, nested_in=self.nested_in(name))
        return new_defs

    def to_json_file(self, path: pathlib.Path) -> None:
        data = [macro.to_dict() for macro in self._defs.values()]
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
        )

    @classmethod
    def from_json_file(cls, path: pathlib.Path) -> 'MacroDefinitions':
        data = json.loads(path.read_text(encoding='utf-8'))
        defs = cls()
        for entry in data:
            defs.add(MacroDef.from_dict(entry))
        return defs


# --- Collection --------------------------------------------------------------

# The definitions collected. `\edef`/`\xdef` are not: their body is expanded
# when they run, so the text written is not what they define.
_COLLECTED = frozenset(
    {'newcommand', 'renewcommand', 'providecommand', 'DeclareRobustCommand'}
    | {'def', 'gdef'}
)
_INCLUDES = frozenset({'input', 'include'})
_PACKAGES = frozenset({'usepackage', 'RequirePackage'})


def _parse(
    text: str, command: str, i: int, source_file: Optional[str]
) -> Optional[Tuple[MacroDef, tex_scan.Definition]]:
    definition = tex_scan.parse_definition(text, command, i)
    if definition is None:
        return None
    macro = MacroDef(
        name=definition.name,
        n_args=definition.n_args,
        default=definition.default,
        body=definition.body(text),
        source_file=source_file,
    )
    return macro, definition


def _undouble(macro: MacroDef, depth: int) -> MacroDef:
    """A definition nested ``depth`` macro bodies deep is written with its
    parameter characters doubled once per level (``\\def\\inner##1{##1}``);
    what it defines when it runs has them single."""
    if depth == 0:
        return macro
    body, default = macro.body, macro.default
    for _ in range(depth):
        body = body.replace('##', '#')
        default = default.replace('##', '#') if default is not None else None
    return dataclasses.replace(macro, body=body, default=default)


IncludeHandler = Callable[[str, str], Optional[MacroDefinitions]]


def _read_include(
    text: str, name: str, i: int, on_include: IncludeHandler
) -> Tuple[Optional[MacroDefinitions], int]:
    """``\\input{f}``/``\\include{f}``/``\\usepackage[o]{a,b}``: the definitions
    ``on_include`` reads for each file, merged, and the index past the command."""
    j = tex_scan.skip_blanks(text, i)
    if name in _PACKAGES:
        while j < len(text) and text[j] == '[':
            end = tex_scan.read_group(text, j, '[')
            if end is None:
                return None, i
            j = tex_scan.skip_blanks(text, end)
    if j >= len(text) or text[j] != '{':
        return None, i
    end = tex_scan.read_group(text, j)
    if end is None:
        return None, i
    arg = tex_scan.strip_tags(text[j + 1 : end - 1]).strip()
    targets = arg.split(',') if name in _PACKAGES else [arg]
    found: Optional[MacroDefinitions] = None
    for target in targets:
        target = target.strip()
        if not target:
            continue
        child = on_include('package' if name in _PACKAGES else 'input', target)
        if child is not None:
            found = found or MacroDefinitions()
            found.merge(child)
    return found, end


def _option_code(text: str, i: int) -> Optional[Tuple[int, int, str]]:
    """``i`` is just past ``\\DeclareOption``: the span of the option's code
    (start, end) and how to name it (``{pt}``, or ``*``)."""
    label = '*'
    j = i
    if j < len(text) and text[j] == '*':
        j += 1
    else:
        j = tex_scan.skip_blanks(text, j)
        if j >= len(text) or text[j] != '{':
            return None
        end = tex_scan.read_group(text, j)
        if end is None:
            return None
        label = '{' + tex_scan.strip_tags(text[j + 1 : end - 1]).strip() + '}'
        j = end
    j = tex_scan.skip_blanks(text, j)
    if j >= len(text) or text[j] != '{':
        return None
    end = tex_scan.read_group(text, j)
    if end is None:
        return None
    return j + 1, end - 1, label


def _scan_definitions(
    text: str,
    source_file: Optional[str],
    defs: MacroDefinitions,
    on_include: Optional[IncludeHandler] = None,
) -> None:
    """One pass over ``text`` in document order, recording every definition
    (descending into bodies, so nested ones are seen with the macro they sit
    in) and merging what ``on_include`` reads at the point a file is loaded."""
    open_bodies: List[Tuple[int, str]] = []  # (end, macro) of bodies containing i
    i = 0
    n = len(text)
    while i < n:
        while open_bodies and i >= open_bodies[-1][0]:
            open_bodies.pop()
        ch = text[i]
        if ch == '%':
            i = tex_scan.skip_comment(text, i)
            continue
        if ch != '\\':
            i += 1
            continue
        name, j = tex_scan.read_control_sequence(text, i)
        skipped = tex_scan.skip_verbatim(text, name, j)
        if skipped is not None:
            i = skipped
            continue

        parsed: Optional[Tuple[MacroDef, tex_scan.Definition]] = None
        if name in _COLLECTED:
            parsed = _parse(text, name, j, source_file)
            if (
                parsed is not None
                and name == 'providecommand'
                and parsed[0].name in defs
            ):
                # Defines nothing when the name already exists; its body is
                # still scanned, like any other.
                definition = parsed[1]
                open_bodies.append((definition.body_end, parsed[0].name))
                i = definition.body_start
                continue
        elif name == 'DeclareOption':
            code = _option_code(text, j)
            if code is not None:
                # Runs only when the option is passed: as conditional as a
                # macro body, and stored in one.
                open_bodies.append((code[1], f'DeclareOption{code[2]}'))
                i = code[0]
                continue
        elif on_include is not None and (name in _INCLUDES or name in _PACKAGES):
            child, j = _read_include(text, name, j, on_include)
            if child is not None:
                defs.merge(child)

        if parsed is not None:
            macro, definition = parsed
            defs.add(
                _undouble(macro, len(open_bodies)),
                nested_in=open_bodies[-1][1] if open_bodies else None,
            )
            open_bodies.append((definition.body_end, macro.name))
            i = definition.body_start
            continue
        i = j


def extract_definitions(
    tex_content: str,
    source_file: Optional[str] = None,
) -> MacroDefinitions:
    """Extract all macro definitions from a TeX string, in document order (so
    a later ``\\renewcommand`` overwrites an earlier one), nested ones included."""
    defs = MacroDefinitions()
    _scan_definitions(tex_content, source_file, defs)
    return defs


def _resolve_input_path(
    name: str, base_dir: pathlib.Path, extensions: tuple = ('.tex',)
) -> Optional[pathlib.Path]:
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


def _collect_text(
    content: str,
    source_file: Optional[str],
    base_dir: pathlib.Path,
    visited: Set[pathlib.Path],
) -> MacroDefinitions:
    def on_include(kind: str, target: str) -> Optional[MacroDefinitions]:
        if kind == 'package':
            path = _resolve_package_path(target, base_dir)
        else:
            path = _resolve_input_path(target, base_dir)
        if path is None:
            return None
        return _collect_recursive(path, base_dir, visited)

    defs = MacroDefinitions()
    _scan_definitions(content, source_file, defs, on_include)
    return defs


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

    return _collect_text(content, str(resolved), base_dir, visited)


def collect_macro_definitions(
    tex_path: pathlib.Path,
    base_dir: Optional[pathlib.Path] = None,
) -> MacroDefinitions:
    """Collect all macro definitions from a TeX file, recursively visiting dependencies."""
    if base_dir is None:
        base_dir = tex_path.parent
    return _collect_recursive(tex_path, base_dir, set())


def collect_macro_definitions_from_text(
    content: str,
    base_dir: pathlib.Path,
    source_file: Optional[pathlib.Path] = None,
) -> MacroDefinitions:
    """:func:`collect_macro_definitions` for TeX that is not (yet) a file:
    dependencies resolve against ``base_dir``, and ``source_file`` is what the
    definitions read from ``content`` itself are attributed to."""
    visited: Set[pathlib.Path] = set()
    source = None
    if source_file is not None:
        resolved = source_file.resolve()
        visited.add(resolved)
        source = str(resolved)
    return _collect_text(content, source, base_dir, visited)


# --- Selection ---------------------------------------------------------------

_PICTURE_RE = re.compile(r'\\begin\s*\{tikzpicture\}|\\tikz(?![A-Za-z@])')
_CONTROL_WORD_RE = re.compile(r'\\([A-Za-z@]+)')


def select_picture_macros(macro_defs: MacroDefinitions) -> MacroDefinitions:
    """The macros that draw a TikZ picture: those whose body holds a
    ``tikzpicture`` or a ``\\tikz``, directly or through another such macro."""
    names = set(macro_defs)
    calls: Dict[str, Set[str]] = {}
    pictures: Set[str] = set()
    for name in names:
        macro = macro_defs.get(name)
        assert macro is not None
        if _PICTURE_RE.search(macro.body):
            pictures.add(name)
        calls[name] = set(_CONTROL_WORD_RE.findall(macro.body)) & names

    changed = True
    while changed:
        changed = False
        for name in names - pictures:
            if calls[name] & pictures:
                pictures.add(name)
                changed = True
    return macro_defs.select(lambda name: name in pictures)


# --- Expansion ---------------------------------------------------------------

# Expansion never looks inside these: a use of `\foo` in `\newcommand{\foo}`
# names the macro being defined rather than calling it.
_DEFINITION_COMMANDS = frozenset(
    {
        'newcommand',
        'renewcommand',
        'providecommand',
        'def',
        'gdef',
        'edef',
        'xdef',
        'DeclareRobustCommand',
        'newenvironment',
        'renewenvironment',
    }
)

_BODY_PARAM_RE = re.compile(r'#(#|\d)')


def _substitute_body(body: str, args: List[str]) -> str:
    """Expand ``body`` the way TeX does: ``#<n>`` becomes the n-th argument and
    ``##`` becomes ``#`` (the parameter character of a definition nested in the
    body)."""

    def replace(match: 're.Match[str]') -> str:
        token = match.group(1)
        if token == '#':
            return '#'
        index = int(token) - 1
        return args[index] if 0 <= index < len(args) else match.group(0)

    return _BODY_PARAM_RE.sub(replace, body)


def _read_use(
    text: str, end_of_name: int, macro: MacroDef
) -> Optional[Tuple[List[str], int]]:
    """The arguments of a use of ``macro`` whose name ends at ``end_of_name``,
    and the index past the last one; ``None`` when they are not all there."""
    args: List[str] = []
    j = end_of_name
    remaining = macro.n_args
    if macro.n_args > 0 and macro.default is not None:
        k = tex_scan.skip_blanks(text, j, newlines=False)
        if k < len(text) and text[k] == '[':
            end = tex_scan.read_group(text, k, '[')
            if end is None:
                return None
            args.append(text[k + 1 : end - 1])
            j = end
        else:
            args.append(macro.default)
        remaining -= 1
    for _ in range(remaining):
        read = tex_scan.read_argument(text, j)
        if read is None:
            return None
        arg, _, j = read
        args.append(arg)
    return args, j


def _find_and_expand(tex_content: str, macro_defs: MacroDefinitions) -> Tuple[str, int]:
    """Single pass: find macro usages via TexSoup and expand them via text replacement."""
    try:
        soup = parse_latex(escape_for_texsoup(tex_content))
    except Exception:
        return tex_content, 0

    replacements: List[Tuple[int, int, str]] = []

    def visit(node: TexNode) -> None:
        name = getattr(node, 'name', None)
        if name in _DEFINITION_COMMANDS:
            return
        macro = macro_defs.get(name) if name else None
        pos = getattr(node, 'position', None)
        if (
            macro is not None
            and pos is not None
            and tex_content.startswith('\\' + name, pos)
        ):
            use = _read_use(tex_content, pos + 1 + len(name), macro)
            if use is not None:
                args, end = use
                replacements.append((pos, end, _substitute_body(macro.body, args)))
                return

        for child in node.contents:
            if isinstance(child, TexNode):
                visit(child)

    visit(soup)

    if not replacements:
        return tex_content, 0

    # A use found inside another use's arguments is expanded with it, on the
    # next pass: keep only the outermost, and apply right-to-left so earlier
    # positions stay valid.
    replacements.sort(key=lambda r: (r[0], -r[1]))
    outermost: List[Tuple[int, int, str]] = []
    for replacement in replacements:
        if outermost and replacement[0] < outermost[-1][1]:
            continue
        outermost.append(replacement)

    result = tex_content
    for start, end, replacement in reversed(outermost):
        result = result[:start] + replacement + result[end:]

    return result, len(outermost)


def expand_macros(
    tex_content: str,
    macro_defs: MacroDefinitions,
    max_iterations: int = 10,
) -> str:
    """Expand all macro usages in a TeX string.

    Uses an iterative fixpoint approach: each iteration parses the current text
    with TexSoup, finds macro usages, and expands them via text replacement.
    Repeats until no more substitutions are made or *max_iterations* is reached
    (handles nested macros). The extent of each use -- its arguments -- is read
    off the text with TeX's rules, so a ``{...}`` after a use is consumed only
    when the macro takes an argument there.

    Uses inside a definition (``\\newcommand{\\foo}{...\\bar...}``) are left
    alone: there they are the name being defined, or a body that runs later.
    """
    if not len(macro_defs):
        return tex_content
    content = tex_content
    for _ in range(max_iterations):
        content, count = _find_and_expand(content, macro_defs)
        if count == 0:
            break
    return content
