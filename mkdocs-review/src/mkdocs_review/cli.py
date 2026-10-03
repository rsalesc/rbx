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
from mkdocs_review.gitops import (
    BuildError,
    GitError,
    Target,
    build_site,
    default_cache_root,
    diff_text,
    ls_files,
    repo_root,
    resolve_target,
    show_file,
)
from mkdocs_review.server import serve
from mkdocs_review.session import SIDES, DraftStore, Session
from mkdocs_review.site import (
    list_built_pages,
    load_mkdocs_config,
    page_table,
    source_map,
)


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


def create_session(args: argparse.Namespace, log=_log) -> Session:
    repo_dir = pathlib.Path(args.repo_dir).resolve()
    repo = repo_root(repo_dir)
    # Relative to --repo-dir, then expressed relative to the repository root.
    config = (repo_dir / args.config).resolve().relative_to(repo.resolve()).as_posix()
    target: Target = resolve_target(repo, args.target, args.remote)
    log(f'Reviewing {target.label}: {target.base_sha[:10]} → {target.head_sha[:10]}')

    cache = args.cache_dir or default_cache_root(repo)
    shas = {'base': target.base_sha, 'head': target.head_sha}
    sites = {
        side: build_site(
            repo, shas[side], args.build_cmd, config, cache, args.rebuild, log
        )
        for side in SIDES
    }

    built, sources = {}, {}
    for side in SIDES:
        docs_dir, directory_urls = _docs_prefix(
            config, show_file(repo, shas[side], config)
        )
        sources[side] = source_map(
            ls_files(repo, shas[side], docs_dir), docs_dir, directory_urls
        )
        built[side] = list_built_pages(sites[side])
    pages = page_table(built['base'], built['head'], sources['base'], sources['head'])

    pr = None
    poster = None
    if target.pr is not None:
        pr = {'number': target.pr.number, 'url': target.pr.url}

        def poster(payload, _pr=target.pr):
            return github.post_review(repo, _pr, payload)

    return Session(
        label=target.label,
        base_sha=target.base_sha,
        head_sha=target.head_sha,
        sites=sites,
        pages=pages,
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

    session.warm(progress)
    changed = sum(1 for p in session.state()['pages'] if p['status'] != 'unchanged')
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
