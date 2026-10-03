"""Split a rendered page into the blocks a reviewer reads and comments on.

A block is the innermost unit of prose: a paragraph, a list item, a heading,
a code block, a table. Containers such as a `blockquote` or a loose `li` whose
text all lives in nested paragraphs are not blocks themselves; their children
are. The same function runs on both sides of a diff, so block order is stable
for a given HTML input.
"""

from typing import Iterator, List, Optional, Sequence

from bs4 import NavigableString, Tag
from bs4.element import Comment, Doctype, ProcessingInstruction

BLOCK_TAGS = frozenset(
    [
        'p',
        'li',
        'h1',
        'h2',
        'h3',
        'h4',
        'h5',
        'h6',
        'pre',
        'table',
        'dt',
        'dd',
        'figcaption',
        'summary',
        'blockquote',
    ]
)
# Blocks whose inner structure is not split any further.
ATOMIC_TAGS = frozenset(['pre', 'table'])
SKIP_TAGS = frozenset(['script', 'style', 'template', 'noscript'])

DEFAULT_SELECTORS = ('article', '[role=main]', 'main', 'body')


def find_main(soup: Tag, selectors: Sequence[str] = DEFAULT_SELECTORS) -> Tag:
    for selector in selectors:
        found = soup.select_one(selector)
        if found is not None:
            return found
    return soup


def own_text_nodes(block: Tag) -> List[NavigableString]:
    """Text nodes that belong to `block` itself, not to a nested block."""
    nodes: List[NavigableString] = []

    def walk(el: Tag):
        for child in el.children:
            if isinstance(child, Tag):
                if child.name in SKIP_TAGS:
                    continue
                if child.name in BLOCK_TAGS and block.name not in ATOMIC_TAGS:
                    continue
                walk(child)
            elif isinstance(child, NavigableString) and not isinstance(
                child, (Comment, Doctype, ProcessingInstruction)
            ):
                nodes.append(child)

    walk(block)
    return nodes


def _own_images(block: Tag) -> Iterator[Tag]:
    def walk(el: Tag):
        for child in el.children:
            if not isinstance(child, Tag) or child.name in SKIP_TAGS:
                continue
            if child.name in BLOCK_TAGS and block.name not in ATOMIC_TAGS:
                continue
            if child.name == 'img':
                yield child
            yield from walk(child)

    yield from walk(block)


def normalize(text: str) -> str:
    return ' '.join(text.split())


def own_text(block: Tag) -> str:
    return normalize(''.join(str(n) for n in own_text_nodes(block)))


def block_key(block: Tag) -> str:
    parts = [own_text(block)]
    parts.extend(f'[img {img.get("src", "")}]' for img in _own_images(block))
    return f'{block.name}:' + ' '.join(p for p in parts if p)


def _is_block(el: Tag) -> bool:
    return bool(own_text(el)) or next(_own_images(el), None) is not None


def extract_blocks(root: Optional[Tag]) -> List[Tag]:
    if root is None:
        return []
    blocks: List[Tag] = []

    def walk(el: Tag):
        for child in el.children:
            if not isinstance(child, Tag) or child.name in SKIP_TAGS:
                continue
            if child.name in BLOCK_TAGS:
                if _is_block(child):
                    blocks.append(child)
                if child.name in ATOMIC_TAGS:
                    continue
            walk(child)

    walk(root)
    return blocks
