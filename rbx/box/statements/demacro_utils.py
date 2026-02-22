import dataclasses
import pathlib
from typing import Dict, Iterator, Optional, Set

from TexSoup.data import BraceGroup, BracketGroup, TexCmd, TexNode

from rbx.box.statements.texsoup_utils import parse_latex


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
