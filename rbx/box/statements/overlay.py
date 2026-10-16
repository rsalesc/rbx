"""Statements v2 overlay stager (design §6.1/§6.2, issue #560).

Mirrors the *directory subtree containing a statement `file`* into a build
overlay, plus the contest chrome subtree, so that every asset resolves by a
plain relative path. The only LaTeX construct the engine injects elsewhere is
``\\subimport`` — this module never parses or rewrites TeX, it only places files
on disk (design §6.5).

Two layouts:

- **Standalone** (`rbx st b`, §6.1): a single *merged* root — contest chrome +
  the problem statement-dir subtree. Because there is exactly one problem and
  one contest, the only collision risk is a problem file vs a chrome file with
  the same relative path; we detect and error on it.
- **Join** (`rbx contest st b`, §6.2): contest chrome at the shared root; each
  problem isolated under ``.problems/<SHORT>/`` and ``\\subimport``-ed, so two
  problems can both ship ``imgs/fig.png`` with zero collision.
"""

import contextlib
import contextvars
import pathlib
import shutil
from typing import Dict, Iterator, List, Optional

from rbx.box.exception import RbxException

PROBLEMS_DIRNAME = '.problems'

# What pdflatex leaves behind for the next pass to read: cross-references, the
# hyperref outline, the tables of contents/figures/tables. The job is always
# `statement` (`latex.Latex.build_pdf`), run from the overlay root.
LATEX_AUX_FILES = tuple(
    f'statement{suffix}' for suffix in ('.aux', '.out', '.toc', '.lof', '.lot')
)

_keep_latex_aux: contextvars.ContextVar[bool] = contextvars.ContextVar(
    'keep_latex_aux', default=False
)


@contextlib.contextmanager
def incremental(enabled: bool = True) -> Iterator[None]:
    """Within this block, :func:`fresh_root` carries the previous build's LaTeX
    auxiliary files into the new overlay (#920).

    An overlay is wiped on every build, and with it the ``.aux``/``.out`` the
    last compile wrote, so a document using hyperref always needs a second
    pdflatex pass to settle its outline -- about a third of a warm build. With
    last build's files in place, one pass usually suffices, and the rerun loop
    in ``render.compile_pdf`` still catches a real change.

    Opt-in (``--incremental``), and never entered by a packager: a published
    PDF is always built from a clean overlay."""
    token = _keep_latex_aux.set(enabled)
    try:
        yield
    finally:
        _keep_latex_aux.reset(token)


def fresh_root(root: pathlib.Path) -> pathlib.Path:
    """Wipe and recreate the overlay ``root``, keeping its LaTeX auxiliary files
    when inside :func:`incremental`. Returns ``root``."""
    kept: Dict[str, bytes] = {}
    if _keep_latex_aux.get():
        for name in LATEX_AUX_FILES:
            path = root / name
            if path.is_file():
                kept[name] = path.read_bytes()
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    for name, data in kept.items():
        (root / name).write_bytes(data)
    return root


def clear_latex_aux(root: pathlib.Path) -> bool:
    """Delete the LaTeX auxiliary files in ``root``. Returns whether any existed."""
    found = False
    for name in LATEX_AUX_FILES:
        path = root / name
        if path.is_file():
            path.unlink()
            found = True
    return found


class OverlayCollisionError(RbxException):
    pass


def _iter_files(src_dir: pathlib.Path) -> List[pathlib.Path]:
    """Relative paths of every regular file under ``src_dir`` (recursive)."""
    if not src_dir.is_dir():
        return []
    return sorted(p.relative_to(src_dir) for p in src_dir.rglob('*') if p.is_file())


def mirror_tree(src_dir: pathlib.Path, dest_dir: pathlib.Path) -> List[pathlib.Path]:
    """Copy every file under ``src_dir`` into ``dest_dir``, preserving relative
    structure. A missing ``src_dir`` is a no-op. Returns the relative paths
    copied.
    """
    relatives = _iter_files(src_dir)
    if not relatives and not src_dir.is_dir():
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    for rel in relatives:
        out = dest_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_dir / rel, out)
    return relatives


def merge_tree(
    src_dir: pathlib.Path,
    dest_dir: pathlib.Path,
    *,
    occupied: List[pathlib.Path],
    src_label: str,
    occupied_label: str,
) -> List[pathlib.Path]:
    """Mirror ``src_dir`` into ``dest_dir`` but error if any relative path is
    already present in ``occupied`` (a real collision in the merged overlay)."""
    relatives = _iter_files(src_dir)
    occupied_set = set(occupied)
    collisions = sorted(rel for rel in relatives if rel in occupied_set)
    if collisions:
        with OverlayCollisionError() as err:
            err.print(
                f'[error]Asset name collision while merging the {src_label} into '
                f'the {occupied_label} overlay:[/error]'
            )
            for rel in collisions:
                err.print(f'[error]  - [item]{rel}[/item][/error]')
            err.print(
                '[warning]Rename one of the conflicting files so the standalone '
                'overlay stays unambiguous.[/warning]'
            )
    mirror_tree(src_dir, dest_dir)
    return relatives


def stage_standalone_overlay(
    dest_root: pathlib.Path,
    *,
    chrome_dir: Optional[pathlib.Path],
    problem_dir: pathlib.Path,
) -> None:
    """Build the merged standalone overlay (§6.1): the problem statement-dir
    subtree plus the contest chrome subtree in one root, erroring on any
    name collision between the two."""
    problem_files = mirror_tree(problem_dir, dest_root)
    if chrome_dir is not None:
        merge_tree(
            chrome_dir,
            dest_root,
            occupied=problem_files,
            src_label='contest chrome',
            occupied_label='problem',
        )


def problem_overlay_dir(dest_root: pathlib.Path, short_name: str) -> pathlib.Path:
    """The isolated ``\\subimport`` base for a problem in the contest join."""
    return dest_root / PROBLEMS_DIRNAME / short_name


def stage_join_problem(
    dest_root: pathlib.Path,
    problem_dir: pathlib.Path,
    short_name: str,
) -> pathlib.Path:
    """Mirror a problem's statement-dir subtree into its isolated join folder
    ``.problems/<SHORT>/`` (§6.2). Returns that folder."""
    target = problem_overlay_dir(dest_root, short_name)
    mirror_tree(problem_dir, target)
    return target


def stage_chrome(dest_root: pathlib.Path, chrome_dir: Optional[pathlib.Path]) -> None:
    """Overlay the contest chrome subtree at the shared overlay root (§6.2)."""
    if chrome_dir is not None:
        mirror_tree(chrome_dir, dest_root)
