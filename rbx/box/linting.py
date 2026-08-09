import difflib
import pathlib
from typing import Optional, Type

import yamlfix
import yamlfix.model
from pydantic import BaseModel

from rbx import console
from rbx.box import schema_urls
from rbx.box.cd import is_contest_package, is_preset_package, is_problem_package
from rbx.box.contest.schema import Contest
from rbx.box.presets import get_preset_yaml
from rbx.box.presets.schema import Preset
from rbx.box.schema import Package
from rbx.box.stats import find_problem_packages_from_contest

# Hosts whose schema headers rbx owns and may rewrite. A user pointing at a
# local or third-party schema is left alone.
_OWNED_SCHEMA_PREFIXES = (
    'https://rsalesc.github.io/rbx/schemas/',
    f'{schema_urls.VERSIONED_BASE_URL}/',
)


def _is_owned_schema_header(line: str) -> bool:
    return any(prefix in line for prefix in _OWNED_SCHEMA_PREFIXES)


def fix_language_server(
    path: pathlib.Path,
    model_cls: Type[BaseModel],
    root: pathlib.Path = pathlib.Path(),
) -> bool:
    orig_text = path.read_text()
    header = (
        f'# yaml-language-server: $schema={schema_urls.schema_url(model_cls, root)}\n'
    )

    lines = orig_text.splitlines(keepends=True)
    existing = {
        i
        for i, line in enumerate(lines)
        if line.strip().startswith('# yaml-language-server:')
    }
    if existing and not all(_is_owned_schema_header(lines[i]) for i in existing):
        # The file points at a schema rbx does not own; do not touch it.
        return False

    kept = [line for i, line in enumerate(lines) if i not in existing]
    insert_at = 1 if kept and kept[0].startswith('---') else 0
    content = ''.join(kept[:insert_at] + [header] + kept[insert_at:])

    if content == orig_text:
        return False
    path.write_text(content)
    return True


def fix_yaml(
    path: pathlib.Path,
    verbose: bool = True,
    print_diff: bool = False,
    model_cls: Optional[Type[BaseModel]] = None,
):
    orig_text = path.read_text()

    # Config to go hand-to-hand with VSCode YAML extension,
    # which we offer first class support to. Unfortunately,
    # YAML extension is not perfect :(
    config = yamlfix.model.YamlfixConfig(
        quote_basic_values=True,
        quote_representation='"',
        comments_min_spaces_from_content=1,
    )
    _, changed = yamlfix.fix_files([str(path)], dry_run=False, config=config)

    if model_cls is not None:
        if fix_language_server(path, model_cls, path.parent):
            changed = True

    if changed and verbose:
        console.console.print(
            f'Formatting [item]{path}[/item].',
        )

    if print_diff and changed:
        unified_diff = difflib.unified_diff(
            orig_text.splitlines(), path.read_text().splitlines()
        )
        console.console.print(
            f'Diff for [item]{path}[/item].\n' + '\n'.join(unified_diff),
        )


def fix_package(root: pathlib.Path = pathlib.Path(), print_diff: bool = False):
    if is_preset_package(root):
        fix_yaml(root / 'preset.rbx.yml', model_cls=Preset, print_diff=print_diff)
        preset = get_preset_yaml(root)
        if preset.problem is not None:
            fix_yaml(
                root / preset.problem / 'problem.rbx.yml',
                model_cls=Package,
                print_diff=print_diff,
            )
        if preset.contest is not None:
            fix_package(root / preset.contest, print_diff=print_diff)
        return

    if is_problem_package(root):
        fix_yaml(root / 'problem.rbx.yml', model_cls=Package, print_diff=print_diff)
    if is_contest_package(root):
        fix_yaml(root / 'contest.rbx.yml', model_cls=Contest, print_diff=print_diff)
        for problem in find_problem_packages_from_contest(root):
            fix_yaml(
                problem / 'problem.rbx.yml',
                model_cls=Package,
                print_diff=print_diff,
            )
