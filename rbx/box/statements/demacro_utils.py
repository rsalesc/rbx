import dataclasses
import json
import pathlib
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from TexSoup.data import BraceGroup, BracketGroup, TexCmd, TexNode

from rbx.box.statements.texsoup_utils import parse_latex


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


class MacroDefinitions:
    def __init__(self) -> None:
        self._defs: Dict[str, MacroDef] = {}

    def add(self, macro_def: MacroDef) -> None:
        self._defs[macro_def.name] = macro_def

    def get(self, name: str) -> Optional[MacroDef]:
        return self._defs.get(name)

    def merge(self, other: 'MacroDefinitions') -> None:
        for name in other:
            macro = other.get(name)
            if macro is not None:
                self.add(macro)

    def __contains__(self, name: str) -> bool:
        return name in self._defs

    def __iter__(self) -> Iterator[str]:
        return iter(self._defs)

    def __len__(self) -> int:
        return len(self._defs)

    def filter(self, to_filter_out: Iterable[str]) -> 'MacroDefinitions':
        to_filter_out = set(to_filter_out)
        new_defs = MacroDefinitions()
        for name, macro in self._defs.items():
            if name not in to_filter_out:
                new_defs.add(macro)
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


_NEWCOMMAND_NAMES = {'newcommand', 'newcommand*', 'renewcommand', 'renewcommand*'}


def _extract_name_from_arg(arg) -> Optional[str]:
    """Extract command name (without backslash) from a newcommand's first argument."""
    if isinstance(arg, BraceGroup):
        for child in arg.contents:
            if isinstance(child, TexCmd):
                return child.name
        text = arg.string.strip()
        if text.startswith('\\'):
            return text[1:]
    return None


def _extract_newcommand(
    node: TexNode, source_file: Optional[str] = None
) -> Optional[MacroDef]:
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

    if idx < len(args) and isinstance(args[idx], BracketGroup):
        try:
            n_args = int(args[idx].string)
        except ValueError:
            pass
        idx += 1

    if idx < len(args) and isinstance(args[idx], BracketGroup):
        default = args[idx].string
        idx += 1

    if idx < len(args) and isinstance(args[idx], BraceGroup):
        body = args[idx].string

    return MacroDef(
        name=name,
        n_args=n_args,
        default=default,
        body=body,
        source_file=source_file,
    )


def _extract_def(
    node: TexNode, source_file: Optional[str] = None
) -> Optional[MacroDef]:
    """Extract a MacroDef from a \\def node (0-arg form only)."""
    args = list(node.args)
    if len(args) < 2:
        return None

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

    # Iterate descendants in document order so that later definitions
    # (e.g. \renewcommand) correctly overwrite earlier ones.
    for node in soup.descendants:
        if not isinstance(node, TexNode):
            continue
        name = getattr(node, 'name', None)
        if name in _NEWCOMMAND_NAMES:
            macro = _extract_newcommand(node, source_file)
            if macro is not None:
                defs.add(macro)
        elif name == 'def':
            macro = _extract_def(node, source_file)
            if macro is not None:
                defs.add(macro)

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

    for cmd_name in ('usepackage', 'RequirePackage'):
        for node in soup.find_all(cmd_name):
            args = list(node.args)
            if not args:
                continue
            pkg_arg = args[-1].string.strip()
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


def _substitute_body(body: str, args: List[str]) -> str:
    """Replace #1, #2, ... in body with actual argument strings."""
    result = body
    for i, arg_val in enumerate(args, 1):
        result = result.replace(f'#{i}', arg_val)
    return result


def _find_and_expand(tex_content: str, macro_defs: MacroDefinitions) -> Tuple[str, int]:
    """Single pass: find macro usages via TexSoup and expand them via text replacement."""
    try:
        soup = parse_latex(tex_content)
    except Exception:
        return tex_content, 0

    replacements: List[Tuple[int, int, str]] = []

    def visit(node: TexNode) -> None:
        if not isinstance(node, TexNode):
            return

        name = getattr(node, 'name', None)
        if name and name in macro_defs:
            macro = macro_defs.get(name)
            if macro is None:
                return
            pos = getattr(node, 'position', None)
            if pos is None:
                return

            node_args = list(node.args)
            arg_strings: List[str] = []

            if macro.n_args == 0:
                # 0-arg macro: don't consume any TexSoup-parsed arguments.
                # TexSoup may greedily parse following braces as args.
                start = pos
                end = start + len('\\' + name)
            else:
                start = pos
                end = start + len(str(node))

                if macro.default is not None:
                    # First arg is optional (BracketGroup).
                    if node_args and isinstance(node_args[0], BracketGroup):
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
            return

        for child in node.contents:
            if isinstance(child, TexNode):
                visit(child)

    visit(soup)

    if not replacements:
        return tex_content, 0

    # Apply replacements right-to-left to preserve earlier positions.
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
    """Expand all macro usages in a TeX string.

    Uses an iterative fixpoint approach: each iteration parses the current text
    with TexSoup, finds macro usages, and expands them via text replacement.
    Repeats until no more substitutions are made or *max_iterations* is reached
    (handles nested macros).
    """
    content = tex_content
    for _ in range(max_iterations):
        content, count = _find_and_expand(content, macro_defs)
        if count == 0:
            break
    return content
