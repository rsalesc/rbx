"""Per-language *packs* of a package (design 2026-09-20 §2-§3).

A preset needs no extra manifest to ship several languages: its template's own
``languages:`` list says which it ships, and its wildcard statements
(``language: "*"``) say which files belong to each -- the paths their
``{lang}`` fields resolve to. Everything else in the template is
language-neutral. This module resolves those packs and edits a package's
language set: pruning at creation, and adding/removing later (``rbx lang``).

Yml edits go through ``EditSession`` so comments and ``!include`` fragments
survive; files are only ever created when missing, never overwritten.
"""

import pathlib
import shutil
from typing import List, Optional, Tuple, Union

import typer
from pydantic import ValidationError

from rbx import console
from rbx.box import yaml_include
from rbx.box.contest.schema import Contest
from rbx.box.schema import Package
from rbx.box.statements.schema import (
    LANG_PLACEHOLDER,
    BaseStatement,
    validate_concrete_language,
)
from rbx.box.statements.wildcards import substitute_lang
from rbx.box.yaml_validation import load_yaml_model

# Path-like statement fields that can name a per-language file.
_PATH_FIELDS = ('file', 'standaloneProblemTemplate', 'contestProblemTemplate')


def _yaml_name(is_contest: bool) -> str:
    return 'contest.rbx.yml' if is_contest else 'problem.rbx.yml'


def _load(root: pathlib.Path, is_contest: bool) -> Union[Package, Contest]:
    path = root / _yaml_name(is_contest)
    return load_yaml_model(path, Contest if is_contest else Package)


def _wildcards(pkg: Union[Package, Contest]) -> List[BaseStatement]:
    lists: List[List[BaseStatement]] = [pkg.statements, pkg.tutorials]  # type: ignore[list-item]
    if isinstance(pkg, Contest):
        lists.append(pkg.documents)  # type: ignore[arg-type]
    return [st for sts in lists for st in sts if st.is_wildcard]


def template_languages(root: pathlib.Path, *, is_contest: bool) -> List[str]:
    """The `languages:` a template (or package) declares; empty when unset, or
    when the template ships no yml at all (a legal, minimal template).

    A raw key read rather than a model load: installing from a template never
    validated its yml, and a template that fails validation must keep failing
    where it always did (when the created package is first loaded)."""
    if not (root / _yaml_name(is_contest)).is_file():
        return []
    return list(_Edit(root, is_contest).languages or [])


def pack_files(
    root: pathlib.Path, lang: str, *, is_contest: bool
) -> List[pathlib.Path]:
    """The files the package's wildcard statements resolve to for `lang`,
    relative to `root`, in declaration order. A wildcard field without
    `{lang}` is language-neutral and belongs to no pack."""
    files: List[pathlib.Path] = []
    for st in _wildcards(_load(root, is_contest)):
        for field in _PATH_FIELDS:
            value = getattr(st, field, None)
            if value is None or LANG_PLACEHOLDER not in str(value):
                continue
            resolved = substitute_lang(pathlib.Path(value), lang)
            if resolved not in files:
                files.append(resolved)
    return files


def _effective_languages(root: pathlib.Path, is_contest: bool) -> List[str]:
    pkg = _load(root, is_contest)
    if is_contest:
        return pkg.effective_languages
    # A problem inside a contest inherits its list; go through the loader so
    # that injection happens.
    from rbx.box import package

    package.clear_package_cache()
    return package.find_problem_package_or_die(root).effective_languages


def list_languages(
    root: pathlib.Path, *, is_contest: bool
) -> List[Tuple[str, List[Tuple[pathlib.Path, bool]]]]:
    """Each effective language with its pack files and whether they exist."""
    return [
        (
            lang,
            [
                (file, (root / file).is_file())
                for file in pack_files(root, lang, is_contest=is_contest)
            ],
        )
        for lang in _effective_languages(root, is_contest)
    ]


class _Edit:
    """A comment-preserving edit of `languages:` and `titles:` in the package's
    yml (or the fragment that owns them)."""

    def __init__(self, root: pathlib.Path, is_contest: bool):
        self.session = yaml_include.EditSession(root / _yaml_name(is_contest))

    @property
    def languages(self) -> Optional[List[str]]:
        value = self.session.target('languages').value
        return None if value is None else list(value)

    def set_languages(self, languages: Optional[List[str]]) -> None:
        owner, parent, key = self.session.resolve(('languages',))
        if languages is None:
            if parent is not None and key in parent:
                del parent[key]
            return
        self.session.target('languages').replace(list(languages))

    def set_title(self, lang: str, title: str) -> None:
        target = self.session.target('titles', lang)
        if target.value is None:
            target.replace(title)

    def get_title(self, lang: str) -> Optional[str]:
        return self.session.target('titles', lang).value

    def drop_title(self, lang: str) -> None:
        _, parent, key = self.session.resolve(('titles', lang))
        if parent is not None and key in parent:
            del parent[key]

    def save(self) -> None:
        self.session.save()


def prune_languages(
    root: pathlib.Path,
    keep: List[str],
    *,
    is_contest: bool,
    inherit: bool = False,
) -> List[pathlib.Path]:
    """Restrict a freshly created package to `keep`: delete the other
    languages' pack files and titles, and rewrite `languages:` to `keep` (or
    drop it when `inherit`, for a problem that follows its contest). Returns
    the deleted files."""
    shipped = template_languages(root, is_contest=is_contest)
    for lang in keep:
        if lang not in shipped:
            console.console.print(
                f'[warning]Language [item]{lang}[/item] is not shipped by the '
                f'template (available: [item]{", ".join(shipped) or "none"}[/item]). '
                'Keeping it in the list, but no files were created for it.[/warning]'
            )
    deleted: List[pathlib.Path] = []
    for lang in shipped:
        if lang in keep:
            continue
        for file in pack_files(root, lang, is_contest=is_contest):
            if (root / file).is_file():
                (root / file).unlink()
                deleted.append(file)

    edit = _Edit(root, is_contest)
    for lang in shipped:
        if lang not in keep:
            edit.drop_title(lang)
    edit.set_languages(None if inherit else list(keep))
    edit.save()
    return deleted


def _die_unshipped(lang: str, shipped: List[str]) -> None:
    console.console.print(
        f'[error]The preset does not ship language [item]{lang}[/item].[/error]'
    )
    console.console.print(
        f'Shipped languages: [item]{", ".join(shipped) or "none"}[/item].'
    )
    console.console.print(
        f'Re-run with [item]--from <lang>[/item] to clone an existing language '
        f'instead (e.g. [item]--from {shipped[0] if shipped else "en"}[/item]).'
    )
    raise typer.Exit(1)


def add_language(
    root: pathlib.Path,
    template: pathlib.Path,
    lang: str,
    *,
    is_contest: bool,
    from_lang: Optional[str] = None,
) -> List[pathlib.Path]:
    """Add `lang` to the package: copy its pack from the template (or clone
    `from_lang`'s files in the package), add a title, and list it. Idempotent:
    existing files and titles are left alone. Returns the created files."""
    try:
        validate_concrete_language(lang)
    except (ValueError, ValidationError) as exc:
        console.console.print(f'[error]{exc}[/error]')
        raise typer.Exit(1) from None

    if not _wildcards(_load(root, is_contest)):
        console.console.print(
            '[error]This package declares no wildcard statements '
            '([item]language: "*"[/item]), so there is nothing to add a language '
            'to: a listed language would have no statement behind it.[/error]'
        )
        console.console.print(
            'Declare the statements once with [item]language: "*"[/item] and '
            '[item]{lang}[/item] in their file names, then re-run.'
        )
        raise typer.Exit(1)

    shipped = template_languages(template, is_contest=is_contest)
    if from_lang is None and lang not in shipped:
        _die_unshipped(lang, shipped)

    created: List[pathlib.Path] = []
    targets = pack_files(root, lang, is_contest=is_contest)
    sources = (
        [template / f for f in targets]
        if from_lang is None
        else [root / f for f in pack_files(root, from_lang, is_contest=is_contest)]
    )
    for src, file in zip(sources, targets):
        dest = root / file
        if dest.exists():
            continue
        if not src.is_file():
            console.console.print(
                f'[warning]Skipping [item]{file}[/item]: source '
                f'[item]{src}[/item] does not exist.[/warning]'
            )
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        created.append(file)

    edit = _Edit(root, is_contest)
    if from_lang is None:
        title = _Edit(template, is_contest).get_title(lang)
    else:
        title = edit.get_title(from_lang)
    if title is None:
        title = _load(root, is_contest).name
    edit.set_title(lang, title)

    languages = edit.languages
    if languages is not None:
        if lang not in languages:
            edit.set_languages([*languages, lang])
    elif is_contest or not _inherits_from_contest(root):
        # No list yet and nothing to inherit from: materialize one.
        current = _load(root, is_contest).effective_languages
        if lang not in current:
            edit.set_languages([*current, lang])
    edit.save()
    return created


def _inherits_from_contest(root: pathlib.Path) -> bool:
    from rbx.box.contest.contest_package import find_contest_languages

    find_contest_languages.cache_clear()
    return find_contest_languages(root) is not None


def remove_language(
    root: pathlib.Path,
    lang: str,
    *,
    is_contest: bool,
    delete_files: bool = False,
) -> List[pathlib.Path]:
    """Unlist `lang` and drop its title. Its pack files are kept and returned
    as orphaned, or deleted when `delete_files`."""
    edit = _Edit(root, is_contest)
    languages = edit.languages
    # A problem without a list follows its contest: judge membership by the
    # effective languages and leave the (absent) list alone.
    listed = (
        languages if languages is not None else _effective_languages(root, is_contest)
    )
    if lang not in listed:
        return []
    files = [
        f for f in pack_files(root, lang, is_contest=is_contest) if (root / f).is_file()
    ]
    if delete_files:
        for file in files:
            (root / file).unlink()
    if languages is not None:
        edit.set_languages([lg for lg in languages if lg != lang])
    edit.drop_title(lang)
    edit.save()
    return files
