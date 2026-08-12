"""Interactive front-end for `cz bump`, used by `mise run bump` / `mise run release`.

Adds two things on top of a bare `cz bump`:

- **Increment override**: `--minor` (or `--major` / `--patch` / `-i MINOR`)
  forces the bump size when commitizen's own reading of the commit log would
  pick something else -- e.g. shipping a `feat!` as a minor release instead of
  the major that `BREAKING CHANGE` implies.
- **Confirmation**: shows current -> next (and what commitizen would have
  chosen on its own) and asks before touching the repo, since the bump commits,
  tags and pushes.

Any argument this script does not recognize is forwarded to `cz bump` verbatim.
"""

import argparse
import subprocess
import sys
from typing import List, Optional

INCREMENTS = ['MAJOR', 'MINOR', 'PATCH']


def _cz(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['cz', *args], capture_output=True, text=True, encoding='utf-8'
    )


def _current_version() -> str:
    res = _cz(['version', '-p'])
    if res.returncode != 0:
        print(res.stderr.strip() or res.stdout.strip(), file=sys.stderr)
        sys.exit(res.returncode)
    return res.stdout.strip()


def _next_version(bump_args: List[str]) -> Optional[str]:
    """Ask commitizen what it would bump to, without touching the repo.

    Returns None when commitizen refuses (most often: no bumpable commits since
    the last tag).
    """
    res = _cz(['bump', '--get-next', *bump_args])
    if res.returncode != 0:
        return None
    return res.stdout.strip().splitlines()[-1].strip() if res.stdout.strip() else None


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f'{prompt} [y/N] ').strip().lower()
    except EOFError:
        return False
    return answer in ('y', 'yes')


def _run(cmd: List[str]) -> None:
    print(f'$ {" ".join(cmd)}')
    res = subprocess.run(cmd)
    if res.returncode != 0:
        sys.exit(res.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Bump the version (with confirmation) and push the tag.',
        epilog='Unrecognized arguments are forwarded to `cz bump`.',
    )
    increment = parser.add_mutually_exclusive_group()
    increment.add_argument(
        '-i',
        '--increment',
        choices=INCREMENTS,
        help='force the increment instead of deriving it from the commit log',
    )
    for level in INCREMENTS:
        increment.add_argument(
            f'--{level.lower()}',
            dest='increment',
            action='store_const',
            const=level,
            help=f'shorthand for --increment {level}',
        )
    parser.add_argument(
        '-y',
        '--yes',
        action='store_true',
        help='skip the confirmation prompt',
    )
    parser.add_argument(
        '--no-push',
        action='store_true',
        help='bump locally but do not push the commit and tag',
    )
    args, extra = parser.parse_known_args()

    bump_args = list(extra)
    if args.increment:
        bump_args = ['--increment', args.increment, *bump_args]

    current = _current_version()
    next_version = _next_version(bump_args)
    if next_version is None:
        print(
            'Commitizen found nothing to bump (no new commits since the last tag?).',
            file=sys.stderr,
        )
        sys.exit(1)

    print(f'Current version: {current}')
    print(f'Next version:    {next_version}', flush=True)

    if args.increment:
        # Show what we are overriding, so a forced --minor over a major bump is
        # a deliberate choice rather than a silent one.
        auto = _next_version(list(extra))
        if auto is not None and auto != next_version:
            print(
                f'(commitizen would have bumped to {auto}; forcing {args.increment})',
                flush=True,
            )

    if not args.yes:
        if not sys.stdin.isatty():
            print(
                'Refusing to bump without a terminal to confirm on; pass --yes.',
                file=sys.stderr,
            )
            sys.exit(1)
        action = 'Bump' if args.no_push else 'Bump, tag and push'
        if not _confirm(f'{action} {current} -> {next_version}?'):
            print('Aborted.')
            sys.exit(1)

    _run(['cz', 'bump', *bump_args])
    if not args.no_push:
        _run(['git', 'push'])
        _run(['git', 'push', '--tags'])


if __name__ == '__main__':
    main()
