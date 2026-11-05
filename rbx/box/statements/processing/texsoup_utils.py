import pathlib
import re
from typing import Any, Callable, List, Mapping, Optional, Tuple

from TexSoup import TexSoup
from TexSoup.data import BraceGroup, BracketGroup, TexNamedEnv, TexNode

from rbx.box.statements.processing import tex_scan

EXTERNALIZATION_DIR = 'artifacts/tikz_figures/'

# Extensions an ``\includegraphics`` argument may carry (LaTeX resolves the
# reference with or without one).
ASSET_EXTS = ('.png', '.jpg', '.jpeg', '.pdf')

# TexSoup bug workaround: \$ is valid LaTeX (literal dollar sign) but TexSoup
# interprets the $ as opening math mode and fails with EOFError.
# We replace \$ with a 2-char private-use Unicode sentinel (preserving string
# length so TexSoup position indices stay correct) before parsing, and restore
# it after.
_ESCAPED_DOLLAR_SENTINEL = '\ue000\ue001'


def escape_for_texsoup(latex_code: str) -> str:
    r"""Replace \$ with a sentinel that TexSoup can parse safely."""
    return latex_code.replace(r'\$', _ESCAPED_DOLLAR_SENTINEL)


def unescape_from_texsoup(text: str) -> str:
    r"""Restore \$ from sentinels after TexSoup processing."""
    return text.replace(_ESCAPED_DOLLAR_SENTINEL, r'\$')


def parse_latex(latex_code: str) -> TexNode:
    return TexSoup(latex_code)


def inject_in_preamble(soup: TexNode, latex_code: str):
    r"""Inject ``latex_code`` into the preamble, right after ``\documentclass``.

    Uses :meth:`TexNode.replace_with` on the ``\documentclass`` node itself rather
    than sibling-index insertion: TexSoup's ``parent.insert`` indexes the
    *children* space (which excludes comments), so a leading comment line — as in
    every default-preset template — offsets the index and drops the preamble
    *before* ``\documentclass`` (``! LaTeX Error: \usepackage before
    \documentclass``, #568). Replacing the node sidesteps the index math
    entirely. When there is no ``\documentclass`` the code is prepended.
    """
    doc_class = soup.find('documentclass')
    if doc_class is not None:
        combined = TexSoup(str(doc_class) + '\n' + latex_code)
        doc_class.replace_with(*combined.contents)
    else:
        soup.insert(0, TexSoup(latex_code))


EXTERNALIZATION_PREAMBLE = f"""
\\usepackage{{tikz}}
\\usetikzlibrary{{external}}
\\tikzexternalize[prefix={EXTERNALIZATION_DIR}]
"""


def inject_externalization_for_tikz(soup: TexNode):
    inject_in_preamble(soup, EXTERNALIZATION_PREAMBLE)


def inject_in_preamble_text(text: str, latex_code: str) -> str:
    r"""``text`` with ``latex_code`` spliced in right after ``\documentclass``
    (prepended when there is none).

    The text counterpart of :func:`inject_in_preamble`, and the one a compile
    should use: it never prints a soup back, so nothing else in the document
    changes. A TexSoup round trip does not preserve TeX -- it prints
    ``\def\foo#1{x}`` as ``\def\foo{#1}{x}``, which TeX reads differently."""
    code = latex_code if latex_code.endswith('\n') else latex_code + '\n'
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '%':
            i = tex_scan.skip_comment(text, i)
            continue
        if ch != '\\':
            i += 1
            continue
        name, j = tex_scan.read_control_sequence(text, i)
        if name != 'documentclass':
            skipped = tex_scan.skip_verbatim(text, name, j)
            i = j if skipped is None else skipped
            continue
        k = tex_scan.skip_blanks(text, j)
        if k < n and text[k] == '[':
            end = tex_scan.read_group(text, k, '[')
            k = tex_scan.skip_blanks(text, end) if end is not None else k
        if k < n and text[k] == '{':
            end = tex_scan.read_group(text, k)
            if end is not None:
                return text[:end] + '\n' + code + text[end:]
        break
    return code + text


# A picture inside one of these is a template, drawn wherever the macro is
# used, not a figure of its own: labeling it would give every use the same name.
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
        'NewDocumentCommand',
        'RenewDocumentCommand',
        'DeclareDocumentCommand',
    }
)


def get_top_level_tikz_nodes(
    soup: TexNode, source: Optional[str] = None
) -> List[TexNode]:
    """
    Returns a list of tikzpicture nodes that are NOT nested inside other tikzpictures.
    We only want to externalize the outermost container.

    Pictures inside a macro definition's body are not figures either: they are
    drawn where the macro is used, which is where the export path expands
    them (``render.expand_picture_macros``). With ``source`` -- the text the
    soup was parsed from -- the bodies are found by reading the text, which
    also catches a definition TexSoup misparses (a comment between
    ``\\newcommand{\\foo}`` and its body leaves the body outside the command).
    """
    all_tikzs = list(soup.find_all('tikzpicture'))
    top_level = []
    bodies = tex_scan.definition_bodies(source) if source is not None else []

    for node in all_tikzs:
        if not isinstance(node, TexNode):
            continue
        position = getattr(node, 'position', None)
        if position is not None and tex_scan.within(position, bodies):
            continue
        # Check ancestors
        is_nested = False
        parent = node.parent
        while parent:
            if parent.name == 'tikzpicture' or parent.name in _DEFINITION_COMMANDS:
                is_nested = True
                break
            parent = parent.parent

        if not is_nested:
            top_level.append(node)

    return top_level


def get_tikz_node_label(tikz_node: TexNode) -> Optional[Tuple[TexNode, str]]:
    parent = tikz_node.parent
    if not parent:
        return None

    # Find the index of the node in the parent's contents
    # We use position because identity checks might be unreliable if TexSoup rebuilds wrappers
    # We use contents to see Tokens/text too
    contents = list(parent.contents)
    node_idx = -1

    target_pos = getattr(tikz_node, 'position', None)

    for i, child in enumerate(contents):
        # First try identity
        if child is tikz_node:
            node_idx = i
            break
        # Fallback to position matching
        if target_pos is not None:
            child_pos = getattr(child, 'position', None)
            if child_pos == target_pos:
                node_idx = i
                break

    if node_idx == -1:
        return None

    # Search backwards from the node
    for i in range(node_idx - 1, -1, -1):
        sibling = contents[i]

        # Check if it's a TexNode
        if not hasattr(sibling, 'name'):
            # It's likely a text/whitespace string or Token
            text = str(sibling)
            if not text.strip():
                continue  # Skip whitespace
            elif text.strip().startswith('%'):
                continue  # Skip comments
            else:
                # Found non-whitespace text, stop searching
                return None

        # It is a node
        name = getattr(sibling, 'name', None)
        if name == 'tikzsetnextfilename':
            # Found the label!
            if sibling.args and len(sibling.args) > 0:
                arg = sibling.args[0]
                return sibling, arg.string
            return None

        # If it's something else (another command or environment), we stop
        return None

    return None


def get_top_level_labeled_tikz_nodes(
    soup: TexNode, source: Optional[str] = None
) -> List[Tuple[TexNode, TexNode, str]]:
    """
    Returns a list of tikzpicture nodes that are NOT nested inside other tikzpictures.
    We only want to externalize the outermost container.
    """
    top_level_tikz = get_top_level_tikz_nodes(soup, source)

    labeled_tikz = []
    for node in top_level_tikz:
        label = get_tikz_node_label(node)
        if label:
            labeled_tikz.append((node, label[0], label[1]))
    return labeled_tikz


def add_labels_to_tikz_nodes(soup: TexNode, prefix: str = 'figure'):
    top_level_tikz = get_top_level_tikz_nodes(soup)

    for i, node in enumerate(top_level_tikz):
        # Skip if already labeled
        label = get_tikz_node_label(node)
        if label:
            continue

        fig_name = f'{prefix}_{i}'
        cmd_str = f'\\tikzsetnextfilename{{{fig_name}}}'
        # No line break between the two: in running text it would typeset as
        # an extra space before the picture.
        replacement_block = f'{cmd_str}{str(node)}'

        # Parse and replace
        # *TexSoup(...).contents unpacks the list of nodes from the new soup
        node.replace_with(*TexSoup(replacement_block).contents)


def replace_labeled_tikz_nodes(
    soup: TexNode, prefix: str = EXTERNALIZATION_DIR, center: bool = True
):
    """Replace each labeled picture with an ``\\includegraphics`` of its
    externalized PDF, placed the way the picture was (see
    :func:`figure_placement`); ``center`` wraps the display ones."""
    labeled_tikz = get_top_level_labeled_tikz_nodes(soup)

    # The soup's own text stands in for its source: where printing it back is
    # not faithful, `_run_text` notices and reads the tokens instead.
    source = str(soup)
    replacements = [
        (tikz_node, label_node, _figure_tex(prefix + label, tikz_node, center, source))
        for tikz_node, label_node, label in labeled_tikz
    ]
    for tikz_node, label_node, cmd_str in replacements:
        label_node.delete()
        tikz_node.replace_with(*TexSoup(cmd_str).contents)


# --- Where a figure sits: inline in text, or a display of its own ------------

INLINE = 'inline'
DISPLAY = 'display'
CENTERED = 'centered'

# End a paragraph, so a figure next to one is not in running text with it.
_PARAGRAPH_BARRIERS = frozenset(
    {
        'par',
        'item',
        'part',
        'chapter',
        'section',
        'subsection',
        'subsubsection',
        'paragraph',
        'subparagraph',
        # Typeset in a paragraph of its own.
        'caption',
        # TeX's display math, as TexSoup names it.
        '$$',
        'displaymath',
    }
)

# Environments that stand on their own lines: a figure beside one is not in
# running text with it either. Anything else (`minipage`, `tabular`, a nested
# picture) is a box in the line, and counts as content.
_DISPLAY_ENVIRONMENTS = frozenset(
    {
        'center',
        'flushleft',
        'flushright',
        'itemize',
        'enumerate',
        'description',
        'quote',
        'quotation',
        'verse',
        'figure',
        'figure*',
        'table',
        'table*',
        'verbatim',
        'lstlisting',
        'minted',
        'equation',
        'equation*',
        'align',
        'align*',
        'gather',
        'gather*',
        'multline',
        'multline*',
    }
)

# Commands that put nothing in the line: declarations, spacing, labels.
_NO_TEXT_COMMANDS = frozenset(
    {
        'tikzsetnextfilename',
        'centering',
        'raggedright',
        'raggedleft',
        'noindent',
        'indent',
        'leavevmode',
        'label',
        'vspace',
        'vspace*',
        'vfill',
        'smallskip',
        'medskip',
        'bigskip',
        'hspace',
        'hspace*',
        'hfill',
        'hfil',
        'quad',
        'qquad',
        'nopagebreak',
        'tiny',
        'scriptsize',
        'footnotesize',
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
        'mdseries',
        'upshape',
        'normalfont',
        'bf',
        'it',
        'tt',
        'sf',
        'rm',
        'sc',
        'sl',
    }
)

_COMMENT_RE = re.compile(r'(?<!\\)%[^\n]*')
_PARAGRAPH_BREAK_RE = re.compile(r'\n[ \t]*\n')


def _group_text(group: Any) -> str:
    """What a group holds, as text. Not TexSoup's ``.string``, which asserts
    unless the group holds exactly one piece of text (``{}``, ``{\\bf x}``)."""
    return tex_scan.strip_tags(''.join(str(item) for item in group.contents))


def _is_environment(node: Any) -> bool:
    return isinstance(getattr(node, 'expr', None), TexNamedEnv)


def _is_root(node: Any) -> bool:
    return getattr(node, 'parent', None) is None


def _is_transparent_group(node: Any) -> bool:
    """A group whose edges are not paragraph edges: a plain ``{...}``."""
    return getattr(node, 'name', None) == 'BraceGroup'


def _is_command(node: Any) -> bool:
    """A command whose argument (or, for ``\\item``, whose text) holds the
    figure: never a place for a ``center`` -- inside ``\\textbf``,
    ``\\caption`` or ``\\centerline`` it would not even compile, and after an
    ``\\item`` the figure shares the line with the label."""
    return not (_is_root(node) or _is_environment(node) or _is_transparent_group(node))


def _body_items(parent: Any) -> List[Any]:
    """``parent``'s contents without its arguments' (an environment's
    ``{arg}``s lead its contents in TexSoup)."""
    contents = list(parent.contents)
    if _is_environment(parent):
        skip = sum(len(list(arg.contents)) for arg in parent.args)
        return contents[skip:]
    return contents


def _index_in(items: List[Any], node: Any) -> int:
    position = getattr(node, 'position', None)
    for i, item in enumerate(items):
        if item is node:
            return i
    for i, item in enumerate(items):
        if position is not None and getattr(item, 'position', None) == position:
            return i
    return -1


def _text_side(text: str, forward: bool) -> Optional[str]:
    """Classify a run of text next to a figure: ``'content'`` when it puts
    words in the figure's paragraph, ``'boundary'`` when a blank line ends the
    paragraph first, ``None`` when it is blank and the search goes on."""
    # A comment is not blank -- a line holding one is not an empty line -- but
    # it is not content either.
    marked = _COMMENT_RE.sub('\x00', tex_scan.strip_tags(text))
    breaks = list(_PARAGRAPH_BREAK_RE.finditer(marked))
    if forward:
        near = marked[: breaks[0].start()] if breaks else marked
    else:
        near = marked[breaks[-1].end() :] if breaks else marked
    if near.replace('\x00', '').strip():
        return 'content'
    return 'boundary' if breaks else None


def _node_side(node: Any) -> Optional[str]:
    name = getattr(node, 'name', None)
    if name in _PARAGRAPH_BARRIERS:
        return 'boundary'
    if _is_environment(node) and name in _DISPLAY_ENVIRONMENTS:
        return 'boundary'
    if name in _NO_TEXT_COMMANDS:
        return None
    if name == 'BraceGroup' and not _group_text(node).strip():
        return None
    return 'content'


def _side_from_tokens(items: List[Any], forward: bool) -> str:
    """:func:`_side` without the source text: the tokens as TexSoup kept them,
    which loses the whitespace it drops between items."""
    run: List[str] = []

    def flush() -> Optional[str]:
        text = ''.join(run if forward else reversed(run))
        run.clear()
        return _text_side(text, forward)

    for item in items if forward else reversed(items):
        if hasattr(item, 'name'):
            verdict = flush() if run else None
            if verdict is None:
                verdict = _node_side(item)
            if verdict is not None:
                return verdict
            continue
        text = str(item)
        # TexSoup keeps a comment's text but drops the newline ending it.
        run.append(text + '\n' if text.startswith('%') else text)
    if run:
        verdict = flush()
        if verdict is not None:
            return verdict
    return 'edge'


def _span(node: Any, source: str) -> Optional[Tuple[int, int]]:
    """Where ``node`` is in ``source``, when what it prints is what is there
    (or, for a picture, when its ``\\end`` can be found)."""
    position = getattr(node, 'position', None)
    if position is None:
        return None
    text = str(node)
    if source.startswith(text, position):
        return position, position + len(text)
    if getattr(node, 'name', None) == 'tikzpicture':
        end = _picture_end(source, node)
        if end is not None:
            return position, end
    return None


_BLANK = ' \t\r\n'


def _side(items: List[Any], forward: bool, source: Optional[str], anchor: Any) -> str:
    """What lies on one side of ``anchor`` among its siblings ``items`` (those
    on that side), nearest first: ``'content'``, a paragraph ``'boundary'``, or
    the ``'edge'`` of the parent.

    The text between nodes is read off ``source``, the text the soup was
    parsed from: TexSoup drops whitespace between items -- the newline after
    an ``\\end{...}`` or ending a comment, a blank line between two
    environments -- and a dropped newline is a lost paragraph break. Without a
    faithful ``source``, the tokens are all there is."""
    anchor_span = _span(anchor, source) if source is not None else None
    if source is None or anchor_span is None:
        return _side_from_tokens(items, forward)

    cursor = anchor_span[1] if forward else anchor_span[0]
    trailing: List[Any] = []
    for item in items if forward else reversed(items):
        if not hasattr(item, 'name'):
            trailing.append(item)
            continue
        span = _span(item, source)
        if span is None:
            return _side_from_tokens(items, forward)
        gap = source[cursor : span[0]] if forward else source[span[1] : cursor]
        verdict = _text_side(gap, forward) or _node_side(item)
        if verdict is not None:
            return verdict
        cursor = span[1] if forward else span[0]
        trailing = []

    # The text between the last node and the parent's edge.
    if trailing:
        positions = [getattr(item, 'position', None) for item in trailing]
        if any(p is None for p in positions):
            return _side_from_tokens(items, forward)
        if forward:
            end = max(p + len(str(t)) for p, t in zip(positions, trailing))
            while end < len(source) and source[end] in _BLANK:
                end += 1
            gap = source[cursor:end]
        else:
            begin = min(positions)
            while begin > 0 and source[begin - 1] in _BLANK:
                begin -= 1
            gap = source[begin:cursor]
        verdict = _text_side(gap, forward)
        if verdict is not None:
            return verdict
    return 'edge'


def _alone_in_paragraph(node: Any, source: Optional[str]) -> bool:
    parent = getattr(node, 'parent', None)
    if parent is None:
        return True
    if _is_command(parent):
        return False
    items = _body_items(parent)
    index = _index_in(items, node)
    if index < 0:
        return False
    before = _side(items[:index], forward=False, source=source, anchor=node)
    after = _side(items[index + 1 :], forward=True, source=source, anchor=node)
    if 'content' in (before, after):
        return False
    if 'edge' in (before, after) and _is_transparent_group(parent):
        return _alone_in_paragraph(parent, source)
    return True


# A display in one of these is already placed: a `center` of its own would
# center it twice (`figure` + `\centering`) or change a box's alignment.
_PLACED_ENVIRONMENTS = frozenset(
    {
        'center',
        'figure',
        'figure*',
        'table',
        'table*',
        'wrapfigure',
        'minipage',
        'subfigure',
    }
)


def _already_placed(node: Any) -> bool:
    """Whether ``node``'s display already has its alignment: it sits in a
    :data:`_PLACED_ENVIRONMENTS` environment, or after a ``\\centering`` in its
    group."""
    child = node
    parent = getattr(node, 'parent', None)
    while parent is not None:
        items = _body_items(parent)
        index = _index_in(items, child)
        if any(getattr(item, 'name', None) == 'centering' for item in items[:index]):
            return True
        if not _is_transparent_group(parent):
            return _is_environment(parent) and parent.name in _PLACED_ENVIRONMENTS
        child, parent = parent, getattr(parent, 'parent', None)
    return False


def figure_placement(node: TexNode, source: Optional[str] = None) -> str:
    """How a figure (a picture, or the ``\\includegraphics`` standing for one)
    sits in its block.

    - :data:`INLINE` -- in running text: other content shares its paragraph,
      as in ``press \\tikz{...} to send``, or it is a command's argument or an
      ``\\item``'s text.
    - :data:`CENTERED` -- alone in its paragraph where its alignment is already
      decided: a ``center``, ``figure`` or ``minipage``, or after
      ``\\centering``.
    - :data:`DISPLAY` -- alone in its paragraph anywhere else.

    "Alone" is TeX's paragraph: up to a blank line, ``\\par``, ``\\item``, a
    ``\\caption``, a sectioning command or a display environment, through
    ``{...}`` groups; comments and commands that typeset nothing
    (``\\centering``, ``\\vspace``, font switches) do not count.

    ``source`` is the text ``node``'s soup was parsed from; without it the
    whitespace TexSoup drops can hide a paragraph break."""
    if not _alone_in_paragraph(node, source):
        return INLINE
    if _already_placed(node):
        return CENTERED
    return DISPLAY


def _figure_tex(
    ref: str, node: TexNode, center: bool, source: Optional[str] = None
) -> str:
    """The TeX a figure becomes: a bare ``\\includegraphics`` in running text
    or in an existing ``center``, and wrapped in a ``center`` of its own
    (``center``) when it is a display."""
    cmd = f'\\includegraphics{{{ref}}}'
    if center and figure_placement(node, source) == DISPLAY:
        return f'\\begin{{center}}{cmd}\\end{{center}}'
    return cmd


# --- Text-level labeling and substitution ------------------------------------
#
# What the build uses. Edits are spliced into the setter's text at the
# positions TexSoup reports, so nothing outside a picture is ever printed back
# from a soup (see `inject_in_preamble_text` for why that matters).


def _picture_end(text: str, node: TexNode) -> Optional[int]:
    """The index just past ``node``'s ``\\end{tikzpicture}`` in ``text``."""
    position = getattr(node, 'position', None)
    if position is None or not text.startswith('\\begin', position):
        return None
    parsed = tex_scan.read_environment_name(text, position + len('\\begin'))
    if parsed is None or parsed[0] != 'tikzpicture':
        return None
    return tex_scan.find_environment_end(text, parsed[1], 'tikzpicture')


def _splice(text: str, edits: List[Tuple[int, int, str]]) -> str:
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def label_tikz_pictures(text: str, prefix: str = 'figure') -> str:
    """``text`` with a ``\\tikzsetnextfilename{<prefix>_<i>}`` before every
    unlabeled top-level picture, so ``\\tikzexternalize`` names its PDF.
    ``i`` counts every top-level picture, labeled or not. Returned unchanged
    when there is nothing to label."""
    if 'tikzpicture' not in text:
        return text
    escaped = escape_for_texsoup(text)  # same length: positions carry over
    soup = parse_latex(escaped)
    edits: List[Tuple[int, int, str]] = []
    for i, node in enumerate(get_top_level_tikz_nodes(soup, escaped)):
        if get_tikz_node_label(node):
            continue
        position = getattr(node, 'position', None)
        if position is None or not text.startswith('\\begin', position):
            continue
        edits.append((position, position, f'\\tikzsetnextfilename{{{prefix}_{i}}}'))
    return _splice(text, edits)


def substitute_labeled_tikz_pictures(
    text: str, prefix: str = EXTERNALIZATION_DIR, center: bool = True
) -> str:
    """``text`` with every labeled top-level picture -- label included --
    replaced by an ``\\includegraphics`` of its externalized PDF, placed as
    :func:`figure_placement` says. The inverse of :func:`label_tikz_pictures`."""
    if 'tikzsetnextfilename' not in text:
        return text
    escaped = escape_for_texsoup(text)  # same length: positions carry over
    soup = parse_latex(escaped)
    edits: List[Tuple[int, int, str]] = []
    for tikz, label_node, label in get_top_level_labeled_tikz_nodes(soup, escaped):
        start = getattr(label_node, 'position', None)
        end = _picture_end(escaped, tikz)
        if start is None or end is None:
            continue
        edits.append((start, end, _figure_tex(prefix + label, tikz, center, escaped)))
    return _splice(text, edits)


def _convert_tikz_command(text: str, i: int) -> Optional[Tuple[str, int]]:
    """``i`` is just past ``\\tikz``: the equivalent environment and the index
    past the command, or ``None`` when its extent cannot be read."""
    n = len(text)
    k = tex_scan.skip_blanks(text, i)
    options = ''
    if k < n and text[k] == '[':
        end = tex_scan.read_group(text, k, '[')
        if end is None:
            return None
        options = text[k:end]
        k = tex_scan.skip_blanks(text, end)
    if k >= n:
        return None
    if text[k] == '{':
        end = tex_scan.read_group(text, k)
        if end is None:
            return None
        body = text[k + 1 : end - 1]
    else:
        # `\tikz <one path>;` -- the picture is everything up to the first `;`
        # outside braces.
        end = k
        depth = 0
        while end < n:
            ch = text[end]
            if ch == '\\':
                _, end = tex_scan.read_control_sequence(text, end)
                continue
            if ch == '%':
                end = tex_scan.skip_comment(text, end)
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth < 0:
                    return None
            elif ch == ';' and depth == 0:
                break
            end += 1
        if end >= n:
            return None
        end += 1
        body = text[k:end]
    body = normalize_tikz_commands(body)
    return f'\\begin{{tikzpicture}}{options}{body}\\end{{tikzpicture}}', end


def normalize_tikz_commands(text: str) -> str:
    """``text`` with every ``\\tikz[...]{...}`` and ``\\tikz[...] ...;`` written
    as the ``tikzpicture`` environment it stands for, so labeling and
    substitution -- which work on environments -- see it too."""
    if '\\tikz' not in text:
        return text
    out: List[str] = []
    last = 0
    i = 0
    n = len(text)
    while i < n:
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
        converted = _convert_tikz_command(text, j) if name == 'tikz' else None
        if converted is None:
            i = j
            continue
        replacement, end = converted
        out.append(text[last:i])
        out.append(replacement)
        last = i = end
    out.append(text[last:])
    return ''.join(out)


def draws_tikz_pictures(text: str) -> bool:
    """Whether ``text`` draws a TikZ picture -- a ``tikzpicture`` or a
    ``\\tikz`` outside a macro definition's body and outside comments."""
    if 'tikz' not in text:
        return False
    normalized = normalize_tikz_commands(text)
    try:
        soup = parse_latex(escape_for_texsoup(normalized))
    except Exception:
        return '\\begin{tikzpicture}' in normalized
    return bool(get_top_level_tikz_nodes(soup, normalized))


def _format_pt(value: float) -> str:
    return f'{value:.2f}'.rstrip('0').rstrip('.') + 'pt'


def size_inline_figures(
    text: str,
    figure_height: Callable[[str], Optional[float]],
    prefix: str = EXTERNALIZATION_DIR,
) -> str:
    """``text`` with a ``height`` on every bare ``\\includegraphics{<prefix>...}``
    that sits in running text, ``figure_height(ref)`` big points tall.

    Written as ``pt`` with the big-point number: pandoc keeps ``pt`` (it drops
    ``bp``) and CSS's ``pt`` *is* the big point, so the HTML a judge renders
    gets the exact size; LaTeX reads it 0.4% small, which it does not show. The
    figure's depth (TikZ's ``.dpth``) is not carried: an image in HTML sits on
    the baseline, so a figure aligned below it rides slightly high.

    For a renderer that does not lay an image out at its natural size: pandoc
    carries the option as ``{height="..pt"}``, so an inline figure -- a button
    drawn in a sentence -- keeps the size it has in the PDF instead of the
    rasterized PNG's pixel size. In LaTeX it is the figure's natural height, so
    it changes nothing."""
    if prefix not in text:
        return text
    escaped = escape_for_texsoup(text)  # same length: positions carry over
    soup = parse_latex(escaped)
    edits: List[Tuple[int, int, str]] = []
    for node in soup.find_all('includegraphics'):
        args = list(node.args)
        if any(isinstance(arg, BracketGroup) for arg in args):
            continue
        brace = next((arg for arg in args if isinstance(arg, BraceGroup)), None)
        if brace is None:
            continue
        ref = _group_text(brace).strip()
        position = getattr(node, 'position', None)
        if (
            not ref.startswith(prefix)
            or position is None
            or not text.startswith('\\includegraphics', position)
            or figure_placement(node, escaped) != INLINE
        ):
            continue
        height = figure_height(ref)
        if height is None:
            continue
        at = position + len('\\includegraphics')
        edits.append((at, at, f'[height={_format_pt(height)}]'))
    return _splice(text, edits)


def strip_asset_ext(ref: str) -> str:
    """Drop a trailing image/PDF extension from an ``\\includegraphics`` argument
    so it lines up with an (extensionless) reference key."""
    path = pathlib.Path(ref)
    return str(path.with_suffix('')) if path.suffix.lower() in ASSET_EXTS else ref


def rewrite_includegraphics(block: str, remap: Mapping[str, str]) -> str:
    """Rewrite every ``\\includegraphics[opts]{ref}`` whose ``ref`` (with any
    image/PDF extension stripped) is a key in ``remap`` to the mapped reference,
    preserving optional arguments and all surrounding text.

    ``remap`` is keyed by extensionless reference and valued by whatever the
    target layout calls the asset (a flattened ``img__diagram.png``, a relative
    ``img/diagram.png`` — the rewrite does not care).

    Parser-based (TexSoup) rather than a naive ``str.replace``: substitutions are
    order-independent and free of substring collisions (remapping both ``pic``
    and ``pic2`` cannot corrupt either), and — by stripping the extension before
    lookup — a reference written *with* its extension never gains a second one
    (``fig.png.png``)."""
    if not remap:
        return block
    soup = parse_latex(block)
    for node in list(soup.find_all('includegraphics')):
        brace = next((arg for arg in node.args if isinstance(arg, BraceGroup)), None)
        if brace is None:
            continue
        target = remap.get(strip_asset_ext(str(brace.string)))
        if target is None:
            continue
        opts = ''.join(
            f'[{arg.string}]' for arg in node.args if isinstance(arg, BracketGroup)
        )
        node.replace_with(*parse_latex(f'\\includegraphics{opts}{{{target}}}').contents)
    return str(soup)
