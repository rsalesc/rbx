"""Diff two built versions of a page and annotate both for the review UI."""

import collections
import dataclasses
import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from bs4 import BeautifulSoup, NavigableString, Tag

from mkdocs_review.blocks import (
    DEFAULT_SELECTORS,
    block_key,
    extract_blocks,
    find_main,
    own_text,
    own_text_nodes,
)
from mkdocs_review.diff import Row, align, hunks, word_marks

TOKEN = re.compile(r'\w+|[^\w\s]')


@dataclasses.dataclass
class BlockInfo:
    index: int
    tag: str
    text: str
    status: str
    pair: Optional[int] = None
    hunk: Optional[int] = None
    # Words this side added (head) or removed (base); every word of a block
    # that only exists on this side.
    words: List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class PageDiff:
    base_html: Optional[str]
    head_html: Optional[str]
    base_blocks: List[BlockInfo]
    head_blocks: List[BlockInfo]
    hunks: List[dict]
    counts: Dict[str, int]

    def blocks(self, side: str) -> List[BlockInfo]:
        return self.head_blocks if side == 'head' else self.base_blocks


@dataclasses.dataclass
class _Side:
    soup: Optional[BeautifulSoup]
    blocks: List[Tag]

    @classmethod
    def parse(cls, html: Optional[str], selectors: Sequence[str]) -> '_Side':
        if html is None:
            return cls(None, [])
        soup = BeautifulSoup(html, 'html.parser')
        return cls(soup, extract_blocks(find_main(soup, selectors)))


Token = Tuple[int, int, int, str]  # node index, start, end, text


def _tokens(nodes: Sequence[NavigableString]) -> List[Token]:
    return [
        (i, m.start(), m.end(), m.group())
        for i, node in enumerate(nodes)
        for m in TOKEN.finditer(str(node))
    ]


def _wrap(
    soup: BeautifulSoup, nodes, tokens: Sequence[Token], marked: Set[int], cls: str
):
    spans: Dict[int, List[List[int]]] = collections.defaultdict(list)
    for t in sorted(marked):
        node_idx, start, end, _ = tokens[t]
        text = str(nodes[node_idx])
        node_spans = spans[node_idx]
        if (
            node_spans
            and text[node_spans[-1][1] : start].strip() == ''
            and node_spans[-1][2] == t - 1
        ):
            node_spans[-1][1] = end
            node_spans[-1][2] = t
        else:
            node_spans.append([start, end, t])
    for node_idx, node_spans in spans.items():
        node = nodes[node_idx]
        text = str(node)
        pieces = []
        pos = 0
        for start, end, _ in node_spans:
            if start > pos:
                pieces.append(NavigableString(text[pos:start]))
            span = soup.new_tag('span', attrs={'class': cls})
            span.string = text[start:end]
            pieces.append(span)
            pos = end
        if pos < len(text):
            pieces.append(NavigableString(text[pos:]))
        node.replace_with(*pieces)


def _mark(block: Tag, info: BlockInfo):
    block['class'] = list(block.get('class', [])) + ['mr-block', f'mr-{info.status}']
    block['data-mr-block'] = str(info.index)
    if info.pair is not None:
        block['data-mr-pair'] = str(info.pair)
    if info.hunk is not None:
        block['data-mr-hunk'] = str(info.hunk)


def _instrument(soup: BeautifulSoup, side: str):
    head = soup.head or soup
    link = soup.new_tag('link', attrs={'rel': 'stylesheet', 'href': '/_mr/inject.css'})
    head.append(link)
    script = soup.new_tag(
        'script', attrs={'src': '/_mr/inject.js', 'data-side': side, 'defer': ''}
    )
    head.append(script)


def _hunk_of_rows(rows: Sequence[Row]) -> List[Optional[int]]:
    result: List[Optional[int]] = []
    current = -1
    previous_same = True
    for row in rows:
        if row.status == 'same':
            result.append(None)
            previous_same = True
            continue
        if previous_same:
            current += 1
        result.append(current)
        previous_same = False
    return result


def diff_page(
    base_html: Optional[str],
    head_html: Optional[str],
    selectors: Sequence[str] = DEFAULT_SELECTORS,
) -> PageDiff:
    base = _Side.parse(base_html, selectors)
    head = _Side.parse(head_html, selectors)
    rows = align(
        [block_key(b) for b in base.blocks], [block_key(b) for b in head.blocks]
    )
    row_hunks = _hunk_of_rows(rows)

    base_info = [
        BlockInfo(i, b.name, own_text(b), 'same') for i, b in enumerate(base.blocks)
    ]
    head_info = [
        BlockInfo(i, b.name, own_text(b), 'same') for i, b in enumerate(head.blocks)
    ]
    counts = {'added': 0, 'removed': 0, 'changed': 0}
    pair = 0
    for row, hunk in zip(rows, row_hunks, strict=True):
        if row.status != 'same':
            counts[row.status] += 1
        b = base_info[row.base] if row.base is not None else None
        h = head_info[row.head] if row.head is not None else None
        for info in (b, h):
            if info is not None:
                info.status = row.status
                info.hunk = hunk
        if b is not None and h is not None:
            b.pair = h.pair = pair
            pair += 1

        if row.status == 'changed':
            base_nodes = own_text_nodes(base.blocks[row.base])
            head_nodes = own_text_nodes(head.blocks[row.head])
            base_tokens = _tokens(base_nodes)
            head_tokens = _tokens(head_nodes)
            removed, added = word_marks(
                [t[3] for t in base_tokens], [t[3] for t in head_tokens]
            )
            b.words = [base_tokens[i][3] for i in sorted(removed)]
            h.words = [head_tokens[i][3] for i in sorted(added)]
            _wrap(base.soup, base_nodes, base_tokens, removed, 'mr-w-del')
            _wrap(head.soup, head_nodes, head_tokens, added, 'mr-w-add')
        elif row.status == 'added':
            h.words = [t[3] for t in _tokens(own_text_nodes(head.blocks[row.head]))]
        elif row.status == 'removed':
            b.words = [t[3] for t in _tokens(own_text_nodes(base.blocks[row.base]))]

    out = {}
    for name, side, infos in (('base', base, base_info), ('head', head, head_info)):
        if side.soup is None:
            out[name] = None
            continue
        for block, info in zip(side.blocks, infos, strict=True):
            _mark(block, info)
        _instrument(side.soup, name)
        out[name] = str(side.soup)

    return PageDiff(
        base_html=out['base'],
        head_html=out['head'],
        base_blocks=base_info,
        head_blocks=head_info,
        hunks=hunks(rows),
        counts=counts,
    )
