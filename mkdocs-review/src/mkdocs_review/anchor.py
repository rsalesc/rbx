"""Place comments made on rendered text onto lines of the PR's diff.

GitHub only accepts review comments on lines that appear in the diff, and the
rendered text a reviewer clicks has lost its markdown. So a comment is matched
against diff lines by the words they share: first the changed lines of the
page's own source, then its context lines, then the changed lines of every
other file (a page can change because a partial or a macro did). A comment
that matches nothing goes into the review body instead.
"""

import dataclasses
import re
from typing import Dict, Iterable, List, Optional, Sequence

QUOTE_LIMIT = 300

# A line is a candidate only when this share of its words appear in the block.
MIN_CONTAINMENT = 0.6
# Lines of files other than the page's source need this many shared words, so
# a one-word line does not match any block that happens to contain the word.
MIN_FOREIGN_WORDS = 3

_WORD = re.compile(r'\w+')
_HUNK = re.compile(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')


@dataclasses.dataclass(frozen=True)
class DiffLine:
    kind: str  # '+', '-' or ' '
    old: Optional[int]
    new: Optional[int]
    text: str


@dataclasses.dataclass
class FileDiff:
    path: str
    old_path: Optional[str]
    lines: List[DiffLine] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class Anchor:
    path: str
    line: int
    side: str  # RIGHT (head) or LEFT (base)


def _strip_prefix(path: str) -> Optional[str]:
    if path == '/dev/null':
        return None
    return path[2:] if path[:2] in ('a/', 'b/') else path


def parse_unified_diff(text: str) -> Dict[str, FileDiff]:
    files: Dict[str, FileDiff] = {}
    current: Optional[FileDiff] = None
    old_path: Optional[str] = None
    old = new = 0
    in_hunk = False
    for raw in text.splitlines():
        if raw.startswith('diff --git '):
            current, old_path, in_hunk = None, None, False
            continue
        if not in_hunk or current is None:
            if raw.startswith('--- '):
                old_path = _strip_prefix(raw[4:].strip())
            elif raw.startswith('+++ '):
                path = _strip_prefix(raw[4:].strip()) or old_path
                current = files.setdefault(path, FileDiff(path, old_path))
            elif raw.startswith('@@') and current is not None:
                pass
            else:
                continue
        match = _HUNK.match(raw)
        if match and current is not None:
            old, new = int(match.group(1)), int(match.group(2))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith('+'):
            current.lines.append(DiffLine('+', None, new, raw[1:]))
            new += 1
        elif raw.startswith('-'):
            current.lines.append(DiffLine('-', old, None, raw[1:]))
            old += 1
        elif raw.startswith(' ') or raw == '':
            current.lines.append(DiffLine(' ', old, new, raw[1:]))
            old += 1
            new += 1
    return files


def strip_markdown(line: str) -> str:
    text = re.sub(r'\{\{\s*([\w.]+)\s*\}\}', r'\1', line)
    text = re.sub(r'\{[^}]*\}', ' ', text)
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'^\s*(?:[-*+]|\d+\.|#+|>|!!!|\?\?\?\+?)\s*', '', text)
    text = re.sub(r'[*_~`]', '', text)
    return ' '.join(text.split())


def _words(text: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _score(line: str, block_words: set, focus: set, min_shared: int) -> float:
    words = _words(strip_markdown(line))
    if not words:
        return 0.0
    shared = sum(1 for w in words if w in block_words)
    if shared < min_shared or shared / len(words) < MIN_CONTAINMENT:
        return 0.0
    focus_hits = len(set(words) & focus)
    return (shared / len(words)) * min(1.0, shared / 3) + 0.25 * min(focus_hits, 3)


def _best(
    candidates: Iterable[tuple],
    block_words: set,
    focus: set,
    min_shared: int,
) -> Optional[Anchor]:
    best, best_score = None, 0.0
    for anchor, text in candidates:
        score = _score(text, block_words, focus, min_shared)
        if score > best_score:
            best, best_score = anchor, score
    return best


def anchor_comment(
    files: Dict[str, FileDiff],
    side: str,
    source: Optional[str],
    block_text: str,
    words: Sequence[str],
) -> Optional[Anchor]:
    block_words = set(_words(block_text))
    focus = set(_words(' '.join(words)))
    changed_kind, gh_side = ('+', 'RIGHT') if side == 'head' else ('-', 'LEFT')

    def lines(diff: FileDiff, kinds: str):
        for ln in diff.lines:
            if ln.kind in kinds:
                number = ln.new if gh_side == 'RIGHT' else ln.old
                yield Anchor(diff.path, number, gh_side), ln.text

    own = files.get(source) if source else None
    if own is None and source:
        own = next((f for f in files.values() if f.old_path == source), None)
    if own is not None:
        for kinds in (changed_kind, ' '):
            found = _best(lines(own, kinds), block_words, focus, 1)
            if found:
                return found
    others = (
        candidate
        for diff in files.values()
        if diff is not own
        for candidate in lines(diff, changed_kind)
    )
    return _best(others, block_words, focus, min(MIN_FOREIGN_WORDS, len(block_words)))


def _quote(text: str) -> str:
    if len(text) > QUOTE_LIMIT:
        text = text[: QUOTE_LIMIT - 1].rstrip() + '…'
    return '> ' + text


def _with_context(item: dict) -> str:
    return f'On `{item["page"]}`:\n{_quote(item["quote"])}\n\n{item["body"]}'


def build_review(items: Sequence[dict], head_sha: str, summary: str = '') -> dict:
    """GitHub "create a review" payload for anchored and unanchored comments.

    Each item has `anchor` (an Anchor or None), `source` (the page's markdown
    path), `page`, `quote` (the rendered block text) and `body`.
    """
    comments = []
    loose = []
    for item in items:
        anchor = item['anchor']
        if anchor is None:
            loose.append(_with_context(item))
            continue
        body = item['body'] if anchor.path == item['source'] else _with_context(item)
        comments.append(
            {
                'path': anchor.path,
                'line': anchor.line,
                'side': anchor.side,
                'body': body,
            }
        )
    body = '\n\n---\n\n'.join(part for part in [summary.strip(), *loose] if part)
    return {
        'commit_id': head_sha,
        'event': 'COMMENT',
        'body': body,
        'comments': comments,
    }
