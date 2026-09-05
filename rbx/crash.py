"""Leave a file behind when rbx dies of an uncaught exception.

Everything useful about a crash -- the traceback, the command that produced it,
the directory it ran in -- otherwise lives only in terminal scrollback, and is
gone by the time anyone gets around to debugging it. `report_crash` writes it
all to a Markdown file with a YAML frontmatter block: parseable at the top,
readable below.

Imports here are deliberately thin, and the heavier ones are deferred into the
functions, because this module is imported by `rbx.box.main` on every single
invocation and does its work on approximately none of them.
"""

import contextlib
import datetime
import json
import os
import pathlib
import platform
import shlex
import sys
import traceback
from typing import Any, Dict, List, Optional

CRASHES_DIR_NAME = 'crashes'
LATEST_NAME = 'latest.md'
PACKAGE_LINK_NAME = 'last-crash.md'

# How many reports to keep around. Old crashes stop being interesting once the
# bug behind them is fixed, and nobody prunes this directory by hand.
MAX_REPORTS = 20

_PACKAGE_MARKERS = ('problem.rbx.yml', 'contest.rbx.yml')


def _yaml_scalar(value: Any) -> str:
    """Render a frontmatter value.

    JSON strings are valid YAML double-quoted scalars, and JSON lists are valid
    YAML flow sequences, so `json.dumps` quotes and escapes everything for free
    -- no value a crash carries can break out of the block.
    """
    return json.dumps(value)


def find_package_dir(cwd: pathlib.Path) -> Optional[pathlib.Path]:
    """The innermost ancestor of `cwd` that looks like an rbx package.

    Deliberately not `package.find_problem`: that one prints, raises
    `typer.Exit` when it finds nothing, and its cache-dir sibling takes locks.
    A crash handler cannot afford any of that.
    """
    for directory in [cwd, *cwd.parents]:
        for marker in _PACKAGE_MARKERS:
            if (directory / marker).is_file():
                return directory
    return None


def _link(link_path: pathlib.Path, target: pathlib.Path) -> None:
    """Point `link_path` at `target`, best-effort.

    Filesystems that refuse symlinks (and Windows without developer mode) just
    do not get the pointer; the report itself is already safely written.
    """
    with contextlib.suppress(OSError, NotImplementedError):
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        link_path.symlink_to(target)


def _prune(crashes_dir: pathlib.Path) -> None:
    reports = sorted(
        (path for path in crashes_dir.glob('*.md') if not path.is_symlink()),
        reverse=True,
    )
    for path in reports[MAX_REPORTS:]:
        with contextlib.suppress(OSError):
            path.unlink()


def _context(exc: BaseException, cwd: pathlib.Path) -> Dict[str, Any]:
    from rbx.__version__ import __version__

    argv: List[str] = list(sys.argv)
    package_dir = find_package_dir(cwd)

    return {
        'rbx_version': __version__,
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'command': shlex.join(argv),
        'cwd': str(cwd),
        'package': str(package_dir) if package_dir is not None else None,
        'exception': type(exc).__name__,
        'message': str(exc),
        'python': platform.python_version(),
        'platform': sys.platform,
        'pid': os.getpid(),
        'argv': argv,
    }


def render_report(exc: BaseException, cwd: pathlib.Path) -> str:
    context = _context(exc, cwd)
    tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    frontmatter = '\n'.join(
        f'{key}: {_yaml_scalar(value)}' for key, value in context.items()
    )
    return (
        f'---\n{frontmatter}\n---\n\n'
        f'# rbx crash\n\n'
        f'`{context["command"]}` in `{context["cwd"]}`\n\n'
        f'## Traceback\n\n'
        f'```\n{tb.rstrip()}\n```\n'
    )


def report_crash(exc: BaseException) -> Optional[pathlib.Path]:
    """Write a crash report and return where it landed.

    Returns `None` if anything at all went wrong. A bug in the crash reporter
    must never mask, replace, or add noise to the crash it exists to record, so
    this swallows everything and the caller prints a path only when it gets one.
    """
    try:
        from rbx import utils
        from rbx.config import CACHE_DIR_NAME

        cwd = pathlib.Path.cwd().absolute()
        report = render_report(exc, cwd)

        crashes_dir = utils.get_app_path() / CRASHES_DIR_NAME
        crashes_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        report_path = crashes_dir / f'{stamp}-{os.getpid()}.md'
        report_path.write_text(report)

        _prune(crashes_dir)
        _link(crashes_dir / LATEST_NAME, report_path)

        # `.rbx` is gitignored by every preset and wiped with the cache, so a
        # pointer dropped in it expires on its own. Only ever a pointer, and
        # only into a cache that already exists -- creating one from a crash
        # handler would be a surprise.
        package_dir = find_package_dir(cwd)
        if package_dir is not None:
            cache_dir = package_dir / CACHE_DIR_NAME
            if cache_dir.is_dir():
                _link(cache_dir / PACKAGE_LINK_NAME, report_path)

        return report_path
    except Exception:
        return None
