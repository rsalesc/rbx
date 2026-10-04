"""mkdocs-review command line."""

import argparse
import pathlib
import posixpath
import sys
import time
import webbrowser
from typing import List, Optional

from mkdocs_review import github
from mkdocs_review.anchor import parse_unified_diff
from mkdocs_review.blocks import DEFAULT_SELECTORS
from mkdocs_review.builds import Builder, BuiltSite
from mkdocs_review.gitops import (
    BuildError,
    GitError,
    Target,
    build_site,
    default_cache_root,
    diff_text,
    fetch_commits,
    ls_files,
    repo_root,
    resolve_target,
    show_file,
)
from mkdocs_review.server import serve
from mkdocs_review.session import DraftStore, Session
from mkdocs_review.site import list_built_pages, load_mkdocs_config, source_map
from mkdocs_review.snapshots import Snapshot, list_snapshots


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='mkdocs-review',
        description=(
            'Build both sides of a docs change with mkdocs, show them side by '
            'side with the differences highlighted, and send your comments to '
            'the pull request as one review.'
        ),
    )
    parser.add_argument(
        'target',
        help=(
            'a pull request number (123 or #123), a range (A..B compares A with B; '
            'A...B compares their merge base with B), or a ref (same as REF...HEAD)'
        ),
    )
    parser.add_argument(
        '--repo-dir', default='.', help='repository to review (default: .)'
    )
    parser.add_argument(
        '-f',
        '--config',
        default='mkdocs.yml',
        help='mkdocs config file (default: mkdocs.yml)',
    )
    parser.add_argument(
        '--build-cmd',
        default='mkdocs build',
        help=(
            'command that builds the docs, run at the root of each side '
            "(default: 'mkdocs build'). '--site-dir DIR' is appended, unless the "
            'command uses the {site_dir} placeholder.'
        ),
    )
    parser.add_argument(
        '--content-selector',
        action='append',
        help=(
            'CSS selector of the main content to diff; repeat to give fallbacks '
            f'(default: {", ".join(DEFAULT_SELECTORS)})'
        ),
    )
    parser.add_argument(
        '--remote', default='origin', help='remote to fetch pull requests from'
    )
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument(
        '--port', type=int, default=0, help='port to serve on (default: any free port)'
    )
    parser.add_argument('--no-open', action='store_true', help='do not open a browser')
    parser.add_argument('--rebuild', action='store_true', help='ignore cached builds')
    parser.add_argument(
        '--no-prebuild',
        dest='prebuild',
        action='store_false',
        help=(
            'build earlier versions only when picked as the base, instead of '
            'all of them in the background'
        ),
    )
    parser.add_argument(
        '--cache-dir', type=pathlib.Path, help='where builds are cached'
    )
    return parser


def _log(message: str):
    print(f'mkdocs-review: {message}', file=sys.stderr, flush=True)


def _docs_prefix(config_path: str, config_text: Optional[str]) -> tuple:
    config = load_mkdocs_config(config_text or '')
    docs_dir = posixpath.normpath(
        posixpath.join(posixpath.dirname(config_path), config['docs_dir'])
    )
    return docs_dir, config['use_directory_urls']


def _earlier_heads(repo, target: Target, remote: str, log) -> tuple:
    """Force-pushed heads (fetched locally) and reviewed commits of a PR."""
    if target.pr is None:
        return [], {}
    try:
        lost = github.force_pushed_heads(repo, target.pr)
        reviews = github.review_commits(repo, target.pr)
    except github.GitHubError as err:
        log(f'Could not list earlier versions of the PR: {err}')
        return [], {}
    heads = fetch_commits(repo, remote, lost)
    if len(heads) < len(lost):
        log(f'{len(lost) - len(heads)} force-pushed head(s) are gone from GitHub')
    reviewed = fetch_commits(repo, remote, list(reviews))
    return heads + reviewed, reviews


def _prebuild_order(snapshots: List[Snapshot], skip: set) -> List[str]:
    """Reviewed snapshots first (the usual "what changed since"), then newest."""
    rest = [s for s in reversed(snapshots) if s.sha not in skip]
    return [s.sha for s in sorted(rest, key=lambda s: not s.notes)]


def create_session(args: argparse.Namespace, log=_log) -> Session:
    repo_dir = pathlib.Path(args.repo_dir).resolve()
    repo = repo_root(repo_dir)
    # Relative to --repo-dir, then expressed relative to the repository root.
    config = (repo_dir / args.config).resolve().relative_to(repo.resolve()).as_posix()
    target: Target = resolve_target(repo, args.target, args.remote)
    log(f'Reviewing {target.label}: {target.base_sha[:10]} → {target.head_sha[:10]}')

    cache = args.cache_dir or default_cache_root(repo)

    def build(sha: str) -> BuiltSite:
        root = build_site(repo, sha, args.build_cmd, config, cache, args.rebuild, log)
        docs_dir, directory_urls = _docs_prefix(config, show_file(repo, sha, config))
        sources = source_map(ls_files(repo, sha, docs_dir), docs_dir, directory_urls)
        return BuiltSite(root, list_built_pages(root), sources)

    builder = Builder(build, log)
    for sha in (target.base_sha, target.head_sha):
        builder.add(sha, build(sha))

    extra, reviews = _earlier_heads(repo, target, args.remote, log)
    snapshots = list_snapshots(repo, target.base_sha, target.head_sha, extra, reviews)
    if len(snapshots) > 2:
        log(f'{len(snapshots) - 2} earlier version(s) available as bases')
        if args.prebuild:
            builder.enqueue(
                _prebuild_order(snapshots, {target.base_sha, target.head_sha})
            )

    pr = None
    poster = None
    if target.pr is not None:
        pr = {'number': target.pr.number, 'url': target.pr.url}

        def poster(payload, _pr=target.pr):
            return github.post_review(repo, _pr, payload)

    return Session(
        label=target.label,
        head_sha=target.head_sha,
        default_base=target.base_sha,
        snapshots=snapshots,
        builder=builder,
        diff_files=parse_unified_diff(
            diff_text(repo, target.base_sha, target.head_sha)
        ),
        drafts=DraftStore(repo / '.mkdocs-review' / f'{target.key}.json'),
        pr=pr,
        poster=poster,
        selectors=args.content_selector or DEFAULT_SELECTORS,
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        session = create_session(args)
    except BuildError as err:
        _log(str(err))
        print(err.tail(), file=sys.stderr)
        return 1
    except (GitError, github.GitHubError) as err:
        _log(str(err))
        return 1

    def progress(done, total):
        if done == total or done % 20 == 0:
            _log(f'Diffed {done}/{total} pages')

    session.warm(progress=progress)
    pages = session.comparison().summaries()
    changed = sum(1 for p in pages if p['status'] != 'unchanged')
    try:
        server = serve(session, args.host, args.port)
    except OSError as err:
        _log(
            f'cannot serve on {args.host}:{args.port}: {err.strerror}; try another --port'
        )
        return 1
    url = f'http://{args.host}:{server.server_address[1]}/'
    _log(f'{changed} page(s) changed. Review at {url} (Ctrl+C to stop)')
    if not args.no_open:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
