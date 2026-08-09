"""Publish versioned JSON schemas to the schemas repo.

One code path for both release entrypoints:

- **Local** (`mise run release` / `mise run publish-schemas`): clones or updates
  a cached checkout of the schemas repo, builds the tree, commits and pushes.
- **CI** (`.github/workflows/release.yml`): passes `--dir` pointing at a
  checkout that `actions/checkout` already made, so nothing is cloned.

The version defaults to the installed rbx version, which is what `cz bump`
has just written to `rbx/__version__.py` -- so running this right after a bump
publishes schemas for exactly the version being released.

Publishing is idempotent: re-running for a version whose schemas are unchanged
commits nothing, so it is safe for the local run and CI to both fire.
"""

import argparse
import pathlib
import subprocess
import sys

from rbx import utils
from rbx.box.schema_publish import build_site

# HTTPS by default, to match how rbx itself is cloned and so the usual git
# credential helper applies. Pass `--repo git@github.com:...` for SSH.
DEFAULT_REPO = 'https://github.com/rsalesc/rbx-schemas.git'
DEFAULT_CACHE_DIR = pathlib.Path.home() / '.cache' / 'rbx' / 'schemas-site'


def _run(args, cwd: pathlib.Path, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return (result.stdout or '').strip()


def _clone_or_update(repo: str, into: pathlib.Path) -> None:
    if (into / '.git').is_dir():
        print(f'Updating {into}...')
        _run(['git', 'fetch', '--prune', 'origin'], cwd=into)
        # The schemas repo is machine-managed; a local divergence is never
        # something we want to merge, so match the remote exactly.
        branch = _run(
            ['git', 'symbolic-ref', '--short', 'HEAD'], cwd=into, capture=True
        )
        _run(['git', 'reset', '--hard', f'origin/{branch}'], cwd=into)
        return

    into.parent.mkdir(parents=True, exist_ok=True)
    print(f'Cloning {repo} into {into}...')
    _run(['git', 'clone', repo, str(into)], cwd=into.parent)


def _assert_is_schemas_site(site: pathlib.Path) -> None:
    """Refuse to publish into anything but a schemas checkout.

    This writes generated files and runs `git add -A` + `git push`, so pointing
    it at the wrong directory -- an empty `--dir`, which resolves to the current
    directory, or a stray path -- would sweep unrelated work into a commit and
    push it. Bail out loudly instead.
    """
    resolved = site.resolve()
    if not resolved.is_dir():
        raise SystemExit(f'--dir {site} is not a directory.')
    if not (resolved / '.git').exists():
        raise SystemExit(f'--dir {site} is not a git checkout.')

    # A source checkout of rbx (or any project) is never a valid target.
    for marker in ('pyproject.toml', 'mise.toml', 'rbx', 'scripts'):
        if (resolved / marker).exists():
            raise SystemExit(
                f'--dir {site} looks like a source checkout (found {marker}), '
                'not the schemas site. Refusing to publish into it.'
            )


def _commit_and_push(site: pathlib.Path, version: str, push: bool) -> bool:
    _run(['git', 'add', '-A'], cwd=site)
    staged = subprocess.run(
        ['git', 'diff', '--staged', '--quiet'], cwd=str(site)
    ).returncode
    if staged == 0:
        print(f'No schema changes for {version}; nothing to publish.')
        return False

    _run(['git', 'commit', '-m', f'chore: publish schemas for {version}'], cwd=site)
    if push:
        # `-u origin HEAD` so the very first publish works too, when the freshly
        # cloned repo has no upstream for its unborn default branch.
        _run(['git', 'push', '-u', 'origin', 'HEAD'], cwd=site)
        print(f'Published schemas for {version}.')
    else:
        print(f'Committed schemas for {version} (not pushed).')
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--version',
        default=None,
        help='Version to publish. Defaults to the installed rbx version.',
    )
    parser.add_argument(
        '--dir',
        type=pathlib.Path,
        default=None,
        help='Existing checkout of the schemas repo. Skips cloning (used by CI).',
    )
    parser.add_argument('--repo', default=DEFAULT_REPO, help='Schemas repo remote.')
    parser.add_argument(
        '--no-push', action='store_true', help='Commit locally but do not push.'
    )
    parser.add_argument(
        '--allow-prerelease',
        action='store_true',
        help='Publish even for a prerelease version (normally skipped).',
    )
    args = parser.parse_args(argv)

    version = args.version or utils.get_version()
    semver = utils.get_semver(version)
    if semver.is_prerelease and not args.allow_prerelease:
        # A prerelease must not expose a schema for a minor nobody can install.
        print(f'{version} is a prerelease; skipping schema publish.')
        return 0

    site = args.dir
    if site is None:
        site = DEFAULT_CACHE_DIR
        _clone_or_update(args.repo, site)
    elif not str(site):
        raise SystemExit('--dir was empty; pass a real path or omit it to clone.')
    _assert_is_schemas_site(site)

    build_site(site, version)
    _commit_and_push(site, version, push=not args.no_push)
    return 0


if __name__ == '__main__':
    sys.exit(main())
