"""The few GitHub calls the tool needs, made through the `gh` CLI."""

import dataclasses
import json
import pathlib
import re
import shutil
import subprocess
from typing import Dict, List, Optional

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


_FORCE_PUSHES = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      timelineItems(itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT], first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { ... on HeadRefForcePushedEvent { beforeCommit { oid } } }
      }
    }
  }
}
"""


def force_pushed_heads(repo: pathlib.Path, pr: PullRequest) -> List[str]:
    """Heads the PR had before each force-push, oldest first."""
    owner, name = pr.slug.split('/', 1)
    heads: List[str] = []
    cursor = None
    while True:
        args = [
            'api',
            'graphql',
            '--hostname',
            pr.host,
            '-f',
            f'query={_FORCE_PUSHES}',
            '-F',
            f'owner={owner}',
            '-F',
            f'name={name}',
            '-F',
            f'number={pr.number}',
        ]
        if cursor:
            args += ['-F', f'cursor={cursor}']
        data = json.loads(_gh(repo, *args))
        items = data['data']['repository']['pullRequest']['timelineItems']
        heads += [
            node['beforeCommit']['oid']
            for node in items['nodes']
            if node and node.get('beforeCommit')
        ]
        if not items['pageInfo']['hasNextPage']:
            return heads
        cursor = items['pageInfo']['endCursor']


def review_commits(repo: pathlib.Path, pr: PullRequest) -> Dict[str, List[str]]:
    """Commit sha -> logins that submitted a review on it."""
    out = _gh(
        repo,
        'api',
        '--hostname',
        pr.host,
        '--paginate',
        f'repos/{pr.slug}/pulls/{pr.number}/reviews',
        '--jq',
        '.[] | [.commit_id, .user.login] | @tsv',
    )
    result: Dict[str, List[str]] = {}
    for line in out.splitlines():
        sha, _, login = line.partition('\t')
        if sha and login and login not in result.setdefault(sha, []):
            result[sha].append(login)
    return result


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
