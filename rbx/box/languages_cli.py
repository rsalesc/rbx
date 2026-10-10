"""`rbx lang`: list, add and remove statement languages (design 2026-09-20 §3).

Runs in *contest mode* at a contest root (the contest and every problem in it)
or in *problem mode* in a standalone problem. A problem that belongs to a
contest follows the contest's language list, so `add`/`rm` refuse to run from
inside it and point at the contest root instead; `ls` works anywhere.
"""

import pathlib
import sys
from typing import Annotated, List, Optional, Tuple

import rich.table
import typer

from rbx import annotations, console
from rbx.box import language_packs, presets
from rbx.box.contest import contest_utils
from rbx.box.contest.contest_package import (
    find_contest_package_or_die,
    find_contest_yaml,
)
from rbx.box.package import find_problem_yaml

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


class _Target:
    """A package `rbx lang` acts on: its root, kind and a display label."""

    def __init__(self, root: pathlib.Path, is_contest: bool, label: str):
        self.root = root
        self.is_contest = is_contest
        self.label = label


def _resolve_targets(*, mutate: bool) -> List[_Target]:
    contest_yaml = find_contest_yaml()
    problem_yaml = find_problem_yaml()
    if contest_yaml is not None and problem_yaml is not None and mutate:
        console.console.print(
            '[error]This problem belongs to a contest and follows its language '
            'list.[/error]'
        )
        console.console.print(
            f'Run this command from the contest root instead: '
            f'[item]{contest_yaml.parent}[/item].'
        )
        raise typer.Exit(1)
    if problem_yaml is not None:
        root = problem_yaml.parent
        return [_Target(root, False, root.name)]
    if contest_yaml is not None:
        root = contest_yaml.parent
        contest = find_contest_package_or_die(root)
        targets = [_Target(root, True, f'contest {contest.name}')]
        for problem in contest.problems:
            targets.append(
                _Target(
                    root / problem.path, False, f'{problem.short_name} ({problem.path})'
                )
            )
        return targets
    console.console.print(
        '[error]No problem or contest found in the current directory.[/error]'
    )
    raise typer.Exit(1)


def _template_for(target: _Target) -> pathlib.Path:
    """The preset template the target was created from, honouring the variant
    recorded in its lock."""
    variant = presets._read_locked_variant(target.root)  # noqa: SLF001
    return presets.get_active_template(
        target.root, is_contest=target.is_contest, variant=variant
    ).path


def _print_files(prefix: str, files: List[pathlib.Path]) -> None:
    for file in files:
        console.console.print(f'  {prefix} [item]{file}[/item]')


@app.command('ls, list', help='List the statement languages of the package(s).')
def ls():
    for target in _resolve_targets(mutate=False):
        table = rich.table.Table(
            title=target.label, title_justify='left', show_lines=False
        )
        table.add_column('language')
        table.add_column('file')
        table.add_column('status')
        listing = language_packs.list_languages(
            target.root, is_contest=target.is_contest
        )
        if not listing:
            console.console.print(f'[item]{target.label}[/item]: no languages.')
            continue
        for lang, files in listing:
            if not files:
                table.add_row(lang, '[dim](shared files only)[/dim]', '')
            for index, (file, exists) in enumerate(files):
                table.add_row(
                    lang if index == 0 else '',
                    str(file),
                    '[success]ok[/success]' if exists else '[error]missing[/error]',
                )
        console.console.print(table)


_YES_OPTION = typer.Option(
    '--yes',
    '-y',
    help='Edit a fragment other contest configs also include without asking.',
)


def _confirm_shared_edits(targets: List[_Target], lang: str, yes: bool) -> None:
    """Warn, and ask once before anything is touched, when the language list
    lives in a fragment that other contest configs (variants) also include:
    the edit changes them too. `--yes` skips the question; without a terminal
    it is required."""
    shared = [
        (target, fragment, others)
        for target in targets
        for fragment, others in language_packs.shared_edits(
            target.root, lang, is_contest=target.is_contest
        )
    ]
    if not shared:
        return
    for target, fragment, others in shared:
        try:
            shown = fragment.relative_to(target.root.resolve())
        except ValueError:
            shown = fragment
        names = ', '.join(sorted(path.name for path in others))
        plural = 's' if len(others) != 1 else ''
        console.console.print(
            f'[warning]Editing [item]{shown}[/item], which is also included by '
            f'{len(others)} other contest{plural}: {names}.[/warning]'
        )
    if yes:
        return
    if not sys.stdin.isatty():
        console.console.print(
            '[error]Refusing to edit a shared fragment without confirmation. '
            'Re-run with [item]--yes[/item] to proceed.[/error]'
        )
        raise typer.Exit(1)
    if not typer.confirm('Proceed?', default=True):
        raise typer.Exit(1)


@app.command('add', help='Add a statement language to the package(s).')
def add(
    lang: Annotated[str, typer.Argument(help='Language to add (ISO 639-1).')],
    from_lang: Annotated[
        Optional[str],
        typer.Option(
            '--from',
            help="Clone this existing language's files instead of the preset skeleton.",
        ),
    ] = None,
    yes: Annotated[bool, _YES_OPTION] = False,
):
    targets = _resolve_targets(mutate=True)
    _confirm_shared_edits(targets, lang, yes)
    for target in targets:
        created = language_packs.add_language(
            target.root,
            _template_for(target),
            lang,
            is_contest=target.is_contest,
            from_lang=from_lang,
        )
        console.console.print(
            f'[item]{target.label}[/item]: added [item]{lang}[/item]'
            + (
                f' ({len(created)} file(s) created)'
                if created
                else ' (nothing to create)'
            )
        )
        _print_files('+', created)
    contest_utils.clear_all_caches()


@app.command('rm, remove', help='Remove a statement language from the package(s).')
def rm(
    lang: Annotated[str, typer.Argument(help='Language to remove.')],
    delete_files: Annotated[
        bool,
        typer.Option(
            '--delete-files',
            help="Also delete the language's files. By default they are kept "
            'and reported as orphaned.',
        ),
    ] = False,
    yes: Annotated[bool, _YES_OPTION] = False,
):
    targets = _resolve_targets(mutate=True)
    _confirm_shared_edits(targets, lang, yes)
    orphaned: List[Tuple[str, pathlib.Path]] = []
    # Problems before the contest: an inheriting problem decides what it has by
    # the contest's list, which must still name the language at that point.
    for target in reversed(targets):
        files = language_packs.remove_language(
            target.root, lang, is_contest=target.is_contest, delete_files=delete_files
        )
        console.console.print(
            f'[item]{target.label}[/item]: removed [item]{lang}[/item]'
        )
        if delete_files:
            _print_files('-', files)
        else:
            orphaned.extend((target.label, file) for file in files)
    if orphaned:
        console.console.print(
            '[warning]The following files are no longer referenced (re-run with '
            '[item]--delete-files[/item] to delete them):[/warning]'
        )
        for label, file in orphaned:
            console.console.print(f'  [item]{label}[/item]: {file}')
    contest_utils.clear_all_caches()


@app.callback()
def callback():
    pass
