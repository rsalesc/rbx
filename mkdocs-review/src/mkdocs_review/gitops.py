"""git plumbing: resolve what to compare, and build each side in isolation."""

import dataclasses
import hashlib
import os
import pathlib
import shlex
import shutil
import subprocess
from typing import Callable, List, Optional

from mkdocs_review import github


class GitError(RuntimeError):
    pass


class BuildError(RuntimeError):
    def __init__(self, sha: str, log_path: pathlib.Path):
        self.sha = sha
        self.log_path = log_path
        super().__init__(f'mkdocs build failed for {sha[:10]}; log: {log_path}')

    def tail(self, lines: int = 30) -> str:
        try:
            return '\n'.join(
                self.log_path.read_text(errors='replace').splitlines()[-lines:]
            )
        except OSError:
            return ''


def git(repo: pathlib.Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ['git', *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise GitError(f'git {" ".join(args)} failed:\n{proc.stderr.strip()}')
    return proc.stdout


def repo_root(path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(git(path, 'rev-parse', '--show-toplevel').strip())


def rev(repo: pathlib.Path, ref: str) -> str:
    return git(repo, 'rev-parse', '--verify', f'{ref}^{{commit}}').strip()


def merge_base(repo: pathlib.Path, a: str, b: str) -> str:
    return git(repo, 'merge-base', a, b).strip()


@dataclasses.dataclass
class Target:
    base_sha: str
    head_sha: str
    label: str
    key: str
    pr: Optional[github.PullRequest] = None


def resolve_range(repo: pathlib.Path, spec: str) -> Target:
    """`A..B` compares A with B; `A...B` and a bare `A` (= `A...HEAD`) compare
    the merge base with B, like a pull request would."""
    if '...' in spec:
        a, b = spec.split('...', 1)
        head = rev(repo, b or 'HEAD')
        base = merge_base(repo, rev(repo, a), head)
    elif '..' in spec:
        a, b = spec.split('..', 1)
        base, head = rev(repo, a), rev(repo, b or 'HEAD')
    else:
        head = rev(repo, 'HEAD')
        base = merge_base(repo, rev(repo, spec), head)
    return Target(base, head, spec, f'range-{base[:10]}-{head[:10]}')


def resolve_pr(repo: pathlib.Path, number: int, remote: str = 'origin') -> Target:
    pr = github.pr_view(repo, number)
    git(
        repo,
        'fetch',
        '--no-tags',
        remote,
        f'refs/pull/{number}/head',
        f'refs/heads/{pr.base_ref}',
    )
    base = merge_base(repo, rev(repo, pr.base_sha), rev(repo, pr.head_sha))
    return Target(base, pr.head_sha, f'#{number} {pr.title}', f'pr-{number}', pr)


def resolve_target(repo: pathlib.Path, spec: str, remote: str = 'origin') -> Target:
    number = spec.lstrip('#')
    if number.isdigit():
        return resolve_pr(repo, int(number), remote)
    return resolve_range(repo, spec)


def fetch_commits(repo: pathlib.Path, remote: str, shas: List[str]) -> List[str]:
    """Fetch commits by sha (e.g. heads lost to a force-push); returns those
    that are now available locally."""
    available = []
    for sha in shas:
        if not _has_commit(repo, sha):
            git(repo, 'fetch', '--no-tags', remote, sha, check=False)
        if _has_commit(repo, sha):
            available.append(sha)
    return available


def _has_commit(repo: pathlib.Path, sha: str) -> bool:
    proc = subprocess.run(
        ['git', 'cat-file', '-e', f'{sha}^{{commit}}'], cwd=repo, capture_output=True
    )
    return proc.returncode == 0


def show_file(repo: pathlib.Path, sha: str, path: str) -> Optional[str]:
    proc = subprocess.run(
        ['git', 'show', f'{sha}:{path}'], cwd=repo, capture_output=True, text=True
    )
    return proc.stdout if proc.returncode == 0 else None


def ls_files(repo: pathlib.Path, sha: str, prefix: str) -> List[str]:
    out = git(repo, 'ls-tree', '-r', '--name-only', sha, '--', prefix.rstrip('/') + '/')
    return out.splitlines()


def diff_text(repo: pathlib.Path, base: str, head: str) -> str:
    return git(repo, 'diff', '--no-color', '--no-ext-diff', '-M', base, head)


def default_cache_root(repo: pathlib.Path) -> pathlib.Path:
    base = os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache')
    digest = hashlib.sha256(str(repo).encode()).hexdigest()[:8]
    return pathlib.Path(base) / 'mkdocs-review' / f'{repo.name}-{digest}'


def build_command(template: str, config: str, site_dir: pathlib.Path) -> str:
    """`{site_dir}`/`{config}` placeholders, else append the flags mkdocs needs."""
    if '{site_dir}' in template:
        return template.format(
            site_dir=shlex.quote(str(site_dir)), config=shlex.quote(config)
        )
    command = template
    if config != 'mkdocs.yml':
        command += f' -f {shlex.quote(config)}'
    return command + f' --site-dir {shlex.quote(str(site_dir))}'


def build_site(
    repo: pathlib.Path,
    sha: str,
    template: str,
    config: str,
    cache_root: pathlib.Path,
    rebuild: bool = False,
    log: Callable[[str], None] = print,
) -> pathlib.Path:
    """Build the docs at `sha` in a throwaway worktree; cached by sha + command."""
    command_id = hashlib.sha256(f'{template}\0{config}'.encode()).hexdigest()[:8]
    out = cache_root / f'{sha[:12]}-{command_id}'
    site = out / 'site'
    done = out / '.complete'
    if done.exists() and not rebuild:
        log(f'Using cached build of {sha[:10]}')
        return site
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    worktree = out / 'src'
    log_path = out / 'build.log'
    git(repo, 'worktree', 'add', '--detach', str(worktree), sha)
    try:
        command = build_command(template, config, site)
        log(f'Building {sha[:10]}: {command}')
        with log_path.open('w') as fp:
            proc = subprocess.run(
                command, shell=True, cwd=worktree, stdout=fp, stderr=subprocess.STDOUT
            )
        if proc.returncode != 0:
            raise BuildError(sha, log_path)
    finally:
        git(repo, 'worktree', 'remove', '--force', str(worktree), check=False)
    done.touch()
    return site
