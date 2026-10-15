import json
import pathlib
import shlex
from typing import Annotated, Dict, List, NoReturn, Optional, Tuple

import syncer
import typer

from rbx import annotations, config, utils
from rbx.annotations import PackagePath
from rbx.box import package, promotion, stress_manifest
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
from rbx.console import console

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


def _non_promotable_reason(
    entry: GenerationTestcaseEntry, script_formats: Dict[pathlib.Path, str]
) -> str:
    """Return a human-readable reason why ``entry`` cannot be promoted.

    Assumes the caller already determined the entry is NOT promotable.
    """
    md = entry.metadata
    if md.generator_script is None:
        return 'is not generated by a generator script'
    if md.copied_from is not None:
        return 'comes from a @copy (already a file)'
    if md.generator_script.path.suffix != '.txt':
        return 'comes from a dynamic generator script (only static .txt scripts can be promoted)'
    if script_formats.get(md.generator_script.path) != 'rbx':
        return 'does not come from an rbx generator script'
    return 'cannot be promoted'


def _promote_source_label(entry: GenerationTestcaseEntry) -> str:
    """Source descriptor for a promotable test, e.g.
    ``gen/0 (gens/gen.cpp 123) [testplan.txt:5]`` -- the identifier and
    generator call (from ``full_repr()``) plus the originating script location.
    """
    label = entry.full_repr()
    gse = entry.metadata.generator_script
    if gse is not None:
        label = f'{label} [{package.relpath(gse.path)}:{gse.line}]'
    return label


async def _pick_manual_group(
    manual_groups: Dict[str, TestcaseGroup],
) -> Optional[TestcaseGroup]:
    """Interactively pick (or create) a manual group to promote tests into.

    Offers the existing ``manual_groups`` plus a ``(create new manual group)``
    option and a ``(skip)`` option. Returns the chosen ``TestcaseGroup`` object,
    or ``None`` when the user skips/aborts.
    """
    import questionary

    choice = await questionary.select(
        'Choose the manual group to promote into:',
        choices=list(manual_groups) + ['(create new manual group)', '(skip)'],
    ).ask_async()

    if choice is None or choice == '(skip)':
        return None

    if choice == '(create new manual group)':
        return await promotion.create_manual_group_interactively()

    return manual_groups[choice]


class _FilenameEditorState:
    """Mutable state for the batch filename editor.

    Holds one editable stem buffer per selected test, the focused row, and the
    fixed glob prefix/suffix used to render each row's full-path preview.
    """

    def __init__(
        self,
        entries: List[GenerationTestcaseEntry],
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
        width = max((len(_promote_source_label(e)) for e in self.entries), default=0)
        for i, entry in enumerate(self.entries):
            selected = i == self.cursor
            pointer = '> ' if selected else '  '
            row_style = 'class:current' if selected else 'class:row'
            source = _promote_source_label(entry).ljust(width)
            fragments.append((row_style, f'{pointer}{source}  ->  '))
            fragments.append(('class:fixed', self.prefix))
            stem_style = 'class:stem-current' if selected else 'class:stem'
            fragments.append((stem_style, self.stems[i] or ' '))
            fragments.append(('class:fixed', self.suffix))
            fragments.append((row_style, '\n'))
        return fragments


async def _edit_filenames(
    target_group: TestcaseGroup,
    chosen_entries: List[GenerationTestcaseEntry],
    input=None,
    output=None,
) -> Optional[List[Tuple[GenerationTestcaseEntry, str]]]:
    """Batch-edit the destination filenames for the selected tests.

    Shows one row per test with its source (read-only) and an editable filename
    stem, pre-filled with a sequential glob-aware default. The full relative
    path is rendered live around the stem. Returns the list of
    ``(entry, stem)`` pairs on submit, or ``None`` if the user aborts (Esc /
    Ctrl-C) or if the package has no chosen entries.
    """
    if not chosen_entries:
        return None

    assert target_group.testcaseGlob is not None
    glob = target_group.testcaseGlob
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


async def _promote_interactive(
    manual_groups: Dict[str, TestcaseGroup],
    script_formats: Dict[pathlib.Path, str],
    group: Optional[str] = None,
    progress: Optional[utils.StatusProgress] = None,
) -> None:
    """Interactively select tests and promote them into a manual group."""
    import questionary

    all_entries = await extract_generation_testcases_from_groups()
    all_entries = [
        entry for entry in all_entries if promotion.is_promotable(entry, script_formats)
    ]
    if not all_entries:
        console.print(
            'No promotable tests found -- only tests generated by an rbx '
            'generator script can be promoted.'
        )
        return

    # Label shows the generator call plus the originating script location
    # (path:line) so the user can see where each test came from. The label is
    # prefixed by the unique group/index (group_entry), so labels are unique and
    # the parallel-zip selected-label->entry mapping is unambiguous.
    labels = [_promote_source_label(entry) for entry in all_entries]
    selected = await questionary.checkbox(
        'Select tests to promote to manual tests:',
        choices=labels,
    ).ask_async()
    if not selected:
        return

    selected_set = set(selected)
    chosen_entries = [
        entry for entry, label in zip(all_entries, labels) if label in selected_set
    ]

    if group is not None:
        target = manual_groups[group]
    else:
        target = await _pick_manual_group(manual_groups)
        if target is None:
            return

    # Edit all filenames in a single batch form, OUTSIDE the live spinner:
    # animating a Rich spinner while a prompt_toolkit app is open causes redraw
    # artifacts. Each row's default stem is a sequential glob-aware counter (see
    # promotion.default_stems). Returns None on abort (Esc / Ctrl-C) -> write
    # nothing, leave the scripts untouched.
    chosen = await _edit_filenames(target, chosen_entries)
    if chosen is None:
        return

    promoted_entries: List[GenerationTestcaseEntry] = []
    with utils.StatusProgress('Promoting tests...') as s:
        for entry, stem in chosen:
            input_path = await _generate_input_for_editing(
                entry, output=False, progress=s
            )
            written = promotion.promote_input_to_group(input_path, target, name=stem)
            gse = entry.metadata.generator_script
            assert gse is not None
            console.print(
                f'[success]Moved [item]{entry.group_entry}[/item] to '
                f'[item]{written}[/item] (removed from '
                f'[item]{package.relpath(gse.path)}:{gse.line}[/item]).[/success]'
            )
            promoted_entries.append(entry)

    # Remove from scripts only AFTER every write succeeded, so a generation
    # failure aborts before any destructive script edit.
    # Not transactional: if removal fails after the .in files were written, the
    # manual copies and the script lines both remain (duplicates) -- clean up by hand.
    promotion.remove_script_entries(promoted_entries)


@app.command('promote', help='Promote generated tests into a manual test group.')
@package.within_problem
@syncer.sync
async def promote(
    selectors: Annotated[
        Optional[List[str]],
        typer.Argument(
            help='Tests to promote, as [group]/[index] selectors. '
            'If omitted, tests are selected interactively.'
        ),
    ] = None,
    group: Annotated[
        Optional[str],
        typer.Option(
            '--group',
            '-G',
            help='Destination manual test group.',
        ),
    ] = None,
    name: Annotated[
        Optional[str],
        typer.Option(
            '--name',
            '-n',
            help='Filename stem for the promoted test. '
            'Only meaningful when promoting exactly one test.',
        ),
    ] = None,
):
    manual_groups = promotion.get_manual_groups_by_name()
    script_formats = promotion.script_format_by_path()

    if not selectors:
        if group is not None and group not in manual_groups:
            console.print(
                f'[error]Manual group [item]{group}[/item] does not exist.[/error]'
            )
            raise typer.Exit(1)
        await _promote_interactive(manual_groups, script_formats, group=group)
        return

    if group is None:
        target = await _pick_manual_group(manual_groups)
        if target is None:
            return
    else:
        if group not in manual_groups:
            console.print(
                f'[error]Manual group [item]{group}[/item] does not exist.[/error]'
            )
            console.print(
                '[error]Create it first by running [item]rbx testcases promote[/item] '
                'interactively (without a [item]--group[/item]).[/error]'
            )
            raise typer.Exit(1)
        target = manual_groups[group]

    patterns = [TestcasePattern.parse(selector) for selector in selectors]
    promoted_entries: List[GenerationTestcaseEntry] = []
    with utils.StatusProgress('Promoting tests...') as s:
        entries = await extract_generation_testcases_from_patterns(patterns)
        if not entries:
            console.print('[error]No tests matched the provided selectors.[/error]')
            raise typer.Exit(1)

        # All-or-nothing: validate every selected entry is a promotable rbx-script
        # test BEFORE writing anything.
        for entry in entries:
            if not promotion.is_promotable(entry, script_formats):
                reason = _non_promotable_reason(entry, script_formats)
                console.print(
                    f'[error]Test [item]{entry.group_entry}[/item] cannot be '
                    f'promoted: it {reason}.[/error]'
                )
                raise typer.Exit(1)

        single = len(entries) == 1
        if name is not None and not single:
            console.print(
                '[warning]--name is ignored when promoting more than one test; '
                'using auto-generated names.[/warning]'
            )
        for entry in entries:
            input_path = await _generate_input_for_editing(
                entry, output=False, progress=s
            )
            written = promotion.promote_input_to_group(
                input_path,
                target,
                name=name if single else None,
            )
            gse = entry.metadata.generator_script
            assert gse is not None
            console.print(
                f'[success]Moved [item]{entry.group_entry}[/item] to '
                f'[item]{written}[/item] (removed from '
                f'[item]{package.relpath(gse.path)}:{gse.line}[/item]).[/success]'
            )
            promoted_entries.append(entry)

    # Remove from scripts only AFTER every write succeeded.
    # Not transactional: if removal fails after the .in files were written, the
    # manual copies and the script lines both remain (duplicates) -- clean up by hand.
    promotion.remove_script_entries(promoted_entries)


def _fail(message: str) -> NoReturn:
    console.print(f'[error]{message}[/error]')
    raise typer.Exit(1)


def _stress_comment(spec: stress_manifest.StressSpec) -> str:
    """Describe the session that found the tests, the way it was asked for."""
    if spec.name is not None:
        args = [spec.name]
    else:
        args = []
        if spec.generator is not None:
            args += ['-g', spec.generator]
        if spec.fuzz is not None:
            args += ['--fuzz-on', *spec.fuzz] if spec.fuzz else ['--fuzz']
        args += ['-f', spec.finder]
    return f'Found by rbx stress {shlex.join(args)}'


def _selected_findings(
    indices: Optional[List[int]],
) -> Tuple[stress_manifest.StressManifest, List[stress_manifest.StressFindingEntry]]:
    """The latest session and the findings `indices` name (all when empty)."""
    manifest = stress_manifest.read_manifest()
    if manifest is None:
        _fail(
            'There is no stress session to take findings from. '
            'Run [item]rbx stress[/item] first.'
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


def _finding_inputs(
    findings: List[stress_manifest.StressFindingEntry],
) -> List[pathlib.Path]:
    paths = [stress_manifest.finding_input_path(f.index) for f in findings]
    for finding, path in zip(findings, paths):
        if not path.is_file():
            _fail(
                f'Could not find the input of finding [item]{finding.index}[/item] '
                f'at [item]{path}[/item].'
            )
    return paths


def _list_groups(as_json: bool) -> None:
    rows = [
        {
            'name': name,
            'kind': 'script',
            # Relative to the package root, which is the cwd here.
            'path': package.relpath(group.generatorScript.path).as_posix(),
        }
        for name, group in promotion.get_script_groups_by_name().items()
        if group.generatorScript is not None
    ] + [
        {'name': name, 'kind': 'manual', 'path': group.testcaseGlob}
        for name, group in promotion.get_manual_groups_by_name().items()
    ]
    if as_json:
        print(json.dumps(rows))
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
    non-interactive counterpart of the prompt `rbx stress` shows when it ends.

    Name the findings by their number in the stress report (from 1), or omit
    them to add all of them. What the group receives depends on its kind:

    - A `.txt` generator script group gets the generator call of each finding
      appended, under a comment naming the stress that found it. The test is
      generated again on the next build, so it stays reproducible.
    - A manual group (one declared with `testcaseGlob`) gets a copy of each
      finding's input, under the next free name its glob allows.

    `--new-script` and `--new-manual` create the group first. `--dry-run`
    shows what the file of a script group would become without writing it,
    and `--list-groups` lists the groups that can take findings. With
    `--json`, the command prints its result as JSON on stdout and nothing else.
""")
@package.within_problem
def add_finding(
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
            'without writing it.',
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
):
    destinations = [d for d in (group, new_script, new_manual) if d is not None]
    if list_groups:
        if destinations or indices or dry_run:
            _fail('--list-groups takes no findings and no destination.')
        _list_groups(as_json)
        return

    if len(destinations) != 1:
        _fail('Pass exactly one of --group, --new-script or --new-manual.')
    if glob is not None and new_manual is None:
        _fail('--glob only applies to --new-manual.')
    if new_manual is not None and glob is None:
        _fail('--new-manual needs a --glob for the files of the new group.')
    if dry_run and group is None:
        _fail('--dry-run only applies to --group.')

    manifest, findings = _selected_findings(indices)
    all_groups = package.get_test_groups_by_name()
    script_groups = promotion.get_script_groups_by_name()
    manual_groups = promotion.get_manual_groups_by_name()

    target: Optional[TestcaseGroup] = None
    if group is not None:
        if group in script_groups:
            target, kind = script_groups[group], 'script'
        elif group in manual_groups:
            target, kind = manual_groups[group], 'manual'
        elif group in all_groups:
            _fail(
                f'Test group [item]{group}[/item] cannot take findings: only a '
                '.txt generatorScript group or a manual (testcaseGlob) group can.'
            )
        else:
            _fail(f'Test group [item]{group}[/item] does not exist.')
    elif new_script is not None:
        kind = 'script'
        if new_script.stem in all_groups:
            _fail(f'Test group [item]{new_script.stem}[/item] already exists.')
    else:
        assert new_manual is not None and glob is not None
        kind = 'manual'
        if new_manual in all_groups:
            _fail(f'Test group [item]{new_manual}[/item] already exists.')
        if '*' not in glob or not glob.endswith('.in'):
            _fail(
                'The glob of a manual group must contain a `*` and end in '
                f'`.in` (got [item]{glob}[/item]).'
            )

    if dry_run and kind != 'script':
        _fail('--dry-run only applies to a generator script group.')

    calls = [finding.generator for finding in findings]
    comment = _stress_comment(manifest.spec)
    # Checked before anything is created or written: all or nothing.
    inputs = _finding_inputs(findings) if kind == 'manual' else []

    if dry_run:
        assert target is not None
        path, before, after = promotion.propose_script_append(target, calls, comment)
        if as_json:
            print(
                json.dumps(
                    {'file': str(utils.abspath(path)), 'before': before, 'after': after}
                )
            )
            return
        console.print(
            f'Would append [item]{len(calls)}[/item] tests to '
            f'[item]{package.relpath(path)}[/item]:'
        )
        console.print(after[len(before) :].strip('\n'), markup=False)
        return

    if target is None:
        if new_script is not None:
            target = promotion.create_script_group(new_script)
        else:
            assert new_manual is not None and glob is not None
            target = promotion.create_manual_group(new_manual, glob)

    if kind == 'script':
        written = [promotion.append_to_script_group(target, calls, comment)]
        message = (
            f'Added [item]{len(calls)}[/item] tests to the generator script of '
            f'[item]{target.name}[/item] at [item]{package.relpath(written[0])}[/item].'
        )
    else:
        written = [promotion.promote_input_to_group(p, target) for p in inputs]
        message = (
            f'Added [item]{len(written)}[/item] tests to manual group '
            f'[item]{target.name}[/item] at '
            f'[item]{promotion.manual_group_dir(target)}[/item].'
        )

    if as_json:
        print(
            json.dumps(
                {
                    'group': target.name,
                    'kind': kind,
                    'files': [str(utils.abspath(p)) for p in written],
                }
            )
        )
        return
    console.print(f'[success]{message}[/success]')
