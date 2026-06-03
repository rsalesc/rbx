import itertools
import pathlib
from typing import Dict, Optional, Set

from rbx import utils
from rbx.box import package, package_utils
from rbx.box.schema import TestcaseGroup


def manual_group_dir(group: TestcaseGroup) -> pathlib.Path:
    """Return the folder backing a glob-based manual group.

    This is the directory portion of the group's ``testcaseGlob`` (e.g.
    ``tests/manual/corner/*.in`` -> ``tests/manual/corner``).
    """
    assert group.testcaseGlob is not None
    return pathlib.Path(group.testcaseGlob).parent


def existing_testcase_stems(folder: pathlib.Path) -> Set[str]:
    """Return the set of ``*.in`` file stems present in ``folder``.

    Empty when the folder does not exist.
    """
    if not folder.is_dir():
        return set()
    return {path.stem for path in folder.glob('*.in')}


def next_testcase_name(folder: pathlib.Path, used: Optional[Set[str]] = None) -> str:
    """Return the next free zero-padded counter name (no extension).

    Scans ``folder`` for ``*.in`` files and returns the lowest non-colliding
    ``f'{i:03d}'`` stem. Returns ``'000'`` for an empty or nonexistent folder.

    ``used`` adds extra reserved stems on top of the on-disk files, letting
    callers simulate a counter across not-yet-written names.
    """
    existing = existing_testcase_stems(folder)
    if used is not None:
        existing |= used

    for i in itertools.count():
        name = f'{i:03d}'
        if name not in existing:
            return name
    raise AssertionError('unreachable')  # pragma: no cover


def promote_input_to_group(
    input_path: pathlib.Path,
    group: TestcaseGroup,
    *,
    name: Optional[str] = None,
    base_dir: pathlib.Path = pathlib.Path(),
) -> pathlib.Path:
    """Write the bytes of ``input_path`` as a static ``.in`` file into the group.

    The destination folder is ``base_dir / manual_group_dir(group)``. The
    filename stem is ``name`` if provided, else the next free counter name.
    INPUT ONLY -- never writes a ``.out``/``.ans`` file.

    Returns the path of the written file.
    """
    folder = base_dir / manual_group_dir(group)
    folder.mkdir(parents=True, exist_ok=True)

    stem = name if name is not None else next_testcase_name(folder)
    dest = folder / f'{stem}.in'
    dest.write_bytes(input_path.read_bytes())
    return dest


def get_manual_groups_by_name() -> Dict[str, TestcaseGroup]:
    """Return test groups backed by a glob-based manual folder.

    Filters ``package.get_test_groups_by_name()`` down to groups whose
    ``testcaseGlob`` is set and ends with ``.in``.
    """
    res: Dict[str, TestcaseGroup] = {}
    for name, group in package.get_test_groups_by_name().items():
        if group.testcaseGlob is not None and group.testcaseGlob.endswith('.in'):
            res[name] = group
    return res


def create_manual_group(name: str, glob: str) -> TestcaseGroup:
    """Create a new glob-backed manual test group in ``problem.rbx.yml``.

    Creates the folder for ``glob``, appends a ``{'name', 'testcaseGlob'}`` entry
    to the ``testcases`` list (preserving comments via ruyaml), saves it, clears
    the package cache, and returns the created ``TestcaseGroup``.
    """
    pathlib.Path(glob).parent.mkdir(parents=True, exist_ok=True)

    ru, problem_yml = package.get_ruyaml()
    if 'testcases' not in problem_yml:
        problem_yml['testcases'] = []
    problem_yml['testcases'].append(
        {
            'name': name,
            'testcaseGlob': glob,
        }
    )
    dest = package.find_problem_yaml()
    assert dest is not None
    utils.save_ruyaml(dest, ru, problem_yml)
    package_utils.clear_package_cache()

    return TestcaseGroup(name=name, testcaseGlob=glob)
