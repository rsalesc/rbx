"""Where a promoted test can go: the package's **sinks**.

Sinks are derived from ``problem.rbx.yml``, never declared. Two kinds:

- **glob** -- a group or subgroup whose ``testcaseGlob`` holds a ``*`` and ends
  in ``.in``. It takes an input file, written by filling the glob's last ``*``.
- **plan** -- a group or subgroup whose effective ``generatorScript`` (its own,
  or the problem-level one it inherits) is a static ``.txt`` file. It takes a
  line: a generator call (a *recipe*) or a ``@copy`` of an input file.

A sink is named by the key its tests run under: the group name, or
``group/subgroup``. A plan sink also has a **scope**, the place in the script
its lines go: the top level when the script backs that key alone, else the
``@testgroup <key>`` block, since an untagged line reaches every key the
script backs.

See ``docs/plans/2026-10-15-promotion-sinks-design.md``.
"""

import dataclasses
import itertools
import os
import pathlib
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set, Tuple

from rbx import utils
from rbx.box import package, promotion, testplan_edit
from rbx.box.generator_script_handlers import group_matches
from rbx.box.schema import GeneratorScript, Package, TestcaseSubgroup

GLOB = 'glob'
PLAN = 'plan'

RECIPE = 'recipe'
COPY = 'copy'


@dataclasses.dataclass(frozen=True)
class Sink:
    name: str
    kind: str
    glob: Optional[str] = None
    script: Optional[GeneratorScript] = None
    scope: Optional[str] = None

    @property
    def path(self) -> str:
        """The glob, or the script relative to the package root."""
        if self.kind == GLOB:
            assert self.glob is not None
            return self.glob
        assert self.script is not None
        return package.relpath(self.script.path).as_posix()

    @property
    def editable(self) -> bool:
        """Whether lines can be placed anywhere in the script, not only appended.

        Only rbx-format scripts have scopes, ``@copy`` lines and in-place edits.
        A ``box``-format script only takes generator calls, at its end.
        """
        return (
            self.kind == PLAN
            and self.script is not None
            and self.script.format == 'rbx'
        )

    def forms(self) -> List[str]:
        """What this sink can hold: bytes for a glob, a call or a copy for a plan."""
        if self.kind == GLOB:
            return [COPY]
        if not self.editable:
            return [RECIPE]
        return [RECIPE, COPY]


def script_key(path: pathlib.Path) -> pathlib.Path:
    """A script path normalized so two spellings of one file compare equal."""
    return utils.abspath(pathlib.Path(os.path.normpath(path)))


def _effective_script(
    subgroup: TestcaseSubgroup, pkg: Package
) -> Optional[GeneratorScript]:
    """The script a group or subgroup runs, as ``testcase_extractors`` decides."""
    if subgroup.generatorScript is not None:
        return subgroup.generatorScript
    if (
        subgroup.testcases
        or subgroup.testcaseGlob
        or subgroup.generators
        or getattr(subgroup, 'subgroups', None)
    ):
        return None
    return pkg.generatorScript


def _nodes(pkg: Package) -> Iterable[Tuple[str, TestcaseSubgroup]]:
    for group in pkg.testcases:
        yield group.name, group
        for subgroup in group.subgroups:
            yield f'{group.name}/{subgroup.name}', subgroup


def list_sinks() -> List[Sink]:
    """Every sink of the package, in package order."""
    pkg = package.find_problem_package_or_die()
    nodes = list(_nodes(pkg))

    users: Counter = Counter()
    for _, node in nodes:
        script = _effective_script(node, pkg)
        if script is not None:
            users[script_key(script.path)] += 1

    sinks: List[Sink] = []
    for key, node in nodes:
        glob = node.testcaseGlob
        if glob is not None and '*' in glob and glob.endswith('.in'):
            sinks.append(Sink(name=key, kind=GLOB, glob=glob))
            continue
        script = _effective_script(node, pkg)
        if script is None or script.path.suffix != '.txt':
            continue
        shared = users[script_key(script.path)] > 1
        scope = key if shared and script.format == 'rbx' else None
        sinks.append(Sink(name=key, kind=PLAN, script=script, scope=scope))
    return sinks


def scripts_by_path() -> Dict[pathlib.Path, GeneratorScript]:
    """Every generator script the package runs, by :func:`script_key`."""
    pkg = package.find_problem_package_or_die()
    res: Dict[pathlib.Path, GeneratorScript] = {}
    for _, node in _nodes(pkg):
        script = _effective_script(node, pkg)
        if script is not None:
            res.setdefault(script_key(script.path), script)
    return res


def find_sink(name: str) -> Optional[Sink]:
    for sink in list_sinks():
        if sink.name == name:
            return sink
    return None


def read_script(sink: Sink) -> str:
    assert sink.script is not None
    path = pathlib.Path(sink.script.path)
    return path.read_text() if path.is_file() else ''


# --- @copy paths --------------------------------------------------------------


def copy_siblings(sink: Sink, script: str) -> List[pathlib.Path]:
    """The files the ``@copy`` statements routed to ``sink`` read, in order."""
    return [
        statement.copy_path
        for statement in testplan_edit.statements(script)
        if statement.kind == 'copy_test'
        and statement.copy_path is not None
        and group_matches(statement.group, sink.name)
    ]


_LAST_DIGITS = re.compile(r'^(.*?)(\d+)(\D*)$')


def _common_prefix(names: List[str]) -> str:
    return os.path.commonprefix(names)


def _common_suffix(names: List[str]) -> str:
    return _common_prefix([name[::-1] for name in names])[::-1]


def _generalize(stems: List[str]) -> Optional[str]:
    """A ``*`` pattern for a set of file stems, or None when they share nothing.

    Numbered names generalize around their last run of digits
    (``edge-001``, ``edge-002`` -> ``edge-*``); others around what they have in
    common, with digits trimmed off the ends of the common part.
    """
    parts = [_LAST_DIGITS.match(stem) for stem in stems]
    if all(parts):
        heads = {m.group(1) for m in parts if m is not None}
        tails = {m.group(3) for m in parts if m is not None}
        if len(heads) == 1 and len(tails) == 1:
            return f'{heads.pop()}*{tails.pop()}'
    if len(stems) < 2:
        return None
    prefix = _common_prefix(stems).rstrip('0123456789')
    suffix = _common_suffix(stems).lstrip('0123456789')
    if len(prefix) + len(suffix) >= min(len(stem) for stem in stems):
        return None
    return f'{prefix}*{suffix}'


def default_copy_pattern(sink: Sink) -> str:
    """Where a ``@copy`` of ``sink`` goes when nothing in its plan says."""
    return f'tests/{sink.name}/*.in'


def suggest_copy_pattern(sink: Sink, script: Optional[str] = None) -> str:
    """The ``*`` pattern new ``@copy`` files of ``sink`` follow.

    Inferred from the ``@copy`` lines already routed to the sink: the folder
    most of them share, and their names generalized around what varies.
    Falls back to :func:`default_copy_pattern`.
    """
    if script is None:
        script = read_script(sink)
    siblings = [p for p in copy_siblings(sink, script) if p.suffix == '.in']
    if not siblings:
        return default_copy_pattern(sink)
    folders = Counter(p.parent.as_posix() for p in siblings)
    best = max(folders.values())
    # The latest folder among the most used ones: what the setter does now.
    folder = next(
        p.parent.as_posix()
        for p in reversed(siblings)
        if folders[p.parent.as_posix()] == best
    )
    stems = [p.stem for p in siblings if p.parent.as_posix() == folder]
    name = _generalize(stems) or '*'
    return (pathlib.PurePosixPath(folder) / f'{name}.in').as_posix()


def glob_regex(glob: str) -> re.Pattern:
    """An anchored regex matching what ``glob`` matches, one segment per ``*``."""
    pattern = ''
    i = 0
    while i < len(glob):
        if glob.startswith('**', i):
            pattern += '.*'
            i += 2
        elif glob[i] == '*':
            pattern += '[^/]*'
            i += 1
        elif glob[i] == '?':
            pattern += '[^/]'
            i += 1
        else:
            pattern += re.escape(glob[i])
            i += 1
    return re.compile(f'^{pattern}$')


def _captured(pattern: str, paths: Iterable[pathlib.Path]) -> Set[str]:
    """What ``pattern``'s last ``*`` captures for each of ``paths`` it matches."""
    head, _, tail = pattern.rpartition('*')
    regex = re.compile(
        f'^{glob_regex(head).pattern[1:-1]}(.*){re.escape(tail)}$'
        if head
        else f'^(.*){re.escape(tail)}$'
    )
    res = set()
    for path in paths:
        match = regex.match(path.as_posix())
        if match and '/' not in match.group(1):
            res.add(match.group(1))
    return res


def allocate_stems(
    pattern: str,
    count: int,
    taken: Iterable[pathlib.Path] = (),
    base_dir: pathlib.Path = pathlib.Path(),
) -> List[str]:
    """``count`` new stems for ``pattern``'s last ``*``, after the ones in use.

    In use are the files on disk matching the pattern and ``taken`` (what a
    plan already names). When some are numbers, the new stems continue after
    the highest, as wide as the widest of them: after ``01`` and ``02`` comes
    ``03``, so a test promoted into a glob group sorts last, where a test
    added to the end of a group belongs. Otherwise they are the lowest free
    counters (``000``, ``001``, ...).
    """
    used = promotion.stems_matching_glob(pattern, base_dir=base_dir) | _captured(
        pattern, taken
    )
    numeric = [stem for stem in used if stem.isdigit()]
    if numeric:
        width = max(len(stem) for stem in numeric)
        start = max(int(stem) for stem in numeric) + 1
        return [f'{n:0{width}d}' for n in range(start, start + count)]
    res: List[str] = []
    for n in itertools.count():
        if len(res) == count:
            break
        stem = f'{n:03d}'
        if stem not in used:
            res.append(stem)
    return res


def matching_globs(path: pathlib.Path) -> List[str]:
    """The groups and subgroups whose ``testcaseGlob`` matches ``path``.

    A file written there becomes one of their tests too.
    """
    rel = package.relpath(path).as_posix()
    pkg = package.find_problem_package_or_die()
    return [
        key
        for key, node in _nodes(pkg)
        if node.testcaseGlob is not None and glob_regex(node.testcaseGlob).match(rel)
    ]
