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
from mkdocs_review.annotate import BlockInfo, PageDiff, diff_page
from mkdocs_review.blocks import DEFAULT_SELECTORS
from mkdocs_review.builds import READY, Builder, BuiltSite
from mkdocs_review.site import Page, page_table
from mkdocs_review.snapshots import Snapshot

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


class Comparison:
    """The head against one base snapshot: its page table and page diffs."""

    def __init__(
        self,
        base_sha: str,
        base: BuiltSite,
        head: BuiltSite,
        selectors: Sequence[str],
    ):
        self.base_sha = base_sha
        self.sites = {'base': base, 'head': head}
        self.pages = page_table(base.pages, head.pages, base.sources, head.sources)
        self._by_path = {p.path: p for p in self.pages}
        self._selectors = selectors
        self._diffs: Dict[str, PageDiff] = {}
        self._lock = threading.Lock()

    def page(self, path: str) -> Optional[Page]:
        return self._by_path.get(path)

    def _read(self, side: str, page: Page) -> Optional[str]:
        if not (page.in_head if side == 'head' else page.in_base):
            return None
        return (self.sites[side].root / page.path).read_text(errors='replace')

    def page_diff(self, path: str) -> PageDiff:
        with self._lock:
            cached = self._diffs.get(path)
        if cached is not None:
            return cached
        page = self._by_path[path]
        result = diff_page(
            self._read('base', page), self._read('head', page), self._selectors
        )
        with self._lock:
            self._diffs[path] = result
        return result

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

    def summaries(self) -> List[dict]:
        return [self.page_summary(p) for p in self.pages]


class NotReady(Exception):
    """The requested base snapshot has not been built (yet)."""


@dataclasses.dataclass
class Session:
    label: str
    head_sha: str
    # The base shown by default and the one GitHub comments are anchored
    # against: the merge base for a pull request.
    default_base: str
    snapshots: List[Snapshot]
    builder: Builder
    diff_files: Dict[str, FileDiff]
    drafts: DraftStore
    pr: Optional[dict] = None  # {'number', 'url'} when reviewing a pull request
    # Posts a review payload, returning GitHub's response; None disables submit.
    poster: Optional[Callable[[dict], dict]] = None
    selectors: Sequence[str] = DEFAULT_SELECTORS

    def __post_init__(self):
        self._comparisons: Dict[str, Comparison] = {}
        self._lock = threading.Lock()
        self._shas = {s.sha for s in self.snapshots}
        # Diff every page against a snapshot as soon as it is built, so that
        # switching to it in the UI is instant.
        self.builder.on_ready = lambda sha: (
            self.warm(sha) if sha != self.head_sha else None
        )

    def resolve_base(self, prefix: Optional[str]) -> str:
        """Full sha of a snapshot from (a prefix of) its sha; default if empty."""
        if not prefix:
            return self.default_base
        matches = [sha for sha in self._shas if sha.startswith(prefix)]
        if len(matches) != 1 or matches[0] == self.head_sha:
            raise KeyError(f'unknown base snapshot {prefix!r}')
        return matches[0]

    def comparison(self, base: Optional[str] = None) -> Comparison:
        base = self.resolve_base(base)
        with self._lock:
            found = self._comparisons.get(base)
        if found is not None:
            return found
        sites = self.builder.sites
        if self.builder.status.get(base) != READY or self.head_sha not in sites:
            raise NotReady(base)
        comparison = Comparison(base, sites[base], sites[self.head_sha], self.selectors)
        with self._lock:
            return self._comparisons.setdefault(base, comparison)

    def warm(
        self,
        base: Optional[str] = None,
        progress: Callable[[int, int], None] = lambda done, total: None,
    ):
        comparison = self.comparison(base)
        for i, page in enumerate(comparison.pages):
            comparison.page_diff(page.path)
            progress(i + 1, len(comparison.pages))

    def snapshot_states(self) -> List[dict]:
        result = []
        for snapshot in self.snapshots:
            data = snapshot.to_json()
            data['status'] = self.builder.status.get(snapshot.sha, 'unbuilt')
            data['error'] = self.builder.errors.get(snapshot.sha)
            result.append(data)
        return result

    def state(self, base: Optional[str] = None) -> dict:
        base = self.resolve_base(base)
        try:
            pages = self.comparison(base).summaries()
        except NotReady:
            self.builder.prioritize(base)
            pages = None
        return {
            'label': self.label,
            'base': base,
            'default_base': self.default_base,
            'head': self.head_sha,
            'pr': self.pr,
            'can_submit': self.poster is not None,
            'snapshots': self.snapshot_states(),
            'pages': pages,
        }

    def _draft_comparison(self, draft: dict) -> Comparison:
        # Base-side blocks are numbered within the base they were made on;
        # head-side blocks are the same whichever base is shown.
        base = draft.get('base') if draft['side'] == 'base' else None
        return self.comparison(base or self.default_base)

    def _block(self, draft: dict) -> BlockInfo:
        comparison = self._draft_comparison(draft)
        return comparison.page_diff(draft['page']).blocks(draft['side'])[draft['block']]

    def _source(self, draft: dict) -> Optional[str]:
        page = self._draft_comparison(draft).page(draft['page'])
        return page.source(draft['side']) if page else None

    def anchor(self, draft: dict) -> Optional[Anchor]:
        block = self._block(draft)
        return anchor_comment(
            self.diff_files,
            draft['side'],
            self._source(draft),
            block.text,
            block.words,
            draft.get('selection') or '',
        )

    def anchors(self, drafts: Sequence[dict]) -> List[dict]:
        result = []
        for draft in drafts:
            try:
                anchor = self.anchor(draft)
            except (NotReady, KeyError, IndexError):
                anchor = None
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
            try:
                anchor, quote = self.anchor(draft), self._block(draft).text
            except (NotReady, KeyError, IndexError):
                anchor, quote = None, draft.get('quote', '')
            items.append(
                {
                    'anchor': anchor,
                    'source': self._source(draft) if anchor else None,
                    'page': draft['page'],
                    'quote': quote,
                    'selection': draft.get('selection') or '',
                    'body': draft['body'],
                    # GitHub's base side is the merge base; text from any
                    # other snapshot must be quoted to make sense there.
                    'context': draft['side'] == 'base'
                    and (draft.get('base') or self.default_base) != self.default_base,
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
