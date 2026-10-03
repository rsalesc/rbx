"""The few GitHub calls the tool needs, made through the `gh` CLI."""

import dataclasses
import json
import pathlib
import re
import shutil
import subprocess
from typing import Optional

_PR_URL = re.compile(r'^https?://([^/]+)/([^/]+/[^/]+)/pull/(\d+)')


class GitHubError(RuntimeError):
    pass


@dataclasses.dataclass
class PullRequest:
    number: int
    url: str
    title: str
    base_ref: str
    base_sha: str
    head_sha: str

    @property
    def host(self) -> str:
        return _PR_URL.match(self.url).group(1)

    @property
    def slug(self) -> str:
        return _PR_URL.match(self.url).group(2)


def _gh(repo: pathlib.Path, *args: str, stdin: Optional[str] = None) -> str:
    if shutil.which('gh') is None:
        raise GitHubError('the GitHub CLI (gh) is not installed')
    proc = subprocess.run(
        ['gh', *args], cwd=repo, input=stdin, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise GitHubError(
            f'gh {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}'
        )
    return proc.stdout


def pr_view(repo: pathlib.Path, number: int) -> PullRequest:
    fields = 'number,url,title,baseRefName,baseRefOid,headRefOid'
    data = json.loads(_gh(repo, 'pr', 'view', str(number), '--json', fields))
    return PullRequest(
        number=data['number'],
        url=data['url'],
        title=data['title'],
        base_ref=data['baseRefName'],
        base_sha=data['baseRefOid'],
        head_sha=data['headRefOid'],
    )


def post_review(repo: pathlib.Path, pr: PullRequest, payload: dict) -> dict:
    out = _gh(
        repo,
        'api',
        '--hostname',
        pr.host,
        '--method',
        'POST',
        f'repos/{pr.slug}/pulls/{pr.number}/reviews',
        '--input',
        '-',
        stdin=json.dumps(payload),
    )
    return json.loads(out)
