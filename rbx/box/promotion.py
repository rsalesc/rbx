import itertools
import pathlib
from typing import Dict, Iterable, Optional, Set

from rbx import utils
from rbx.box import package, package_utils
from rbx.box.generation_schema import GenerationTestcaseEntry
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


def script_format_by_path() -> Dict[pathlib.Path, str]:
    """Map each generator-script path in the package to its format ('rbx'/'box')."""
    res: Dict[pathlib.Path, str] = {}
    for group in package.get_test_groups_by_name().values():
        gs = group.generatorScript
        if gs is not None:
            res[gs.path] = gs.format
    return res


def is_promotable(
    entry: GenerationTestcaseEntry, script_formats: Dict[pathlib.Path, str]
) -> bool:
    """True iff entry came from an rbx generator script and is not a @copy."""
    md = entry.metadata
    if md.generator_script is None or md.copied_from is not None:
        return False
    return script_formats.get(md.generator_script.path) == 'rbx'


def remove_script_entries(entries: Iterable[GenerationTestcaseEntry]) -> None:
    """Delete each entry's originating statement from its rbx generator script."""
    from rbx.box import generator_script_handlers as gsh

    by_path: Dict[pathlib.Path, Set[int]] = {}
    for entry in entries:
        gse = entry.metadata.generator_script
        assert gse is not None
        by_path.setdefault(gse.path, set()).add(gse.line)

    groups = package.get_test_groups_by_name()
    script_entry_by_path = {
        g.generatorScript.path: g.generatorScript
        for g in groups.values()
        if g.generatorScript is not None
    }

    for path, start_lines in by_path.items():
        script_entry = script_entry_by_path[path]
        handler = gsh.get_generator_script_handler(
            path.read_text(),
            gsh.GeneratorScriptHandlerParams(script_entry),
        )
        handler.remove(start_lines)
        new_text = (
            handler.script if handler.script.endswith('\n') else handler.script + '\n'
        )
        path.write_text(new_text)

    package_utils.clear_package_cache()


async def create_manual_group_interactively() -> Optional[TestcaseGroup]:
    """Interactively prompt for a new manual group's name and glob, then create it.

    Prompts for the group NAME and then the GLOB path (e.g.
    ``tests/manual/corner/*.in``). If either prompt is aborted (``None`` from
    Ctrl-C) or left empty/whitespace, returns ``None`` without creating anything.
    Otherwise delegates to :func:`create_manual_group` and returns the resulting
    ``TestcaseGroup``.
    """
    import questionary

    name = await questionary.text('Name for the new manual group:').ask_async()
    if name is None or not name.strip():
        return None

    glob = await questionary.text(
        'Glob for the new manual group (e.g. tests/manual/corner/*.in):'
    ).ask_async()
    if glob is None or not glob.strip():
        return None

    return create_manual_group(name, glob)
