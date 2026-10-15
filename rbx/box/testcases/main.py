import contextlib
import datetime
import functools
import json
import os
import pathlib
import shlex
import sys
from typing import Annotated, Any, Dict, List, NoReturn, Optional, TextIO, Tuple, Union

import syncer
import typer

from rbx import annotations, config, utils
from rbx.annotations import PackagePath
from rbx.box import (
    package,
    promotion,
    promotion_plan,
    promotion_sinks,
    stress_manifest,
    testcase_selectors,
    validators,
)
from rbx.box.generators import (
    GenerationTestcaseEntry,
    generate_outputs_for_testcases,
    generate_standalone,
)
from rbx.box.schema import TestcaseGroup
from rbx.box.testcase_extractors import (
    extract_generation_testcases,
    extract_generation_testcases_from_groups,
    extract_generation_testcases_from_patterns,
)
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testcase_utils import TestcasePattern
from rbx.console import console, stderr_console

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


async def _find_testcase(entry: TestcaseEntry) -> GenerationTestcaseEntry:
    extracted = await extract_generation_testcases([entry])
    if not extracted:
        console.print(f'[error]Testcase [item]{entry}[/item] not found.[/error]')
        raise typer.Exit(1)
    return extracted[0]


def _should_generate_output(entry: GenerationTestcaseEntry) -> bool:
    return (
        entry.metadata.copied_from is None
        or entry.metadata.copied_from.outputPath is None
    ) and package.get_main_solution() is not None


async def _generate_input_for_editing(
    entry: GenerationTestcaseEntry,
    output: bool = True,
    progress: Optional[utils.StatusProgress] = None,
) -> pathlib.Path:
    if (
        output and _should_generate_output(entry)
    ) or entry.metadata.copied_from is None:
        await generate_standalone(
            entry.metadata,
            validate=False,
            group_entry=entry.group_entry,
            progress=progress,
        )
    if entry.metadata.copied_from is not None:
        return entry.metadata.copied_from.inputPath
    return entry.metadata.copied_to.inputPath


async def _generate_output_for_editing(
    entry: GenerationTestcaseEntry,
    progress: Optional[utils.StatusProgress] = None,
) -> Optional[pathlib.Path]:
    if (
        entry.metadata.copied_from is not None
        and entry.metadata.copied_from.outputPath is not None
    ):
        return entry.metadata.copied_from.outputPath
    if not _should_generate_output(entry):
        return None
    await generate_outputs_for_testcases([entry.group_entry], progress=progress)
    return entry.metadata.copied_to.outputPath


async def _generate_for_editing(
    entry: GenerationTestcaseEntry,
    input: bool,
    output: bool,
    progress: Optional[utils.StatusProgress] = None,
) -> List[pathlib.Path]:
    res = []
    input_path = await _generate_input_for_editing(
        entry, output=output, progress=progress
    )
    if input:
        res.append(input_path)
    if output:
        output_path = await _generate_output_for_editing(entry, progress=progress)
        if output_path is not None:
            res.append(output_path)
    return res


async def _entries_for_selectors(
    selectors: List[str],
) -> List[GenerationTestcaseEntry]:
    """:func:`testcase_selectors.entries_for_selectors`, failing the command."""
    try:
        return await testcase_selectors.entries_for_selectors(selectors)
    except testcase_selectors.SelectorError as e:
        _fail(str(e))


@app.command('view, v', help='View a testcase in your default editor.')
@package.within_problem
@syncer.sync
async def view(
    tc: Annotated[
        str,
        typer.Argument(help='Testcase to view. Format: [group]/[index].'),
    ],
    input_only: bool = typer.Option(
        False,
        '--input',
        '-i',
        help='Whether to open only the input file in the editor.',
    ),
    output_only: bool = typer.Option(
        False,
        '--output',
        '-o',
        help='Whether to open only the output file in the editor.',
    ),
):
    if input_only and output_only:
        console.print(
            '[error]Flags --input and --output cannot be used together.[/error]'
        )
        raise typer.Exit(1)

    entry = TestcaseEntry.parse(tc)
    testcase = await _find_testcase(entry)

    with utils.StatusProgress('Preparing testcase...') as s:
        items = await _generate_for_editing(
            testcase, input=not output_only, output=not input_only, progress=s
        )
    config.edit_multiple(items, readonly=True)


async def _validate_generated(
    entry: GenerationTestcaseEntry,
    input_path: pathlib.Path,
    progress: Optional[utils.StatusProgress] = None,
) -> List[validators.TestcaseValidationInfo]:
    all_validators = ([entry.validator] if entry.validator is not None else []) + list(
        entry.extra_validators
    )
    digests = await validators.compile_validators(all_validators, progress=progress)
    if progress:
        progress.update('Validating test...')
    return await validators.validate_one_off(
        input_path,
        all_validators,
        digests,
        generation_metadata=entry.metadata,
        testcase_entry=entry.group_entry,
    )


async def _generate(
    selector: str, output: bool, validate: bool, json_out: Optional[TextIO]
) -> None:
    entries = await _entries_for_selectors([selector])
    if not entries:
        _fail(f'No test matches [item]{selector}[/item].')
    if len(entries) > 1:
        _fail(
            f'[item]{selector}[/item] matches {len(entries)} tests; '
            'name exactly one, as [group]/[index] or [script]:[line].'
        )
    entry = entries[0]

    answer_path: Optional[pathlib.Path] = None
    infos: Optional[List[validators.TestcaseValidationInfo]] = None
    with utils.StatusProgress('Generating test...') as s:
        input_path = await _generate_input_for_editing(entry, output=output, progress=s)
        if output:
            answer_path = await _generate_output_for_editing(entry, progress=s)
        if validate:
            infos = await _validate_generated(entry, input_path, progress=s)
    valid = infos is None or all(info.ok for info in infos)

    if json_out is not None:
        md = entry.metadata
        print(
            json.dumps(
                {
                    'test': str(entry.group_entry),
                    'source': (
                        f'{package.relpath(md.generator_script.path).as_posix()}:'
                        f'{md.generator_script.line}'
                        if md.generator_script is not None
                        else None
                    ),
                    'call': (
                        str(md.generator_call)
                        if md.generator_call is not None
                        else None
                    ),
                    'input': str(utils.abspath(input_path)),
                    'answer': (
                        str(utils.abspath(answer_path))
                        if answer_path is not None
                        else None
                    ),
                    'validation': (
                        None
                        if infos is None
                        else [
                            {
                                'validator': info.validator.path.as_posix(),
                                'ok': info.ok,
                                'message': info.message or None,
                            }
                            for info in infos
                        ]
                    ),
                }
            ),
            file=json_out,
        )
    else:
        console.print(
            f'[success]Generated [item]{entry.group_entry}[/item] at '
            f'[item]{package.relpath(input_path)}[/item].[/success]'
        )
        if answer_path is not None:
            console.print(f'Answer at [item]{package.relpath(answer_path)}[/item].')
        for info in infos or []:
            if info.ok:
                console.print(
                    f'[success]Validator {info.validator.href()} accepted it.[/success]'
                )
                continue
            console.print(
                f'[error]Validator {info.validator.href()} rejected it.[/error]'
            )
            if info.message:
                console.print(utils.escape_markup(info.message.strip()))
        if infos == []:
            console.print('[warning]No validator applies to this test.[/warning]')
    if not valid:
        raise typer.Exit(1)


@app.command(
    'generate, g',
    help='Generate a single test, without building the rest of the testset.',
)
@package.within_problem
@syncer.sync
async def generate(
    selector: Annotated[
        str,
        typer.Argument(
            help='Test to generate, as [group]/[index] or as [script]:[line], the '
            'line of a generator script its statement starts on.'
        ),
    ],
    output: Annotated[
        bool,
        typer.Option(
            '--output',
            '-o',
            help='Also generate the answer, by running the main solution.',
        ),
    ] = False,
    validate: Annotated[
        bool,
        typer.Option(
            '--validate',
            '-v',
            help="Run the test group's validators on the input; "
            'exit with an error if any rejects it.',
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option('--json', help='Print the result as JSON on stdout.'),
    ] = False,
):
    if not as_json:
        await _generate(selector, output, validate, json_out=None)
        return
    # Everything else printed on the way goes to stderr, so stdout parses as JSON.
    json_out = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        await _generate(selector, output, validate, json_out=json_out)


@app.command('info, i', help='Show information about testcases.')
@package.within_problem
@syncer.sync
async def info(
    pattern: Annotated[
        Optional[str],
        typer.Argument(
            help='Testcases to detail, as a pattern. Might be a group, or a specific test in the format [group]/[index].'
        ),
    ] = None,
):
    tc_pattern = TestcasePattern.parse(pattern or '*')
    testcases = await extract_generation_testcases_from_patterns([tc_pattern])
    if not testcases:
        console.print(
            f'[error]No testcases found matching pattern [item]{pattern}[/item].[/error]'
        )
        raise typer.Exit(1)

    for testcase in testcases:
        console.print(f'[status]Identifier:[/status] {testcase.group_entry}')
        if testcase.metadata.generator_call is not None:
            console.print(
                f'[status]Generator call:[/status] {testcase.metadata.generator_call}'
            )
        if testcase.metadata.copied_from is not None:
            console.print(
                f'[status]Input file:[/status] {testcase.metadata.copied_from.inputPath}'
            )
            if testcase.metadata.copied_from.outputPath is not None:
                console.print(
                    f'[status]Output file:[/status] {testcase.metadata.copied_from.outputPath}'
                )

        if testcase.metadata.generator_script is not None:
            console.print(
                f'[status]Generator script:[/status] {testcase.metadata.generator_script.path}, line {testcase.metadata.generator_script.line}'
            )
        console.print()


def _promote_source_label(entry: GenerationTestcaseEntry) -> str:
    """Source descriptor for a test, e.g.
    ``gen/0 (gens/gen.cpp 123) [testplan.txt:5]`` -- the identifier and
    generator call (from ``full_repr()``) plus the originating script location.
    """
    label = entry.full_repr()
    gse = entry.metadata.generator_script
    if gse is not None:
        label = f'{label} [{package.relpath(gse.path)}:{gse.line}]'
    return label


def _label(item: Union[GenerationTestcaseEntry, promotion_plan.Source]) -> str:
    """How a test is shown while promoting it."""
    if isinstance(item, GenerationTestcaseEntry):
        return _promote_source_label(item)
    if item.entry is not None:
        return _promote_source_label(item.entry)
    return item.selector


class _FilenameEditorState:
    """Mutable state for the batch filename editor.

    Holds one editable stem buffer per test being promoted to a file, the
    focused row, and the fixed text around the pattern's last ``*`` used to
    render each row's full-path preview.
    """

    def __init__(
        self,
        entries: List[Union[GenerationTestcaseEntry, promotion_plan.Source]],
        glob: str,
        defaults: List[str],
    ):
        self.entries = entries
        self.glob = glob
        # The fixed text around the glob's last '*' (e.g. 'manual_tests/manual-'
        # and '.in'); the stem is what the user edits between them.
        head, _, tail = glob.rpartition('*')
        self.prefix = head
        self.suffix = tail
        self.stems: List[str] = list(defaults)
        self.cursor: int = 0
        self.done: bool = False

    def current_stem(self) -> str:
        return self.stems[self.cursor]

    def move(self, delta: int) -> None:
        n = len(self.entries)
        if n:
            self.cursor = (self.cursor + delta) % n

    def type_char(self, data: str) -> None:
        self.stems[self.cursor] += data

    def backspace(self) -> None:
        self.stems[self.cursor] = self.stems[self.cursor][:-1]

    def error(self) -> Optional[str]:
        return promotion.validate_stems(self.stems)

    def render_fragments(self):
        """prompt_toolkit formatted-text fragments: list of (style, text)."""
        fragments = []
        width = max((len(_label(e)) for e in self.entries), default=0)
        for i, entry in enumerate(self.entries):
            selected = i == self.cursor
            pointer = '> ' if selected else '  '
            row_style = 'class:current' if selected else 'class:row'
            source = _label(entry).ljust(width)
            fragments.append((row_style, f'{pointer}{source}  ->  '))
            fragments.append(('class:fixed', self.prefix))
            stem_style = 'class:stem-current' if selected else 'class:stem'
            fragments.append((stem_style, self.stems[i] or ' '))
            fragments.append(('class:fixed', self.suffix))
            fragments.append((row_style, '\n'))
        return fragments


async def _edit_filenames(
    target: Union[str, TestcaseGroup],
    chosen_entries: List[Union[GenerationTestcaseEntry, promotion_plan.Source]],
    input=None,
    output=None,
    defaults: Optional[List[str]] = None,
) -> Optional[List[Tuple[Any, str]]]:
    """Batch-edit the destination filenames for the selected tests.

    ``target`` is the ``*`` pattern the files follow (or a glob group, for
    its glob). Shows one row per test with its source (read-only) and an
    editable filename stem, pre-filled with ``defaults`` (sequential glob-aware
    counters when not given). The full relative path is rendered live around
    the stem. Returns the list of ``(entry, stem)`` pairs on submit, or
    ``None`` if the user aborts (Esc / Ctrl-C) or there is nothing to name.
    """
    if not chosen_entries:
        return None

    if isinstance(target, str):
        glob = target
    else:
        assert target.testcaseGlob is not None
        glob = target.testcaseGlob
    if defaults is None:
        defaults = promotion.default_stems(glob, len(chosen_entries))
    state = _FilenameEditorState(chosen_entries, glob, defaults)

    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    HEADER_LINES = [
        'Edit the filename for each promoted test:',
        'Tab/↓ next · Shift-Tab/↑ prev · type to edit · enter confirm · esc cancel',
    ]

    def _header_fragments():
        return [
            ('class:header' if i == 0 else 'class:hint', line + '\n')
            for i, line in enumerate(HEADER_LINES)
        ]

    def _status_fragments():
        if state.done:
            return []
        error = state.error()
        if error:
            return [('class:error', f'⚠ {error}\n')]
        return [('class:ok', 'Press enter to confirm.\n')]

    header = FormattedTextControl(_header_fragments)
    body = FormattedTextControl(
        state.render_fragments, focusable=True, show_cursor=False
    )
    status = FormattedTextControl(_status_fragments)

    kb = KeyBindings()

    @kb.add('up')
    @kb.add('s-tab')
    def _(event):
        state.move(-1)

    @kb.add('down')
    @kb.add('tab')
    def _(event):
        state.move(1)

    @kb.add('backspace')
    def _(event):
        state.backspace()

    @kb.add('enter')
    def _(event):
        # Block submit while the batch is invalid (empty/duplicate names).
        if state.error() is not None:
            return
        state.done = True
        event.app.exit(result=list(zip(state.entries, state.stems)))

    @kb.add('escape', eager=True)
    @kb.add('c-c')
    def _(event):
        event.app.exit(result=None)

    @kb.add('<any>')
    def _(event):
        # Only printable, non-whitespace single characters edit the focused
        # stem; control keys, whitespace (which would yield an awkward
        # filename), and multi-char sequences are ignored.
        if (
            len(event.data) == 1
            and event.data.isprintable()
            and not event.data.isspace()
        ):
            state.type_char(event.data)

    layout = Layout(
        HSplit(
            [
                Window(
                    content=header,
                    height=len(HEADER_LINES),
                    always_hide_cursor=True,
                ),
                Window(
                    content=body,
                    height=len(chosen_entries),
                    always_hide_cursor=True,
                ),
                Window(content=status, height=1, always_hide_cursor=True),
            ]
        )
    )
    style = Style.from_dict(
        {
            'header': 'bold',
            'hint': 'ansibrightblack',
            'current': 'bold',
            'row': '',
            'fixed': 'ansibrightblack',
            'stem': 'ansicyan',
            'stem-current': 'ansicyan bold reverse',
            'error': 'ansired bold',
            'ok': 'ansibrightblack',
        }
    )
    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        input=input,
        output=output,
    )
    return await app.run_async()


def _fail(message: str) -> NoReturn:
    # stderr, so that with --json stdout carries the result and nothing else.
    stderr_console.print(f'[error]{message}[/error]')
    raise typer.Exit(1)


def _inside_package(path: pathlib.Path) -> bool:
    # The cwd is the package root here (`within_problem`).
    root = pathlib.Path.cwd().resolve()
    return pathlib.Path(os.path.abspath(path)).resolve().is_relative_to(root)


def _check_new_script(path: pathlib.Path, all_groups: Dict[str, Any]) -> pathlib.Path:
    """Validate the path of --new-script; return it relative to the package."""
    if path.suffix not in ('', '.txt'):
        _fail(f'--new-script must name a .txt file (got [item]{path}[/item]).')
    path = path.with_suffix('.txt')
    if not _inside_package(path):
        _fail(f'--new-script must be inside the package (got [item]{path}[/item]).')
    path = package.relpath(path)

    error = promotion.group_name_error(path.stem)
    if error is not None:
        _fail(f'Cannot name a group after [item]{path}[/item]: {error}')
    if path.stem in all_groups:
        _fail(f'Test group [item]{path.stem}[/item] already exists.')
    for name, other in all_groups.items():
        gs = other.generatorScript
        if gs is not None and package.relpath(gs.path) == path:
            _fail(
                f'[item]{path}[/item] is already the generator script of '
                f'test group [item]{name}[/item].'
            )
    return path


def _check_new_manual(name: str, glob: str, all_groups: Dict[str, Any]) -> None:
    """Validate --new-manual and --glob."""
    error = promotion.group_name_error(name)
    if error is not None:
        _fail(error)
    if name in all_groups:
        _fail(f'Test group [item]{name}[/item] already exists.')
    if '*' not in glob or not glob.endswith('.in'):
        _fail(
            'The glob of a manual group must contain a `*` and end in '
            f'`.in` (got [item]{glob}[/item]).'
        )
    if not _inside_package(pathlib.Path(glob.split('*')[0] or '.')):
        _fail(f'--glob must be inside the package (got [item]{glob}[/item]).')


def _new_group(
    new_manual: Optional[str],
    glob: Optional[str],
    new_script: Optional[pathlib.Path],
) -> Optional[promotion_plan.NewGroup]:
    """The group --new-manual/--glob or --new-script asks for, validated."""
    all_groups = package.get_test_groups_by_name()
    if new_manual is not None:
        assert glob is not None
        _check_new_manual(new_manual, glob, all_groups)
        return promotion_plan.NewGroup(name=new_manual, glob=glob)
    if new_script is not None:
        path = _check_new_script(new_script, all_groups)
        return promotion_plan.NewGroup(name=path.stem, script=path)
    return None


def _sink_or_fail(name: str) -> promotion_sinks.Sink:
    sink = promotion_sinks.find_sink(name)
    if sink is not None:
        return sink
    if name in package.get_test_groups_by_name():
        _fail(
            f'Test group [item]{name}[/item] cannot take promoted tests: only a '
            'manual group (a `testcaseGlob` ending in `.in`) or a group with a '
            '`.txt` `generatorScript` can.'
        )
    _fail(f'Test group [item]{name}[/item] does not exist.')


def _ordered_sinks(
    sources: List[promotion_plan.Source],
) -> List[promotion_sinks.Sink]:
    """Sinks in picker order: where the tests already live, then the samples,
    then the rest as the package lists them."""
    all_sinks = promotion_sinks.list_sinks()

    def rank(sink: promotion_sinks.Sink) -> int:
        if promotion_plan.in_place(sink, sources):
            return 0
        if sink.name == 'samples':
            return 1
        return 2

    return sorted(all_sinks, key=rank)


def _sink_rows(sources: List[promotion_plan.Source]) -> List[Dict[str, Any]]:
    rows = []
    for sink in _ordered_sinks(sources):
        forms = (
            promotion_plan.available_forms(sink, sources) if sources else sink.forms()
        )
        if not forms:
            continue
        suggested = None
        if promotion_sinks.COPY in forms:
            suggested, _ = promotion_plan.copy_layout(sink, 0)
        rows.append(
            {
                **promotion_plan.sink_json(sink),
                'forms': forms,
                'form': forms[0],
                'suggested': suggested,
                'inPlace': promotion_plan.in_place(sink, sources),
            }
        )
    return rows


async def _list_sinks(selectors: List[str], json_out: Optional[TextIO]) -> None:
    sources = await _resolve_sources(selectors) if selectors else []
    rows = _sink_rows(sources)
    if json_out is not None:
        print(json.dumps(rows), file=json_out)
        return
    if not rows:
        console.print('No test group can take promoted tests.')
        return
    for row in rows:
        where = f' @testgroup {row["scope"]}' if row['scope'] else ''
        here = ' [success](in place)[/success]' if row['inPlace'] else ''
        console.print(
            f'[item]{row["name"]}[/item] ({row["kind"]}): '
            f'{row["path"]}{where} -- {"/".join(row["forms"])}{here}'
        )


def _list_manual_groups(json_out: Optional[TextIO]) -> None:
    """The manual-group rows `promote --list-groups` printed before sinks.

    Kept, hidden, for clients that still ask for them.
    """
    rows = [
        {'name': name, 'kind': 'manual', 'path': group.testcaseGlob}
        for name, group in promotion.get_manual_groups_by_name().items()
    ]
    if json_out is not None:
        print(json.dumps(rows), file=json_out)
        return
    if not rows:
        console.print('No manual test group exists yet.')
        return
    for row in rows:
        console.print(f'[item]{row["name"]}[/item]: {row["path"]}')


async def _resolve_sources(selectors: List[str]) -> List[promotion_plan.Source]:
    try:
        return await promotion_plan.resolve_sources(selectors)
    except promotion_plan.PromotionError as e:
        _fail(str(e))


def _print_plan(plan: promotion_plan.Plan, applied: bool) -> None:
    for row in plan.promoted:
        what = 'generator call' if row.form == promotion_sinks.RECIPE else 'copy'
        if row.in_place:
            verb = 'Turned' if applied else 'Would turn'
            console.print(
                f'[success]{verb} [item]{row.source}[/item] into a {what} in '
                f'place ([item]{row.to}[/item]).[/success]'
            )
            continue
        verb = ('Moved' if row.moved else 'Copied') if applied else 'Would promote'
        console.print(
            f'[success]{verb} [item]{row.source}[/item] to '
            f'[item]{plan.sink.name}[/item] as a {what} '
            f'([item]{row.to}[/item]).[/success]'
        )
    for row in plan.skipped:
        console.print(
            f'[warning]Skipped [item]{row.source}[/item]: {row.reason}.[/warning]'
        )
    if not applied:
        for change in plan.changes:
            console.print(f'  {change.action} {package.relpath(change.path)}')


async def _pick_destination(
    sources: List[promotion_plan.Source],
) -> Union[promotion_sinks.Sink, promotion_plan.NewGroup, None]:
    """Interactively pick a sink, or a new group to create, or nothing."""
    import questionary

    sinks_by_name = {sink.name: sink for sink in _ordered_sinks(sources)}
    choice = await questionary.select(
        'Choose the test group to promote into:',
        choices=list(sinks_by_name)
        + [_NEW_MANUAL_CHOICE, _NEW_SCRIPT_CHOICE, _SKIP_CHOICE],
    ).ask_async()
    if choice is None or choice == _SKIP_CHOICE:
        return None
    if choice == _NEW_MANUAL_CHOICE:
        name = await questionary.text('Name for the new manual group:').ask_async()
        if name is None or not name.strip():
            return None
        glob = await questionary.text(
            'Glob for the new manual group (e.g. tests/manual/corner/*.in):'
        ).ask_async()
        if glob is None or not glob.strip():
            return None
        return _new_group(name.strip(), glob.strip(), None)
    if choice == _NEW_SCRIPT_CHOICE:
        path = await questionary.text(
            'Path of the new .txt generator script (e.g. tests/edge.txt):'
        ).ask_async()
        if path is None or not path.strip():
            return None
        return _new_group(None, None, pathlib.Path(path.strip()))
    return sinks_by_name[choice]


_NEW_MANUAL_CHOICE = '(create new manual group)'
_NEW_SCRIPT_CHOICE = '(create new script group)'
_SKIP_CHOICE = '(skip)'


async def _promote_interactively(
    sources: List[promotion_plan.Source],
    *,
    to: Optional[str],
    form: Optional[str],
    keep_source: bool,
) -> None:
    """Pick what is missing -- the destination, the form, the file names --
    then promote ``sources``."""
    import questionary

    new_group: Optional[promotion_plan.NewGroup] = None
    if to is not None:
        sink = _sink_or_fail(to)
    else:
        picked = await _pick_destination(sources)
        if picked is None:
            return
        if isinstance(picked, promotion_plan.NewGroup):
            new_group = picked
            sink = picked.sink()
        else:
            sink = picked

    if form is None:
        forms = promotion_plan.available_forms(sink, sources)
        if len(forms) > 1:
            labels = {
                promotion_sinks.RECIPE: 'as the generator call (regenerated on build)',
                promotion_sinks.COPY: 'as a @copy of its input (frozen)',
            }
            picked_form = await questionary.select(
                'Promote the tests:',
                choices=[questionary.Choice(labels[f], value=f) for f in forms],
            ).ask_async()
            if picked_form is None:
                return
            form = picked_form

    try:
        files = promotion_plan.copy_sources(sources, sink, form, keep_source)
    except promotion_plan.PromotionError as e:
        _fail(str(e))
    stems: Optional[List[str]] = None
    if files:
        pattern, defaults = promotion_plan.copy_layout(sink, len(files))
        # Edited OUTSIDE the live spinner: animating a Rich spinner while a
        # prompt_toolkit app is open causes redraw artifacts. Esc / Ctrl-C
        # writes nothing.
        named = await _edit_filenames(pattern, files, defaults=defaults)
        if named is None:
            return
        stems = [stem for _, stem in named]

    with utils.StatusProgress('Promoting tests...') as s:
        try:
            plan = await promotion_plan.plan_promotion(
                sources,
                None if new_group is not None else sink,
                new_group=new_group,
                form=form,
                keep_source=keep_source,
                stems=stems,
                progress=s,
            )
            promotion_plan.apply_plan(plan)
        except promotion_plan.PromotionError as e:
            _fail(str(e))
    _print_plan(plan, applied=True)


async def _promote_picked_tests(
    to: Optional[str], form: Optional[str], keep_source: bool
) -> None:
    """Interactively select tests, then promote them."""
    import questionary

    all_entries = await extract_generation_testcases_from_groups()
    if not all_entries:
        console.print('This problem has no tests to promote yet.')
        return

    # Labels are prefixed by the unique group/index, so they are unique and the
    # selected-label -> entry mapping is unambiguous.
    labels = [_promote_source_label(entry) for entry in all_entries]
    selected = await questionary.checkbox(
        'Select tests to promote:',
        choices=labels,
    ).ask_async()
    if not selected:
        return
    selected_set = set(selected)
    sources = [
        promotion_plan.source_from_entry(promotion_plan.entry_selector(entry), entry)
        for entry, label in zip(all_entries, labels)
        if label in selected_set
    ]
    await _promote_interactively(sources, to=to, form=form, keep_source=keep_source)


_PROMOTE_DOCS = """
    Promotes tests into a test group: a generated test into a file of its own,
    a stress finding or any input file into the testset, or a test from one
    group into another.

    Name the tests to promote as `[group]/[index]`, as `[script]:[line]` (the
    test whose statement starts on that line of a generator script),
    `finding:K` (finding K of the latest `rbx stress`) or `file:IN[:ANS]` (an
    input file, and optionally an answer to keep with it). With no tests, they
    are picked interactively.

    A test can go into any group whose `testcaseGlob` ends in `.in`, which
    gets a copy of its input, or any group with a `.txt` generator script,
    which gets a line: the generator call that makes the test, or a `@copy` of
    its input file. `--as` picks one; the default is the call when the test
    has one. A `@copy` file goes where the other `@copy` lines of the group
    suggest, which `--path` overrides. When several groups share the script,
    the line goes into the group's `@testgroup` block.

    A test whose statement is already in the group's script is changed in
    place, so `--as copy` on a generator call freezes it into a `@copy`.
    Anything else lands at the end of the group, and is removed from where it
    was unless `--keep-source` is given. `--dry-run` shows the changes without
    making them; `--list-sinks` lists where the tests can go.
"""


async def _promote(
    *,
    selectors: List[str],
    to: Optional[str],
    new_manual: Optional[str],
    glob: Optional[str],
    new_script: Optional[pathlib.Path],
    form: Optional[str],
    name: Optional[str],
    path: Optional[str],
    keep_source: bool,
    dry_run: bool,
    list_sinks: bool,
    list_groups: bool,
    json_out: Optional[TextIO],
    session: Optional[str] = None,
) -> None:
    destinations = [d for d in (to, new_manual, new_script) if d is not None]
    if list_groups:
        if selectors or destinations or glob is not None or name:
            _fail('--list-groups takes no tests, destination, --glob or --name.')
        _list_manual_groups(json_out)
        return
    if list_sinks:
        if destinations or glob is not None or name or path or dry_run:
            _fail('--list-sinks takes only the tests to promote.')
        await _list_sinks(selectors, json_out)
        return
    if len(destinations) > 1:
        _fail('Pass at most one of --to, --new-manual or --new-script.')
    if glob is not None and new_manual is None:
        _fail('--glob only applies to --new-manual.')
    if new_manual is not None and glob is None:
        _fail('--new-manual needs a --glob for the files of the new group.')
    if form is not None and form not in (
        promotion_sinks.RECIPE,
        promotion_sinks.COPY,
    ):
        _fail(f'--as must be `recipe` or `copy` (got [item]{form}[/item]).')

    if not selectors:
        if json_out is not None or dry_run or new_manual or new_script:
            _fail(
                'Name the tests to promote to use --json, --dry-run, '
                '--new-manual or --new-script.'
            )
        if to is not None:
            _sink_or_fail(to)
        await _promote_picked_tests(to, form, keep_source)
        return

    if session is not None:
        manifest = stress_manifest.read_manifest()
        if manifest is None or not _is_session(manifest, session):
            _fail(
                'The stress session changed since you picked this finding; '
                'promote it again from the new session.'
            )
    new_group = _new_group(new_manual, glob, new_script)
    sink = _sink_or_fail(to) if to is not None else None

    with utils.StatusProgress('Promoting tests...') as s:
        sources = await _resolve_sources(selectors)
        if name is not None and len(sources) > 1:
            console.print(
                '[warning]--name is ignored when promoting more than one test; '
                'using auto-generated names.[/warning]'
            )
            name = None
        if sink is None and new_group is None:
            if json_out is not None or dry_run:
                _fail(
                    'Pass --to, --new-manual or --new-script to use --json or '
                    '--dry-run.'
                )
            plan = None
        else:
            try:
                plan = await promotion_plan.plan_promotion(
                    sources,
                    sink,
                    new_group=new_group,
                    form=form,
                    name=name,
                    path=path,
                    keep_source=keep_source,
                    progress=s,
                )
                if not dry_run:
                    promotion_plan.apply_plan(plan)
            except promotion_plan.PromotionError as e:
                _fail(str(e))

    if plan is None:
        await _promote_interactively(
            sources, to=None, form=form, keep_source=keep_source
        )
        return
    if json_out is not None:
        print(json.dumps(plan.to_json()), file=json_out)
        return
    _print_plan(plan, applied=not dry_run)


@app.command(
    'promote',
    help='Promote tests into a test group: as files, generator calls or @copy lines.',
)
@annotations.docs(_PROMOTE_DOCS)
@package.within_problem
@syncer.sync
async def promote(
    selectors: Annotated[
        Optional[List[str]],
        typer.Argument(
            help='Tests to promote: [group]/[index], [script]:[line], finding:K '
            'or file:IN[:ANS]. If omitted, tests are selected interactively.',
            metavar='TEST',
            show_default=False,
        ),
    ] = None,
    to: Annotated[
        Optional[str],
        typer.Option(
            '--to',
            '--group',
            '-G',
            help='Test group (or group/subgroup) to promote into.',
            autocompletion=annotations._adapt('testgroup'),  # noqa: SLF001
        ),
    ] = None,
    form: Annotated[
        Optional[str],
        typer.Option(
            '--as',
            help='Promote into a generator script as `recipe` (the generator '
            'call) or `copy` (a @copy of the input). Default: the call, when '
            'the test has one.',
            show_default=False,
        ),
    ] = None,
    name: Annotated[
        Optional[str],
        typer.Option(
            '--name',
            '-n',
            help='File name, without `.in`, of the promoted input. '
            'Only meaningful when promoting exactly one test.',
        ),
    ] = None,
    path: Annotated[
        Optional[str],
        typer.Option(
            '--path',
            help='Where a @copy file goes, instead of where the group suggests: '
            'a file, or a pattern whose `*` is filled with the next free name.',
        ),
    ] = None,
    keep_source: Annotated[
        bool,
        typer.Option(
            '--keep-source',
            help='Copy the tests instead of moving them: leave their statement '
            'or file where it is.',
        ),
    ] = False,
    new_manual: Annotated[
        Optional[str],
        typer.Option(
            '--new-manual',
            help='Create a manual group with this name (needs --glob), '
            'and promote the tests into it.',
        ),
    ] = None,
    glob: Annotated[
        Optional[str],
        typer.Option(
            '--glob',
            help='Glob of the group --new-manual creates, e.g. tests/manual/*.in.',
        ),
    ] = None,
    new_script: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            '--new-script',
            help='Create a generator script group backed by this .txt file, '
            'and promote the tests into it.',
        ),
        PackagePath,
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            '--dry-run',
            help='Show what would change, without changing it.',
        ),
    ] = False,
    list_sinks: Annotated[
        bool,
        typer.Option(
            '--list-sinks',
            help='List the test groups the tests can be promoted into, and exit.',
        ),
    ] = False,
    list_groups: Annotated[
        bool,
        typer.Option('--list-groups', hidden=True),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option('--json', help='Print the result as JSON on stdout.'),
    ] = False,
    session: Annotated[
        Optional[str],
        typer.Option(
            '--session',
            help='The startedAt of the stress session finding:K was picked '
            'from; refuse to run if the latest session is another one.',
            hidden=True,
        ),
    ] = None,
):
    run = functools.partial(
        _promote,
        session=session,
        selectors=selectors or [],
        to=to,
        new_manual=new_manual,
        glob=glob,
        new_script=new_script,
        form=form,
        name=name,
        path=path,
        keep_source=keep_source,
        dry_run=dry_run,
        list_sinks=list_sinks,
        list_groups=list_groups,
    )
    if not as_json:
        await run(json_out=None)
        return
    # Everything else printed on the way goes to stderr, so stdout parses as JSON.
    json_out = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        await run(json_out=json_out)


# --- add-finding ----------------------------------------------------------------

_DRY_RUN_ONLY_FOR_SCRIPTS = (
    '--dry-run only applies to a generator script group passed with --group.'
)


def _stress_comment(spec: stress_manifest.StressSpec) -> str:
    """The command that runs the session again, as a one-line comment."""
    args = ['rbx', 'stress']
    if spec.name is not None:
        args.append(spec.name)
    else:
        if spec.generator is not None:
            args += ['-g', spec.generator]
        if spec.fuzz is not None:
            if spec.fuzz:
                for fuzzed in spec.fuzz:
                    args += ['--fuzz-on', fuzzed]
            else:
                args.append('--fuzz')
        args += ['-f', spec.finder]
    command = shlex.join(args).replace('\r', ' ').replace('\n', ' ')
    return f'Found by: {command}'


def _is_session(manifest: stress_manifest.StressManifest, session: str) -> bool:
    """Whether `session` (an ISO 8601 `startedAt`) names `manifest`'s session.

    Compares datetimes, not strings, so `2026-10-15T12:00:00+00:00` and
    `2026-10-15T12:00:00Z` match. A naive value never equals an aware one.
    """
    value = session.strip()
    if value.endswith(('Z', 'z')):
        # `fromisoformat` only accepts a `Z` suffix from Python 3.11 on.
        value = value[:-1] + '+00:00'
    try:
        return datetime.datetime.fromisoformat(value) == manifest.startedAt
    except ValueError:
        return False


def _selected_findings(
    indices: Optional[List[int]],
    session: Optional[str] = None,
) -> Tuple[stress_manifest.StressManifest, List[stress_manifest.StressFindingEntry]]:
    """The latest session and the findings `indices` name (all when empty).

    With `session`, the latest session must be that one: a client that picked
    findings by index must not promote another session's findings under the
    same numbers.
    """
    manifest = stress_manifest.read_manifest()
    if manifest is None:
        _fail(
            'There is no stress session to take findings from. '
            'Run [item]rbx stress[/item] first.'
        )
    if session is not None and not _is_session(manifest, session):
        _fail(
            'The stress session changed since you picked this finding; '
            'promote it again from the new session.'
        )
    if not manifest.findings:
        _fail('The latest stress session found nothing.')
    if not indices:
        return manifest, list(manifest.findings)

    by_index = {finding.index: finding for finding in manifest.findings}
    unknown = [k for k in indices if k not in by_index]
    if unknown:
        known = ', '.join(str(k) for k in sorted(by_index))
        _fail(
            f'Unknown finding [item]{unknown[0]}[/item] '
            f'(the latest stress session has: {known}).'
        )
    return manifest, [by_index[k] for k in dict.fromkeys(indices)]


def _finding_sources(
    findings: List[stress_manifest.StressFindingEntry], need_inputs: bool
) -> List[promotion_plan.Source]:
    sources = []
    for finding in findings:
        path = stress_manifest.finding_input_path(finding.index)
        if need_inputs and not path.is_file():
            _fail(
                f'Could not find the input of finding [item]{finding.index}[/item] '
                f'at [item]{path}[/item].'
            )
        sources.append(
            promotion_plan.Source(
                selector=f'finding:{finding.index}',
                recipe=finding.generator,
                input_path=path,
                copy_only=True,
                dedup=True,
            )
        )
    return sources


def _list_groups(json_out: Optional[TextIO]) -> None:
    rows = []
    for sink in promotion_sinks.list_sinks():
        kind = 'manual' if sink.kind == promotion_sinks.GLOB else 'script'
        rows.append({'name': sink.name, 'kind': kind, 'path': sink.path})
    # Script groups first, as add-finding always listed them.
    rows.sort(key=lambda row: row['kind'] != 'script')

    if json_out is not None:
        print(json.dumps(rows), file=json_out)
        return
    if not rows:
        console.print('No test group can take stress findings.')
        return
    for row in rows:
        console.print(f'[item]{row["name"]}[/item] ({row["kind"]}): {row["path"]}')


@app.command(
    'add-finding',
    help='Add findings of the latest stress session to a test group.',
)
@annotations.docs("""
    Adds tests found by the latest `rbx stress` session to a test group: the
    non-interactive counterpart of the prompt `rbx stress` shows when it ends,
    and the same as `rbx testcases promote finding:K`.

    Name the findings by their number in the stress report (from 1), or omit
    them to add all of them. What the group receives depends on its kind:

    - A `.txt` generator script group gets the generator call of each finding
      added, under a comment with the `rbx stress` command that found it.
      The test is generated again on the next build, so it stays reproducible.
    - A manual group (one declared with `testcaseGlob`) gets a copy of each
      finding's input, under the next free name its glob allows.

    A finding the group already has -- the same generator call, or an input
    with the same bytes -- is skipped, so adding the same findings twice is
    harmless.

    `--new-script` and `--new-manual` create the group first. `--dry-run`
    shows what the file of a script group would become without writing it,
    and `--list-groups` lists the groups that can take findings. With
    `--json`, the command prints its result as JSON on stdout and nothing else.
""")
@package.within_problem
@syncer.sync
async def add_finding(
    indices: Annotated[
        Optional[List[int]],
        typer.Argument(
            help='Findings to add, by their number in the stress report (from 1). '
            'All of them if omitted.',
            metavar='K',
            show_default=False,
        ),
    ] = None,
    group: Annotated[
        Optional[str],
        typer.Option(
            '--group',
            '-G',
            help='Existing test group to add the findings to: a .txt generator '
            'script group or a manual group.',
            autocompletion=annotations._adapt('testgroup'),  # noqa: SLF001
        ),
    ] = None,
    new_script: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            '--new-script',
            help='Create a generator script group backed by this .txt file, '
            'and append the findings to it.',
        ),
        PackagePath,
    ] = None,
    new_manual: Annotated[
        Optional[str],
        typer.Option(
            '--new-manual',
            help='Create a manual group with this name (needs --glob), '
            'and copy the findings into it.',
        ),
    ] = None,
    glob: Annotated[
        Optional[str],
        typer.Option(
            '--glob',
            help='Glob of the group --new-manual creates, '
            'e.g. tests/manual/stress/*.in.',
        ),
        PackagePath,
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            '--dry-run',
            help='Show how the generator script of --group would change, '
            'without writing it (script groups only).',
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option('--json', help='Print the result as JSON on stdout.'),
    ] = False,
    list_groups: Annotated[
        bool,
        typer.Option(
            '--list-groups',
            help='List the test groups that can take findings, and exit.',
        ),
    ] = False,
    session: Annotated[
        Optional[str],
        typer.Option(
            '--session',
            help='The startedAt of the stress session the findings were picked '
            'from; refuse to run if the latest session is another one.',
            hidden=True,
        ),
    ] = None,
):
    run = functools.partial(
        _add_finding,
        indices=indices,
        group=group,
        new_script=new_script,
        new_manual=new_manual,
        glob=glob,
        dry_run=dry_run,
        list_groups=list_groups,
        session=session,
    )
    if not as_json:
        await run(json_out=None)
        return
    # Whatever else gets printed on the way -- including by the helpers this
    # calls -- goes to stderr, so stdout parses as JSON. `within_problem` prints
    # its issue report after this returns, outside the redirect: safe today, as
    # add-finding records no issues.
    json_out = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        await run(json_out=json_out)


async def _add_finding(
    *,
    indices: Optional[List[int]],
    group: Optional[str],
    new_script: Optional[pathlib.Path],
    new_manual: Optional[str],
    glob: Optional[str],
    dry_run: bool,
    list_groups: bool,
    session: Optional[str],
    json_out: Optional[TextIO],
) -> None:
    destinations = [d for d in (group, new_script, new_manual) if d is not None]
    if list_groups:
        if destinations or indices or dry_run or glob is not None:
            _fail('--list-groups takes no findings, destination or --glob.')
        _list_groups(json_out)
        return

    if len(destinations) != 1:
        _fail('Pass exactly one of --group, --new-script or --new-manual.')
    if glob is not None and new_manual is None:
        _fail('--glob only applies to --new-manual.')
    if new_manual is not None and glob is None:
        _fail('--new-manual needs a --glob for the files of the new group.')
    if dry_run and group is None:
        _fail(_DRY_RUN_ONLY_FOR_SCRIPTS)

    manifest, findings = _selected_findings(indices, session)
    new_group = _new_group(new_manual, glob, new_script)
    if new_group is not None:
        sink = new_group.sink()
    else:
        assert group is not None
        sink = _sink_or_fail(group)
    kind = 'manual' if sink.kind == promotion_sinks.GLOB else 'script'
    if dry_run and kind != 'script':
        _fail(_DRY_RUN_ONLY_FOR_SCRIPTS)

    sources = _finding_sources(findings, need_inputs=kind == 'manual')
    try:
        plan = await promotion_plan.plan_promotion(
            sources,
            None if new_group is not None else sink,
            new_group=new_group,
            comment=_stress_comment(manifest.spec),
        )
    except promotion_plan.PromotionError as e:
        _fail(str(e))
    skipped = {row.source for row in plan.skipped}
    fresh = [source.selector not in skipped for source in sources]

    if dry_run:
        assert sink.script is not None
        script = utils.abspath(pathlib.Path(sink.script.path))
        change = next((c for c in plan.changes if c.path == script), None)
        before = after = script.read_text() if script.is_file() else ''
        if change is not None:
            before, after = change.before or '', change.after or ''
        if json_out is not None:
            print(
                json.dumps({'file': str(script), 'before': before, 'after': after}),
                file=json_out,
            )
            return
        new_count = sum(fresh)
        if new_count:
            console.print(
                f'Would append [item]{new_count}[/item] tests to '
                f'[item]{package.relpath(script)}[/item]:'
            )
            added = after[len(before) :] if after.startswith(before) else after
            console.print(added.strip('\n'), markup=False)
        _print_skipped(findings, fresh, sink.name)
        return

    try:
        promotion_plan.apply_plan(plan)
    except promotion_plan.PromotionError as e:
        _fail(str(e))

    if kind == 'script':
        assert sink.script is not None
        script = utils.abspath(pathlib.Path(sink.script.path))
        written = [c.path for c in plan.changes if c.path == script]
        message = (
            f'Added [item]{sum(fresh)}[/item] tests to the generator script of '
            f'[item]{sink.name}[/item] at '
            f'[item]{package.relpath(script)}[/item].'
        )
    else:
        written = [
            c.path
            for c in plan.changes
            if c.action == promotion_plan.CREATE and c.path.suffix == '.in'
        ]
        assert sink.glob is not None
        message = (
            f'Added [item]{len(written)}[/item] tests to manual group '
            f'[item]{sink.name}[/item] at '
            f'[item]{pathlib.Path(sink.glob).parent}[/item].'
        )

    if json_out is not None:
        print(
            json.dumps(
                {
                    'group': sink.name,
                    'kind': kind,
                    'files': [str(utils.abspath(p)) for p in written],
                    'skipped': [f.index for f, new in zip(findings, fresh) if not new],
                }
            ),
            file=json_out,
        )
        return
    console.print(f'[success]{message}[/success]')
    _print_skipped(findings, fresh, sink.name)


def _print_skipped(
    findings: List[stress_manifest.StressFindingEntry],
    fresh: List[bool],
    group: str,
) -> None:
    skipped = [str(f.index) for f, new in zip(findings, fresh) if not new]
    if skipped:
        console.print(
            f'[warning]Skipped findings [item]{", ".join(skipped)}[/item]: '
            f'test group [item]{group}[/item] already has them.[/warning]'
        )
