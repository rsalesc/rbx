"""Promoting tests into a sink: computed as a plan, then applied.

A promotion is a **plan** -- an ordered list of file changes -- before it is
anything else. ``rbx testcases promote --dry-run --json`` prints it, the VS Code
extension previews and applies it as one editor edit, and without
``--dry-run`` rbx applies it itself (:func:`apply_plan`). There is one
implementation of what a promotion *does*, and every surface shows the same
thing before doing it.

What goes where (see ``docs/plans/2026-10-15-promotion-sinks-design.md``):

- a test lands at the end of the sink's scope, except that a statement already
  routed to the sink in its own plan is **replaced in place**;
- a plan sink takes the source's recipe when it has one, else a ``@copy``;
  ``form`` overrides; a glob sink always takes the input file;
- the source is **moved** unless ``keep_source``: its statement is removed, or
  its glob files deleted. Findings and plain files are always copies.
"""

import dataclasses
import hashlib
import pathlib
import shutil
from typing import Any, Dict, List, Optional, Set, Tuple

from rbx import utils
from rbx.box import generator_script_handlers as gsh
from rbx.box import package, package_utils, promotion, testplan_edit, yaml_include
from rbx.box import promotion_sinks as sinks
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.promotion_sinks import COPY, GLOB, PLAN, RECIPE, Sink
from rbx.box.schema import GeneratorCall, GeneratorScript

CREATE = 'create'
MODIFY = 'modify'
DELETE = 'delete'


class PromotionError(Exception):
    """A promotion that cannot be planned; the message says why, for the setter."""


# --- sources ------------------------------------------------------------------


@dataclasses.dataclass
class Source:
    """One thing being promoted, and what it can be written as."""

    # As the setter named it: `tests/plan.txt:3`, `main/2`, `finding:1`, ...
    selector: str
    # The generator call that makes it, when one does.
    recipe: Optional[GeneratorCall] = None
    # Its input, when it is already a file (a glob test, a @copy, a finding).
    input_path: Optional[pathlib.Path] = None
    # A setter-written answer that travels with the input.
    answer_path: Optional[pathlib.Path] = None
    # A built test, to generate the input from when there is no file yet.
    entry: Optional[GenerationTestcaseEntry] = None
    # The statement it comes from, in an rbx-format plan.
    script: Optional[pathlib.Path] = None
    statement: Optional[testplan_edit.Statement] = None
    # The files of a glob test, which a move deletes.
    glob_files: List[pathlib.Path] = dataclasses.field(default_factory=list)
    # Nothing to remove: findings and plain files are always copied.
    copy_only: bool = False
    # Why it cannot be removed, when it cannot.
    unmovable: Optional[str] = None
    # Skip it when the sink already has it (findings: re-adding is harmless).
    dedup: bool = False

    @property
    def has_bytes(self) -> bool:
        return self.input_path is not None or self.entry is not None

    @property
    def current_form(self) -> Optional[str]:
        """What the statement it comes from already is, in its plan."""
        if self.statement is None:
            return None
        if self.statement.kind == 'generator_call':
            return RECIPE
        if self.statement.kind == 'copy_test':
            return COPY
        return None


def source_from_finding(index: int) -> Source:
    from rbx.box import stress_manifest

    manifest = stress_manifest.read_manifest()
    finding = None
    if manifest is not None:
        finding = next((f for f in manifest.findings if f.index == index), None)
    if finding is None:
        raise PromotionError(f'The latest stress session has no finding {index}.')
    path = stress_manifest.finding_input_path(index)
    if not path.is_file():
        raise PromotionError(f'Could not find the input of finding {index} at {path}.')
    return Source(
        selector=f'finding:{index}',
        recipe=finding.generator,
        input_path=path,
        copy_only=True,
        dedup=True,
    )


def source_from_file(spec: str) -> Source:
    """``IN`` or ``IN:ANS``: an input file, and maybe the answer to keep with it."""
    input_spec, _, answer_spec = spec.partition(':')
    input_path = pathlib.Path(input_spec)
    if not input_path.is_file():
        raise PromotionError(f'There is no input file at {input_spec}.')
    answer_path = None
    if answer_spec:
        answer_path = pathlib.Path(answer_spec)
        if not answer_path.is_file():
            raise PromotionError(f'There is no answer file at {answer_spec}.')
    return Source(
        selector=f'file:{spec}',
        input_path=input_path,
        answer_path=answer_path,
        copy_only=True,
    )


def source_from_entry(selector: str, entry: GenerationTestcaseEntry) -> Source:
    """A built test, from wherever the package declares it."""
    md = entry.metadata
    src = Source(selector=selector, entry=entry, recipe=md.generator_call)
    if md.copied_from is not None:
        src.input_path = md.copied_from.inputPath
        output = md.copied_from.outputPath
        if output is not None and output.is_file():
            src.answer_path = output

    gse = md.generator_script
    if gse is not None:
        script = sinks.scripts_by_path().get(sinks.script_key(gse.path))
        if gse.path.suffix != '.txt' or script is None:
            src.unmovable = 'comes from a dynamic generator script'
        elif script.format != 'rbx':
            src.unmovable = (
                'comes from a box-format script, whose lines cannot be removed'
            )
        else:
            src.script = sinks.script_key(gse.path)
            src.statement = testplan_edit.statement_at(
                pathlib.Path(gse.path).read_text(), gse.line
            )
        return src

    if md.copied_from is not None:
        glob = _glob_of(entry)
        rel = package.relpath(md.copied_from.inputPath).as_posix()
        if glob is not None and sinks.glob_regex(glob).match(rel):
            src.glob_files = [md.copied_from.inputPath]
            if src.answer_path is not None:
                src.glob_files.append(src.answer_path)
        else:
            src.unmovable = 'is listed under `testcases:` in problem.rbx.yml'
        return src

    src.unmovable = 'is listed under `generators:` in problem.rbx.yml'
    return src


FINDING_PREFIX = 'finding:'
FILE_PREFIX = 'file:'


def entry_selector(entry: GenerationTestcaseEntry) -> str:
    """How to name a built test back: by its statement when it has one."""
    gse = entry.metadata.generator_script
    if gse is not None:
        return f'{package.relpath(gse.path).as_posix()}:{gse.line}'
    return str(entry.group_entry)


async def resolve_sources(selectors: List[str]) -> List[Source]:
    """Sources for ``finding:K``, ``file:IN[:ANS]``, ``[script]:[line]`` and
    ``[group]/[index]`` selectors -- the tests first, then the rest, in order."""
    from rbx.box import testcase_selectors

    others: List[Source] = []
    tests: List[str] = []
    for selector in selectors:
        if selector.startswith(FINDING_PREFIX):
            index = selector[len(FINDING_PREFIX) :]
            if not index.isdigit():
                raise PromotionError(
                    f'Invalid finding [item]{selector}[/item]: expected finding:K, '
                    'K its number in the stress report.'
                )
            others.append(source_from_finding(int(index)))
        elif selector.startswith(FILE_PREFIX):
            others.append(source_from_file(selector[len(FILE_PREFIX) :]))
        else:
            tests.append(selector)

    res: List[Source] = []
    if tests:
        try:
            entries = await testcase_selectors.entries_for_selectors(tests)
        except testcase_selectors.SelectorError as e:
            raise PromotionError(str(e)) from None
        if not entries:
            raise PromotionError('No tests matched the provided selectors.')
        res = [source_from_entry(entry_selector(e), e) for e in entries]
    return res + others


def _glob_of(entry: GenerationTestcaseEntry) -> Optional[str]:
    node = package.get_test_groups_by_name().get(entry.group_entry.group)
    key = entry.subgroup_entry.group
    if '/' in key:
        group, _, sub = key.partition('/')
        parent = package.get_test_groups_by_name().get(group)
        node = next(
            (s for s in getattr(parent, 'subgroups', []) if s.name == sub), None
        )
    return node.testcaseGlob if node is not None else None


async def _input_of(
    source: Source, progress: Optional[utils.StatusProgress] = None
) -> pathlib.Path:
    """The source's input as a file, generating it when it is not one yet."""
    if source.input_path is not None:
        return source.input_path
    assert source.entry is not None
    from rbx.box.generators import generate_standalone

    await generate_standalone(
        source.entry.metadata,
        validate=False,
        group_entry=source.entry.group_entry,
        progress=progress,
    )
    return source.entry.metadata.copied_to.inputPath


# --- the plan -----------------------------------------------------------------


@dataclasses.dataclass
class Change:
    path: pathlib.Path
    action: str
    before: Optional[str] = None
    after: Optional[str] = None
    # A create copies its bytes from here when it has no `after` text.
    source: Optional[pathlib.Path] = None

    def to_json(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            'path': str(utils.abspath(self.path)),
            'action': self.action,
        }
        if self.action == MODIFY:
            res['before'] = self.before
            res['after'] = self.after
        elif self.action == CREATE:
            if self.source is not None:
                res['from'] = str(utils.abspath(self.source))
            else:
                res['content'] = self.after
        return res


@dataclasses.dataclass
class Promoted:
    source: str
    form: str
    # The file written, or the plan the line went into; package-relative.
    to: str
    in_place: bool = False
    # Whether the source left its old place.
    moved: bool = False

    def to_json(self) -> Dict[str, Any]:
        return {
            'source': self.source,
            'form': self.form,
            'to': self.to,
            'inPlace': self.in_place,
            'moved': self.moved,
        }


@dataclasses.dataclass
class Skipped:
    source: str
    reason: str

    def to_json(self) -> Dict[str, Any]:
        return {'source': self.source, 'reason': self.reason}


@dataclasses.dataclass
class NewGroup:
    """A group to create along with the promotion: a glob or a script one."""

    name: str
    glob: Optional[str] = None
    script: Optional[pathlib.Path] = None

    def sink(self) -> Sink:
        if self.glob is not None:
            return Sink(name=self.name, kind=GLOB, glob=self.glob)
        assert self.script is not None
        return Sink(name=self.name, kind=PLAN, script=GeneratorScript(path=self.script))

    def entry(self) -> Dict[str, Any]:
        if self.glob is not None:
            return {'name': self.name, 'testcaseGlob': self.glob}
        assert self.script is not None
        return {'name': self.name, 'generatorScript': {'path': self.script.as_posix()}}


@dataclasses.dataclass
class Plan:
    sink: Sink
    changes: List[Change]
    promoted: List[Promoted]
    skipped: List[Skipped]
    new_group: Optional[NewGroup] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            'sink': sink_json(self.sink),
            'changes': [c.to_json() for c in self.changes],
            'promoted': [p.to_json() for p in self.promoted],
            'skipped': [s.to_json() for s in self.skipped],
        }


def sink_json(sink: Sink) -> Dict[str, Any]:
    return {
        'name': sink.name,
        'kind': sink.kind,
        'path': sink.path,
        'scope': sink.scope,
    }


def default_form(sink: Sink, sources: List[Source]) -> str:
    """Recipe when every source has one and the sink takes it, else a copy."""
    if sink.kind == GLOB:
        return COPY
    if not sink.editable or all(s.recipe is not None for s in sources):
        return RECIPE
    return COPY


def _recipe_line(call: GeneratorCall, script: GeneratorScript) -> str:
    name = call.name
    if package.get_generator_or_nil(name) is None:
        handler = gsh.get_generator_script_handler(
            '', gsh.GeneratorScriptHandlerParams(script)
        )
        name = handler.normalize_call_name(name)
    return f'{name} {call.args or ""}'.rstrip()


def _call_key(name: str, args: Optional[str]) -> Tuple[str, str]:
    return name, ' '.join((args or '').split())


def _sink_calls(sink: Sink, text: str) -> Set[Tuple[str, str]]:
    """The calls ``sink``'s plan already routes to it, as comparable keys."""
    assert sink.script is not None
    handler = gsh.get_generator_script_handler(
        text, gsh.GeneratorScriptHandlerParams(sink.script, group=sink.name)
    )
    return {
        _call_key(inp.generator_call.name, inp.generator_call.args)
        for inp in handler.parse()
        if inp.generator_call is not None
    }


def _digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sink_digests(sink: Sink, text: Optional[str]) -> Set[str]:
    """The inputs a sink already holds as files, by content."""
    if sink.kind == GLOB:
        assert sink.glob is not None
        files = [p for p in pathlib.Path().glob(sink.glob) if p.is_file()]
    else:
        assert text is not None
        files = [p for p in sinks.copy_siblings(sink, text) if p.is_file()]
    return {_digest(p) for p in files}


class _Scripts:
    """The working text of every script a plan touches."""

    def __init__(self):
        self.before: Dict[pathlib.Path, str] = {}
        self.replace: Dict[pathlib.Path, Dict[int, List[str]]] = {}
        self.remove: Dict[pathlib.Path, Set[int]] = {}
        self.insert: Dict[
            pathlib.Path, List[Tuple[Optional[str], List[str], Optional[str]]]
        ] = {}
        # A box-format sink only appends, through its own handler.
        self.box_append: Dict[
            pathlib.Path, Tuple[GeneratorScript, List[GeneratorCall], Optional[str]]
        ] = {}
        self.created: Set[pathlib.Path] = set()

    def text(self, path: pathlib.Path) -> str:
        key = sinks.script_key(path)
        if key not in self.before:
            self.before[key] = path.read_text() if path.is_file() else ''
            if not path.is_file():
                self.created.add(key)
        return self.before[key]

    def changes(self) -> List[Change]:
        res = []
        for key, before in self.before.items():
            text = before
            if key in self.box_append:
                script, calls, comment = self.box_append[key]
                handler = gsh.get_generator_script_handler(
                    text, gsh.GeneratorScriptHandlerParams(script)
                )
                handler.append(calls, comment=comment)
                text = handler.script
            if self.replace.get(key) or self.remove.get(key):
                text = _edit_statements(
                    text, self.replace.get(key, {}), self.remove.get(key, set())
                )
            for scope, lines, comment in self.insert.get(key, []):
                text = testplan_edit.insert_in_scope(text, scope, lines, comment)
            if text == before and key not in self.created:
                continue
            if key in self.created:
                res.append(Change(path=key, action=CREATE, after=text))
            else:
                res.append(Change(path=key, action=MODIFY, before=before, after=text))
        return res


def _edit_statements(text: str, replace: Dict[int, List[str]], remove: Set[int]) -> str:
    """Replacements and removals of the statements starting on those lines.

    Replacements go bottom-up, so each leaves the lines above it in place. A
    replacement swaps one statement for exactly one, so the statements to
    remove are found again afterwards by their position among all of them.
    """
    ordinals = [
        i
        for i, s in enumerate(testplan_edit.statements(text))
        if s.start_line in remove
    ]
    for line in sorted(replace, reverse=True):
        text = testplan_edit.replace_statement(text, line, replace[line])
    if ordinals:
        now = testplan_edit.statements(text)
        text = testplan_edit.remove_statements(
            text, [now[i].start_line for i in ordinals]
        )
    return text


def _inside_package(path: pathlib.Path) -> bool:
    # The cwd is the package root (`within_problem`).
    root = pathlib.Path.cwd().resolve()
    return utils.abspath(path).resolve().is_relative_to(root)


def _same_file(a: pathlib.Path, b: pathlib.Path) -> bool:
    return utils.abspath(a) == utils.abspath(b)


async def _references() -> Dict[pathlib.Path, Set[Any]]:
    """For each input file a test reads, what reads it: a statement or a test."""
    from rbx.box.testcase_extractors import extract_generation_testcases_from_groups

    res: Dict[pathlib.Path, Set[Any]] = {}
    for entry in await extract_generation_testcases_from_groups():
        md = entry.metadata
        if md.copied_from is None:
            continue
        gse = md.generator_script
        ref = (
            (sinks.script_key(gse.path), gse.line)
            if gse is not None
            else ('test', str(entry.subgroup_entry))
        )
        res.setdefault(utils.abspath(md.copied_from.inputPath), set()).add(ref)
    return res


def _new_group_changes(new_group: NewGroup) -> List[Change]:
    dest = package.find_problem_yaml()
    assert dest is not None
    session = yaml_include.EditSession(dest)
    # `testcases` may live in an `!include`d fragment; edit whichever file owns it.
    target = session.target('testcases')
    if target.value is None:
        target.replace([new_group.entry()])
    else:
        target.value.append(new_group.entry())
    return [
        Change(path=path, action=MODIFY, before=before, after=after)
        for path, (before, after) in sorted(session.pending().items())
    ]


@dataclasses.dataclass
class _Decision:
    source: Source
    form: str
    move: bool
    in_place: bool


def _decide(
    sources: List[Source], sink: Sink, form: Optional[str], keep_source: bool
) -> List[_Decision]:
    """Each source's form, and whether it moves.

    Refuses anything that cannot be done before anything is computed, so a
    plan is all or nothing.
    """
    if form is not None and form not in sink.forms():
        raise PromotionError(
            f'Test group {sink.name} cannot hold a {form}: '
            + (
                'a glob group holds input files.'
                if sink.kind == GLOB
                else 'its box-format script only takes generator calls.'
            )
        )
    sink_script = (
        sinks.script_key(sink.script.path) if sink.script is not None else None
    )
    res = []
    for src in sources:
        chosen = form
        if chosen is None:
            chosen = (
                RECIPE if RECIPE in sink.forms() and src.recipe is not None else COPY
            )
            if chosen not in sink.forms():
                chosen = sink.forms()[0]
        if chosen == RECIPE and src.recipe is None:
            raise PromotionError(
                f'{src.selector} is not made by a generator call, so it can only '
                'be promoted as a copy of its input.'
            )
        if chosen == COPY and not src.has_bytes:
            raise PromotionError(f'{src.selector} has no input to copy.')
        move = not keep_source and not src.copy_only
        if move and src.unmovable is not None:
            raise PromotionError(
                f'{src.selector} cannot be moved: it {src.unmovable}. '
                'Pass --keep-source to copy it instead.'
            )
        in_place = (
            move
            and sink.editable
            and src.statement is not None
            and src.script == sink_script
            and gsh.group_matches(src.statement.group, sink.name)
        )
        res.append(_Decision(src, chosen, move, in_place))
    return res


def _copy_pattern(
    sink: Sink, path: Optional[str], sink_text: Optional[str]
) -> Tuple[str, Optional[pathlib.Path]]:
    """The ``*`` pattern new files follow, and the one file a literal path names."""
    if sink.kind == GLOB:
        assert sink.glob is not None
        return sink.glob, None
    if path is not None and '*' not in path:
        return path, pathlib.Path(path)
    if path is not None:
        return path, None
    return sinks.suggest_copy_pattern(sink, sink_text), None


def default_stems(
    sink: Sink, pattern: str, count: int, sink_text: Optional[str] = None
) -> List[str]:
    """The names ``count`` new files of ``sink`` get unless told otherwise.

    A glob keeps its long-standing rule (the lowest free counters); a plan
    continues after the highest numbered file it already copies.
    """
    if sink.kind == GLOB:
        return promotion.default_stems(pattern, count)
    if sink_text is None:
        sink_text = sinks.read_script(sink)
    taken = sinks.copy_siblings(sink, sink_text)
    return sinks.allocate_stems(pattern, count, taken=taken)


def available_forms(sink: Sink, sources: List[Source]) -> List[str]:
    """The forms every one of ``sources`` can take in ``sink``, default first."""
    forms = [
        form
        for form in sink.forms()
        if (form == RECIPE and all(s.recipe is not None for s in sources))
        or (form == COPY and all(s.has_bytes for s in sources))
    ]
    forms.sort(key=lambda form: form != default_form(sink, sources))
    return forms


def in_place(sink: Sink, sources: List[Source]) -> bool:
    """Whether some of ``sources`` already live in ``sink``'s plan, routed to it."""
    if not sink.editable or sink.script is None:
        return False
    key = sinks.script_key(sink.script.path)
    return any(
        s.statement is not None
        and s.script == key
        and gsh.group_matches(s.statement.group, sink.name)
        for s in sources
    )


def copy_sources(
    sources: List[Source],
    sink: Sink,
    form: Optional[str] = None,
    keep_source: bool = False,
) -> List[Source]:
    """The sources that become new files, in the order ``stems`` names them."""
    return [
        d.source
        for d in _decide(sources, sink, form, keep_source)
        if d.form == COPY and not (d.in_place and d.source.current_form == COPY)
    ]


def copy_layout(sink: Sink, count: int) -> Tuple[str, List[str]]:
    """The ``*`` pattern ``sink``'s new files follow, and ``count`` default names."""
    text = sinks.read_script(sink) if sink.script is not None else None
    pattern, _ = _copy_pattern(sink, None, text)
    return pattern, default_stems(sink, pattern, count, text)


async def plan_promotion(
    sources: List[Source],
    sink: Optional[Sink] = None,
    *,
    new_group: Optional[NewGroup] = None,
    form: Optional[str] = None,
    name: Optional[str] = None,
    path: Optional[str] = None,
    keep_source: bool = False,
    comment: Optional[str] = None,
    stems: Optional[List[str]] = None,
    progress: Optional[utils.StatusProgress] = None,
) -> Plan:
    """What promoting ``sources`` into ``sink`` (or a ``new_group``) changes.

    ``name`` is the stem of a single promoted file; ``path`` overrides where a
    plan sink's ``@copy`` files go -- a pattern when it holds a ``*``, else the
    file itself; ``stems`` names every promoted file, in the order of
    :func:`copy_sources`. Nothing is written: see :func:`apply_plan`.
    """
    if new_group is not None:
        sink = new_group.sink()
    assert sink is not None
    if not sources:
        raise PromotionError('Name at least one test to promote.')
    if name is not None and path is not None:
        raise PromotionError('Pass at most one of --name or --path.')
    if path is not None and sink.kind == GLOB:
        raise PromotionError(
            f'Test group {sink.name} keeps its files at {sink.glob}; '
            'pick the file name with --name instead of --path.'
        )
    if path is not None and not path.endswith('.in'):
        raise PromotionError(f'A promoted input must end in `.in` (got {path}).')
    if name is not None:
        error = promotion.validate_stems([name])
        if error is not None:
            raise PromotionError(error)

    decisions = _decide(sources, sink, form, keep_source)
    scripts = _Scripts()
    sink_key = sinks.script_key(sink.script.path) if sink.script is not None else None
    sink_text = scripts.text(sink.script.path) if sink.script is not None else None

    # Where new files go, decided up front for the whole batch.
    copies = [
        d
        for d in decisions
        if d.form == COPY and not (d.in_place and d.source.current_form == COPY)
    ]
    pattern, literal = _copy_pattern(sink, path, sink_text)
    if (name is not None or literal is not None) and len(copies) > 1:
        raise PromotionError(
            '--name and a --path without `*` name one file, but '
            f'{len(copies)} tests are being promoted as files.'
        )
    taken = sinks.copy_siblings(sink, sink_text) if sink_text is not None else []
    if stems is not None:
        if len(stems) != len(copies):
            raise PromotionError(
                f'{len(copies)} tests are being promoted as files, '
                f'but {len(stems)} names were given.'
            )
        error = promotion.validate_stems(stems)
        if error is not None:
            raise PromotionError(error)
    elif name is not None:
        stems = [name]
    elif literal is not None:
        stems = []
    else:
        stems = default_stems(sink, pattern, len(copies), sink_text)
    stem_of = {id(d): stem for d, stem in zip(copies, stems)}

    calls_seen = _sink_calls(sink, sink_text) if sink_text is not None else set()
    digests: Optional[Set[str]] = None

    changes: List[Change] = []
    promoted: List[Promoted] = []
    skipped: List[Skipped] = []
    inserted: List[str] = []
    box_calls: List[GeneratorCall] = []
    removed: List[Source] = []
    planned_files: Set[pathlib.Path] = set()

    for decision in decisions:
        src = decision.source
        if decision.in_place and decision.form == src.current_form:
            skipped.append(
                Skipped(src.selector, f'it is already a {decision.form} in {sink.name}')
            )
            continue

        if decision.form == RECIPE:
            assert src.recipe is not None and sink.script is not None
            line = _recipe_line(src.recipe, sink.script)
            name_, _, args = line.partition(' ')
            key = _call_key(name_, args)
            if src.dedup and key in calls_seen:
                skipped.append(Skipped(src.selector, f'{sink.name} already has it'))
                continue
            calls_seen.add(key)
            if not sink.editable:
                box_calls.append(src.recipe)
            elif decision.in_place:
                assert src.statement is not None and sink_key is not None
                scripts.replace.setdefault(sink_key, {})[src.statement.start_line] = [
                    line
                ]
            else:
                inserted.append(line)
            promoted.append(
                Promoted(
                    src.selector, RECIPE, sink.path, decision.in_place, decision.move
                )
            )
        else:
            input_path = await _input_of(src, progress)
            if src.dedup:
                if digests is None:
                    digests = _sink_digests(sink, sink_text)
                digest = _digest(input_path)
                if digest in digests:
                    skipped.append(Skipped(src.selector, f'{sink.name} already has it'))
                    continue
                digests.add(digest)
            dest = (
                literal
                if literal is not None
                else promotion.fill_glob(pattern, stem_of[id(decision)])
            )
            # Moving a @copy to where its file already is moves only the line.
            reused = (
                decision.move
                and src.statement is not None
                and src.statement.kind == 'copy_test'
                and _same_file(dest, input_path)
            )
            if not reused:
                _check_destination(dest, sink, taken, planned_files)
                planned_files.add(utils.abspath(dest))
                changes.append(Change(path=dest, action=CREATE, source=input_path))
                if src.answer_path is not None:
                    changes.append(
                        Change(
                            path=dest.with_suffix('.ans'),
                            action=CREATE,
                            source=src.answer_path,
                        )
                    )
            if sink.kind == PLAN:
                line = testplan_edit.copy_line(package.relpath(dest))
                if decision.in_place:
                    assert src.statement is not None and sink_key is not None
                    scripts.replace.setdefault(sink_key, {})[
                        src.statement.start_line
                    ] = [line]
                else:
                    inserted.append(line)
            promoted.append(
                Promoted(
                    src.selector,
                    COPY,
                    package.relpath(dest).as_posix(),
                    decision.in_place,
                    decision.move,
                )
            )
            if reused:
                # The file stays: only the line moves.
                src = dataclasses.replace(src, input_path=None, answer_path=None)

        if decision.move and not decision.in_place:
            removed.append(src)

    if sink_key is not None and sink.script is not None:
        if box_calls:
            scripts.box_append[sink_key] = (sink.script, box_calls, comment)
        if inserted:
            scripts.insert.setdefault(sink_key, []).append(
                (sink.scope, inserted, comment)
            )

    deletes = await _removals(removed, scripts)
    changes = scripts.changes() + changes
    if new_group is not None:
        changes += _new_group_changes(new_group)
    seen: Set[pathlib.Path] = set()
    for path_ in deletes:
        key_ = utils.abspath(path_)
        if key_ not in seen:
            seen.add(key_)
            changes.append(Change(path=path_, action=DELETE))
    return Plan(sink, changes, promoted, skipped, new_group)


async def _removals(removed: List[Source], scripts: _Scripts) -> List[pathlib.Path]:
    """Mark the statements of moved sources for removal; return the files to
    delete: a moved glob test's, and a moved ``@copy``'s when nothing else
    reads it."""
    deletes: List[pathlib.Path] = []
    references: Optional[Dict[pathlib.Path, Set[Any]]] = None
    removed_refs = {
        (src.script, src.statement.start_line)
        for src in removed
        if src.script is not None and src.statement is not None
    }
    for src in removed:
        if src.statement is not None and src.script is not None:
            scripts.text(src.script)
            scripts.remove.setdefault(src.script, set()).add(src.statement.start_line)
            if src.statement.kind == 'copy_test' and src.input_path is not None:
                if references is None:
                    references = await _references()
                readers = references.get(utils.abspath(src.input_path), set())
                if readers <= removed_refs and _inside_package(src.input_path):
                    deletes.append(src.input_path)
                    if src.answer_path is not None:
                        deletes.append(src.answer_path)
        deletes.extend(src.glob_files)
    return deletes


def _check_destination(
    dest: pathlib.Path,
    sink: Sink,
    taken: List[pathlib.Path],
    planned: Set[pathlib.Path],
) -> None:
    if dest.suffix != '.in':
        raise PromotionError(f'A promoted input must end in `.in` (got {dest}).')
    if not _inside_package(dest):
        raise PromotionError(f'{dest} is outside the package.')
    rel = package.relpath(dest)
    if dest.exists() or utils.abspath(dest) in planned:
        raise PromotionError(f'{rel} already exists; pick another name.')
    if any(_same_file(dest, other) for other in taken):
        raise PromotionError(f'{rel} is already copied by {sink.name}.')
    owners = [
        g
        for g in sinks.matching_globs(dest)
        if not (sink.kind == GLOB and g == sink.name)
    ]
    if owners:
        raise PromotionError(
            f'{rel} matches the glob of test group {owners[0]}, so it would be '
            'one of its tests too; pick another path.'
        )


# --- applying -----------------------------------------------------------------


def check_plan(plan: Plan) -> Optional[str]:
    """Why ``plan`` no longer applies to the disk, or None when it does."""
    for change in plan.changes:
        rel = package.relpath(change.path)
        if change.action == CREATE and change.path.exists():
            return f'{rel} appeared since the promotion was planned.'
        if change.action == DELETE and not change.path.exists():
            return f'{rel} is gone since the promotion was planned.'
        if change.action == MODIFY:
            now = change.path.read_text() if change.path.is_file() else ''
            if now != change.before:
                return f'{rel} changed since the promotion was planned.'
    return None


def apply_plan(plan: Plan) -> None:
    """Write ``plan``: creates, then modifications, then deletions.

    In that order so a failure part-way never loses the only copy of a test:
    a moved input exists in its new place before its old one goes.
    """
    error = check_plan(plan)
    if error is not None:
        raise PromotionError(error)
    for change in plan.changes:
        if change.action != CREATE:
            continue
        change.path.parent.mkdir(parents=True, exist_ok=True)
        if change.source is not None:
            shutil.copyfile(change.source, change.path)
        else:
            change.path.write_text(change.after or '')
    for change in plan.changes:
        if change.action == MODIFY:
            change.path.write_text(change.after or '')
    for change in plan.changes:
        if change.action == DELETE:
            change.path.unlink()
    package_utils.clear_package_cache()
