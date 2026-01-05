import dataclasses
from typing import List, NamedTuple, Optional, Set, Tuple

from TexSoup.data import TexNode, Token

from rbx.box.exception import RbxException
from rbx.box.statements.texsoup_utils import parse_latex


class PolygonInvalidConstruct(NamedTuple):
    construct: str
    location: Tuple[int, int]
    reason: str


@dataclasses.dataclass
class PolygonTeXConfig:
    allowed_commands: Set[str]
    allowed_environments: Set[str]
    allowed_math_delimiters: Set[str]

    # Commands that start a math mode (like \( or \[) are strictly disallowed
    # if they are not in allowed_math_delimiters.

    @classmethod
    def default(cls) -> 'PolygonTeXConfig':
        return cls(
            allowed_commands={
                # Text Styles
                'bf',
                'textbf',
                'it',
                'textit',
                't',
                'tt',
                'texttt',
                'emph',
                'underline',
                'sout',
                'textsc',
                'textsubscript',
                'textsuperscript',
                # Sizes
                'tiny',
                'scriptsize',
                'small',
                'normalsize',
                'large',
                'Large',
                'LARGE',
                'huge',
                'Huge',
                # Structure
                'par',
                'item',
                # Verbatim/Code
                'verb',
                # Links/Images
                'url',
                'href',
                'includegraphics',
                # Tables
                'hline',
                'cline',
                'multicolumn',
                'multirow',
                # Misc
                'epigraph',
                'def',
                # We also need to allow basic accents or symbols if they are commands?
                # The manual mentions specific special chars escape sequences like \%, \$, etc.
                # These often parse as commands or escaped chars in TexSoup.
                '%',
                '$',
                '&',
                '#',
                '_',
                '{',
                '}',
            },
            allowed_environments={
                'itemize',
                'enumerate',
                'verbatim',
                'lstlisting',
                'center',
                'tabular',
            },
            allowed_math_delimiters={'$', '$$'},
        )


FONT_SWITCHES = {
    'it',
    'bf',
    'tt',
    'sf',
    'sl',
    'sc',
    'rm',
    'tiny',
    'scriptsize',
    'small',
    'normalsize',
    'large',
    'Large',
    'LARGE',
    'huge',
    'Huge',
    'bfseries',
    'itshape',
    'ttfamily',
    'sffamily',
    'rmfamily',
}

BARRIERS = {
    'item',
    'section',
    'subsection',
    'subsubsection',
    'chapter',
    'part',
    'begin',
    'end',
    'par',
}


def _get_node_position(node: TexNode, original_text: str) -> Tuple[int, int]:
    """
    Approximates the (line, column) of a node.
    TexSoup nodes have a .position attribute (absolute index).
    """
    pos = getattr(node, 'position', None)
    if pos is None:
        return (0, 0)

    # Calculate line and col
    # TODO: This might be slow for very large texts if done repeatedly from scratch,
    # but statements are usually small.
    current_line = 1
    last_newline = -1
    for i in range(pos):
        if original_text[i] == '\n':
            current_line += 1
            last_newline = i

    col = pos - last_newline - 1
    return (current_line, max(0, col))


def validate_polygon_tex(
    latex_code: str, config: Optional[PolygonTeXConfig] = None
) -> List[PolygonInvalidConstruct]:
    if config is None:
        config = PolygonTeXConfig.default()

    errors = []

    # Use the existing parse_latex from texsoup_utils
    # Note: TexSoup might fail on very broken latex, but we assume it's parseable enough.
    try:
        soup = parse_latex(latex_code)
    except Exception as e:
        # If parsing fails, raise a hard exception
        err = RbxException()
        err.print(f'Failed to parse LaTeX: {e}')
        raise err from e

    def traverse(node_or_list):
        # Unwrap list-like structures if needed
        nodes = (
            node_or_list if isinstance(node_or_list, list) else node_or_list.contents
        )

        for node in nodes:
            if isinstance(node, Token):
                # Check for math delimiters in tokens if they appear as such
                # TexSoup often handles $ as a specific Token or Node depending on parsing
                if node.text in ('$', '$$'):
                    # Math mode!
                    # If it's a math delimiter supported by us, we skip content validation?
                    # Actually TexSoup usually parses math environments as nodes if it recognizes them.
                    pass
                continue

            if not isinstance(node, TexNode):
                continue

            node_name = node.name

            # 1. Check for Math Modes
            # TexSoup typically parses $...$ as a node with name '$' or '$$' (if strict) or sometimes just text.
            # If recognized as a math environment:
            if node_name in config.allowed_math_delimiters:
                # Valid math block. Skip recursive validation of contents.
                continue

            # Check for invalid math delimiters
            # TexSoup parses \( ... \) as 'math' and \[ ... \] as 'displaymath'
            if node_name == 'math':
                errors.append(
                    PolygonInvalidConstruct(
                        construct=r'\(',
                        location=_get_node_position(node, latex_code),
                        reason='Unsupported math delimiter. Use $...$.',
                    )
                )
                continue
            if node_name == 'displaymath':
                errors.append(
                    PolygonInvalidConstruct(
                        construct=r'\[',
                        location=_get_node_position(node, latex_code),
                        reason='Unsupported math delimiter. Use $$...$$.',
                    )
                )
                continue

            if node_name in ('\\[', '\\]', '\\(', '\\)'):
                errors.append(
                    PolygonInvalidConstruct(
                        construct=node_name,
                        location=_get_node_position(node, latex_code),
                        reason='Unsupported math delimiter. Use $ or $$.',
                    )
                )
                continue  # Don't recurse into invalid math

            # Check for known math environments that are disallowed
            # (TexSoup might parse \begin{equation} as name='equation')
            if node_name in ('equation', 'align', 'gather', 'split'):
                errors.append(
                    PolygonInvalidConstruct(
                        construct=f'\\begin{{{node_name}}}',
                        location=_get_node_position(node, latex_code),
                        reason='Unsupported math environment. Use $$...$$ and standard MathJax.',
                    )
                )
                continue

            # 2. Check Environments
            # In TexSoup, environments usually have begin/end logic.
            # We can detect environments if it appears in `allowed_environments` or if it starts with 'begin' logic?
            # TexSoup abstracts 'begin{foo}' ... 'end{foo}' into a node named 'foo'.
            # However, commands are also nodes named 'command'.
            # We can distinguish by checking if valid environment.

            # If it's a standard token/text, name is generic or None.
            # Construct names in TexSoup are the command names.

            if node_name in config.allowed_environments:
                # Valid environment. Recurse.
                traverse(node)
                continue

            # 3. Check Commands
            if node_name in config.allowed_commands:
                # Valid command. Recurse (arguments might contain other commands).
                traverse(node)
                continue

            # If we are here, the node name is NOT in allowed commands OR environments.
            # But wait, TexSoup uses the command name as the node name.
            # So `\section{...}` -> name='section'.
            # `\begin{itemize}` -> name='itemize'.

            # Is it actually a command/environment?
            # Some things are plain text or other tokens.
            if not node_name:
                # Likely a root or some structural wrapper without a name
                traverse(node)
                continue

            # If it's not allowed, report error.
            # We construct the representation for the user
            # Heuristic: if it usually has \begin / \end, but TexSoup might mask that.
            # We can check the source or just report the name.

            # Special case for [text] or other weird nodes TexSoup might create?
            # Usually simple text nodes have name='#text' or similar, but we filtered `isinstance(node, TexNode)`.
            # TexNode always has a name corresponding to the command/env.

            errors.append(
                PolygonInvalidConstruct(
                    construct=f'\\{node_name}'
                    if not node_name.startswith('\\')
                    else node_name,
                    location=_get_node_position(node, latex_code),
                    reason=f'Unsupported command or environment: {node_name}',
                )
            )

            # We assume if the outer construct is invalid, we probably still want to check its children?
            # Or maybe not, to avoid noise?
            # "fail fast" or "find all"? "Find all" is better.
            traverse(node)

    traverse(soup)
    return errors


def convert_to_polygon_tex(latex_code: str) -> str:
    """
    Converts standard LaTeX to Polygon-compatible LaTeX.

    Main transformations:
    1. Replaces \( ... \) with $ ... $
    2. Replaces \[ ... \] with $$ ... $$
    3. Wraps font switch commands (like \it, \huge) in braces { \it ... }
       until a barrier (like \item or end of scope) is reached.
    """
    try:
        soup = parse_latex(latex_code)
    except Exception as e:
        err = RbxException()
        err.print(f'Failed to parse LaTeX for conversion: {e}')
        raise err from e

    config = PolygonTeXConfig.default()

    # Identify verbatim-like environments to skip
    VERBATIM_LIKE = {'verb', 'lstlisting', 'verbatim', 'spverbatim', 'minted'}

    def transform_nodes(nodes) -> str:
        result = []
        i = 0
        node_list = list(nodes)

        while i < len(node_list):
            node = node_list[i]

            # Helper to handle non-TexNodes (Tokens, strings)
            if not isinstance(node, TexNode):
                # Just append string representation
                result.append(str(node))
                i += 1
                continue

            node_name = node.name

            # --- Skip Verbatim-like Constructs ---
            if node_name in VERBATIM_LIKE:
                result.append(str(node))
                i += 1
                continue

            # --- Math Transformations ---
            if node_name == 'math':  # \( ... \)
                # Extract contents and wrap in $
                transformed_contents = transform_nodes(node.contents)
                result.append(f'${transformed_contents}$')
                i += 1
                continue

            if node_name == 'displaymath':  # \[ ... \]
                transformed_contents = transform_nodes(node.contents)
                result.append(f'$${transformed_contents}$$')
                i += 1
                continue

            # --- Font Switch Handling ---
            if node_name in FONT_SWITCHES and not node.args:
                # Undelimited font switch! e.g. \it text...
                # We need to wrap this and subsequent nodes until a barrier.

                switch_cmd = f'\\{node_name}'
                captured_nodes = []

                # Move to next node
                j = i + 1
                while j < len(node_list):
                    next_node = node_list[j]

                    # Check for barrier
                    if isinstance(next_node, TexNode):
                        if next_node.name in BARRIERS:
                            break
                    # Tokens/strings are captured

                    captured_nodes.append(next_node)
                    j += 1

                # Transform captured segment
                transformed_segment = transform_nodes(captured_nodes)

                # Result is { \switch transformed... }
                if captured_nodes:
                    result.append(f'{{{switch_cmd}{transformed_segment}}}')
                else:
                    result.append(f'{{{switch_cmd}}}')

                # Advance main index
                i = j
                continue

            # --- Default Recursive Step ---

            # Identify "true contents" (children that are not arguments)
            # This logic avoids duplicating argument text if TexSoup puts it in contents
            # args_set = set(node.args) # BraceGroup unhashable
            args_list = list(node.args)
            true_contents = [c for c in node.contents if c not in args_list]

            # Reconstruct arguments
            transformed_args = []
            for arg in node.args:
                t_arg = transform_nodes(arg.contents)
                # BraceGroup might not have type, implies required
                arg_type = getattr(arg, 'type', 'required')
                if arg_type == 'optional':
                    transformed_args.append(f'[{t_arg}]')
                else:
                    transformed_args.append(f'{{{t_arg}}}')

            args_str = ''.join(transformed_args)

            # Handle BraceGroup (implicit group { ... })
            if node_name == 'BraceGroup':
                body = transform_nodes(node.contents)
                result.append(f'{{{body}}}')
                i += 1
                continue

            # Reconstruct Environment vs Command
            is_env = node_name in config.allowed_environments or node_name in (
                'math',
                'displaymath',
            )

            if is_env:
                # Environment
                body = transform_nodes(node.contents)
                result.append(
                    f'\\begin{{{node_name}}}{args_str}{body}\\end{{{node_name}}}'
                )
            else:
                # Command
                # Recursively process contents (children) if any (and not already args)
                # Heuristic: Standard commands usually duplicate text in contents if they have args.
                # Only 'item' consumes following text as contents regardless of args.
                has_args = bool(args_list)
                should_process_contents = (node_name == 'item') or (not has_args)

                if should_process_contents:
                    extra_contents = (
                        transform_nodes(true_contents) if true_contents else ''
                    )
                else:
                    extra_contents = ''

                result.append(f'\\{node_name}{args_str}{extra_contents}')

            i += 1

        return ''.join(result)

    return transform_nodes(soup.contents)
