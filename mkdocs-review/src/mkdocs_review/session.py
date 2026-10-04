"""Everything one review needs, independent of how it is served."""

import dataclasses
import json
import pathlib
import threading
import time
from typing import Callable, Dict, List, Optional, Sequence

from mkdocs_review.anchor import (
    Anchor,
    FileDiff,
    anchor_comment,
    build_review,
)
from mkdocs_review.annotate import PageDiff, diff_page
from mkdocs_review.blocks import DEFAULT_SELECTORS
from mkdocs_review.site import Page

SIDES = ('base', 'head')


class DraftStore:
    """Unsent comments, kept in the repository so a restart does not lose them."""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> List[dict]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []

    def save(self, drafts: List[dict]):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            ignore = self.path.parent / '.gitignore'
            if not ignore.exists():
                ignore.write_text('*\n')
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(drafts, indent=2))
            tmp.replace(self.path)

    def archive(self, drafts: List[dict], review: dict):
        """Keep a copy of what was submitted, then start over."""
        stamp = time.strftime('%Y%m%d-%H%M%S')
        archived = self.path.with_name(f'{self.path.stem}.submitted-{stamp}.json')
        archived.write_text(json.dumps({'review': review, 'drafts': drafts}, indent=2))
        self.save([])


@dataclasses.dataclass
class Session:
    label: str
    base_sha: str
    head_sha: str
    sites: Dict[str, pathlib.Path]
    pages: List[Page]
    diff_files: Dict[str, FileDiff]
    drafts: DraftStore
    pr: Optional[dict] = None  # {'number', 'url'} when reviewing a pull request
    # Posts a review payload, returning GitHub's response; None disables submit.
    poster: Optional[Callable[[dict], dict]] = None
    selectors: Sequence[str] = DEFAULT_SELECTORS

    def __post_init__(self):
        self._by_path = {p.path: p for p in self.pages}
        self._diffs: Dict[str, PageDiff] = {}
        self._lock = threading.Lock()

    def page(self, path: str) -> Optional[Page]:
        return self._by_path.get(path)

    def _read(self, side: str, page: Page) -> Optional[str]:
        if not (page.in_head if side == 'head' else page.in_base):
            return None
        return (self.sites[side] / page.path).read_text(errors='replace')

    def page_diff(self, path: str) -> PageDiff:
        with self._lock:
            cached = self._diffs.get(path)
        if cached is not None:
            return cached
        page = self._by_path[path]
        result = diff_page(
            self._read('base', page), self._read('head', page), self.selectors
        )
        with self._lock:
            self._diffs[path] = result
        return result

    def warm(self, progress: Callable[[int, int], None] = lambda done, total: None):
        for i, page in enumerate(self.pages):
            self.page_diff(page.path)
            progress(i + 1, len(self.pages))

    def page_summary(self, page: Page) -> dict:
        diff = self.page_diff(page.path)
        if not page.in_base:
            status = 'added'
        elif not page.in_head:
            status = 'removed'
        elif diff.hunks:
            status = 'modified'
        else:
            status = 'unchanged'
        blocks = diff.head_blocks or diff.base_blocks
        title = next((b.text for b in blocks if b.tag == 'h1'), None)
        return {
            'path': page.path,
            'title': title or page.path,
            'source': page.head_source or page.base_source,
            'status': status,
            'counts': diff.counts,
            'hunks': diff.hunks,
        }

    def state(self) -> dict:
        return {
            'label': self.label,
            'base': self.base_sha,
            'head': self.head_sha,
            'pr': self.pr,
            'can_submit': self.poster is not None,
            'pages': [self.page_summary(p) for p in self.pages],
        }

    def _block(self, draft: dict):
        diff = self.page_diff(draft['page'])
        return diff.blocks(draft['side'])[draft['block']]

    def anchor(self, draft: dict) -> Optional[Anchor]:
        page = self._by_path[draft['page']]
        block = self._block(draft)
        return anchor_comment(
            self.diff_files,
            draft['side'],
            page.source(draft['side']),
            block.text,
            block.words,
            draft.get('selection') or '',
        )

    def anchors(self, drafts: Sequence[dict]) -> List[dict]:
        result = []
        for draft in drafts:
            anchor = self.anchor(draft)
            result.append(
                {
                    'id': draft['id'],
                    'anchor': dataclasses.asdict(anchor) if anchor else None,
                }
            )
        return result

    def review_payload(self, drafts: Sequence[dict], summary: str = '') -> dict:
        items = []
        for draft in drafts:
            page = self._by_path[draft['page']]
            items.append(
                {
                    'anchor': self.anchor(draft),
                    'source': page.source(draft['side']),
                    'page': draft['page'],
                    'quote': self._block(draft).text,
                    'selection': draft.get('selection') or '',
                    'body': draft['body'],
                }
            )
        return build_review(items, self.head_sha, summary)

    def submit(self, summary: str = '') -> dict:
        if self.poster is None:
            raise RuntimeError(
                'submitting is only available when reviewing a pull request'
            )
        drafts = [d for d in self.drafts.load() if d.get('body', '').strip()]
        if not drafts and not summary.strip():
            raise ValueError('nothing to submit')
        payload = self.review_payload(drafts, summary)
        review = self.poster(payload)
        self.drafts.archive(drafts, review)
        return review
