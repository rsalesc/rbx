import pathlib
import shutil

import typer

from rbx import console
from rbx.box import (
    cd,
    global_package,
    package,
    visualization,
)
from rbx.box.contest.contest_package import (
    get_contest_root_build_path,
)
from rbx.grading.judge.lock import CacheBusyError


def revalidate_cache(cache_path: pathlib.Path, name: str) -> bool:
    """Clear `cache_path` if it was written by an incompatible rbx version.

    The check and the wipe happen under the cache's exclusive lock, so two rbx
    processes starting at once do not wipe each other's cache, and neither
    wipes one that a third process is already using (issue #700).
    """

    def _on_wait():
        console.console.print(
            f'[warning]Waiting for other [item]rbx[/item] processes to release the {name.lower()}...[/warning]'
        )

    try:
        cleared = global_package.ensure_cache_dir_is_valid(cache_path, on_wait=_on_wait)
    except CacheBusyError:
        console.console.print(
            f'[error]{name} was written by another version of [item]rbx[/item] and cannot be '
            'cleared while other [item]rbx[/item] processes are using it. '
            'Try again once they finish.[/error]'
        )
        raise typer.Exit(1) from None
    if cleared:
        console.console.print(
            f'[warning]{name} was incompatible with the current version of [item]rbx[/item], so it was cleared.[/warning]'
        )
    return cleared


def refuse_incompatible_cache() -> None:
    """Exit rather than clear a cache written by an incompatible rbx.

    Clearing is right for a build the user asked for and wrong for a read-only
    command: the cost lands as a surprise full rebuild, triggered by something
    that was supposed to only look at a file.
    """
    if not cd.is_problem_package():
        return
    fingerprint_file = package.get_problem_cache_path() / 'fingerprint'
    if not fingerprint_file.is_file():
        # Nothing built yet, so there is no cache to lose.
        return
    if fingerprint_file.read_text().strip() == global_package.get_cache_fingerprint():
        return

    console.stderr_console.print(
        '[error]This [item]rbx[/item] uses a different cache format than the one '
        'that built this package.[/error]'
    )
    console.stderr_console.print(
        '[error]Refusing, because touching the cache would clear it and force a '
        'full rebuild.[/error]'
    )
    console.stderr_console.print(
        'Run [item]rbx build[/item] with this [item]rbx[/item] if that is what you want.'
    )
    raise typer.Exit(visualization.EXIT_CACHE_SKEW)


def _clean_dir(path: pathlib.Path):
    if not path.exists():
        return
    console.console.print(f'Cleaning [item]{path}[/item]...')
    shutil.rmtree(path, ignore_errors=True)


def clean_cache_dir(cache_path: pathlib.Path, name: str):
    """Empty a cache directory, waiting for other rbx processes to let go of it.

    The directory and its lock files stay in place: deleting them would pull the
    ground from under any process that still has the cache open, and would break
    mutual exclusion for every process that comes after (issue #700).
    """
    if not cache_path.is_dir():
        return
    console.console.print(f'Cleaning [item]{cache_path}[/item]...')

    def _on_wait():
        console.console.print(
            f'[warning]Waiting for other [item]rbx[/item] processes to release the {name.lower()}...[/warning]'
        )

    try:
        global_package.clear_cache_dir(cache_path, on_wait=_on_wait)
    except CacheBusyError:
        console.console.print(
            f'[error]{name} is being used by another [item]rbx[/item] process and was not cleared. '
            'Try again once it finishes.[/error]'
        )
        raise typer.Exit(1) from None


@cd.within_closest_package
def clean_build_dirs():
    _clean_dir(pathlib.Path('build'))
    if cd.is_problem_package():
        _clean_dir(package.get_build_path())
    if cd.is_contest_package():
        # Deliberately unscoped: clean wipes every variant's subtree, so its
        # blast radius does not depend on whether -C was passed. It also works
        # in an unselected dispatcher, where the scoped accessor would die.
        _clean_dir(get_contest_root_build_path())


@cd.within_closest_package
def clear_package_cache():
    console.console.print('Cleaning cache and build directories...')

    clean_build_dirs()
    if cd.is_problem_package():
        clean_cache_dir(package.get_problem_cache_path(), 'Cache')

    if cd.is_contest_package():
        console.console.print(
            '[warning]If you want to clear the problem caches of all problems in the contest, '
            'run [item]rbx contest each clean[/item].[/warning]'
        )
