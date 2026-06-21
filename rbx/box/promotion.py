import dataclasses
import itertools
import pathlib
import re
from typing import Dict, Iterable, List, Optional, Set

from rbx import utils
from rbx.box import generator_script_handlers as gsh
from rbx.box import package, package_utils
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.generator_script_handlers import _group_matches
from rbx.box.schema import GeneratorCall, GeneratorScript, TestcaseGroup
from rbx.box.stressing import generator_script_parser as gsp
from rbx.box.testcase_extractors import iter_effective_scripts


def manual_group_dir(group: TestcaseGroup) -> pathlib.Path:
    """Return the folder backing a glob-based manual group.

    This is the directory portion of the group's ``testcaseGlob`` (e.g.
    ``tests/manual/corner/*.in`` -> ``tests/manual/corner``).
    """
    assert group.testcaseGlob is not None
    return pathlib.Path(group.testcaseGlob).parent


def fill_glob(glob: str, stem: str) -> pathlib.Path:
    """Return the path obtained by filling ``glob``'s last ``*`` with ``stem``.

    Examples:
        ``manual_tests/manual-*.in`` + ``000`` -> ``manual_tests/manual-000.in``
        ``tests/manual/*.in`` + ``000`` -> ``tests/manual/000.in``

    If ``glob`` contains multiple ``*``, only the LAST one is filled; the rest
    are kept as literal text. If ``glob`` has no ``*``, a ``ValueError`` is
    raised: a manual group glob must contain a ``*`` to receive promoted tests.
    """
    if '*' not in glob:
        raise ValueError(f'manual group glob must contain a `*` (got {glob!r})')
    head, _, tail = glob.rpartition('*')
    return pathlib.Path(f'{head}{stem}{tail}')


def stems_matching_glob(glob: str, base_dir: pathlib.Path = pathlib.Path()) -> Set[str]:
    """Return the substring each on-disk file's last ``*`` captured for ``glob``.

    Enumerates files under ``base_dir`` matching ``glob`` and, for each, returns
    the text that the glob's LAST ``*`` matched. Earlier ``*`` are treated as
    non-capturing wildcards. Files that do not match the anchored pattern are
    ignored. Returns an empty set when nothing matches.
    """
    if '*' not in glob:
        raise ValueError(f'manual group glob must contain a `*` (got {glob!r})')

    # Build an anchored regex from the glob: literal segments are escaped, each
    # '*' becomes a wildcard, and the LAST '*' is the only capturing group so we
    # can recover the stem it matched.
    segments = glob.split('*')
    last = len(segments) - 1
    pattern = ''
    for i, segment in enumerate(segments):
        pattern += re.escape(segment)
        if i != last:
            pattern += '(.*)' if i == last - 1 else '.*'
    regex = re.compile(f'^{pattern}$')

    stems: Set[str] = set()
    # Candidates are pre-filtered by ``base_dir.glob(glob)`` (pathlib ``*`` does
    # not cross ``/``), so each candidate lies within a single path segment and
    # the regex's ``.*`` greediness is safely bounded to that segment.
    for path in base_dir.glob(glob):
        rel = path.relative_to(base_dir).as_posix()
        match = regex.match(rel)
        if match is None:
            continue
        stems.add(match.group(match.lastindex))
    return stems


def next_testcase_name(
    glob: str,
    used: Optional[Set[str]] = None,
    base_dir: pathlib.Path = pathlib.Path(),
) -> str:
    """Return the next free zero-padded counter name (no extension).

    Scans for files matching ``glob`` under ``base_dir`` (deducing each one's
    ``*`` stem) and returns the lowest non-colliding ``f'{i:03d}'`` stem.
    Returns ``'000'`` when nothing matches the glob yet.

    ``used`` adds extra reserved stems on top of the on-disk files, letting
    callers simulate a counter across not-yet-written names.
    """
    existing = stems_matching_glob(glob, base_dir=base_dir)
    if used is not None:
        existing |= used

    for i in itertools.count():
        name = f'{i:03d}'
        if name not in existing:
            return name
    raise AssertionError('unreachable')  # pragma: no cover


def default_stems(
    glob: str, count: int, base_dir: pathlib.Path = pathlib.Path()
) -> List[str]:
    """Assign ``count`` sequential glob-aware default stems.

    Simulates the on-disk counter so the defaults are sequential and
    collision-free against both files already matching ``glob`` and the stems
    assigned earlier in the same batch (000, 001, ... skipping taken ones).
    """
    # ``next_testcase_name`` re-scans disk on every call and unions ``used`` on
    # top, so we only need to accumulate the stems chosen so far this batch --
    # the on-disk collisions are handled for us.
    used: Set[str] = set()
    stems: List[str] = []
    for _ in range(count):
        stem = next_testcase_name(glob, used=used, base_dir=base_dir)
        used.add(stem)
        stems.append(stem)
    return stems


def validate_stems(stems: List[str]) -> Optional[str]:
    """Return an error message if ``stems`` is not a valid batch, else ``None``.

    A batch is invalid if any stem is empty/whitespace-only (no filename),
    contains whitespace (would yield an awkward filename), or if two stems are
    equal (they would map to the same file and overwrite one another).
    """
    for stem in stems:
        if not stem.strip():
            return 'Filenames cannot be empty.'
        if any(ch.isspace() for ch in stem):
            return f'Filename {stem!r} must not contain whitespace.'
    seen: Set[str] = set()
    for stem in stems:
        if stem in seen:
            return f'Duplicate filename {stem!r}: each test needs a distinct name.'
        seen.add(stem)
    return None


def promote_input_to_group(
    input_path: pathlib.Path,
    group: TestcaseGroup,
    *,
    name: Optional[str] = None,
    base_dir: pathlib.Path = pathlib.Path(),
) -> pathlib.Path:
    """Write the bytes of ``input_path`` as a static ``.in`` file into the group.

    The destination path is ``base_dir / fill_glob(group.testcaseGlob, stem)``,
    so the written file always MATCHES the group's glob. The stem is ``name`` if
    provided, else the next free counter name. INPUT ONLY -- never writes a
    ``.out``/``.ans`` file.

    Returns the path of the written file.
    """
    assert group.testcaseGlob is not None
    stem = (
        name
        if name is not None
        else next_testcase_name(group.testcaseGlob, base_dir=base_dir)
    )
    dest = base_dir / fill_glob(group.testcaseGlob, stem)
    dest.parent.mkdir(parents=True, exist_ok=True)
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
    """Map each EFFECTIVE generator-script path (explicit or inherited) to its
    format ('rbx'/'box')."""
    res: Dict[pathlib.Path, str] = {}
    for _run_key, gs in iter_effective_scripts():
        res[gs.path] = gs.format
    return res


def run_keys_by_script_path() -> Dict[pathlib.Path, Set[str]]:
    """Map each effective script path to the set of run-keys generating from it.

    A problem-level script inherited by several groups/subgroups appears once,
    mapped to all the run-keys that share it.
    """
    res: Dict[pathlib.Path, Set[str]] = {}
    for run_key, gs in iter_effective_scripts():
        res.setdefault(gs.path, set()).add(run_key)
    return res


def removal_affects_only_run_key(
    run_key: str, annotation: Optional[str], run_keys: Set[str]
) -> bool:
    """True iff a line annotated ``annotation`` in a script shared by ``run_keys``
    matches ONLY ``run_key`` -- so removing it cannot change another group."""
    matched = {k for k in run_keys if _group_matches(annotation, k)}
    return matched == {run_key}


def line_annotation(script_path: pathlib.Path, line: int) -> Optional[str]:
    """The @testgroup path of the statement at ``line`` (None if untagged)."""
    inputs = gsp.parse_and_transform(script_path.read_text(), script_path)
    for inp in inputs:
        if inp.generator_script is not None and inp.generator_script.line == line:
            return inp.group
    return None


def is_isolated_removal(
    entry: GenerationTestcaseEntry, run_keys_by_path: Dict[pathlib.Path, Set[str]]
) -> bool:
    """True iff removing ``entry``'s originating line affects only its run-key.

    A line in a @testgroup block scoped to this run-key, or a line in a script
    used by only this run-key, is safe to remove. An untagged line in a script
    shared by other groups -- or a parent tag that bleeds into sibling
    subgroups -- is not.
    """
    gse = entry.metadata.generator_script
    if gse is None:
        return False
    run_keys = run_keys_by_path.get(gse.path)
    if not run_keys:
        return False
    annotation = line_annotation(gse.path, gse.line)
    return removal_affects_only_run_key(
        entry.subgroup_entry.group, annotation, run_keys
    )


@dataclasses.dataclass
class ScriptAddTarget:
    """A place to append generator-script lines for one run-key."""

    run_key: str
    script: GeneratorScript
    block_start_line: Optional[int]  # existing @testgroup block; None => create/append
    top_level: bool  # only when block_start_line is None: append untagged
    label: str


def script_add_targets() -> List[ScriptAddTarget]:
    """Targets for appending tests to rbx-format ``.txt`` generator scripts.

    For each leaf run-key with such an effective script, yields one target per
    existing ``@testgroup`` block matching the run-key exactly, plus a
    create/append target. The create/append target appends at top level when the
    script is used by only that run-key (so the new line cannot leak), else it
    creates a fresh ``@testgroup <run-key>`` block scoping the addition.
    """
    run_keys = run_keys_by_script_path()
    targets: List[ScriptAddTarget] = []
    for run_key, gs in iter_effective_scripts():
        if gs.format != 'rbx' or gs.path.suffix != '.txt' or not gs.path.is_file():
            continue
        rel = package.relpath(gs.path)
        for block in gsp.testgroup_blocks(gs.path.read_text()):
            if block.path == run_key:
                targets.append(
                    ScriptAddTarget(
                        run_key,
                        gs,
                        block.start_line,
                        False,
                        f'{run_key} @ {rel}:{block.start_line}',
                    )
                )
        exclusive = run_keys.get(gs.path) == {run_key}
        targets.append(
            ScriptAddTarget(
                run_key,
                gs,
                None,
                exclusive,
                f'{run_key} @ {rel} '
                + ('(append)' if exclusive else '(new @testgroup block)'),
            )
        )
    return targets


def add_calls_to_target(
    target: ScriptAddTarget,
    calls: List[GeneratorCall],
    comment: Optional[str] = None,
) -> None:
    """Append ``calls`` to ``target``'s script, scoped to its run-key."""
    path = target.script.path
    handler = gsh.get_generator_script_handler(
        path.read_text(), gsh.GeneratorScriptHandlerParams(target.script)
    )
    if target.block_start_line is not None:
        handler.append_in_block(target.block_start_line, calls, comment)
    elif target.top_level:
        handler.append(calls, comment)
    else:
        handler.append_new_block(target.run_key, calls, comment)
    path.write_text(handler.script)
    package_utils.clear_package_cache()


def is_promotable(
    entry: GenerationTestcaseEntry, script_formats: Dict[pathlib.Path, str]
) -> bool:
    """True iff entry came from an rbx generator script and is not a @copy.

    This does NOT check removal isolation (see :func:`is_isolated_removal`); the
    commands gate on both.
    """
    md = entry.metadata
    if md.generator_script is None or md.copied_from is not None:
        return False
    # Only static ``.txt`` scripts are line-addressable; dynamic scripts (a
    # program that emits the plan, e.g. ``.py``) cannot be edited line-by-line.
    if md.generator_script.path.suffix != '.txt':
        return False
    return script_formats.get(md.generator_script.path) == 'rbx'


def remove_script_entries(entries: Iterable[GenerationTestcaseEntry]) -> None:
    """Delete each entry's originating statement from its rbx generator script."""
    by_path: Dict[pathlib.Path, Set[int]] = {}
    for entry in entries:
        gse = entry.metadata.generator_script
        assert gse is not None
        by_path.setdefault(gse.path, set()).add(gse.line)

    # Effective scripts include the inherited problem-level path, so a test
    # generated by the inherited script resolves to a registered entry.
    script_entry_by_path = {gs.path: gs for _rk, gs in iter_effective_scripts()}

    for path, start_lines in by_path.items():
        assert path in script_entry_by_path, (
            f'No registered generator script found for {path}.'
        )
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
