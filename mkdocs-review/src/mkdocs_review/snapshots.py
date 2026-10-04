"""The states a change went through, any of which can serve as the base.

A review always shows the latest head on the right. On the left it can show
the merge base (what the PR changes as a whole), any earlier commit of the
branch (what changed since then), or a head that was later force-pushed away
(what changed since that version, e.g. since the last review).
"""

import dataclasses
import pathlib
from typing import Dict, Iterable, List, Sequence, Tuple

from mkdocs_review.gitops import git


@dataclasses.dataclass
class Snapshot:
    sha: str
    kind: str  # base | commit | force-push | head
    subject: str
    time: int  # committer timestamp
    when: str  # human-readable, e.g. '3 days ago'
    notes: List[str] = dataclasses.field(default_factory=list)

    def to_json(self) -> dict:
        return dataclasses.asdict(self)


def _describe(repo: pathlib.Path, sha: str) -> Tuple[str, int, str]:
    out = git(repo, 'show', '-s', '--format=%s%x00%ct%x00%cr', sha)
    subject, timestamp, when = out.rstrip('\n').split('\x00')
    return subject, int(timestamp), when


def list_snapshots(
    repo: pathlib.Path,
    base_sha: str,
    head_sha: str,
    force_pushed: Iterable[str] = (),
    reviews: Dict[str, Sequence[str]] = None,
) -> List[Snapshot]:
    """Base first, head last, everything else in commit-time order.

    `force_pushed` are earlier heads that must already be present locally;
    `reviews` maps a sha to the logins that submitted a review on it.
    """
    reviews = reviews or {}
    commits = git(
        repo, 'rev-list', '--reverse', '--first-parent', f'{base_sha}..{head_sha}'
    ).split()
    middle = {sha: 'commit' for sha in commits if sha != head_sha}
    for sha in force_pushed:
        if sha not in middle and sha not in (base_sha, head_sha):
            middle[sha] = 'force-push'

    def snapshot(sha: str, kind: str) -> Snapshot:
        subject, timestamp, when = _describe(repo, sha)
        notes = [f'reviewed by {login}' for login in reviews.get(sha, ())]
        return Snapshot(sha, kind, subject, timestamp, when, notes)

    ordered = sorted(
        (snapshot(sha, kind) for sha, kind in middle.items()), key=lambda s: s.time
    )
    return [snapshot(base_sha, 'base'), *ordered, snapshot(head_sha, 'head')]
