"""Align the blocks of two versions of a page, and the words of two blocks."""

import dataclasses
import difflib
import re
from typing import List, Optional, Sequence, Set, Tuple

# Two blocks inside a replaced region are treated as one edited block, rather
# than a removal plus an addition, when their text is at least this similar.
PAIR_SIMILARITY = 0.4


@dataclasses.dataclass(frozen=True)
class Row:
    base: Optional[int]
    head: Optional[int]
    status: str  # same | changed | added | removed


_WORD = re.compile(r'\w+|[^\w\s]')


def _similarity(a: str, b: str) -> float:
    """Word-level similarity of two `tag:text` keys; 0 across different tags."""
    tag_a, _, text_a = a.partition(':')
    tag_b, _, text_b = b.partition(':')
    if tag_a != tag_b:
        return 0.0
    words_a = _WORD.findall(text_a.lower())
    words_b = _WORD.findall(text_b.lower())
    return difflib.SequenceMatcher(None, words_a, words_b, autojunk=False).ratio()


def _pair_region(
    base_keys: Sequence[str],
    head_keys: Sequence[str],
    i1: int,
    i2: int,
    j1: int,
    j2: int,
) -> List[Row]:
    """Pair blocks of a replaced region greedily, keeping both orders."""
    rows: List[Row] = []
    j = j1
    for i in range(i1, i2):
        match = None
        for k in range(j, j2):
            if _similarity(base_keys[i], head_keys[k]) >= PAIR_SIMILARITY:
                match = k
                break
        if match is None:
            rows.append(Row(i, None, 'removed'))
            continue
        rows.extend(Row(None, k, 'added') for k in range(j, match))
        rows.append(Row(i, match, 'changed'))
        j = match + 1
    rows.extend(Row(None, k, 'added') for k in range(j, j2))
    return rows


def align(base_keys: Sequence[str], head_keys: Sequence[str]) -> List[Row]:
    matcher = difflib.SequenceMatcher(None, base_keys, head_keys, autojunk=False)
    rows: List[Row] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            rows.extend(Row(i1 + d, j1 + d, 'same') for d in range(i2 - i1))
        elif tag == 'delete':
            rows.extend(Row(i, None, 'removed') for i in range(i1, i2))
        elif tag == 'insert':
            rows.extend(Row(None, j, 'added') for j in range(j1, j2))
        else:
            rows.extend(_pair_region(base_keys, head_keys, i1, i2, j1, j2))
    return rows


def _anchor(rows: Sequence[Row], start: int, end: int, side: str) -> Optional[int]:
    """First block of `side` in rows[start:end], else the nearest outside it."""
    for row in rows[start:end]:
        if getattr(row, side) is not None:
            return getattr(row, side)
    for row in reversed(rows[:start]):
        if getattr(row, side) is not None:
            return getattr(row, side)
    for row in rows[end:]:
        if getattr(row, side) is not None:
            return getattr(row, side)
    return None


def hunks(rows: Sequence[Row]) -> List[dict]:
    """Group consecutive changed rows; anchor each group on both sides."""
    result: List[dict] = []
    i = 0
    while i < len(rows):
        if rows[i].status == 'same':
            i += 1
            continue
        end = i
        while end < len(rows) and rows[end].status != 'same':
            end += 1
        result.append(
            {
                'id': len(result),
                'base': _anchor(rows, i, end, 'base'),
                'head': _anchor(rows, i, end, 'head'),
            }
        )
        i = end
    return result


def word_marks(
    base_words: Sequence[str], head_words: Sequence[str]
) -> Tuple[Set[int], Set[int]]:
    """Indices of words removed from the base and added to the head."""
    matcher = difflib.SequenceMatcher(None, base_words, head_words, autojunk=False)
    removed: Set[int] = set()
    added: Set[int] = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        removed.update(range(i1, i2))
        added.update(range(j1, j2))
    return removed, added
