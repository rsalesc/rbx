from typing import List, Optional, Tuple

from TexSoup import TexSoup
from TexSoup.data import TexNode

EXTERNALIZATION_DIR = 'artifacts/tikz_figures/'

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
    """
    Injects LaTeX code into the preamble (after documentclass).
    """
    new_nodes = TexSoup(latex_code)
    doc_class = soup.find('documentclass')

    if doc_class:
        # Insert after documentclass.
        # We access the parent (usually root) and insert at the correct index.
        parent = doc_class.parent

        # Find index robustly to handle potential TexSoup node wrapper issues
        index = -1
        contents = list(parent.contents)
        target_pos = getattr(doc_class, 'position', None)
        doc_str = str(doc_class)

        for i, child in enumerate(contents):
            # Try identity first
            if child is doc_class:
                index = i
                break
            # Fallback to position matching
            if target_pos is not None:
                if getattr(child, 'position', None) == target_pos:
                    index = i
                    break
            # Fallback to string matching (safe for documentclass as it's typically unique)
            if str(child) == doc_str:
                index = i
                break

        if index != -1:
            # Insert the new nodes (unpacked)
            for node in reversed(list(new_nodes.contents)):
                # TexSoup requires nodes to be parentless or copied when inserting
                if isinstance(node, TexNode):
                    node = node.copy()
                parent.insert(index + 1, node)
        else:
            # Fallback if we couldn't find the node in parent (shouldn't happen usually)
            soup.insert(0, new_nodes)
    else:
        # No documentclass found, insert at top
        soup.insert(0, new_nodes)


def inject_externalization_for_tikz(soup: TexNode):
    preamble_injection = f"""
\\usepackage{{tikz}}
\\usetikzlibrary{{external}}
\\tikzexternalize[prefix={EXTERNALIZATION_DIR}]
"""
    inject_in_preamble(soup, preamble_injection)


def get_top_level_tikz_nodes(soup: TexNode) -> List[TexNode]:
    """
    Returns a list of tikzpicture nodes that are NOT nested inside other tikzpictures.
    We only want to externalize the outermost container.
    """
    all_tikzs = list(soup.find_all('tikzpicture'))
    top_level = []

    for node in all_tikzs:
        if not isinstance(node, TexNode):
            continue
        # Check ancestors
        is_nested = False
        parent = node.parent
        while parent:
            if parent.name == 'tikzpicture':
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
    soup: TexNode,
) -> List[Tuple[TexNode, TexNode, str]]:
    """
    Returns a list of tikzpicture nodes that are NOT nested inside other tikzpictures.
    We only want to externalize the outermost container.
    """
    top_level_tikz = get_top_level_tikz_nodes(soup)

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
        replacement_block = f'{cmd_str}\n{str(node)}'

        # Parse and replace
        # *TexSoup(...).contents unpacks the list of nodes from the new soup
        node.replace_with(*TexSoup(replacement_block).contents)


def replace_labeled_tikz_nodes(
    soup: TexNode, prefix: str = EXTERNALIZATION_DIR, center: bool = True
):
    labeled_tikz = get_top_level_labeled_tikz_nodes(soup)

    for tikz_node, label_node, label in labeled_tikz:
        fig_name = f'{prefix}{label}'

        cmd_str = f'\\includegraphics{{{fig_name}}}'
        if center:
            cmd_str = f'\\begin{{center}}{cmd_str}\\end{{center}}'
        label_node.delete()
        tikz_node.replace_with(*TexSoup(cmd_str).contents)
